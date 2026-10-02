# Live bridge: driving a running Blender from the agent

`assets/live_bridge.py` turns an open Blender session into a stateful Python REPL over a localhost socket, so
the user watches the model appear and you can grab the viewport after every change.

## Start it

```powershell
# Windows / PowerShell
& "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --python "$env:USERPROFILE\.pi\agent\skills\bpy\assets\live_bridge.py"
```

```bash
# bash (any OS). Non-default port, and headless is refused unless asked for:
BLENDER_BRIDGE_PORT=9000 blender --python ~/.pi/agent/skills/bpy/assets/live_bridge.py
blender --python ~/.pi/agent/skills/bpy/assets/live_bridge.py -- --bridge-background
```

Also works from Blender's Text Editor (Open file -> Run Script / `Alt+P`), or as an add-on via its
`register()` hook. Startup prints `[blender-bridge] listening on http://127.0.0.1:8765 (pid N)` and
`ready - agent can now send code` - up in ~2 s on a warm machine (measured).

## Use it

```bash
python scripts/bridge_send.py --ping                      # health + session summary
python scripts/bridge_send.py --code "import bpy; print(len(bpy.data.meshes))"
python scripts/bridge_send.py --file examples/parametric_bracket.py --screenshot C:/m/view.png
python scripts/bridge_send.py --eval "PARAMS['name']"     # namespace persists across requests
python scripts/bridge_send.py --file payloads/preview.py --opt out=C:/m/shot.png --opt angles=4
python scripts/bridge_send.py --file payloads/scene_report.py --opt pretty=1 --opt name=Bracket
python scripts/bridge_send.py --code "bpy.ops.wm.read_factory_settings(use_empty=True)"
python scripts/bridge_send.py --stop --quit-blender       # --stop alone leaves Blender open
```

Exit codes: `0` ok, `1` the remote code raised (the full traceback is printed), `2` bridge unreachable,
`3` stopped. `--json` gives the raw reply (`ok`, `stdout`, `result`, `error`, `screenshot`, `blender`,
`objects`, `active_object`, `blend`), `--indent N` pretty-prints a dict/list `result`, `--timeout` defaults to
300 s. `--opt KEY=VALUE` (repeatable) is delivered as `BRIDGE_OPTS` in the payload's globals;
`payloads/preview.py` and `payloads/scene_report.py` read it before falling back to `--flags` after `--`, which
is how you parameterise a payload in a session that has no argv of its own.

## Protocol

One request per TCP connection; frame = 4-byte big-endian length + UTF-8 JSON, max 4 MB.

```jsonc
{"action": "exec|eval|ping|status|stop", "code": "...", "id": 1,
 "screenshot": "C:\\m\\view.png", "opts": {"angles": 4, "out": "C:/m/s.png"}, "quit_blender": false}

{"ok": true, "id": 1, "stdout": "...", "result": "repr(...)", "error": null,
 "screenshot": {"path": "...", "ok": true, "method": "opengl"},
 "blender": "5.1.0", "background": false, "objects": 1, "scenes": ["Scene"], "active_object": "Bracket_L"}
```

`eval` is a single **expression** (`repr()` of the value); statements must go through `exec`/`--code`
(`--eval "import bpy; ..."` is a `SyntaxError`, not a bug). `exec` runs with `__name__ == "__main__"` in a
persistent namespace, so a payload's `if __name__ == "__main__": raise SystemExit(main())` block runs exactly
as under `blender --python file.py`, and a `SystemExit(0)` is reported as success while a non-zero code is
reported as an error.

## Why it is built this way (each rule is a crash or a hang avoided)

* **No threads.** Blender's Python integration is not thread-safe; anything touching `bpy` off the main thread
  can corrupt memory. The server is a non-blocking socket polled from `bpy.app.timers`, which runs in Blender's
  main thread, so behaviour matches the Python Console.
* **A raising timer callback is unregistered by Blender.** The process stays alive, the port stays open, and
  every later request hangs until timeout - which looks like a network bug. `_tick()` wraps `_poll()` in
  `try/except`, answers with an error frame, and keeps the interval; observed behaviour after the fix: a
  failing payload replies `ok: false` and the bridge keeps serving.
* **One request per tick**, and frames are read incrementally, so a long upload cannot stall the UI. If a
  modal operator (an open file dialog, a drag) blocks the main thread, the reply stalls - the sender reports
  `no reply header from Blender (is a modal operator blocking the main thread?)`.
* **Context is bare inside a timer.** `bpy.context.view_layer` / `.scene` work; `bpy.context.object`,
  `.active_object`, `.selected_objects` raise `AttributeError`, and object operators fail with
  `poll() failed, context is incorrect` (see `references/api-reality.md` §4). The bridge overrides
  `window/screen/area/region` to soften this. Overriding `view_layer` or `scene` **crashed Blender** with
  `EXCEPTION_ACCESS_VIOLATION` in `deg_check_base_in_depsgraph` - do not add those keys back.
* **`--stop` does not close Blender** (unsaved work), and `--quit-blender` quits through a timer so the reply
  is flushed first.
* **Security:** listens on `127.0.0.1` only, executes arbitrary Python with your Blender (and file)
  permissions, no authentication. Anything else on the machine that can open a localhost port can drive it.
  Run it only while you are working, and `--stop` when done.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `connection refused` | Blender not running or the bridge not registered: check the console for the `listening` line; look in `bpy.app.timers` output |
| `no reply header` / timeout with Blender alive | the timer is gone (a callback raised) or a modal operator owns the main thread |
| `EXCEPTION_ACCESS_VIOLATION`, Blender vanishes | `temp_override` with `view_layer`/`scene`, or touching `bpy` off the main thread |
| payload "did nothing", no stdout | the file's `if __name__ == "__main__":` did not fire - check the bridge is new enough to set `__name__`, or call the function explicitly |
| `AttributeError: 'Context' object has no attribute 'selected_objects'` | payload used UI-derived context; use `bpy.context.view_layer.objects` / `select_get()` |
| screenshot `method: none` | running `--background`, or the active screen has no `VIEW_3D` area - use `payloads/preview.py` instead |
| everything slow | the payload triggers a depsgraph update per request; batch edits, then one `view_layer.update()` |
| two Blender sessions | each holds its own bridge on the same port - the second fails to bind (the log says so); use `BLENDER_BRIDGE_PORT` |
