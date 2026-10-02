"""Pac-Man as a spherical 3D ball: a UV sphere with an azimuthal wedge (the mouth) removed,
rounded mouth edges, and two lens-shaped eyes pressed into the surface.

    python scripts/bridge_send.py --file examples/pacman_ball.py --screenshot C:/m/pacman_ball.png
    python scripts/bridge_send.py --file examples/pacman_ball.py         --opt mouth_degrees=90 --opt eye_spread_deg=26 --opt eye_radius=0.13
    python scripts/blender_run.py --script pacman_ball.py --save-as C:/m/pacman_ball.blend

Why built from trig instead of a boolean: `sphere MINUS wedge` as a boolean is exactly the case
where the legacy FAST solver produces junk (the cutter's apex sits at the sphere centre, so the
cut is degenerate at a point). Sweeping the grid instead gives an exactly closed mesh by
construction: the removed wedge is simply not generated, and its two flat faces are fans from the
sphere centre (a half-disc is the set of points along the arc directions from the centre).

Volume check: an azimuthal sector of a ball holds exactly (m / 2*pi) of the volume, independent of
the angle, so the expected body volume is analytic.
"""

from __future__ import annotations

import json
import math

PARAMS = {
    "name": "PacmanBall",
    "radius": 0.50,
    "mouth_degrees": 70.0,
    "mouth_centre_deg": 0.0,          # mouth opens towards +X
    "azimuth_segments": 96,
    "polar_segments": 48,
    "wedge_hinge": "y",               # "y" => mouth opens towards +X with jaws above/below it
                                      # "z" => arcade top-view (hinge vertical, no "above the mouth")
    "mouth_bevel": 0.018,
    "bevel_segments": 3,
    "eye_up_tilt_deg": 62.0,          # rotation of the eye direction up from the mouth direction
                                      # (arcade sprite puts the eye ~60-70 deg from the mouth axis;
                                      #  47 deg measured only 0.026 of the frame above the upper lip)
    "eye_spread_deg": 21.0,           # roll of each eye about the mouth axis (+-). Measured surface
                                      # separation = 2x asin(...) => +-21 deg gives a ~10 deg gap
                                      # between the lenses (13 deg wide each).
    "eye_radius": 0.115,
    "eye_sink": 0.30,                 # fraction of eye radius buried in the ball
    "eye_flatten": 0.38,              # squashed along the surface normal -> lens, not marble
    "eye_segments": 40,
    "pupil_segments": 20,
    "body_color": (0.93, 0.78, 0.03),
    "eye_color": (0.98, 0.98, 0.98),
    "pupil": True,
    "pupil_radius": 0.048,
    "pupil_flatten": 0.18,            # pupils are lenses too, just flatter than the eyes
    "pupil_embed": 0.60,              # fraction of the pupil's own half-thickness buried in the eye
    "pupil_drop_deg": 4.0,            # rotate the pupil towards the mouth (eyes read 'up' otherwise)
    "pupil_color": (0.01, 0.01, 0.01),
}


def unit(elevation_deg: float, azimuth_deg: float):
    el, az = math.radians(elevation_deg), math.radians(azimuth_deg)
    return (math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))


def eye_direction(up_tilt_deg: float, spread_deg: float):
    """Unit vector for an eye: rotate the mouth direction (+X) up, then spread it sideways.

    Defined *relative to the mouth* on purpose - an eye placed by absolute azimuth/elevation is what
    put both eyes 90 deg away from the mouth in the first revision (azimuth is measured about the
    hinge, so 'over the mouth' is an elevation offset from the mouth direction, not an azimuth one).
    """
    # Roll about the MOUTH axis (+X), not yaw about world Z. Yaw at 62 deg elevation moves an eye
    # only sin(elevation)-discounted along a small circle: +-13 deg yaw measured as 9.1 deg of real
    # angular separation, while each lens is 13 deg wide - the eyes were literally overlapping.
    # Rolling about +X keeps the angular distance from the mouth direction and spaces them properly.
    up, roll = math.radians(up_tilt_deg), math.radians(spread_deg)
    return (math.cos(up), -math.sin(up) * math.sin(roll), math.sin(up) * math.cos(roll))


