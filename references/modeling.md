# Modelling: turning requirements into manifold geometry

Pick a construction method, build one manifold solid, verify, look. Roughly in that order of preference:

| Need | Method |
|---|---|
| Exact numeric control, no UI, deterministic output | `mesh.from_pydata(verts, edges, faces)` (+ modifiers) - the default in this skill |
| Local edits, extrudes, bevels, booleans on a mesh you already have | `bmesh` + `bmesh.ops.*` (no context needed, works everywhere) |
| Standard shapes quickly | `bpy.ops.mesh.primitive_*_add(...)` (needs an operator context; fine in `-b` and in the bridge) |
| Round/organic sections, swept profiles, text | curve/font data (`bevel_depth`, `extrude`, `bevel_object`) then `object.convert(target='MESH')` |
| Procedural, parametric, instancing, user-editable setups | Geometry Nodes modifier (`modifiers.new("GN", 'NODES')` + `modifier.node_group`) |
| Print/game export of an existing model | `object.convert(target='MESH')` + modifiers baked through the depsgraph |

## 1. Mesh from data (the workhorse)

```python
mesh = bpy.data.meshes.new("Part_mesh")
mesh.from_pydata([(x * MM, y * MM, z * MM) for x, y, z in verts], [], faces)
if mesh.validate(verbose=False):          # truthy => it had to repair something: your indices are wrong
    raise RuntimeError("invalid geometry")
mesh.update()
obj = bpy.data.objects.new("Part", mesh)
scene.collection.objects.link(obj)        # or a dedicated child collection, see section 5
bpy.context.view_layer.update()           # before reading matrix_world / dimensions / bound_box
```

Three rules that decide whether the result is usable:

* **Face winding defines the normal.** Quads must be consistently counter-clockwise when viewed from outside;
  fix a whole mesh with `bmesh.ops.recalc_face_normals(bm, faces=bm.faces)` (or check `polygon.center` and
  `polygon.normal` per face). Inverted normals show up as a *negative* volume in the report and as black faces.
* **One closed shell per solid.** Do not model a bracket as two overlapping boxes: coincident faces give you
  boundary + non-manifold edges (measured: 24 + 36 on such a part) and bevels explode past the bounding box.
  Build an L cross-section and sweep it (`examples/parametric_bracket.py::extrude_profile`), or union the
  boxes with an `EXACT` boolean.
* **Edges must be shared.** If the same corner exists twice as two vertices, modifiers split and the mesh is
  not watertight: `bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)`, then `dissolve_degenerate`.

Useful `from_pydata` patterns: axis-aligned `box(center, size)`, `extrude_profile(profile_xz, y_min, y_max)`
for any prismatic part, `revolve(profile_xz, segments)` for shafts/bushings, and a grid loop for shells;
each returns `(verts, faces)` with an index offset when merged (`join_parts`).

## 2. bmesh for local operations

```python
import bmesh
bm = bmesh.new(); bm.from_mesh(obj.data)
bmesh.ops.bevel(bm, geom=list(bm.edges), affect='EDGES', offset=0.002, segments=3, profile=0.5,
                clamp_overlap=True)
bmesh.ops.solidify(bm, geom=list(bm.faces), thickness=0.003)
bmesh.ops.dissolve_limit(bm, angle_limit=0.035, verts=bm.verts, edges=bm.edges)
bm.normal_update()
bm.to_mesh(obj.data); bm.free(); obj.data.update()
```

`bmesh` is the right tool when the operation depends on the mesh you already built (select edges by angle,
islands, or boundary). No context, no undo pollution, and safe in the live bridge. Always `bm.free()`.
Read `bmesh.types.BMVert/BMEdge/BMFace` attributes (`is_boundary`, `is_manifold`, `link_faces`, `calc_length`,
`calc_area`, `index`) instead of hand-rolling adjacency - the verifier in `payloads/scene_report.py` shows the
manual version only because it must work on any input.

## 3. Modifiers, fillets and holes

Order matters and is the #1 silent modelling bug: **boolean first, fillet last** (a fillet before a boolean
gets cut in half), or apply the fillet to specific edges via a vertex group (`vertex_group` +
`invert_vertex_group` on `BevelModifier`).

```python
bevel = obj.modifiers.new("Fillet", 'BEVEL')
bevel.width, bevel.segments = 0.002, 3
bevel.limit_method = 'ANGLE'                  # verified name; `limit` does not exist
bevel.angle_limit = 0.785398                  # radians (45 deg)
bevel.miter_outer = 'MITER_ARC'
bevel.use_clamp_overlap = True

hole = obj.modifiers.new("Hole_1", 'BOOLEAN')
hole.operation, hole.solver, hole.object, hole.use_self = 'DIFFERENCE', 'EXACT', cutter, True
```

Cutter rules (each one is a real failure mode): the cutter must be a **closed manifold**; it must **pass
through both surfaces** with margin (`depth = plate_thickness + 20 mm`); use `solver='EXACT'` for anything a
human will manufacture (`FAST` is the legacy float solver and produces junk on coplanar faces); `use_self=True`
when the cutter self-intersects or the target is non-convex; delete the cutters and `orphans_purge` afterwards.

