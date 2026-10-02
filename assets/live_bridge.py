"""Live bridge: lets an external agent stream Python into a RUNNING Blender session.

Start it from a terminal (recommended - no add-on install needed, works on 4.2/4.4/5.x):

    "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" --python assets/live_bridge.py
    BLENDER_BRIDGE_PORT=9000 blender --python .../live_bridge.py      # custom port
    blender --python .../live_bridge.py -- --bridge-background        # also allow headless

or inside Blender: Text Editor -> Open this file -> Run Script (Alt-P).

Design constraints (documented Blender behaviour, not a guess):
  * Blender's Python integration is NOT thread safe, so this server never spawns a thread.
    It polls a non-blocking socket from bpy.app.timers, which runs in Blender's MAIN THREAD,
    so everything the agent sends executes exactly as if typed in Blender's Python Console.
  * The exec namespace persists between requests, so the agent gets a stateful REPL:
    objects, variables and undo history from previous requests are still there.
  * Listens on 127.0.0.1 only. Code is executed with your full Blender permissions.

Protocol: 4-byte big-endian length + UTF-8 JSON frame, one request per connection.
Request:  {"action": "exec"|"eval"|"ping"|"status"|"stop",
           "code": "...", "id": 1, "screenshot": "C:\\\\tmp\\\\view.png", "timeout": 120}
Reply:    {"ok": true, "stdout": "...", "result": "...", "error": null,
           "screenshot": {"path": ..., "ok": true, "method": "opengl"},
           "blender": "5.1.0", "objects": 12, "id": 1}
"""

from __future__ import annotations

import io
import json
import os
import select
import socket
import struct
import sys
import time
import traceback
import contextlib
from contextlib import redirect_stdout

PORT = int(os.environ.get("BLENDER_BRIDGE_PORT", "8765"))
HOST = "127.0.0.1"
MAX_FRAME = 4 * 1024 * 1024
CONTEXT_OVERRIDE_KEYS = ("screenshot",)

_NS: dict = {}
_SERVER: socket.socket | None = None
_PENDING: dict = {}          # connection state while a frame is still arriving
_STOP_REQUESTED = False

try:  # only available when Blender imports this file
    import bpy  # type: ignore
except ImportError:  # pragma: no cover - running under plain python
    bpy = None


# --------------------------------------------------------------------------- transport

def _listen() -> socket.socket:
    global _SERVER
    if _SERVER is not None:
        return _SERVER
    _SERVER = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _SERVER.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _SERVER.bind((HOST, PORT))
    _SERVER.listen(8)
    _SERVER.setblocking(False)
    print(f"[blender-bridge] listening on http://{HOST}:{PORT} (pid {os.getpid()})")
    return _SERVER


def _recv_frame(conn: socket.socket) -> dict | None:
    """Return a decoded request, or None when the frame is not complete yet."""
    state = _PENDING.setdefault(conn, {"buffer": b"", "since": time.time()})
    try:
        state["buffer"] += conn.recv(65536)
    except BlockingIOError:
        return None
    except OSError:
        _PENDING.pop(conn, None)
        return None

    buffer = state["buffer"]
    if len(buffer) > MAX_FRAME:
        _PENDING.pop(conn, None)
        conn.close()
        return {"action": "exec", "code": "", "_error": "frame too large"}
    if len(buffer) < 4:
        return None
    (length,) = struct.unpack("!I", buffer[:4])
    if len(buffer) < 4 + length:
        if time.time() - state["since"] > 30:
            _PENDING.pop(conn, None)
            conn.close()
        return None
    payload = buffer[4:4 + length]
    _PENDING.pop(conn, None)
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception as error:  # noqa: BLE001
        return {"action": "exec", "code": "", "_error": f"bad request json: {error}"}


def _send(conn: socket.socket, reply: dict) -> None:
    payload = json.dumps(reply, default=str).encode("utf-8")
    try:
        conn.sendall(struct.pack("!I", len(payload)) + payload)
    except OSError:
        pass
    finally:
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        conn.close()


# --------------------------------------------------------------------------- execution

def _namespace() -> dict:
    if not _NS:
        # '__main__' so payloads written as `def main(): ...` + `if __name__ == "__main__": raise SystemExit(main())`
        # behave exactly as they do under `blender --python file.py` (otherwise the file is loaded and nothing runs).
        _NS.update({"__name__": "__main__", "__builtins__": __builtins__})
        if bpy is not None:
            _NS["bpy"] = bpy
            _NS["mathutils"] = __import__("mathutils")
    return _NS


