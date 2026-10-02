"""Example build script: parametric L-bracket with fillets and clearance holes.

The loop this example is built around:

    python scripts/blender_run.py --script examples/parametric_bracket.py --save-as C:/m/bracket.blend
    python scripts/blender_run.py --open    C:/m/bracket.blend --script payloads/preview.py -- --out C:/m/bracket --angles 4 --light
    python scripts/blender_run.py --open    C:/m/bracket.blend --script payloads/scene_report.py -- --pretty
    python scripts/bridge_send.py --file examples/parametric_bracket.py --screenshot C:/m/bracket.png   # live session instead

Conventions that keep exported models correct (see references/modeling.md):
  * model in metres (1 Blender unit == 1 m) and convert millimetres at the borders: MM = 0.001
  * build ONE manifold solid (extrude a closed profile), never overlapping boxes - a self-intersecting
    shell makes bevel/boolean output non-manifold and blows up the bounding box
  * verify: watertight, boundary edges, and a volume that matches the hand calculation
"""

from __future__ import annotations

import json

MM = 0.001

PARAMS = {
    "name": "Bracket_L",
    "plate": (80.0, 40.0, 6.0),         # X, Y, Z in millimetres
    "riser_thickness": 6.0,
    "height": 56.0,                     # total Z including the plate
    "hole_radius": 3.25,                # M6 clearance
    "hole_count": 2,
    "hole_edge_offset": 8.0,
    "fillet": 2.0,
    "segments": 48,                     # hole tessellation
    "apply_modifiers": True,
}


def extrude_profile(profile_xz, y_min, y_max):
    """(vertices, faces) for a closed XZ profile swept along Y. Single manifold solid.

    profile_xz: list of (x, z) in order around the outline (no repeated first point).
    """
    count = len(profile_xz)
    front = [(x, y_min, z) for x, z in profile_xz]
    back = [(x, y_max, z) for x, z in profile_xz]
    verts = front + back
    faces = []
    for index in range(count):
        nxt = (index + 1) % count
        faces.append((index, nxt, count + nxt, count + index))       # side quads, outward if profile is CCW in XZ
    faces.append(tuple(reversed(range(count))))                       # -Y cap
    faces.append(tuple(range(count, 2 * count)))                      # +Y cap
    return verts, faces


def build(bpy, params):
    """Build the bracket and return the finished object."""
    ops = bpy.ops
    # Reset FIRST, then look anything up: read_factory_settings destroys the old Scene, so references
    # held across it raise "StructRNA of type Scene has been removed".
    ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"          # 1 unit == 1 m; mm is a reporting unit only

    plate_x, plate_y, plate_z = params["plate"]
    riser_t = params["riser_thickness"]
    total_z = params["height"]

    # L cross-section in XZ, counter-clockwise so the swept normals face outward.
    profile = [
        (0.0, 0.0),
        (plate_x, 0.0),
        (plate_x, total_z),
        (plate_x - riser_t, total_z),
        (plate_x - riser_t, plate_z),
        (0.0, plate_z),
    ]
    verts, faces = extrude_profile(profile, -plate_y / 2.0, plate_y / 2.0)

    mesh = bpy.data.meshes.new(f"{params['name']}_mesh")
    mesh.from_pydata([(x * MM, y * MM, z * MM) for x, y, z in verts], [], faces)
    if mesh.validate(verbose=False):
        raise RuntimeError(f"{params['name']}: from_pydata produced invalid geometry")
    mesh.update()

    obj = bpy.data.objects.new(params["name"], mesh)
    scene.collection.objects.link(obj)
    bpy.context.view_layer.update()

    fillet = obj.modifiers.new("Fillet", 'BEVEL')
    fillet.width = params["fillet"] * MM
    fillet.segments = 3
    fillet.limit_method = 'ANGLE'                  # verified RNA: limit_method (there is no `limit`)
    fillet.angle_limit = 0.785398                   # 45 degrees, in radians
    fillet.miter_outer = 'MITER_ARC'
    fillet.use_clamp_overlap = True

    # Clearance holes through the plate: cylinders as EXACT-boolean cutters, deleted after the apply.
    spacing = ((plate_y - 2 * params["hole_edge_offset"]) / (params["hole_count"] - 1)
               if params["hole_count"] > 1 else 0.0)
    cutters = []
    for index in range(params["hole_count"]):
        y_mm = -plate_y / 2 + params["hole_edge_offset"] + index * spacing
        ops.mesh.primitive_cylinder_add(radius=params["hole_radius"] * MM,
                                        depth=(plate_z + 20) * MM,
                                        vertices=params["segments"],
                                        location=(params["hole_edge_offset"] * MM, y_mm * MM, plate_z / 2 * MM))
        cutter = bpy.context.view_layer.objects.active   # Context has no active_object in Blender 5.x
        cutter.name = f"{params['name']}_cut_{index + 1}"
        cutters.append(cutter)

        boolean = obj.modifiers.new(cutter.name, 'BOOLEAN')
        boolean.operation = 'DIFFERENCE'
        boolean.solver = 'EXACT'                    # FAST is the legacy float solver: not for manufacturing
        boolean.object = cutter
        boolean.use_self = True

    if params["apply_modifiers"]:
        apply_modifiers(bpy, obj)

    for cutter in cutters:
        bpy.data.objects.remove(cutter, do_unlink=True)
    bpy.data.orphans_purge(do_recursive=True)

    material = bpy.data.materials.new(f"{params['name']}_alu")
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.62, 0.63, 0.65, 1.0)
    for socket_name, value in (("Metallic", 1.0), ("Roughness", 0.3)):
        if socket_name in bsdf.inputs:
            bsdf.inputs[socket_name].default_value = value
    obj.data.materials.append(material)
    return obj