def apply_hinge(verts, hinge: str):
    """Rotate the generated ball so the wedge hinge runs along the requested axis.

    The grid is generated with the hinge on Z (arcade top-view). Rotating +90 deg about X maps
    Z -> -Y (hinge lateral, through the ears) and keeps +X as the mouth direction, so the wedge
    becomes a mouth with an upper and a lower jaw - and 'above the mouth' becomes a real place.
    """
    if hinge == "z":
        return verts
    return [(x, -z, y) for x, y, z in verts]


def ball_mesh_data(params):
    """(verts, faces, debug) for a ball with the azimuthal sector [mouth_centre + m/2, ... + 2pi) kept."""
    radius = params["radius"]
    mouth = math.radians(params["mouth_degrees"])
    start = math.radians(params["mouth_centre_deg"]) + mouth / 2.0
    sweep = 2.0 * math.pi - mouth
    columns = max(3, int(params["azimuth_segments"]) + 1)     # +1: the seam is the mouth, not welded
    rows = max(2, int(params["polar_segments"])) + 1          # poles included

    verts = [(0.0, 0.0, radius), (0.0, 0.0, -radius), (0.0, 0.0, 0.0)]   # 0 N, 1 S, 2 centre
    index_of = {}
    for row in range(1, rows):                               # skip the pole rows
        polar = math.pi * row / rows                         # 0 = north pole
        z = radius * math.cos(polar)
        ring = radius * math.sin(polar)
        for column in range(columns):
            angle = start + sweep * column / (columns - 1)
            index_of[(row, column)] = len(verts)
            verts.append((ring * math.cos(angle), ring * math.sin(angle), z))

    # Pole fans, written without index offsets: the north fan hangs off the FIRST ring (row 1),
    # the south fan off the LAST ring (row rows-1). Two off-by-one variants of this each cost a
    # watertightness failure - 96 non-manifold edges (duplicated ring) + boundary edges at the pole.
    def ring(row, column):
        return index_of[(row, column)]

    faces = []
    for column in range(columns - 1):
        faces.append((0, ring(1, column + 1), ring(1, column)))                 # north pole fan
        faces.append((1, ring(rows - 1, column), ring(rows - 1, column + 1)))   # south pole fan

    for row in range(1, rows - 1):
        for column in range(columns - 1):
            a, b = ring(row, column), ring(row, column + 1)
            c, d = ring(row + 1, column + 1), ring(row + 1, column)
            faces.append((a, b, c, d))

    # The two flat mouth faces: half-discs from pole to pole, triangulated as fans from the centre.
    # The poles MUST be in this ring: the half-disc's straight edge is the whole N-S axis, and its
    # curved edge runs pole -> ring -> pole. Omitting them leaves 4 boundary edges (and the bevel
    # multiplies them), which is exactly how this file first reported 112 boundary / 96 non-manifold.
    for column in (0, columns - 1):
        arc = [0] + [index_of[(row, column)] for row in range(1, rows)] + [1]
        for position in range(len(arc) - 1):
            faces.append((2, arc[position], arc[position + 1]) if column == 0
                         else (2, arc[position + 1], arc[position]))
    verts = apply_hinge(verts, params.get("wedge_hinge", "y"))
    return verts, faces, {"verts": len(verts), "faces": len(faces)}


