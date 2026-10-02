# Verify and look: the loop that makes output trustworthy

Blender rarely tells you a model is wrong. A misaimed camera, an unavailable engine, an inverted normal or a
self-intersecting shell all produce "success". So every model gets **two verifications**: measure the geometry,
and measure the pixels.

## 1. Geometry: `payloads/scene_report.py`

```bash
python scripts/blender_run.py --open model.blend --script payloads/scene_report.py -- --pretty
python scripts/bridge_send.py --file payloads/scene_report.py            # same thing in a live session
```

Per mesh object it reports (world-space, evaluated mesh unless `--no-evaluated`):

| Field | Meaning / what to check |
|---|---|
| `watertight` | every edge used exactly twice (`boundary == 0 and non_manifold == 0`) |
| `boundary_edges` | edges of a single face -> holes, open rims, un-welded mirror seams |
| `non_manifold_edges` | edges with >2 faces -> coincident shells, doubled walls, bad booleans |
| `volume`, `surface_area` | signed tetrahedron sum / triangle fan areas, world space |
| `world_bounds_min/max`, `world_size` | actual size after transforms (catches scale/unit bugs) |
| `triangles_estimate` | budget for engines/printers |
| `materials`, `modifiers`, `vertex_groups` | what a human will inherit when they open the file |
| `warnings` | unapplied transforms, no material, not in any collection, missing textures … |

The maths is exact, verified on a real Blender 5.1: a default 2 m cube reports `surface_area 24.0`,
`volume 8.0`, `watertight true`. Two implementation traps that are easy to repeat:

* volume uses `sum(v0 · (v1 × v2) / 6)` over fan triangles (origin-relative - correct only for a closed mesh);
* **area must use relative arms**: `(v1 - v0) × (v2 - v0) / 2`. Using `v1 × v2` (the volume-style shortcut)
  reported 16.97 instead of 24.0 on that same cube.

**Always compare volume with a hand calculation.** `examples/parametric_bracket.py` does:
`plate + riser - holes = 30 801.8 mm³`, measured `30 111.69 mm³` (-2.2 %, exactly the fillet material), and
reports `volume_within_6pct: true`. A 3 % band covers fillets/chamfers; 20 % means a boolean did something you
did not intend, and a negative raw value means inverted normals.

## 2. Pixels: `payloads/preview.py`

```bash
python scripts/blender_run.py --open model.blend --script payloads/preview.py -- \
       --out C:/m/shot --angles 4 --size 900
python scripts/bridge_send.py --file payloads/preview.py --opt out=C:/m/shot.png --opt angles=2   # live
```

It adds a temporary camera + world + key/fill rig, frames the evaluated bounding sphere with the camera's real
FOV (`distance = radius / tan(fov/2) * 1.1`), renders 1/2/4/6 azimuths, then restores `camera`, `engine`,
`filepath`, resolution, `film_transparent`, `view_transform` and `world` (restore **before** `orphans_purge`).
The JSON includes `engine_requested`, `engine_used`, `engine_fallback`, `engines_available`, `framed_objects`,
`center`, `radius` and per-image `checks`:

```json
"checks": { "...shot_00.png": { "ok": true, "size": [640, 360],
  "coverage": 0.181, "pixel_stats": {"min": 0.5647, "max": 1.0, "mean": 0.74},
  "subject_bbox": [190, 82, 510, 359], "framing": "ok" } }
```

`coverage` = sampled fraction of pixels differing from the corner (background) pixel; `framing` is
`too_small` (< 3 %), `ok`, `too_close` (> 92 %); `pixel_stats` distinguishes "empty because background" from
"empty because the model renders black" (`max - min < 0.01` -> single flat value -> blank). Measured runs:
default cube `0.6921`, bracket at 4 angles `0.2254 / 0.1801 / 0.1810 / 0.2262`.

