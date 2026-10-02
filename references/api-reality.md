# Blender API reality check (measured, not remembered)

Everything here was executed against **Blender 5.1.0** (hash `adfe2921d5f3`, Windows 11) with
`scripts/blender_run.py`. Blender's API changes between majors and the docs lag the binary, so treat this as
"a sample of what to expect" and re-run the introspection recipes on the user's build before relying on a
property name. Version-specific LTS lists: `/websites/blender_api_4_2`, `/websites/blender_api_4_5` (context7).

## 1. Introspect instead of guessing

One headless run replaces five failed attempts:

```python
def props(cls):                      # what can I set on this type?
    return sorted(p.identifier for p in cls.bl_rna.properties if not p.is_readonly
                  and p.identifier not in ("bl_rna", "rna_type"))

print(props(bpy.types.BevelModifier))
print(props(type(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))))   # evaluated instance
print([i.identifier for i in scene.render.bl_rna.properties["engine"].enum_items])   # enum values
print([s.name for s in node.inputs])                    # shader sockets: match by name, names change
print([p.identifier for p in bpy.types.Object.bl_rna.properties if p.identifier.startswith("visible")])
print(bpy.ops.object.modifier_add.get_rna_type().properties["type"].enum_items)  # op enum args -> identifiers
```

Blender also tells you when you are wrong - `AttributeError: 'BevelModifier' object has no attribute 'limit'.
Did you mean: 'limit_method'?` - so always run payloads through `scripts/blender_run.py` (it adds
`--python-exit-code 1`) instead of swallowing errors.

## 2. Render engines (this is where hard-coded strings break)

| Blender | identifiers in `scene.render.bl_rna.properties["engine"].enum_items` |
|---|---|
| 4.2 LTS | `BLENDER_WORKBENCH`, `BLENDER_EEVEE_NEXT` (Workbench is `BLENDER_WORKBENCH`) |
| 4.4 / 4.5 LTS | `BLENDER_WORKBENCH`, `BLENDER_EEVEE_NEXT` (+ `CYCLES` when the extension is enabled) |
| **5.1 (measured)** | **`['BLENDER_EEVEE']` only** - Workbench is gone; EEVEE is `BLENDER_EEVEE` again; Cycles ships as an extension and is absent under `--factory-startup` |

Rules: never hard-code an engine; read the list, pick, and *report* which one you used
(`payloads/preview.py` returns `engine_requested`, `engine_used`, `engine_fallback`, `engines_available`).
`CYCLES` needs `bpy.ops.preferences.addon_enable(module="cycles")`-era workflows replaced by
`bpy.ops.extensions.package_install(repo_index=0, pkg_id="cycles")` - ask before installing anything.

Note also that `view_transform.enum_items` returned **`['NONE']`** under `--factory-startup` while
`scene.view_settings.view_transform` was `"AgX"`: that enum is filled dynamically, so do not validate view
transforms against `enum_items` - read the property, and set values inside `try/except`.

## 3. Measured property names (Blender 5.1)

`BevelModifier`: `width`, `width_pct`, `segments`, `limit_method` (**not** `limit`), `angle_limit` (radians),
`offset_type`, `profile_type`, `profile`, `spread`, `miter_outer`, `miter_inner`, `use_clamp_overlap`,
`harden_normals`, `mark_seam`, `mark_sharp`, `loop_slide`, `affect`, `vertex_group`, `invert_vertex_group`,
`face_strength_mode`, `vmesh_method`, `use_apply_on_spline`, plus the standard `show_*`/`is_active` set.

`BooleanModifier`: `operation`, `solver` (`'EXACT'`, `'FAST'`), `object`, `operand_type`, `collection`,
`use_self`, `use_hole_tolerant`, `double_threshold`, `material_mode`, `debug_options`.

