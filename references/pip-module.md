# Blender as an installable Python module (`pip install bpy`)

Deep reference for the *pip module* route of the `bpy` skill: the version matrix, wheel constraints and the
documented `bpy` gotchas. Read this when the user wants Blender inside their own Python process, a CI job or
a web service. Otherwise prefer the live-bridge / headless-runner loops in `../SKILL.md`. Written from
`docs.blender.org/api/current` plus PyPI metadata; see `../SKILL.md` for what was executed on a real machine.


# bpy - Blender as a Python module

`bpy` is Blender compiled as an importable extension module: `pip install bpy`, then `import bpy` in any
normal Python process. It is the same data API used by add-ons, minus the window, and is meant for
pipelines, web services, batch rendering, file conversion and data visualization.

**Choose the mode first:**

| Situation | Use |
|---|---|
| Library/service/CI script that owns the process | `pip install bpy` + `import bpy` (this skill) |
| One-off script for an existing `.blend`, Blender already installed | `blender -b -noaudio file.blend --python script.py -- args` |
| Interactive add-on development inside the GUI | `~/.config/blender/.../extensions/`, not this skill |
| Control a *running* Blender GUI from outside | an RPC bridge (e.g. an addon socket server), not `bpy` |

## 1. Version and Python matrix (hard constraints)

Each Blender release supports **exactly one** CPython version; the wheel declares it as
`requires_python: "==3.13.*"`, so a mismatched interpreter fails to install/import rather than misbehaving.

| `bpy` on PyPI | Blender | CPython | Wheels | Wheel size |
|---|---|---|---|---|
| `5.2.2` (latest, 2026-09-15) | 5.2 | **3.13** | manylinux_2_28 x86_64, macos 11+ arm64, win_amd64, win_arm64 | ~383 MB |
| `5.1.2` | 5.1 | 3.13 | same | ~373 MB |
| `4.5.14` (LTS) | 4.5 LTS | **3.11** | above + macos x86_64, incl. win_arm64 | ~356 MB |
| `4.2.23` (LTS) | 4.2 LTS | **3.11** | above (no win_arm64) | ~334 MB |

Rules that follow:

- **Pin the version in production.** `bpy==5.2.2` ties your pipeline to one Blender + one Python.
- **Outside the current LTS window PyPI drops old `bpy` releases.** Install them from Blender's own index:
  ```bash
  pip install "bpy==4.2.15" --extra-index-url https://download.blender.org/pypi/
  ```
  (browsable at `https://download.blender.org/pypi/bpy/`)
- Install pulls real deps: `numpy>=2.2,<3`, `requests`, `cattrs`, `cython`, `zstandard`.
- License is GPL-3.0; that affects distribution of derivative *code*, and it is why `bpy` cannot be
  vendored into a proprietary wheel casually.
- `bpy.app.version`, `bpy.app.version_string`, `bpy.app.version_cycle` report the running Blender;
  write version guards (`if bpy.app.version >= (5, 0, 0): ...`) instead of assuming.

## 2. Install and verify

```bash
# 1) Create an interpreter with the exact minor the target bpy needs.
py -3.13 -m venv .venv-bpy && .venv-bpy\Scripts\activate        # Windows
# python3.13 -m venv .venv-bpy && source .venv-bpy/bin/activate # Linux/macOS

pip install --upgrade pip
pip install "bpy==5.2.2"          # or: bpy==4.5.14 (LTS, Python 3.11)
python -c "import bpy; print(bpy.app.version_string, bpy.app.background)"
```

Diagnostics and a full report (interpreter compatibility, installed bpy, engines, GPU, paths):

```bash
python scripts/env_check.py                       # works even when bpy is missing
python scripts/env_check.py --require 5.2         # exit 1 if unavailable
```

