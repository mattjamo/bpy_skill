#!/usr/bin/env python3
"""Report whether this interpreter can run `bpy`, and what that bpy can do.

Safe to run with any interpreter: it never imports bpy unless the import succeeds.

Usage:
    python env_check.py [--require [MAJOR.MINOR]] [--json]
"""

from __future__ import annotations

import argparse
import json
import platform
import struct
import sys
from importlib import metadata

# Verified against PyPI on 2026-09-30 (bpy 5.2.2 is the newest release).
EXPECTED_PYTHON = {
    (5, 2): "3.13",
    (5, 1): "3.13",
    (4, 5): "3.11",
    (4, 2): "3.11",
}


def wheel_platform() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Linux":
        return f"manylinux_2_28_{machine}"
    if system == "Windows":
        return "win_arm64" if machine in ("arm64", "aarch64") else "win_amd64"
    if system == "Darwin":
        return f"macosx_11_0_{'arm64' if machine == 'arm64' else 'x86_64'}"
    return f"{system.lower()}-{machine}"


def check_bpy() -> dict:
    report: dict = {"importable": False}
    try:
        import bpy  # noqa: PLC0415 - must be imported lazily and always before mathutils
    except Exception as error:  # noqa: BLE001 - report any import failure verbatim
        report["error"] = f"{type(error).__name__}: {error}"
        return report

    import mathutils  # after bpy, or it is not found

    engines = []
    try:
        engines = [item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    except Exception:  # noqa: BLE001
        pass

    report.update(
        {
            "importable": True,
            "version": list(bpy.app.version),
            "version_string": bpy.app.version_string,
            "version_cycle": bpy.app.version_cycle,
            "background": bpy.app.background,
            "factory_startup": bpy.app.factory_startup,
            "binary_path": bpy.app.binary_path,
            "tempdir": bpy.app.tempdir,
            "mathutils_ok": hasattr(mathutils, "Vector"),
            "engines": engines,
            "cycles_gpu": cycles_status(),
            "objects_in_memory": len(bpy.data.objects),
        }
    )
    return report


def cycles_status() -> dict:
    try:
        import bpy  # noqa: PLC0415

        prefs = bpy.context.preferences.addons["cycles"].preferences
    except Exception as error:  # noqa: BLE001
        return {"available": False, "reason": f"{type(error).__name__}: {error}"}
    devices = []
    try:
        prefs.get_devices()
        devices = [{"name": d.name, "type": d.type, "use": d.use} for d in prefs.devices]
    except Exception as error:  # noqa: BLE001
        return {"available": True, "error": str(error)}
    return {"available": True, "compute_device_type": prefs.compute_device_type, "devices": devices}


def expected_python(version: tuple) -> str | None:
    return EXPECTED_PYTHON.get(version[:2])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--require", nargs="?", const="any", default=None, metavar="MAJOR.MINOR",
                        help="exit non-zero when bpy is missing, or older than the given Blender version")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    report = {
        "python": {"version": running, "executable": sys.executable, "bits": struct.calcsize("P") * 8,
                   "platform": wheel_platform()},
        "bpy": check_bpy(),
        "installed_distribution": None,
    }
    try:
        report["installed_distribution"] = metadata.version("bpy")
    except Exception:  # noqa: BLE001
        pass

    bpy_info = report["bpy"]
    if bpy_info.get("importable"):
        want = expected_python(tuple(bpy_info["version"]))
        report["python_matches_bpy"] = {"expected": want, "running": running, "ok": want in (None, running)}
    else:
        # Advise the interpreter the newest releases want, using metadata when pip knows the version.
        report["advice"] = (
            "pip install failed or bpy is missing. Each bpy release pins one CPython minor: "
            "bpy 5.x -> 3.13, bpy 4.5/4.2 LTS -> 3.11. "
            "Try: python3.13 -m venv .venv && pip install 'bpy==5.2.2'. "
            "Releases off PyPI: --extra-index-url https://download.blender.org/pypi/"
        )

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"python      : {running} ({report['python']['bits']}-bit) {sys.executable}")
        print(f"platform    : {report['python']['platform']}")
        print(f"bpy on pypi : {report['installed_distribution'] or 'not installed / unknown'}")
        if bpy_info.get("importable"):
            print(f"bpy         : {bpy_info['version_string']} ({bpy_info['version_cycle']}) background={bpy_info['background']}")
            print(f"engines     : {', '.join(bpy_info['engines']) or 'none registered'}")
            print(f"binary_path : {bpy_info['binary_path'] or '(empty - set bpy.app.binary_path if you need the CLI)'}")
            cycles = bpy_info.get("cycles_gpu", {})
            if cycles.get("available"):
                devices = [d["name"] for d in cycles.get("devices", []) if d["type"] != 'CPU']
                print(f"cycles      : {cycles.get('compute_device_type')} / GPU devices: {devices or 'none'}")
            else:
                print(f"cycles      : unavailable ({cycles.get('reason')})")
            match = report.get("python_matches_bpy", {})
            print(f"python pin  : expects {match.get('expected')}, running {match.get('running')} -> "
                  f"{'OK' if match.get('ok') else 'MISMATCH'}")
        else:
            print(f"bpy         : NOT IMPORTABLE - {bpy_info.get('error')}")
            print(f"advice      : {report['advice']}")

    if args.require is not None:
        if not bpy_info.get("importable"):
            print("\nFAIL: bpy is required but not usable in this interpreter", file=sys.stderr)
            return 1
        if args.require != "any":
            want = tuple(int(part) for part in str(args.require).split("."))
            if tuple(bpy_info["version"])[: len(want)] < want:
                print(f"\nFAIL: bpy {bpy_info['version_string']} < required {args.require}", file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