Bake the stack **without operators** so the same payload works in the bridge, in `-b` and in pip `bpy`:

```python
depsgraph = bpy.context.evaluated_depsgraph_get()
baked = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph),
                                       preserve_all_data_layers=True, depsgraph=depsgraph)
previous, obj.data = obj.data, baked
for modifier in list(obj.modifiers):
    obj.modifiers.remove(modifier)
if previous.users == 0:
    bpy.data.meshes.remove(previous)
```

If you must use the operator (`bpy.ops.object.modifier_apply`) remember it can return `{'CANCELLED'}` with no
exception, and it needs the object **visible, active, selected, in OBJECT mode**, in a *non-excluded*
view-layer collection.

## 4. Units and transforms

* Work in **metres = Blender units** and convert millimetres at the borders (`MM = 0.001`). Exporters
  (glTF/USD/OBJ/STL) and game engines assume metres.
* **Never** combine `unit_settings.scale_length = 0.001` with pre-multiplied coordinates - you scale twice.
  Either: `scale_length = 0.001` *and* build in raw mm numbers (nice UI readouts), or default
  `scale_length = 1.0` *and* build in metres (what the example does; mm is a reporting unit only).
* Set `scene.unit_settings.system = 'METRIC'`, `length_unit = 'MILLIMETERS'` (or `'METERS'`) for the user's
  sake only - it changes no numbers.
* Unapplied transforms are the classic export bug: a mesh whose `obj.scale` is `(0.08, 0.08, 0.08)` exports at
  the wrong size or with non-uniform normals. Bake with
  `bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)` (operator context!) or,
  context-free: `obj.data.transform(obj.matrix_world); obj.matrix_world = Matrix.Identity(4)`.
  Then `origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')` if the pivot should sit on the part.
* Check afterwards: `dimensions`, `matrix_world`, and `payloads/scene_report.py`, which warns about
  unapplied transforms on root objects.

## 5. Structure that survives editing

* Put modelled parts in a named **child** collection: `col = bpy.data.collections.new("Bracket");
  scene.collection.children.link(col); col.objects.link(obj)`. Objects linked only into
  `scene.collection` *do* render, but child collections are what you can hide/exclude/instanced-link and what
  exporters can select.
* Ops that edit an object require its layer collection:
  `view_layer.active_layer_collection = <the one whose .collection == obj.users_collection[0]>`
  (`examples/parametric_bracket.py::find_layer_collection` walks the tree).
* Deterministic names (`f"{part}_{index:02d}"`, `f"{part}_cut_{n}"`) make scripts idempotent; look things up
  with `bpy.data.objects.get(name)` and clear by prefix instead of assuming a clean scene.
* Name the mesh `f"{obj.name}_mesh"`, materials `f"{obj.name}_alu"` - orphan cleanup and `orphans_purge`
  depend on nothing else holding them.
* One object per material per part is simpler than `polygon.material_index`, but for multi-material parts set
  `polygon.material_index` explicitly and keep `mesh.materials` in a known order.
* `bpy.data.orphans_purge(do_recursive=True)` at the end of a build - but **after** you restored any references
  you still need (see `references/api-reality.md` §5).

## 6. Curves, text, and "CAD-ish" extras

* Pipe/rod/wire: curve data with `bevel_depth` + `bevel_resolution` + `use_fill_caps`, or `extrude` for a flat
  ribbon; `bevel_object` for a profile. Convert with `bpy.ops.object.convert(target='MESH')` before export.
* Text (labels, engraving, part numbers): `bpy.ops.object.text_add()` then `obj.data.body`, `align_x`,
  `size`, `extrude` (thickness), `bevel_depth` (edge roundness); convert to mesh for export, or boolean it
  into the part for a real engraving (negative depth + `EXACT` difference).
* Stamps/patterns: `ARRAY` with `use_object_offset` (an empty carrying the transform) rather than loops of
  duplicated objects; `MIRROR` with `use_clip=True` for symmetric halves; `WELD`/`remove_doubles` after
  mirroring.
* Surface finish / fillet networks you cannot parametrically control: Geometry Nodes
  (`modifiers.new("GN", 'NODES')` + a node group you build with `bpy.data.node_groups.new(...)`); keep it in a
  single modifier so a human can tweak it later.
* 3D-print-ready means: single manifold, outward normals, no zero-area faces, wall thickness >= ~1.2 mm for
  FDM, exported as STL/3MF with the object at the origin and the print bed below Z=0.

## 7. Before you say "done"

```
1. payloads/scene_report.py            watertight, boundary == 0, non_manifold == 0, no unapplied transforms
2. hand-computed volume vs measured    parametric_bracket.py asserts within 6%  (measured delta: 2.2%)
3. payloads/preview.py --angles 4      framing "ok", coverage sane, and look at the PNG if you can see images
4. dimensions vs the spec              80.0 x 40.0 x 56.0 mm, not 79999.994
5. exporters you plan to use           see references/export.md (selection-only, +Y up, applied transforms)
```

For concepts and signatures use context7 with `/websites/blender_api_current` (manuals for
`/websites/blender_api_4_2`, `/websites/blender_api_4_5`), and confirm the exact property against the local
binary with the recipes in `references/api-reality.md`.