def build(bpy, params):
    """Returns {'body': obj, 'eyes': [obj, ...]} - body is one closed manifold."""
    import bmesh

    ops = bpy.ops
    ops.wm.read_factory_settings(use_empty=True)             # reset before any lookup
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"

    collection = bpy.data.collections.new(params["name"])
    scene.collection.children.link(collection)

    verts, faces, _info = ball_mesh_data(params)
    mesh = bpy.data.meshes.new(f"{params['name']}_mesh")
    bm = bmesh.new()
    bm_verts = [bm.verts.new(co) for co in verts]
    for face in faces:
        try:
            bm.faces.new([bm_verts[i] for i in face])
        except ValueError:
            pass                                             # duplicate face guard
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)         # outward for a closed mesh
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    if mesh.validate(verbose=False):
        raise RuntimeError("ball mesh needed repair - check the ring indexing")
    mesh.update()

    body = bpy.data.objects.new(params["name"], mesh)
    collection.objects.link(body)

    bevel = body.modifiers.new("Mouth", 'BEVEL')
    bevel.width = params["mouth_bevel"]
    bevel.segments = int(params["bevel_segments"])
    bevel.limit_method = 'ANGLE'                             # verified: not 'limit'
    bevel.angle_limit = math.radians(35.0)
    bevel.use_clamp_overlap = True
    bake_modifiers(bpy, body)

    radius = params["radius"]
    eye_objects = []
    for side, sign in (("L", 1.0), ("R", -1.0)):
        direction = eye_direction(params["eye_up_tilt_deg"], sign * params["eye_spread_deg"])
        centre = eye_centre(direction, radius, params)
        eye = add_lens(bpy, collection, f"{params['name']}_Eye_{side}", centre, direction, params)
        eye_objects.append(eye)
        if params.get("pupil"):
            # The lens apex is MEASURED off the eye mesh, not estimated. The earlier estimate used
            # eye_radius * (1 - eye_flatten), but the lens is squashed ALONG the normal, so the real
            # apex is centre + r * flatten: 9 mm above the ball instead of the assumed 37 mm, and the
            # pupils shipped ~20 mm in front of the eyes (visible as floating dots).
            from mathutils import Vector as _Vector
            pupil_direction = _Vector(eye_direction(params["eye_up_tilt_deg"] - params["pupil_drop_deg"],
                                                     sign * params["eye_spread_deg"]))
            apex = surface_offset(eye, pupil_direction)
            half_thickness = params["pupil_radius"] * params["pupil_flatten"]
            offset = apex - params["pupil_embed"] * half_thickness
            eye_objects.append(add_lens(bpy, collection, f"{params['name']}_Pupil_{side}",
                                        tuple(component * offset for component in pupil_direction),
                                        tuple(pupil_direction), params, radius=params["pupil_radius"],
                                        flatten=params["pupil_flatten"], color=params["pupil_color"],
                                        segments=params["pupil_segments"]))

    body.data.materials.append(solid_material(bpy, f"{params['name']}_yellow", params["body_color"]))
    shade_by_radius(body, radius)
    bpy.context.view_layer.update()
    return {"body": body, "eyes": eye_objects}


def eye_centre(direction, radius, params):
    """Point along `direction` where a lens with this sink sits: centre inside the ball by eye_sink*r."""
    return tuple(component * (radius - params["eye_sink"] * params["eye_radius"]) for component in direction)


