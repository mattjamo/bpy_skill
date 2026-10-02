---
name: bpy
description: "Design and build 3D models in Blender by driving it with Python - from the agent. Use for: bpy / Blender scripting, building or editing 3D geometry procedurally (meshes from pydata, bmesh, curves, text, metaballs), modifiers (bevel/fillet, boolean holes, solidify, mirror, array, weld), materials/shader nodes, cameras and lighting, keyframes/animation, .blend files, scene introspection, EEVEE/Cycles/Workbench renders, preview screenshots of a model, exporting glTF/GLB/USD/OBJ/STL for game engines or printing, millimetre-accurate CAD-ish parts, and checking that a generated model is actually watertight, manifold, correctly sized and correctly oriented. Works against a running Blender GUI (live code REPL + viewport screenshots), against headless `blender -b -P`, or against pip-installed `bpy`."
license: GPL-3.0-or-later AND CC-BY-4.0 (Blender docs quoted/summarised)
compatibility: "Any OS with Blender 4.2 / 4.4 / 4.5 LTS / 5.x installed (auto-discovered), or pip `bpy` which pins exactly one CPython (5.x -> 3.13). Verified on Windows 11 + Blender 5.1.0 (adfe2921d5f3). EEVEE renders work headless when a GPU/GL context is available."
metadata:
  verified: "executed on a real machine 2026-09-30: build -> save -> 4-angle preview -> pixel framing check -> geometry report (watertight, 80x40x56 mm, volume within 2.2% of hand calc)"
  context7_library_ids: "/websites/blender_api_current, /websites/blender_api_4_5, /websites/blender_api_4_2, /blender/blender"
---

# Blender from Python: build, look, verify

The Blender API is enormous (2 000+ RNA properties, hundreds of operators) and *silently* forgiving: a wrong
attribute name, a misaimed camera or a self-intersecting shell usually produces **no error at all** - just a
wrong model or an empty render. So this skill is not a catalogue, it is **two feedback loops plus a verifier**.
Never report a model as finished without running both verifications.

## Pick the loop

| Situation | Loop |
|---|---|
| User has Blender open and wants to watch it happen / iterate visually | **A. live bridge** |
| Batch, CI, no GUI, generating many variants, "just give me the .blend/glb" | **B. headless** |
| Code must run inside the user's own Python process / service | read `references/pip-module.md` (pip `bpy`, one CPython per Blender release) |

## Loop A - live session (primary: you can see the result)