def _ui_override() -> dict:
    """Context kwargs resembling the Python Console's, for payloads that touch context.active_object etc.

    Verified behaviour: inside a bpy.app.timers callback `bpy.context` is a bare context - members that
    come from the window/area (`active_object`, `area`, `region`, `selected_objects`) can raise
    AttributeError there even though they exist in background mode. Prefer `bpy.context.view_layer.*` in
    payloads; this override makes the sloppier code work too.
    """
    if bpy is None or bpy.app.background:
        return {}
    kwargs: dict = {}
    try:
        window = getattr(bpy.context, "window", None) or (
            bpy.context.window_manager.windows[0] if len(bpy.context.window_manager.windows) else None)
        if window is None:
            return {}
        # Verified the hard way: overriding view_layer/scene here crashes Blender with
        # EXCEPTION_ACCESS_VIOLATION. Only window/screen/area/region are safe override keys here.
        kwargs["window"] = window
        if window.screen:
            kwargs["screen"] = window.screen
            area = next((a for a in window.screen.areas if a.type == "VIEW_3D"), window.screen.areas[0] if len(window.screen.areas) else None)
            if area is not None:
                kwargs["area"] = area
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                if region is not None:
                    kwargs["region"] = region
    except Exception:  # noqa: BLE001
        return {}
    return kwargs


def _run(code: str, mode: str) -> tuple[str, str, str | None]:
    stream = io.StringIO()
    error_text = None
    result = ""
    override = _ui_override()
    stack = contextlib.ExitStack()
    try:
        if override:
            stack.enter_context(bpy.context.temp_override(**override))
        with stack, redirect_stdout(stream):
            if mode == "eval":
                result = repr(eval(code, _namespace()))       # noqa: S307 - intentional bridge
            else:
                exec(compile(code, "<blender-bridge>", "exec"), _namespace())  # noqa: S102
    except SystemExit as exit_error:          # payloads legitimately end with `raise SystemExit(main())`;
        code = exit_error.code                # catching it is also what stops a payload from killing Blender
        if code not in (None, 0):
            error_text = f"SystemExit({code}) - the payload asked to exit with a failure code"
    except BaseException:  # noqa: BLE001 - the agent needs the full traceback
        error_text = traceback.format_exc()
    return stream.getvalue(), result, error_text


def _grab_viewport(path: str) -> dict:
    """Best-effort picture of what the user is looking at, for visual iteration."""
    if bpy is None or bpy.app.background:
        return {"path": path, "ok": False, "method": "none", "detail": "no GUI (background mode)"}

    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)

    windows = bpy.context.window_manager.windows
    window = getattr(bpy.context, "window", None) or (windows[0] if len(windows) else None)
    if window is None:
        return {"path": path, "ok": False, "method": "none", "detail": "no open window"}

    for area in window.screen.areas if window.screen else []:
        if area.type != "VIEW_3D":
            continue
        region = next((reg for reg in area.regions if reg.type == "WINDOW"), None)
        if region is None:
            continue
        with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
            scene = bpy.context.scene
            # SpaceView3D has no image_settings in 4.x/5.x - the opengl grab writes through the
            # scene's own render image settings, so configure those.
            previous = (scene.render.image_settings.file_format, scene.render.filepath)
            scene.render.image_settings.file_format = "PNG"
            scene.render.filepath = path
            try:
                bpy.ops.view3d.view_all()
            except Exception:  # noqa: BLE001 - framing is cosmetic
                pass
            try:
                for call in (lambda: bpy.ops.render.opengl(write_still=True, view_context=True),
                             lambda: bpy.ops.render.opengl(write_still=True)):
                    try:
                        call()
                        return {"path": path, "ok": os.path.exists(path), "method": "opengl"}
                    except Exception as error:  # noqa: BLE001 - fall through to a real render
                        detail = str(error)
            finally:
                scene.render.image_settings.file_format, scene.render.filepath = previous
        break
    else:
        detail = "no VIEW_3D area on the current screen"

    engine = bpy.context.scene.render.engine
    options = [item.identifier for item
               in bpy.context.scene.render.bl_rna.properties["engine"].enum_items]
    try:  # fall back to a real (fast) render instead of a viewport grab
        scene = bpy.context.scene
        for candidate in ("BLENDER_WORKBENCH", "BLENDER_EEVEE"):
            if candidate in options:
                scene.render.engine = candidate
                break
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        return {"path": path, "ok": os.path.exists(path), "method": scene.render.engine}
    except Exception as error:  # noqa: BLE001
        return {"path": path, "ok": False, "method": "failed", "detail": f"{detail}; {error}"}
    finally:
        bpy.context.scene.render.engine = engine


def _status() -> dict:
    info = {"bridge": True, "pid": os.getpid(), "port": PORT}
    if bpy is not None:
        info.update({
            "blender": bpy.app.version_string,
            "background": bpy.app.background,
            "blend": bpy.data.filepath or None,
            "objects": len(bpy.data.objects),
            "scenes": [scene.name for scene in bpy.data.scenes],
            "active_object": getattr(bpy.context, "object", None) and bpy.context.object.name,
        })
    return info


