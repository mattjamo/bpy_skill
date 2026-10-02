# bpy — Blender skill for the Pi coding agent

Build, inspect, verify, render and export 3D models by driving **Blender from
Python** through the Pi coding agent. The skill is two feedback loops plus a
verifier:

- **Live bridge** — a stateful Python REPL inside a running Blender GUI
  (`assets/live_bridge.py`); the user watches the model appear, the agent grabs
  viewport screenshots after each change.
- **Headless runner** — `blender -b -P` for batch/CI (`scripts/blender_run.py`),
  with auto-framed preview renders and a whole-scene geometry report.

Verification is not optional in this skill: every model gets a geometry check
(watertight / boundary / non-manifold edges, world bounds, per-object volume
and surface area) and a pixel-level check of the renders (coverage, framing,
blank-frame detection). Blender's Python API is enormous and *silently*
forgiving — wrong attribute names and misaimed cameras produce no error, just
a wrong model or an empty frame, so the loops exist to catch that.

## Requirements

| Dependency | Notes |
|---|---|
| Blender 4.2 / 4.4 / 4.5 LTS / 5.x | auto-discovered: install dirs, `$BLENDER_BIN`, `--version`, `$PATH`, or pip `bpy` |
| Python 3 on `PATH` | **stdlib only** — nothing to `pip install` |

Verified on Windows 11 + Blender 5.1. The live bridge works on any OS with a
Blender GUI; headless rendering works anywhere (EEVEE needs a GL context).

## Install

### As a Pi package

```bash
pi install /path/to/bpy_skill                        # local directory - no publishing
pi install git:github.com/mattjamo/bpy_skill@v0.2.0  # git (pinned by tag)
```

`pi list` and `pi config` show and toggle discovered resources. The
`package.json` manifest declares the skill at the package root
(`"pi": { "skills": ["./"] }`), so the conventional `skills/` subdirectory is
not needed.

### Manually

Copy this directory into any Pi skills location — directories containing
`SKILL.md` are discovered recursively:

```
~/.pi/agent/skills/         # personal (Pi)
~/.agents/skills/           # personal (Agent Skills convention)
<project>/.agents/skills/   # project (loaded only after project trust)
```

Start Pi and check the startup diagnostics or run `/skill:bpy`. After editing
a skill in an active session, run `/reload`.

## Quick start

Live loop (Blender open, watch it happen):

```powershell
# from PowerShell, using the installed skill directory
& "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --python "$env:USERPROFILE\.pi\agent\skills\bpy\assets\live_bridge.py"
```

```bash
python <skill>/scripts/bridge_send.py --ping
python <skill>/scripts/bridge_send.py --code "import bpy; print(len(bpy.data.objects))"
python <skill>/scripts/bridge_send.py --file <skill>/examples/parametric_bracket.py --screenshot C:/m/view.png
```

Headless loop (batch / CI):

```bash
python <skill>/scripts/blender_run.py --script <build>.py --save-as C:/m/model.blend
python <skill>/scripts/blender_run.py --open C:/m/model.blend --script <skill>/payloads/preview.py -- --out C:/m/shot --angles 4 --size 900
python <skill>/scripts/blender_run.py --open C:/m/model.blend --script <skill>/payloads/scene_report.py -- --pretty
```

`<skill>` = the directory where the skill is installed. Full protocol, payload
options, API-reality notes and troubleshooting live in `references/`.

## Security note

The live bridge listens on **127.0.0.1 only, with no authentication**, and
executes arbitrary Python with your Blender process's (and file system's)
permissions. Anything else on the machine that can open a localhost port can
drive it. Run it only while you are working, and send `--stop` (optionally
`--quit-blender`) when done.

## Layout

| Path | What it is |
|---|---|
| `SKILL.md` | agent-facing instructions: the two loops, the verifier, hard-won Blender 5.x rules |
| `assets/live_bridge.py` | socket REPL inside Blender (main-thread `bpy.app.timers`, no threads) |
| `scripts/` | agent-side tools: `bridge_send.py`, `blender_run.py`, `env_check.py`, `render_still.py` |
| `payloads/` | `preview.py` (auto-framed temp camera + light rig + pixel checks), `scene_report.py` (whole-scene geometry JSON) |
| `examples/` | worked builds: `parametric_bracket.py` (CAD-ish, volume-checked against hand calc), `pacman_ball.py` (organic), `train_build.py`, `shot_views.py` (multi-angle shots) |
| `references/` | deep dives: live-bridge protocol, modeling, materials/render, export, measured 4.x-vs-5.x API reality, verification triage |

## License

Apache License 2.0 (Apache-2.0) - the whole repository, code and
documentation alike, as declared in the `SKILL.md` frontmatter.