Why the pixel check exists: a model that is not in the frame does not exist, and these numbers catch it
without anyone looking. **If your model can see images, also read the PNGs** - the numbers say "something is
there", the image says whether it is the right shape. Report the paths either way; the user can look.

## 3. Blank or wrong frame: triage in measured order

1. **Camera aim.** `to_track_quat` aligns the *given local axis* with the vector, so it must be
   `(target - camera.location).to_track_quat('-Z', 'Y')`. The inverted version renders a perfectly lit,
   perfectly **empty** frame (`coverage 0.0`, `pixel_stats` all background) and is the single most common
   cause - it cost an hour here.
2. **Nothing lights the model.** A metallic part (Metallic 1.0, Roughness 0.3) in the default black world
   renders pure black in EEVEE - indistinguishable from a missing model. Keep the rig on
   (drop `--no-rig` only when you intend to judge the scene's own lighting), or add a `SUN` and a
   grey `Background` world (`payloads/preview.py` sets 0.35 grey at strength 1 + suns 4.0/1.2).
3. **Engine fallback.** Blender 5.x has no Workbench (`engines_available: ["BLENDER_EEVEE"]`), so an
   engine that does not exist must not silently "work" - check `engine_fallback` in the output.
4. **Clip planes vs part scale.** For millimetre parts `clip_start = 0.1` clips the model at 30 cm framing;
   the payload sets `clip_start = max(0.0001, radius / 500)`, `clip_end = max(1000, radius * 500)`.
5. **Not in the render.** `hide_render`, `hide_viewport`, an excluded view-layer collection, or a
   `visible_camera=False` ray-visibility flag; also objects linked into a collection that is disabled in the
   view layer. The payload's `framed_objects` list tells you whether geometry was even found.
6. **Wrong place.** Geometry built in mm while the camera was framed for metres (or `dimensions` read before
   `view_layer.update()`) puts the subject 1000× off-screen; check `center`/`radius` in the JSON against the
   part's real size.
7. **Image reading.** `bpy.data.images.load(path)` needs no extra keyword; pixel data is lazy but `.pixels`
   does load it (`has_data` is `True`, values are floats 0..1, bottom-up). If you sample
   `pixels[i::N]` you are also reading the **alpha channel** (always 1.0) - step by 4 and compare RGB only,
   which is why a fully black image once looked like `max 1.0`.
8. **Ghost / duplicated geometry in the render.** The object list is clean (single collection, no duplis,
   `instance_type` all `NONE`) yet the frame shows a translucent second copy of the model, strongest near a
   large flat ground plane: EEVEE Next **Fast GI**. On a fresh 5.1 scene `scene.eevee.use_fast_gi` is `True`.
   Confirm by hiding the ground (ghost vanishes), then set `use_fast_gi = False` and re-render. Do not chase
   this with scene surgery - it is a render artifact, not duplicated data.

## 4. Screenshots of the user's viewport (live bridge)

```bash
python scripts/bridge_send.py --code "bpy.ops.object.mode_set(mode='OBJECT')" --screenshot C:/m/view.png
```

The bridge answers with `{"screenshot": {"path": ..., "ok": true, "method": "opengl"}}` (measured:
`method: opengl, ok: True` from inside a real GUI session). `SpaceView3D` has **no** `image_settings` in
4.x/5.x - the OpenGL grab writes through `scene.render.image_settings` / `scene.render.filepath`, which the
payload restores. If there is no `VIEW_3D` area or no window (`--background`), it returns
`{"ok": false, "method": "none", "detail": ...}` and falls back to a fast real render through an engine taken
from the available list.

## 5. Quality stills

`scripts/render_still.py` is the "make it pretty" path (samples, world, view transform, transparent film,
engines chosen from what is available). Use it once the geometry is verified - rendering an unverified model
faster is still wrong. `scripts/env_check.py` reports Blender/bpy version, available engines, GPU/devices,
unit settings and paths, and is the right first call on an unknown machine.
