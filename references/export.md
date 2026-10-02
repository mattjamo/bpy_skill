# Export: getting the model out intact (measured on Blender 5.1)

## Which exporters actually exist

Verified with `bpy.ops.<x>.get_rna_type()` under `--factory-startup`:

| Operator | 5.1 | Notes |
|---|---|---|
| `bpy.ops.export_scene.gltf` | ✅ registered | glTF 2.0 / GLB; `export_format` in `GLB`, `GLTF_SEPARATE`, `GLTF_EMBEDDED` |
| `bpy.ops.wm.usd_export` | ✅ registered | USD `.usda/.usdc/.usdz`, optional MaterialX materials |
| `bpy.ops.wm.obj_export` | ✅ registered | the modern C++ OBJ exporter |
| `bpy.ops.wm.stl_export` | ✅ registered | the modern C++ STL exporter (printing) |
| `bpy.ops.wm.ply_export` | ✅ registered | point clouds / scans |
| `bpy.ops.export_scene.obj` | ❌ **missing** | legacy Python add-on - now an extension |
| `bpy.ops.export_mesh.stl` | ❌ **missing** | same story |

**`hasattr(bpy.ops.export_mesh, "stl")` returns `True` even though the operator does not exist** (operator
modules resolve attributes dynamically). Never probe exporters with `hasattr` - use
`bpy.ops.export_scene.obj.get_rna_type()` inside `try/except KeyError`, or just call it and catch
`AttributeError: ... error, could not be found`. Old tutorials' `export_scene.obj(...)` / `export_mesh.stl(...)`
calls fail on 5.x with exactly that message; use the `wm.*` replacements. Missing exporters can be installed
with `bpy.ops.extensions.package_install(repo_index=0, pkg_id="obj")` - ask first, it hits the network.

Measured key properties (from the operators' own RNA):

| Exporter | selection | axes / scale | modifiers / materials |
|---|---|---|---|
| `wm.obj_export` | `export_selected_objects` | `forward_axis`, `up_axis`, `global_scale` | `apply_modifiers`, `apply_transform`, `export_eval_mode`, `export_materials`, `export_material_groups`, `export_triangulated_mesh` |
| `wm.stl_export` | `export_selected_objects` | `forward_axis`, `up_axis`, `global_scale`, `use_scene_unit` | `apply_modifiers` |
| `wm.ply_export` | `export_selected_objects` | `forward_axis`, `up_axis`, `global_scale` | `apply_modifiers`, `export_triangulated_mesh` |
| `wm.usd_export` | `selected_objects_only` | `export_global_forward_selection`, `export_global_up_selection` | `evaluation_mode`, `export_materials`, `generate_materialx_network`, `export_meshes`, `triangulate_meshes`, `export_animation`, `export_uvmaps`, `export_normals`, `export_shapekeys…` |
| `export_scene.gltf` | `use_selection` | (fixed glTF convention: +Y up, -Z forward; `export_yup=True` is the default) | `export_apply`, `export_format`, `export_image_format`, `export_texture_dir`, `export_use_gltfpack`, **`export_materials` is an enum**, not a bool: `EXPORT`, `PLACEHOLDER`, `VIEWPORT`, `NONE` (default off-ish: a round-trip without it returned 0 materials, and `export_materials=True` raises `TypeError: Converting py args to operator properties: expected a string enum, not bool`) |

Reference run (watertight 80 × 40 × 56 mm bracket, one material, 250 polygons):
`bracket.glb` = 33 348 B via `gltf(filepath=..., export_format='GLB', use_selection=True, export_apply=True)`,
`bracket.usda` = 68 951 B via `wm.usd_export(filepath=..., selected_objects_only=True)` (92 ms). Both
`use_selection` / `selected_objects_only` worked as documented, and `export_scene.obj` / `export_mesh.stl`
failed with "could not be found" as tabled above.

## Recipe

```python
import bpy
from mathutils import Matrix

def prepare(obj):
    """Selection-clean, transform-baked, modifier-baked export copy of the geometry."""
    for other in bpy.context.view_layer.objects:
        other.select_set(other is obj)
    bpy.context.view_layer.objects.active = obj
    return obj

obj = prepare(bpy.data.objects["Bracket_L"])
bpy.ops.export_scene.gltf(filepath="C:/m/bracket.glb", export_format='GLB',
                          use_selection=True, export_apply=True)
bpy.ops.wm.stl_export(filepath="C:/m/bracket.stl", export_selected_objects=True,
                      global_scale=1000.0, apply_modifiers=True)     # slicers expect mm
bpy.ops.wm.obj_export(filepath="C:/m/bracket.obj", export_selected_objects=True,
                      forward_axis='-Y', up_axis='Z', apply_modifiers=True)
bpy.ops.wm.usd_export(filepath="C:/m/bracket.usda", selected_objects_only=True)
```

Rules that prevent "the model is tiny/upside-down/missing" in the next tool:

1. **Verify before exporting**, not after: `payloads/scene_report.py` (watertight, dimensions, volume vs hand
   calculation) and one `payloads/preview.py` pass. Exporting an unverified model just moves the bug.
2. **Units are a contract.** Build in metres (1 BU = 1 m). glTF/USD stay metric; STL has no unit, so decide
   with the consumer: `global_scale=1000` for millimetre-assuming slicers, `1.0` for metre-based engines.
   `use_scene_unit` (STL) derives the scale from `scene.unit_settings.scale_length` - only sensible if you did
   *not* pre-scale your coordinates.
3. **Bake transforms.** Non-uniform or unapplied scale exports as wrong size and/or broken normals. Either
   `apply_modifiers=True`/`export_apply=True` plus a clean `matrix_world`, or bake explicitly:
   `obj.data.transform(obj.matrix_world); obj.matrix_world = Matrix.Identity(4)`.
4. **Select explicitly.** `use_selection=True` with a stale selection exports the wrong objects (or nothing).
   Set the selection yourself right before the call; do not rely on what the user had clicked.
5. **Axis conventions differ.** glTF is always +Y up / -Z forward (the exporter converts). For CAD/DCC targets
   pick `forward_axis`/`up_axis` deliberately (`-Y`/`Z` is the common CAD/FBX-style pair) and tell the user
   which you chose.
6. **Materials survive only partially.** glTF carries Principled values + image textures (it merges the node
   tree into a glTF Material); USD does it via MaterialX (`generate_materialx_network=True`); OBJ gives you a
   `.mtl` with base colour/roughness approximations; **STL carries no material at all**.
7. **Triangulate for consumers that need it** (`export_triangulated_mesh` on OBJ/PLY) but keep the quad mesh
   in the `.blend` you hand back to a human.
8. **Round-trip check.** Re-import the exported file into a clean Blender and compare vertex count and
   dimensions - it catches unit, axis and modifier mistakes in seconds:

```python
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath="C:/m/bracket.glb")          # glTF importer is present in 5.1
obj = bpy.context.view_layer.objects.active
print(obj.name, tuple(round(v, 4) for v in obj.dimensions))      # expect ~(0.08, 0.04, 0.056) m
```

9. **Animation**: `export_scene.gltf(export_animation_mode=...)` and `wm.usd_export(export_animation=True)`;
   for a game engine, export the rig + actions as glTF and keep `.blend` as the source of truth.
10. **Keep the `.blend`.** Always `--save-as model.blend` alongside the export; it is the only format that
    retains the modifier stack, node setups and collections for the next iteration.
