#!/usr/bin/env python3
"""Run a bpy script headless against a Blender install (or the pip `bpy` module).

    python scripts/blender_run.py --list
    python scripts/blender_run.py --script payloads/scene_report.py
    python scripts/blender_run.py --version 5.1 --script build.py -- --width 800
    python scripts/blender_run.py --open C:/m/work.blend --script tweak.py --save-as C:/m/work_v2.blend
    python scripts/blender_run.py --pip-bpy --script build.py        # use `pip install bpy` instead

Blender's own discovery order: --bin, $BLENDER_BIN, --version, newest install, PATH, pip bpy.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile

WIN_GLOB = r"C:\Program Files\Blender Foundation\Blender *\blender.exe"
MAC_GLOB = "/Applications/Blender*.app/Contents/MacOS/blender"
LINUX_GLOB = ["/usr/local/blender*/blender", "/opt/blender*/blender", "/snap/blender/current/blender"]


def discover() -> list[str]:
    candidates: list[str] = []
    if os.name == "nt":
        candidates += glob.glob(WIN_GLOB)
    elif sys.platform == "darwin":
        candidates += glob.glob(MAC_GLOB)
    else:
        for pattern in LINUX_GLOB:
            candidates += glob.glob(pattern)
    from shutil import which  # noqa: PLC0415 - cheap, avoid cost when not needed

    if (found := which("blender")):
        candidates.append(found)
    return sorted({os.path.abspath(item) for item in candidates if os.path.exists(item)})


def version_of(binary: str) -> str:
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        return "unknown"
    match = re.search(r"Blender\s+(\d+\.\d+(?:\.\d+)?)", out or "")
    return match.group(1) if match else "unknown"


def pick_binary(args: argparse.Namespace) -> str | None:
    if args.bin:
        return os.path.abspath(os.path.expanduser(args.bin))
    if os.environ.get("BLENDER_BIN"):
        return os.environ["BLENDER_BIN"]

    found = discover()
    if not found:
        return None
    if args.version:
        for binary in found:
            if version_of(binary).startswith(str(args.version)):
                return binary
        print(f"no Blender {args.version} among: " + ", ".join(version_of(b) for b in found), file=sys.stderr)
        return None
    return max(found, key=version_of)


def wrap_script(script: str, save_as: str | None) -> str:
    """Optionally wrap the payload so the resulting .blend is saved afterwards."""
    if not save_as:
        return os.path.abspath(script)
    wrapper = tempfile.NamedTemporaryFile("w", suffix="_wrapper.py", delete=False, encoding="utf-8")
    wrapper.write(
        "import runpy\n"
        "import bpy\n"
        "import sys\n"
        "_status = 0\n"
        "try:\n"
        f"    runpy.run_path({os.path.abspath(script)!r}, run_name='__main__')\n"
        "except SystemExit as _error:                          # payloads end with 'raise SystemExit(main())'\n"
        "    _status = _error.code if isinstance(_error.code, int) else 0   # so the save still runs\n"
        "bpy.context.view_layer.update()\n"
        f"bpy.ops.wm.save_as_mainfile(filepath={os.path.abspath(save_as)!r})\n"
        f"print('[blender_run] saved', {os.path.abspath(save_as)!r})\n"
        "sys.exit(_status)\n"
    )
    wrapper.close()
    return wrapper.name


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--script", help="python file to execute inside Blender")
    parser.add_argument("--open", dest="blend", help="existing .blend to load first")
    parser.add_argument("--save-as", help="save the session to this .blend after the script runs")
    parser.add_argument("--bin", help="explicit blender executable")
    parser.add_argument("--version", help="pick an install by version prefix, e.g. 5.1 or 4.2")
    parser.add_argument("--pip-bpy", action="store_true", help="run with this interpreter using pip-installed bpy")
    parser.add_argument("--gui", action="store_true", help="launch Blender with a window instead of -b")
    parser.add_argument("--no-factory-startup", action="store_true", help="keep the user's startup/add-ons")
    parser.add_argument("--list", action="store_true", help="show discovered Blender installs and exit")
    parser.add_argument("--timeout", type=float, default=0, help="kill the run after N seconds")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="passed to the script after a '--' separator")
    args = parser.parse_args(argv)

    if args.list:
        installs = discover()
        if not installs:
            print("no Blender install found; use --bin, $BLENDER_BIN, or `pip install bpy` + --pip-bpy")
        for binary in installs:
            print(f"{version_of(binary):<10} {binary}")
        return 0

    if not args.script:
        parser.error("--script is required (unless --list)")
    if not os.path.exists(args.script):
        parser.error(f"script not found: {args.script}")

    payload = [os.path.abspath(a) if a.endswith(".py") else a for a in (args.args or [])]
    while payload and payload[0] in ("--", "-"):
        payload = payload[1:]

    if args.pip_bpy:
        command = [sys.executable, args.script, *payload]
    else:
        binary = pick_binary(args)
        if binary is None:
            print("Blender not found. Options: --bin <path>, BLENDER_BIN, --pip-bpy, or install Blender.",
                  file=sys.stderr)
            return 2
        command = [binary]
        if not args.gui:
            command += ["-b", "-noaudio"]
        if not args.no_factory_startup:
            command += ["--factory-startup"]
        if args.blend:
            command += [os.path.abspath(args.blend)]
        command += ["-P", wrap_script(args.script, args.save_as), "--python-exit-code", "1"]
        if payload:
            command += ["--", *payload]

    print("$ " + " ".join(command), file=sys.stderr)
    try:
        completed = subprocess.run(command, timeout=args.timeout or None)
    except FileNotFoundError as error:
        print(f"cannot launch {command[0]}: {error}", file=sys.stderr)
        return 2
    except subprocess.TimeoutExpired:
        print(f"[blender_run] killed after {args.timeout}s", file=sys.stderr)
        return 124

    if completed.returncode:
        print(f"[blender_run] exit {completed.returncode} (python errors inside Blender exit non-zero "
              f"thanks to --python-exit-code)", file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