Common install failures are listed in [Troubleshooting](#8-troubleshooting).

## 3. Bootstrap template

`bpy` behaves like `blender --background --factory-startup`, with documented differences
(source: [Blender as a Python Module](https://docs.blender.org/api/current/info_advanced_blender_as_bpy.html)).

```python
import sys
import bpy
import mathutils                      # and gpu, mathutils.bvhtree, ...: ALWAYS after bpy
from mathutils import Vector, Matrix

# On load, bpy contains the DEFAULT STARTUP SCENE (cube, camera, light), not an empty file.
bpy.ops.wm.read_factory_settings(use_empty=True)   # <- do this first for clean builds

# Command-line args are NOT forwarded to Blender; your own args still work via sys.argv:
args = sys.argv[sys.argv.index("--")[1:] if "--" in sys.argv else 1:]

# bpy.app.binary_path is "" in the module. Set it if you need the real executable
# (subprocess renders, USD/houdini interop, tests):
import shutil
if (binary := shutil.which("blender")):
    bpy.app.binary_path = binary

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"          # see the engine note below
scene.render.resolution_x, scene.render.resolution_y = 1280, 720
scene.frame_start, scene.frame_end, scene.render.fps = 1, 120, 24
```

**Render engine identifiers differ by version.** In Blender 5.x the EEVEE enum item is
`BLENDER_EEVEE`; in 4.2-4.5 the new EEVEE is `BLENDER_EEVEE_NEXT` while legacy EEVEE was `BLENDER_EEVEE`
(removed in 4.3+). `CYCLES` and `BLENDER_WORKBENCH` are registered by bundled extensions/add-ons, so
discover at runtime instead of guessing:

```python
print([item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items])
# If CYCLES is missing, try:  import addon_utils; addon_utils.enable("cycles", default_set=True)
```

Differences from `blender -b` you must design around:

- `bpy.utils.expose_bundled_modules()` adds Blender's bundled VFX python bindings (OpenEXR/OpenImageIO/…) to `sys.path` - call it if you need them.
- Blender's own command-line switches (`--threads`, `--log`, …) have no Python equivalent.
- Signal handlers are not installed: Ctrl-C does **not** cancel a render, and no crash log is written.
- User preferences and startup file are ignored; opt back in with `bpy.ops.wm.read_userpref()` / `bpy.ops.wm.read_homefile()`.
- Only **one `.blend` at a time** per process; to work on many files use `multiprocessing` (each worker imports its own `bpy`), or `bpy.data.libraries.load()`, `BlendDataLibraries.write()`, `bpy.types.BlendData.temp_data()` for read-mostly access.
- `importlib.reload(bpy)` raises by design - reset state with `bpy.ops.wm.read_factory_settings()` instead.

## 4. Mental model

| Namespace | Role | Notes |
|---|---|---|
| `bpy.data` | the `.blend` databag: `meshes`, `objects`, `materials`, `images`, `scenes`, `node_groups`, … | creating data does **not** put it in the scene; objects must be linked into a collection |
| `bpy.context` | what is "active": `scene`, `view_layer`, `active_object`, `selected_objects`, `window`, `area`, `region` | headless has no `window`/`area`, which is why many operators' `poll()` fails |
| `bpy.ops` | user tools (add/delete/convert/render/export) | takes no object arguments - it acts on context and returns `{'FINISHED'}`/`{'CANCELLED'}` |
| `bpy.app` | process state: `version`, `background`, `binary_path`, `factory_startup`, `handlers`, `tempdir`, `cachedir`, `driver_namespace`, `debug_value` | |
| `bpy.utils` | `register_class`, `resource_path`, `blend_paths`, `refresh_script_paths`, `modules_from_path`, `expose_bundled_modules` | |
| `mathutils` | `Vector`, `Matrix`, `Quaternion`, `Euler`, `kdtree`, `bvhtree`, `geometry` | import after `bpy` |
| `bpy.props`, `bpy.types` | property/type definitions for add-on/Operator code | not needed for pure scripting |

Three things beginners get wrong, all documented in the official gotchas:

1. **Data vs evaluated data.** `obj.data`, `obj.location`, modifiers and constraints are *inputs*.
   For the computed result (after animation, modifiers, drivers) evaluate the depsgraph:
   ```python
   depsgraph = bpy.context.evaluated_depsgraph_get()
   obj_eval = obj.evaluated_get(depsgraph)
   real_mesh = bpy.data.meshes.new_from_object(obj_eval)   # snapshot you own
   ```
2. **`bpy.context.view_layer.update()`** after moving things: `matrix_world` and anything depending on it
   is stale until an update runs.
3. **IDs outlive their Python wrappers, and names are not keys.** Wrapper objects are transient, so keep
   your own `dict[str, bpy.types.Object]` mapping; `bpy.data.meshes.new(name=x)` / `obj.name = x` can
   silently change the name (length limit, duplicate -> `.001`, empty string), so `bpy.data.objects[name]`
   lookups are a bug source. Delete leftovers with `bpy.data.orphans_purge(do_recursive=True)`.

## 5. Recipes

### 5.1 Mesh from vertices/faces, no operators

```python
verts = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0), (0, 0, 1.4)]
faces = [(0, 1, 2, 3), (0, 4, 1), (1, 4, 2), (2, 4, 3), (3, 4, 0)]

mesh = bpy.data.meshes.new(name="Pyramid")          # name may be adjusted - keep the object
mesh.from_pydata(verts, [], faces)                   # from_pydata(vertices, edges, faces, shade_flat=True)
mesh.validate(verbose=True)                          # fix/reports bad geometry
mesh.update()
for polygon in mesh.polygons:
    polygon.use_smooth = True

obj = bpy.data.objects.new("Pyramid", mesh)
bpy.context.scene.collection.objects.link(obj)       # unlinked data is invisible
```

Fast bulk attribute access with NumPy (avoid per-item Python loops on big meshes):

```python
import numpy as np
co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
mesh.vertices.foreach_get("co", co)
mesh.vertices.foreach_set("co", co.reshape(-1))       # then mesh.update()
```

### 5.2 Operators + `temp_override` (context they require)

```python
bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0, 0, 0), segments=48, ring_count=24)
sphere = bpy.context.active_object

with bpy.context.temp_override(active_object=sphere, selected_editable_objects=[sphere]):
    bpy.ops.object.shade_smooth()
```

`RuntimeError: Operator ...poll() failed, context is incorrect` means the context the operator inspects
(active area type, active/selected/visible object, edit mode, image editor space, …) is missing - either
supply it via `temp_override(...)`, or prefer the data API. Some UI-bound operators (`buttons.file_browse`,
`constraint.limitdistance_reset`, `modifier_copy`, …) are not scriptable; rewrite them by hand.

### 5.3 Node material (Principled BSDF)

```python
mat = bpy.data.materials.new("Metal")
mat.use_nodes = True
tree = mat.node_tree                          # nodes + links
bsdf = tree.nodes.get("Principled BSDF")
bsdf.inputs["Base Color"].default_value = (0.8, 0.5, 0.2, 1.0)
if (key := next((k for k in ("Specular IOR Level", "Specular") if k in bsdf.inputs), None)):
    bsdf.inputs[key].default_value = 0.7      # input names changed in Blender 4.0
bsdf.inputs["Roughness"].default_value = 0.15

tex = tree.nodes.new("ShaderNodeTexNoise"); tex.inputs["Scale"].default_value = 8.0
tree.links.new(tex.outputs["Fac"], bsdf.inputs["Roughness"])
obj.data.materials.append(mat)                # or: obj.data.materials[0] = mat
```

### 5.4 Modifiers

```python
subsurf = obj.modifiers.new("Subsurf", 'SUBSURF'); subsurf.levels = subsurf.render_levels = 2
bev = obj.modifiers.new("Bevel", 'BEVEL'); bev.width = 0.05
bpy.context.view_layer.update()
```

### 5.5 Animation

```python
obj.location[2] = 0.0
obj.keyframe_insert(data_path="location", frame=1, index=2)     # index = which component
obj.location[2] = 2.5
obj.keyframe_insert(data_path="location", frame=60, index=2)

for fcurve in obj.animation_data.action.fcurves:               # 4.4+ slotted actions: action.layers/channels
    for kp in fcurve.keyframe_points:
        kp.interpolation = "CUBIC"        # valid: 'BEZIER', 'CUBIC', 'LINEAR', 'CONSTANT', 'SINE', ...
        kp.easing = 'EASE_IN_OUT'
scene.frame_set(30)                                            # evaluate + refresh depsgraph
```

Also animatable: `obj.rotation_euler`, `obj.scale`, `mat.node_tree` inputs (via
`bsdf.inputs["Roughness"].keyframe_insert("default_value", frame=…)`), `scene.frame_set()` to drive it.

### 5.6 Camera, light, and rendering

```python
cam_data = bpy.data.cameras.new("Cam"); cam_data.lens = 50
cam = bpy.data.objects.new("Cam", cam_data); scene.collection.objects.link(cam)
cam.location = (6, -6, 4); cam.rotation_euler = (1.1, 0, 0.78)
scene.camera = cam

light_data = bpy.data.lights.new("Key", 'AREA'); light_data.energy = 400; light_data.size = 3
light = bpy.data.objects.new("Key", light_data); scene.collection.objects.link(light)
light.location = (3, -3, 5)

scene.render.engine = "BLENDER_EEVEE"        # 5.x; "BLENDER_EEVEE_NEXT" on 4.2-4.5
scene.render.film_transparent = False
scene.render.use_persistent_data = True      # faster animation renders
scene.view_layers[0].use_pass_depth = True   # optional AOVs
scene.render.filepath = "/tmp/shot"          # dir/prefix; '#' pads frame numbers
scene.render.image_settings.file_format = 'PNG'
bpy.ops.render.render(write_still=True)                  # single frame -> scene.render.filepath
bpy.ops.render.render(animation=True, frame_start=1, frame_end=60)
bpy.data.images["Render Result"].save_render("/tmp/shot.png")   # explicit save
```

Cycles + GPU:

```python
scene.render.engine = "CYCLES"
scene.cycles.samples = 128
scene.cycles.use_denoising = True
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "OPTIX"          # OPTIX | CUDA | HIP | METAL | ONEAPI | NONE
prefs.get_devices()
for device in prefs.devices:
    device.use = True
scene.cycles.device = "GPU"                  # falls back silently to CPU if no device is usable
```

EEVEE needs a usable GPU/GL context; on a headless Linux box it may fail without a display-capable
driver (use `BLENDER_WORKBENCH` or CPU `CYCLES` there). Blender/Cycles can conflict with other
Python libraries holding the GPU - documented limitation of the `bpy` module.

### 5.7 `.blend` I/O, append and link

```python
bpy.ops.wm.save_as_mainfile(filepath=r"F:\out\scene.blend")   # save_mainfile() keeps the current path
bpy.ops.wm.open_mainfile(filepath=r"F:\in\other.blend")        # replaces ALL state

with bpy.data.libraries.load(r"F:\in\library.blend", link=False) as (data_from, data_to):
    data_to.objects = [n for n in data_from.objects if n.startswith("Bolt_")]
for obj in data_to.objects:                      # appended data still needs linking into the scene
    if obj is not None:
        scene.collection.objects.link(obj)
```

`link=True` keeps live references into the source file. `bpy.types.BlendData.temp_data()` gives a
temporary databag for read-only probing of ID data without touching the current file.

### 5.8 Import / export

```python
bpy.ops.import_scene.gltf(filepath="in.glb")
bpy.ops.export_scene.gltf(filepath="out.glb", export_format='GLB', export_apply=True)
bpy.ops.wm.obj_import(filepath="in.obj");  bpy.ops.wm.obj_export(filepath="out.obj")
bpy.ops.wm.usd_import(filepath="in.usd");  bpy.ops.wm.usd_export(filepath="out.usd")
bpy.ops.object.convert(target='MESH')            # apply modifiers/curves to selected objects
```

Exporter operator names live in `bpy.ops.wm.*` / `bpy.ops.export_scene.*` since Blender 3.x
(the old `io_export_wavefront` era add-ons are gone). List what exists:
`[op for op in dir(bpy.ops.export_scene) if not op.startswith("_")]`.

### 5.9 Callbacks and add-on-style registration

```python
def on_frame_change(scene, depsgraph=None):
    ...
bpy.app.handlers.frame_change_pre.append(on_frame_change)       # ..._post, render_pre, render_post,
                                                                # render_complete, depsgraph_update_post,
                                                                # save_pre/save_post, load_post, undo_post,
                                                                # redo_post, exit_pre, blend_import_post, ...
bpy.utils.register_class(MyOperator)                            # Operator/Panel classes: unregister in reverse
```

`bpy.app.driver_namespace` is the place for Python callables used by F-curve/drivers.

## 6. Performance notes

- `foreach_get`/`foreach_set` (or `mesh.vertices.foreach_set`) instead of per-vertex Python loops.
- `scene.render.use_persistent_data = True` for animation batches.
- `bpy.app.debug_value`, `bpy.app.debug_depsgraph` for debugging evaluation order.
- Set `bpy.context.view_layer.update()` only where needed; per-object updates inside tight loops are expensive.
- One `bpy` per process: parallelise with `multiprocessing`, never with threads.

## 7. Documented gotchas that bite in production

- **Python threads are unsupported.** They crash Blender in hard-to-diagnose ways (e.g. inside Cycles or
  Python drivers). Threads are only safe if they finish before your script continues
  (`thread.join()`), and while they run **nothing** may call `bpy`. Use `multiprocessing` instead.
  Beware stdlib users of hidden threads (e.g. `multiprocessing.Queue`).
- **`poll()` failures** are context problems, not bugs - read the operator's poll or use `temp_override`.
- **Never persist wrappers** of Blender data or rely on name lookups (see section 4).
- **Edit-mode mesh access**: `object_data` is not editable from the API unless the object is in edit mode
  via a real context override; build data with `from_pydata` instead.
- **`bpy.ops` return values are `FINISHED`/`CANCELLED`**, not results; check `('CANCELLED' in result)` explicitly.
- **Reloading `bpy` is unsupported** - restart the process or `read_factory_settings()`.
- **Ctrl-C / no crash handler**: for long renders install your own handling or run in a subprocess.
- **GPU contention** with other Python GPU libraries is a known limitation.
- **`bpy.app.binary_path` is empty**; set it if anything needs the real binary.
- Startup file is loaded by default - call `read_factory_settings(use_empty=True)` or your objects land
  next to the default cube.

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `pip` says no matching distribution for `bpy==5.2.2` | Wrong CPython (needs 3.13), unsupported platform (needs x86_64 Linux, win_amd64/arm64, or macOS 11+ arm64), or that release left PyPI - add `--extra-index-url https://download.blender.org/pypi/` |
| `ImportError: bpy ... cp313` / `undefined symbol` | Interpreter minor mismatch, or glibc older than the `manylinux_2_28` wheel requires |
| `ModuleNotFoundError: mathutils` (or `gpu`) | You imported it **before** `bpy`; import `bpy` first |
| `Operator ...poll() failed, context is incorrect` | Missing context - `temp_override` or use the data API |
| Empty/black render | EEVEE without a GPU/GL context → `BLENDER_WORKBENCH` or CPU `CYCLES`; or camera/light not linked into the scene |
| Nothing renders / objects missing | Data created but never linked: `scene.collection.objects.link(obj)` |
| Stale transforms | Missing `bpy.context.view_layer.update()` / depsgraph re-evaluation |
| Random segfaults | Threads touching `bpy`; or holding wrappers of freed data |
| Disk blowup | Wheels are 330-390 MB each; keep one pinned version per venv and prune |

## 9. Scripts in this skill

```bash
python scripts/env_check.py                 # interpreter/bpy/engine/GPU report (safe, read-only)
python scripts/render_still.py --engine BLENDER_EEVEE --output /tmp/shot.png
python scripts/render_still.py --engine CYCLES --samples 64 --animation --frames 1 48
# also runnable inside Blender:
blender -b --factory-startup --python scripts/render_still.py -- --engine CYCLES
```

## 10. Authoritative references

- Blender as a Python Module: https://docs.blender.org/api/current/info_advanced_blender_as_bpy.html
- Gotchas (threads, internal data, operators, meshes, armatures, encoding): https://docs.blender.org/api/current/info_gotcha.html
- API overview / how to run scripts: https://docs.blender.org/api/current/info_overview.html
- Types & operators reference: https://docs.blender.org/api/current/bpy.types.html , https://docs.blender.org/api/current/bpy.ops.html
- PyPI project (version/Python truth): https://pypi.org/project/bpy/
- Query these through context7 with library id `/websites/blender_api_current` (or `/websites/blender_api_4_5`, `/websites/blender_api_4_2` for LTS targets).
