#!/usr/bin/env python3
"""Send Python code to a Blender session running assets/live_bridge.py and print the reply.

    python scripts/bridge_send.py --ping
    python scripts/bridge_send.py --code "import bpy; print(len(bpy.data.objects))"
    python scripts/bridge_send.py --file build_bracket.py --screenshot C:/tmp/preview.png
    python scripts/bridge_send.py --eval "sum(o.name for o in bpy.data.objects)"   # namespace persists
    python scripts/bridge_send.py --code "bpy.ops.wm.read_factory_settings(use_empty=True)"
    python scripts/bridge_send.py --stop

Exit codes: 0 = ok, 1 = the remote code raised, 2 = cannot reach the bridge, 3 = bridge stopped.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import sys

DEFAULT_PORT = int(os.environ.get("BLENDER_BRIDGE_PORT", "8765"))


def request(payload: dict, port: int, timeout: float) -> dict:
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
        conn.settimeout(timeout)
        body = json.dumps(payload).encode("utf-8")
        conn.sendall(struct.pack("!I", len(body)) + body)

        header = _recv_exactly(conn, 4, timeout)
        if header is None:
            raise TimeoutError("no reply header from Blender (is a modal operator blocking the main thread?)")
        (length,) = struct.unpack("!I", header)
        if length > 4 * 1024 * 1024:
            raise ValueError(f"reply too large: {length} bytes")
        raw = _recv_exactly(conn, length, timeout)
        if raw is None:
            raise TimeoutError("incomplete reply from Blender")
        return json.loads(raw.decode("utf-8"))


def _recv_exactly(conn: socket.socket, count: int, timeout: float) -> bytes | None:
    buffer = b""
    while len(buffer) < count:
        try:
            chunk = conn.recv(count - len(buffer))
        except socket.timeout:
            return None
        if not chunk:
            return None
        buffer += chunk
    return buffer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--code", help="python source to execute in the live session")
    source.add_argument("--file", help="path to a .py file to execute")
    source.add_argument("--stdin", action="store_true", help="read code from stdin")
    source.add_argument("--eval", help="evaluate a single expression and print repr()")
    source.add_argument("--ping", action="store_true", help="health check / session summary")
    source.add_argument("--stop", action="store_true", help="shut the bridge down")
    parser.add_argument("--quit-blender", action="store_true",
                        help="with --stop: also close Blender (never assumed - the session may hold unsaved work)")
    parser.add_argument("--opt", action="append", default=[], metavar="KEY=VALUE",
                        help="option forwarded to the payload as BRIDGE_OPTS (repeatable), "
                             "e.g. --opt out=C:/m/shot.png --opt angles=4")
    parser.add_argument("--screenshot", help="ask Blender to save a viewport grab to this path")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout", type=float, default=300.0, help="seconds to wait for the code to finish")
    parser.add_argument("--json", action="store_true", help="print the raw reply object")
    parser.add_argument("--indent", type=int, default=None, help="pretty-print dict/list results with this indent")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)

    payload: dict = {"id": 1}
    if args.ping:
        payload["action"] = "ping"
    elif args.stop:
        payload["action"] = "stop"
        if args.quit_blender:
            payload["quit_blender"] = True
    elif args.eval:
        payload.update({"action": "eval", "code": args.eval})
    else:
        if args.file:
            with open(args.file, "r", encoding="utf-8") as handle:
                payload["code"] = handle.read()
        elif args.stdin:
            payload["code"] = sys.stdin.read()
        elif args.code:
            payload["code"] = args.code
        else:
            payload.update({"action": "ping"})
        payload["action"] = "exec"
    if args.opt:
        opts: dict = {}
        for item in args.opt:
            if "=" not in item:
                print(f"--opt expects KEY=VALUE, got {item!r}", file=sys.stderr)
                return 2
            key, _, value = item.partition("=")
            if value.strip().lower() in ("true", "false"):
                parsed: object = value.strip().lower() == "true"
            else:
                try:
                    parsed = int(value)
                except ValueError:
                    parsed = value
            opts[key.lstrip("-")] = parsed
        payload["opts"] = opts
    if args.screenshot:
        payload["screenshot"] = os.path.abspath(args.screenshot)

    try:
        reply = request(payload, args.port, args.timeout)
    except (ConnectionRefusedError, TimeoutError, OSError) as error:
        print(f"cannot reach the Blender bridge on 127.0.0.1:{args.port}: {error}", file=sys.stderr)
        print("start it with:  blender --python <skill>/assets/live_bridge.py", file=sys.stderr)
        print("(or use scripts/blender_run.py for a headless one-shot run)", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(reply, indent=2, default=str))
    else:
        stdout = (reply.get("stdout") or "").rstrip()
        if stdout:
            print(stdout)
        result = reply.get("result")
        if result:
            if args.indent is not None:
                try:
                    print(json.dumps(eval(result, {"__builtins__": {}}, {}), indent=args.indent))  # noqa: S307
                except Exception:  # noqa: BLE001
                    print(result)
            else:
                print(f"result: {result}")
        if reply.get("screenshot"):
            shot = reply["screenshot"]
            print(f"screenshot: {shot.get('path')} [{shot.get('method')}] ok={shot.get('ok')}"
                  f"{' - ' + str(shot.get('detail')) if not shot.get('ok') else ''}")
        if reply.get("error"):
            print("---- Blender raised ----", file=sys.stderr)
            print(reply["error"], file=sys.stderr)

    if not args.json:
        status_bits = [reply.get(key) for key in ("blender", "objects")]
        if status_bits[0]:
            print(f"[blender {status_bits[0]}, {status_bits[1]} objects]", file=sys.stderr)

    if payload["action"] == "stop":
        return 3 if reply.get("ok") else 1
    return 0 if reply.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