def add_lens(bpy, collection, name, centre, direction, params, radius=None, flatten=None,
             color=None, segments=None):
    """A uv-sphere squashed along the surface normal: a lens that hugs the ball."""
    radius = params["eye_radius"] if radius is None else radius
    flatten = params["eye_flatten"] if flatten is None else flatten
    ops = bpy.ops
    segments = int(segments or params["eye_segments"])
    ops.mesh.primitive_uv_sphere_add(radius=radius, segments=segments,
                                     ring_count=max(8, segments // 2), location=centre)
    obj = bpy.context.view_layer.objects.active
    obj.name = name
    from mathutils import Vector
    obj.rotation_euler = Vector(direction).to_track_quat("Z", "Y").to_euler()   # local Z along the normal
    obj.scale = (1.0, 1.0, flatten)
    for link in list(obj.users_collection):
        link.objects.unlink(obj)
    collection.objects.link(obj)
    bpy.context.view_layer.update()
    bake_transform(obj)                      # NOT transform_apply: see the note in bake_transform
    obj.data.materials.append(solid_material(bpy, obj.name + "_mat", color or params["eye_color"]))
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def surface_offset(obj, direction):
    """Distance from the ball centre to this object's surface along `direction` (world units).

    Sampling the mesh is the only way to get the true apex of a squashed lens: bounding boxes and
    formulae both lie once a scale has been folded into the mesh data.
    """
    import mathutils
    best = 0.0
    for vertex in obj.data.vertices:
        projection = (obj.matrix_world @ mathutils.Vector(vertex.co)).dot(direction)
        best = projection if projection > best else best
    return best


def bake_transform(obj):
    """Fold rotation/scale into the mesh data without an operator.

    Measured: bpy.ops.object.transform_apply(rotation=True, scale=True) returned {'CANCELLED'} inside
    the live bridge (and I never checked), so the eyes shipped with scale (1, 1, 0.38) unapplied -
    payloads/scene_report.py is what caught it. Baking the matrix needs no context at all, so it is
    correct in -b, in the bridge and in pip bpy.
    """
    from mathutils import Matrix
    obj.data.transform(obj.matrix_world)
    obj.matrix_world = Matrix.Identity(4)
    obj.data.update()


def bake_modifiers(bpy, obj):
    """Depsgraph bake: no context, so it works in -b, in pip bpy and inside the live bridge."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    baked = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph),
                                          preserve_all_data_layers=True, depsgraph=depsgraph)
    previous, obj.data = obj.data, baked
    for modifier in list(obj.modifiers):
        obj.modifiers.remove(modifier)
    if previous.users == 0:
        bpy.data.meshes.remove(previous)
    bpy.context.view_layer.update()


def shade_by_radius(obj, radius):
    """Smooth the sphere itself, keep the mouth faces and bevel facets flat."""
    for polygon in obj.data.polygons:
        distance = (obj.matrix_world @ polygon.center).length
        polygon.use_smooth = distance > radius * 0.995


def solid_material(bpy, name, rgb):
    material = bpy.data.materials.new(name)
    if not getattr(material, "use_nodes", True):             # deprecated in 5.1, gone in 6.0
        material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF") or next(
        node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
    bsdf.inputs["Base Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    for socket, value in (("Roughness", 0.35), ("Metallic", 0.0)):
        if socket in bsdf.inputs:                            # socket names move between versions
            bsdf.inputs[socket].default_value = value
    return material


def report(bpy, obj):
    import mathutils
    mesh = obj.data
    points = [obj.matrix_world @ mathutils.Vector(v.co) for v in mesh.vertices]
    signed_volume = 0.0
    for polygon in mesh.polygons:
        tri = [points[i] for i in polygon.vertices]
        for k in range(1, len(tri) - 1):
            signed_volume += tri[0].dot(tri[1].cross(tri[2])) / 6.0
    edge_faces: dict = {}
    for polygon in mesh.polygons:
        for key in polygon.edge_keys:
            edge_faces[key] = edge_faces.get(key, 0) + 1
    boundary = sum(1 for count in edge_faces.values() if count == 1)
    non_manifold = sum(1 for count in edge_faces.values() if count > 2)
    return {
        "object": obj.name,
        "polygons": len(mesh.polygons),
        "watertight": boundary == 0 and non_manifold == 0,
        "boundary_edges": boundary,
        "non_manifold_edges": non_manifold,
        "normals_outward": signed_volume > 0,                # signed: negative == inverted shell
        "volume_m3": round(abs(signed_volume), 5),
        "size_m": [round(value, 4) for value in obj.dimensions],
    }


def main() -> int:
    import bpy
    objects = build(bpy, PARAMS)
    body = report(bpy, objects["body"])
    radius, mouth = PARAMS["radius"], math.radians(PARAMS["mouth_degrees"])
    expected = 4.0 / 3.0 * math.pi * radius ** 3 * (2.0 * math.pi - mouth) / (2.0 * math.pi)
    delta = abs(body["volume_m3"] - expected) / expected
    eyes = [report(bpy, eye) for eye in objects["eyes"]]

    # Are the eyes actually over the mouth? Measure it instead of looking at it and hoping.
    from mathutils import Vector
    mouth_dir = Vector((1.0, 0.0, 0.0))
    half_mouth = PARAMS["mouth_degrees"] / 2.0
    eye_angular_radius = math.degrees(math.atan2(PARAMS["eye_radius"], PARAMS["radius"]))
    placement = []
    for eye in objects["eyes"]:
        centre = sum((eye.matrix_world @ mathutils.Vector(v.co) for v in eye.data.vertices),
                     mathutils.Vector()) / len(eye.data.vertices)
        offset_deg = math.degrees(mouth_dir.angle(centre.normalized()))
        placement.append({"object": eye.name, "offset_from_mouth_deg": round(offset_deg, 1),
                          "above_upper_lip_deg": round(offset_deg - half_mouth, 1)})
    # The nearest point of an eye must clear the upper lip, otherwise it sits inside the mouth.
    eyes_over_mouth = all(item["above_upper_lip_deg"] - eye_angular_radius >= 0.0
                          for item in placement if "Eye" in item["object"])

    # "Too close together" is measurable: angle between the two eye directions, minus how much of
    # that angle each lens already occupies. Negative means the lenses overlap.
    lens = [item for item in placement if "Eye_" in item["object"] and "Pupil" not in item["object"]]
    directions = []
    for item in lens:
        obj = bpy.data.objects[item["object"]]
        centre = sum((obj.matrix_world @ mathutils.Vector(v.co) for v in obj.data.vertices),
                     mathutils.Vector()) / len(obj.data.vertices)
        directions.append(centre.normalized())
    eye_separation_deg = math.degrees(directions[0].angle(directions[1])) if len(directions) == 2 else 0.0

    # Pupils: how far do they stick out of the eye? Measured off both meshes, along each pupil's own
    # axis. "on the surface or slightly protruding" == 0 mm .. 10 mm.
    protrusion_mm = []
    for side in ("L", "R"):
        eye_obj = bpy.data.objects.get(f"{PARAMS['name']}_Eye_{side}")
        pupil_obj = bpy.data.objects.get(f"{PARAMS['name']}_Pupil_{side}")
        if eye_obj and pupil_obj:
            centre = sum((pupil_obj.matrix_world @ mathutils.Vector(v.co) for v in pupil_obj.data.vertices),
                         mathutils.Vector()) / len(pupil_obj.data.vertices)
            axis = centre.normalized()
            protrusion_mm.append(round((surface_offset(pupil_obj, axis) - surface_offset(eye_obj, axis)) * 1000.0, 2))
    pupils_flush = bool(protrusion_mm) and all(0.0 <= value <= 10.0 for value in protrusion_mm)
    lens_gap_deg = round(eye_separation_deg - 2.0 * eye_angular_radius, 1)
    eyes_spread_apart = lens_gap_deg >= 5.0
    ok = bool(body["watertight"] and body["normals_outward"] and delta < 0.05
              and all(eye["watertight"] for eye in eyes) and eyes_over_mouth and eyes_spread_apart and pupils_flush)
    print(json.dumps({"ok": ok, "body": body, "expected_body_volume_m3": round(expected, 5),
                      "volume_delta_pct": round(delta * 100.0, 2),
                      "eye_angular_radius_deg": round(eye_angular_radius, 1),
                      "eye_separation_deg": round(eye_separation_deg, 1),
                      "lens_gap_deg": lens_gap_deg, "eyes_spread_apart": eyes_spread_apart,
                      "pupil_protrusion_mm": protrusion_mm, "pupils_flush": pupils_flush,
                      "upper_lip_at_deg": half_mouth, "eyes_over_mouth": eyes_over_mouth,
                      "eye_placement": placement}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