Start Blender with the bridge (a plain script, no add-on install needed). From PowerShell:

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --python "$env:USERPROFILE\.pi\agent\skills\bpy\assets\live_bridge.py"
```

Then, from this skill's directory, one request per command; the Python namespace **persists**, so it behaves
like a stateful REPL inside Blender's main thread:

```bash
python scripts/bridge_send.py --ping
python scripts/bridge_send.py --code "import bpy; print([o.name for o in bpy.data.objects])"
python scripts/bridge_send.py --file examples/parametric_bracket.py --screenshot C:/m/shot.png
python scripts/bridge_send.py --eval "len(bpy.data.meshes)"
python scripts/bridge_send.py --stop
```

Send geometry code, then immediately ask for a viewport grab (`--screenshot`) and look at it. Details, protocol
and troubleshooting: `references/live-bridge.md`.

## Loop B - headless (reproducible, scriptable, chainable)

```bash
# 1. build a model and save it
python scripts/blender_run.py --script examples/parametric_bracket.py --save-as C:/m/bracket.blend
# 2. look at it: temp camera + light rig, N angles, auto-framed, restores the scene afterwards
python scripts/blender_run.py --open C:/m/bracket.blend --script payloads/preview.py -- --out C:/m/bracket --angles 4 --size 900
# 3. measure it
python scripts/blender_run.py --open C:/m/bracket.blend --script payloads/scene_report.py -- --pretty
```

`scripts/blender_run.py` finds the newest install (`--bin`, `$BLENDER_BIN`, `--version 4.2`, `$PATH`, or
`--pip-bpy`), always adds `--python-exit-code 1` so a Python error is a non-zero exit, and never blocks
without `--timeout`. It also re-saves the file *after* a payload that ended in `SystemExit` - payloads may
`raise SystemExit(main())` freely.

## Verify - the part that makes the output trustworthy

1. **Geometry** (`payloads/scene_report.py`, or `geometry_report()` in `examples/parametric_bracket.py`):
   watertight flag, boundary/non-manifold edge counts, world bounds, per-object volume and surface area
   (signed tetrahedron sum - verified exact: a 2 m cube reports area 24.0 / volume 8.0), unapplied-transform
   and missing-material warnings. Compare the volume against a hand calculation; `parametric_bracket.py` does
   exactly that and reports `volume_within_6pct`.
2. **Pixels** (`payloads/preview.py` -> `checks`): every render is re-read and measured - `coverage`
   (fraction of pixels differing from the corner/background), `subject_bbox`, `pixel_stats`, `framing`
   (`ok` / `too_small` / `too_close`) and a `hint` when the frame is blank. **A model that is not visible in
   the frame does not exist**, and these checks catch it without needing eyes.
   If your model *can* see images, read the PNG too - the numbers say "something is there", the image says
   whether it is the right thing.
3. If a preview is blank, `references/verify-and-preview.md` lists the five real causes (inverted camera aim
   is #1) instead of guessing.

## Don't guess the API - introspect it

Two commands answer most "does this property exist on this Blender version" questions, and cost one headless
run instead of five failed attempts:

```python
cls = bpy.types.BevelModifier            # or type(bpy.context.object.modifiers.new("x", 'BEVEL'))
print(sorted(p.identifier for p in cls.bl_rna.properties if not p.is_readonly))
print([i.identifier for i in prop.enum_items])          # enum values: prop.enum_items, NOT enum_keys
```

For concepts, signatures and tutorials use context7 with library id `/websites/blender_api_current` (or
`/websites/blender_api_4_2`, `/websites/blender_api_4_5` for LTS targets). Docs lag the binary; the binary
wins - confirm with `bl_rna`. A list of what was measured on Blender 5.1 (and what changed vs 4.x) is in
`references/api-reality.md`.

## Rules that came from real failures on Blender 5.1

* **`to_track_quat` needs camera -> target**: `(target - cam.location).to_track_quat('-Z','Y')`. The reverse
  aim renders a perfectly lit, perfectly empty frame.
* **Blender 5.x has no Workbench.** `scene.render.bl_rna.properties["engine"].enum_items` on 5.1 returns
  `['BLENDER_EEVEE']` only (Cycles ships as an extension and is absent under `--factory-startup`). Never hard
  code an engine: pick from the list and report which one you used.
* **A preview needs its own rig.** A metallic part in the default black world renders pure black, which looks
  identical to "the model is missing". `payloads/preview.py` installs a temporary world + key + fill. The same
  trap hits saved deliverables: a `.blend` with no lights or world of its own renders pure black for anyone who
  renders it directly, so bake a grey world and at least one sun into the file before calling it done.
* **EEVEE Fast GI ghosts the model.** On a fresh 5.x scene `scene.eevee.use_fast_gi` is `True`, and near large
  flat surfaces (a 50 m ground plane) it renders a translucent *duplicate* of the model - a train looked doubled
  in every wide shot while `bpy.data.objects`, collections and instancing were provably clean. If geometry
  appears duplicated in renders but not in the scene data, set `scene.eevee.use_fast_gi = False` (hiding the
  ground makes the ghost vanish - a fast confirmation).
* **`EnumProperty.enum_items`**, not `enum_keys`. `bpy.data.images.load(path)` takes no `check_data`.
* **`object.users_collection` is a tuple of Collections**, not a count -> `if not obj.users_collection:`.
* **No `Object.display_mode`** (it is `display_type`); **`Mesh.shade_smooth` is read-only** (use
  `polygon.use_smooth`); **`BevelModifier.limit_method`**, not `limit`.
* **Never hold RNA references across a scene wipe.** `bpy.ops.wm.read_factory_settings(use_empty=True)`
  destroys the old `Scene`; a reference kept across it raises `ReferenceError: StructRNA of type Scene has
  been removed`. Reset first, then look things up.
* **Restore state before `bpy.data.orphans_purge()`** - the purge frees the block you are about to restore
  (`ReferenceError: ... World has been removed`).
* **`modifier_apply` needs the object visible, active and selected** and returns `{'CANCELLED'}` silently;
  always `if result != {"FINISHED"}: raise`. Objects in an excluded view-layer collection cannot be edited ->
  set `view_layer.active_layer_collection` (see `find_layer_collection`).
* **Model in metres, report in millimetres** (`MM = 0.001`). Never combine `unit_settings.scale_length` with
  pre-scaled coordinates - that is how a bracket became 80 km wide.
* **Build one manifold solid** (extrude a closed profile) instead of overlapping boxes. Two coincident boxes
  report `watertight` but leave 24 boundary + 36 non-manifold edges and make bevels explode past the bounding
  box.
* **`World.use_nodes` is deprecated in 5.1** (gone in 6.0) - guard it with `getattr`.

## Files

| Path | What it is |
|---|---|
| `assets/live_bridge.py` | socket REPL *inside* Blender (main-thread `bpy.app.timers`, no threads); `--python` this file |
| `scripts/bridge_send.py` | agent-side sender: `--code` / `--file` / `--eval` / `--screenshot` / `--ping` / `--stop` |
| `scripts/blender_run.py` | headless runner + install discovery + `--save-as` + guaranteed non-zero on script errors |
| `payloads/preview.py` | auto-framing temp camera + light rig, N angles, pixel-level framing check |
| `payloads/scene_report.py` | whole-scene JSON: objects, mesh stats, materials, modifiers, warnings |
| `scripts/env_check.py`, `scripts/render_still.py` | capability probe (engines, GPU, units) and a quality still render |
| `examples/parametric_bracket.py` | worked CAD-ish part: profile sweep, EXACT booleans, fillet, volume checked against a hand calculation |
| `examples/pacman_ball.py` | organic/stylised build: manifold-by-construction sphere + wedge, mouth-relative eye placement, measured lens gap and pupil protrusion |
| `examples/shot_views.py` | head-on / profile / three-quarter shots for models whose "face" is not along world Z |
| `references/api-reality.md` | measured property lists, 4.x vs 5.x differences, introspection recipes |
| `references/modeling.md` | pydata/bmesh/curves/text, modifier recipes, booleans, units, transforms |
| `references/verify-and-preview.md` | the verification API, blank-frame triage, geometry math |
| `references/live-bridge.md` | protocol, screenshots, timeouts, what blocks the main thread |
| `references/materials-render.md` | node materials, EEVEE 5.x settings, lighting, view transforms, film |
| `references/export.md` | glTF/GLB/USD/OBJ/STL, mm vs m, selection-only export, applied transforms |
| `references/pip-module.md` | `pip install bpy`: version matrix, wheel rules, module-mode gotchas |