`SolidifyModifier`: `thickness`, `offset`, `use_even_offset`, `use_rim`, `use_rim_only`, `rim_vertex_group`,
`shell_vertex_group`, `material_offset`, `material_offset_rim`, `use_flip_normals`, `use_quality_normals`,
`use_flat_faces`, `edge_crease_inner/outer/rim`, `solidify_mode`, `thickness_clamp`,
`nonmanifold_boundary_mode`, `nonmanifold_thickness_mode`, `nonmanifold_merge_threshold`.

`ArrayModifier`: `count`, `relative_offset_displace`, `use_relative_offset`, `constant_offset_displace`,
`use_constant_offset`, `use_object_offset`, `offset_object`, `fit_type`, `fit_length`, `merge_threshold`,
`use_merge_vertices`, `use_merge_vertices_cap`, `start_cap`, `end_cap`

`MirrorModifier`: `use_axis` (bool array), `mirror_object`, `use_mirror_x/y/z`, `use_clip`,
`merge_threshold`, `bisect_axis`, `use_bisect_axis`, `use_bisect_flip_axis`, `bisect_threshold`.

`WeldModifier`: `merge_threshold`, `loose_edges`, `mode`, `vertex_group`.

Modifier types for `modifiers.new(name, type)` (verified `modifier_add` enum, abridged):
`ARRAY BEVEL BOOLEAN BUILD DECIMATE EDGE_SPLIT NODES MASK MIRROR MESH_TO_VOLUME MULTIRES REMESH SCREW SKIN
SOLIDIFY SUBSURF TRIANGULATE VOLUME_TO_MESH WELD WIREFRAME LINEART DATA_TRANSFER MESH_CACHE UV_PROJECT
UV_WARP WEIGHTED_NORMAL NORMAL_EDIT` + many `GREASE_PENCIL_*` (the printed list was truncated by Blender's
own enum ordering; re-run the recipe for the full set).

`bpy.ops.object.convert(target=...)`: `CURVE MESH POINTCLOUD CURVES GREASEPENCIL`.
`bpy.ops.object.origin_set(type=...)`: `GEOMETRY_ORIGIN ORIGIN_GEOMETRY ORIGIN_CURSOR ORIGIN_CENTER_OF_MASS
ORIGIN_CENTER_OF_VOLUME`.
Mesh primitives: `primitive_circle_add cone_add cube_add cylinder_add grid_add ico_sphere_add monkey_add
plane_add torus_add uv_sphere_add`. Curves: `curve.primitive_bezier_curve_add`,
`primitive_bezier_circle_add`, `primitive_nurbs_curve_add`, `primitive_nurbs_circle_add`,
`primitive_nurbs_path_add`, `curve.vertex_add`. Text: `bpy.ops.object.text_add` (Font data: `body`,
`align_x`, `align_y`, `size`, `extrude`, `bevel_depth`, `space_line`).
Curve data props: `bevel_depth`, `bevel_resolution`, `extrude`, `resolution_u`, `use_fill_caps`,
`twist_mode`, `bevel_mode`, `bevel_object`.

Exporters present under `--factory-startup` on 5.1: `bpy.ops.export_scene.gltf` ✓, `bpy.ops.wm.usd_export` ✓,
`bpy.ops.export_scene.obj` ✓, `bpy.ops.export_mesh.stl` ✓.

`Object` visibility/display subset: `display_type`, `display_bounds_type`, `show_wire`, `show_bounds`,
`show_in_front`, `show_name`, `show_transparent`, `show_texture_space`, `show_only_shape_key`,
`show_instancer_for_viewport`, `show_instancer_for_render`, `visible_camera`, `visible_diffuse`,
`visible_glossy`, `visible_shadow`, `delta_location`, `delta_rotation_euler`, `delta_scale`.
**There is no `Object.display_mode`** and **`Mesh.shade_smooth` is read-only** (use `polygon.use_smooth`
or `bpy.ops.object.shade_smooth()` with a proper context).

`object.users_collection` is a **tuple of Collections**, not a count.