def apply_modifiers(bpy, obj):
    """Bake the modifier stack into the mesh without operators.

    `bpy.ops.object.modifier_apply` polls the context and fails with "poll() failed, context is
    incorrect" when called from a GUI timer (e.g. the live bridge), and silently returns
    {'CANCELLED'} whenever the object is not visible+active+selected. The depsgraph route needs no
    context at all, so it behaves identically in the bridge, in `blender -b -P` and in pip `bpy`.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    baked = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
    previous = obj.data
    obj.data = baked
    for modifier in list(obj.modifiers):
        obj.modifiers.remove(modifier)
    if previous.users == 0:
        bpy.data.meshes.remove(previous)
    bpy.context.view_layer.update()


def find_layer_collection(bpy, collection):
    """Objects in excluded/hidden collections cannot be edited - resolve the view-layer copy."""
    def walk(layer_collection):
        if layer_collection.collection == collection:
            return layer_collection
        for child in layer_collection.children:
            if (found := walk(child)) is not None:
                return found
        return None
    return walk(bpy.context.view_layer.layer_collection) or bpy.context.view_layer.layer_collection


def geometry_report(bpy, obj):
    """Dimensions, volume, area and a watertightness verdict - check these before exporting."""
    import mathutils
    mesh = obj.data
    verts = [obj.matrix_world @ mathutils.Vector(vertex.co) for vertex in mesh.vertices]

    area = 0.0
    volume = 0.0
    for polygon in mesh.polygons:
        points = [verts[index] for index in polygon.vertices]
        for index in range(1, len(points) - 1):
            first, middle, last = points[0], points[index], points[index + 1]
            volume += first.dot(middle.cross(last)) / 6.0                     # signed tetrahedron sum
            area += (middle - first).cross((last - first)).length / 2.0       # fan triangles, relative arms

    edge_faces: dict = {}
    for polygon in mesh.polygons:
        for key in polygon.edge_keys:
            edge_faces[key] = edge_faces.get(key, 0) + 1
    boundary = sum(1 for count in edge_faces.values() if count == 1)
    non_manifold = sum(1 for count in edge_faces.values() if count > 2)

    return {
        "object": obj.name,
        "vertices": len(mesh.vertices),
        "polygons": len(mesh.polygons),
        "watertight": boundary == 0 and non_manifold == 0,
        "boundary_edges": boundary,
        "non_manifold_edges": non_manifold,
        "size_mm": [round(value / MM, 3) for value in obj.dimensions],
        "volume_mm3": round(abs(volume) / (MM ** 3), 2),
        "surface_area_mm2": round(area / (MM ** 2), 2),
        "modifiers_left": [modifier.name for modifier in obj.modifiers],
    }


def main() -> int:
    import bpy
    obj = build(bpy, PARAMS)
    report = geometry_report(bpy, obj)

    # Self-check against the hand calculation, so a silent modelling bug cannot ship.
    plate_x, plate_y, plate_z = PARAMS["plate"]
    expected = plate_x * plate_y * plate_z + PARAMS["riser_thickness"] * plate_y * (PARAMS["height"] - plate_z)
    holes = PARAMS["hole_count"] * 3.141592653589793 * PARAMS["hole_radius"] ** 2 * plate_z
    tolerance = (expected - holes) * 0.06          # fillets and hole chamfers shave a few percent
    report["expected_volume_mm3"] = round(expected - holes, 2)
    report["volume_within_6pct"] = abs(report["volume_mm3"] - (expected - holes)) <= tolerance

    print(json.dumps({"ok": bool(report["watertight"] and report["volume_within_6pct"]),
                      "object": obj.name, "report": report}, indent=2))
    return 0 if report["watertight"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