def _handle(request: dict) -> dict:
    reply: dict = {"id": request.get("id"), "ok": True}
    if request.get("_error"):
        reply.update({"ok": False, "error": request["_error"]})
        return reply

    opts = request.get("opts")
    if isinstance(opts, dict):
        # Payloads read BRIDGE_OPTS first and sys.argv-after-'--' second, so the same file works in a
        # live session (no argv of its own) and under `blender -b -P file.py -- --out ...`.
        _namespace()["BRIDGE_OPTS"] = opts

    action = request.get("action", "exec")
    if action in {"exec", "eval"}:
        stdout, result, error_text = _run(request.get("code", ""), action)
        reply.update({"stdout": stdout, "result": result, "error": error_text, "ok": error_text is None})
        if request.get("screenshot") and error_text is None:
            reply["screenshot"] = _grab_viewport(request["screenshot"])
    elif action in {"ping", "status"}:
        reply["status"] = _status()
    elif action == "stop":
        global _STOP_REQUESTED
        _STOP_REQUESTED = True
        reply["stopping"] = True
        if request.get("quit_blender"):
            # Never kill a user's session by accident: only close Blender when explicitly asked,
            # and via a timer so this reply is flushed to the agent first.
            bpy.app.timers.register(_quit_blender, first_interval=0.5)
            reply["quit_blender"] = True
    else:
        reply.update({"ok": False, "error": f"unknown action {action!r}"})
    reply.update(_status())
    return reply


# --------------------------------------------------------------------------- main-thread poll

def _tick() -> float | None:
    """bpy.app.timers callback.

    A timer callback that raises an exception is *unregistered by Blender*, which leaves the process
    running but permanently deaf (connections are accepted by the OS and never answered). Nothing here
    is allowed to escape, and the agent sees an error frame instead of a timeout.
    """
    try:
        return _poll()
    except Exception as error:  # noqa: BLE001 - the bridge must survive any single bad request
        print(f"[blender-bridge] poll error, staying alive: {type(error).__name__}: {error}")
        return 0.2


def _poll() -> float | None:
    """Runs in Blender's main thread via bpy.app.timers. Never blocks."""
    global _STOP_REQUESTED
    if _STOP_REQUESTED:
        _shutdown()
        return None

    server = _listen()
    try:
        conn, peer = server.accept()
    except BlockingIOError:
        conn = None
    except OSError:
        conn = None

    if conn is not None:
        if peer[0].startswith("127.0.0.1"):
            conn.setblocking(False)
            _PENDING[conn] = {"buffer": b"", "since": time.time()}
        else:
            conn.close()

    for connection in list(_PENDING):
        request = _recv_frame(connection)
        if request is None:
            continue
        _PENDING.pop(connection, None)
        try:
            reply = _handle(request)
        except Exception as error:  # noqa: BLE001 - always answer, never leave the client hanging
            reply = {"id": request.get("id"), "ok": False,
                     "error": f"{type(error).__name__}: {error}\n{traceback.format_exc()[:2000]}"}
        try:
            _send(connection, reply)
        except OSError as error:
            print(f"[blender-bridge] could not send the reply: {error}")
        finally:
            try:
                connection.close()
            except OSError:
                pass
        break  # one request per tick keeps Blender responsive

    return 0.05


def _quit_blender() -> None:
    """Close Blender from the main thread, after the reply has been sent."""
    try:
        bpy.ops.wm.quit_blender()
    except Exception as error:  # noqa: BLE001
        print(f"[blender-bridge] could not quit Blender: {error}")
    return None


def _shutdown() -> None:
    global _SERVER
    if _SERVER is not None:
        try:
            _SERVER.close()
        except OSError:
            pass
        _SERVER = None
    print("[blender-bridge] stopped")


def start() -> None:
    _listen()
    if bpy is not None:
        if not bpy.app.timers.is_registered(_tick):
            bpy.app.timers.register(_tick, first_interval=0.1, persistent=True)
        print(f"[blender-bridge] ready - agent can now send code on {HOST}:{PORT} (Blender {bpy.app.version_string})")
    else:
        print("[blender-bridge] no bpy: run this file WITH blender --python <file>", file=sys.stderr)


def stop() -> None:
    if bpy is not None and bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    _shutdown()


# Add-on-style hooks (optional; --python start-up is the supported path on Blender 5.x).
def register() -> None:  # pragma: no cover - add-on entry point
    start()


def unregister() -> None:  # pragma: no cover - add-on entry point
    stop()


if bpy is not None:
    start()