`object.select_get()` / `select_set(bool)` for selection; `view_layer.objects.active` for the active object.

### Principled BSDF sockets (5.1, in order)

`Base Color, Metallic, Roughness, IOR, Alpha, Normal, Weight, Diffuse Roughness, Subsurface Weight,
Subsurface Radius, Subsurface Scale, Subsurface IOR, Subsurface Anisotropy, Specular IOR Level, Specular Tint,
Anisotropic, Anisotropic Rotation, Tangent, Transmission Weight, Coat Weight, Coat Roughness, Coat IOR,
Coat Tint, Coat Normal, Sheen Weight, Sheen Roughness, Sheen Tint, Emission Color, Emission Strength,
Thin Film Thickness, Thin Film IOR`

The 4.x names `Transmission`, `Subsurface`, `Specular`, `Coat Tint`-era differences mean old snippets break:
**always test membership** - `if "Metallic" in bsdf.inputs: bsdf.inputs["Metallic"].default_value = 1.0`.
Node lookup by name (`material.node_tree.nodes["Principled BSDF"]`) raises `KeyError` when the node was
renamed or localised - use `nodes.get("Principled BSDF")` and fall back to
`next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')`.

## 4. Context: what works where (verified, including one crash)

| Where | `bpy.context.view_layer` | `bpy.context.scene` | `bpy.context.object` / `active_object` / `selected_objects` | operators |
|---|---|---|---|---|
| `blender -b -P script.py` (background) | yes | yes | yes | most object ops work |
| pip `bpy` script | yes | yes | mostly yes | poll() failures are common |
| **inside a `bpy.app.timers` callback (live bridge)** | yes | yes | **AttributeError** | ops needing an object poll() fail |

Consequences, all learned from a real failure:

* In payloads that must run in the bridge too, use `bpy.context.view_layer.objects.active`,
  `view_layer.objects` and `obj.select_get()`; do not touch `bpy.context.selected_objects`.
* `bpy.ops.object.modifier_apply` fails there with `poll() failed, context is incorrect` - bake through the
  depsgraph instead (`evaluated_get()` + `bpy.data.meshes.new_from_object(...)`; see
  `examples/parametric_bracket.py::apply_modifiers`). Elsewhere it can also return `{'CANCELLED'}` silently:
  always compare with `{"FINISHED"}`.
* `bpy.context.temp_override(window=, screen=, area=, region=)` is safe from a timer. Adding
  `view_layer=` or `scene=` to it **crashed Blender with `EXCEPTION_ACCESS_VIOLATION` inside
  `deg_check_base_in_depsgraph`** - never override the depsgraph-owned context members.
* A `bpy.app.timers` callback that raises an exception is **unregistered by Blender**: the process stays
  alive but the bridge goes permanently deaf. Wrap every callback body in `try/except` and always reply
  (`assets/live_bridge.py::_tick`).

## 5. Data-block lifetime

* `bpy.ops.wm.read_factory_settings(use_empty=True)` / `read_homefile` **destroy the current `Scene`**:
  references held across it raise `ReferenceError: StructRNA of type Scene has been removed`. Reset first,
  then look things up.
* `bpy.data.orphans_purge(do_recursive=True)` frees blocks you may still be holding - restore state, then
  purge (`payloads/preview.py` does restore-then-purge for exactly this reason).
* After `from_pydata` call `mesh.validate(verbose=False)` (truthy return means it *had* to fix something) and
  `mesh.update()`; after moving objects call `bpy.context.view_layer.update()` before reading
  `matrix_world`/`dimensions`.
* `bpy.data.images.load(filepath)` accepts only `(filepath, check_existing)` - no `check_data`.
* `World.use_nodes` is deprecated in 5.1 (removed in 6.0): guard it with `getattr`.
* Blender's Python is **not thread-safe**: never spawn threads that touch `bpy`; poll from
  `bpy.app.timers` (main thread) as the bridge does.
