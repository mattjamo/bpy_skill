"""Scene / model report as JSON - the agent's eyes when it cannot look at the viewport.

Works in all three contexts: pip `bpy`, headless (`blender -b -P payloads/scene_report.py`),
and inside the live bridge (send this file's contents as code).

Reads only: never modifies the scene.

    python scripts/blender_run.py --script payloads/scene_report.py
    python scripts/bridge_send.py --file payloads/scene_report.py
    options after '--': --pretty --objects-only --name BRACKET_01 --no-evaluated
"""

from __future__ import annotations

import json
import math
import os
import sys

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
# Inside the live bridge there is no argv of its own, so options arrive as BRIDGE_OPTS.
OPTS = globals().get("BRIDGE_OPTS") or {}
PRETTY = "--pretty" in ARGS or bool(OPTS.get("pretty"))
EVALUATED = "--no-evaluated" not in ARGS and not OPTS.get("no-evaluated")
ONLY = OPTS.get("name") or (ARGS[ARGS.index("--name") + 1] if "--name" in ARGS else None)


def _arg(flag: str, default):
    key = flag.lstrip("-")
    if key in OPTS:
        return OPTS[key]
    return ARGS[ARGS.index(flag) + 1] if flag in ARGS else default


def main() -> int:
    import bpy  # imported late so this file also imports cleanly outside Blender
    from mathutils import Matrix, Vector  # after bpy

    context = bpy.context
    scene = context.scene
    settings = bpy.context.scene.unit_settings
    depsgraph = context.evaluated_depsgraph_get()

    def clean(vector_value) -> list:
        return [round(float(component), 5) for component in vector_value]

    def mesh_stats(mesh, matrix: Matrix) -> dict:
        count_v, count_e, count_p = len(mesh.vertices), len(mesh.edges), len(mesh.polygons)
        coords = [0.0] * (count_v * 3)
        if count_v:
            mesh.vertices.foreach_get("co", coords)
        coords = [matrix @ Vector(coords[i:i + 3]) for i in range(0, len(coords), 3)]
        finite = all(math.isfinite(value) for vertex in coords for value in vertex)

        edge_faces: dict = {}
        for polygon in mesh.polygons:
            for key in polygon.edge_keys:
                edge_faces[key] = edge_faces.get(key, 0) + 1
        boundary = sum(1 for faces in edge_faces.values() if faces == 1)
        non_manifold = sum(1 for faces in edge_faces.values() if faces > 2)

        volume = 0.0          # signed tetrahedron sum; positive when normals face outward
        area = 0.0
        for polygon in mesh.polygons:
            verts = [coords[index] for index in polygon.vertices]
            for index in range(1, len(verts) - 1):
                first, middle, last = verts[0], verts[index], verts[index + 1]
                volume += first.dot(middle.cross(last)) / 6.0          # signed tetra from origin
                area += (middle - first).cross((last - first)).length / 2.0

        bounds_min = [min((vertex[axis] for vertex in coords), default=0.0) for axis in range(3)]
        bounds_max = [max((vertex[axis] for vertex in coords), default=0.0) for axis in range(3)]
        bounds_size = [high - low for high, low in zip(bounds_max, bounds_min)]

        return {
            "vertices": count_v,
            "edges": count_e,
            "polygons": count_p,
            "triangles_estimate": count_p + sum(max(0, len(poly.vertices) - 3) for poly in mesh.polygons),
            "world_bounds_min": clean(bounds_min),
            "world_bounds_max": clean(bounds_max),
            "world_size": clean(bounds_size),
            "surface_area": round(float(area), 6),
            "volume": round(float(abs(volume)), 6),
            "watertight": boundary == 0 and non_manifold == 0 and count_v > 0,
            "boundary_edges": boundary,
            "non_manifold_edges": non_manifold,
            "finite_vertices": finite,
        }

    def describe_material(material) -> dict | None:
        if material is None:
            return None
        info: dict = {
            "name": material.name,
            "use_nodes": getattr(material, "use_nodes", None),   # deprecated in 5.1
            "blend_method": getattr(material, "blend_method", None),
            "diffuse_color": clean(material.diffuse_color),
            "nodes": [],
            "image_textures": [],
        }
        tree = getattr(material, "node_tree", None) if getattr(material, "use_nodes", True) else None
        if tree is not None:
            info["nodes"] = sorted({node.bl_idname for node in tree.nodes})
            for node in tree.nodes:
                if node.bl_idname == "ShaderNodeTexImage" and node.image is not None:
                    path = bpy.path.abspath(node.image.filepath)
                    info["image_textures"].append({
                        "image": node.image.name,
                        "filepath": path or None,
                        "exists": bool(path) and os.path.exists(path),
                        "resolution": [node.image.size[0], node.image.size[1]],
                    })
            info["surface_linked"] = any(
                link.to_node.bl_idname == "OutputMaterial" and link.to_socket.name == "Surface"
                for link in tree.links
            )
        return info

    def describe_object(obj) -> dict:
        matrix = obj.matrix_world
        entry: dict = {
            "name": obj.name,
            "type": obj.type,
            "collection": [collection.name for collection in obj.users_collection],
            "parent": obj.parent.name if obj.parent else None,
            "parent_type": obj.parent_type,
            "location": clean(obj.location),
            "rotation_euler": clean(obj.rotation_euler),
            "scale": clean(obj.scale),
            "world_origin": clean(matrix.translation),
            "dimensions": clean(obj.dimensions),
            "hide_viewport": obj.hide_viewport,
            "hide_render": obj.hide_render,
            "visible_in_viewport": obj.visible_get(),
            "linked": len(obj.users_collection) > 0,   # users_collection is a tuple of Collections
            "data": obj.data.name if obj.data else None,
            "data_users": obj.data.users if obj.data else None,
            "custom_properties": {key: str(obj[key]) for key in obj.keys() if not key.startswith("_")},
        }
        if obj.type == "MESH":
            entry["modifiers"] = [{
                "name": modifier.name,
                "type": modifier.type,
                "show_viewport": modifier.show_viewport,
                "show_render": modifier.show_render,
                "show_in_viewport": modifier.show_viewport,
            } for modifier in obj.modifiers]
            entry["materials"] = [describe_material(slot.material) for slot in obj.material_slots]
            entry["display_type"] = getattr(obj, "display_type", None)
            entry["shade_smooth"] = obj.data.shade_smooth if obj.data else None
            if EVALUATED:
                evaluated_object = obj.evaluated_get(depsgraph)
                mesh = evaluated_object.to_mesh() if evaluated_object else None
                if mesh is not None:
                    try:
                        entry["evaluated"] = mesh_stats(mesh, matrix)
                    finally:
                        evaluated_object.to_mesh_clear()
            if obj.data:
                entry["base_mesh"] = mesh_stats(obj.data, matrix)
        elif obj.type in {"CURVE", "FONT"}:
            entry["curve"] = {
                "splines": len(obj.data.splines),
                "bevel_depth": obj.data.bevel_depth,
                "bevel_resolution": obj.data.bevel_resolution,
                "extrude": obj.data.extrude,
                "fill_mode": obj.data.fill_mode,
                "resolution_u": obj.data.resolution_u,
                "use_fill_mode_caps": getattr(obj.data, "use_fill_mode_caps", None),
            }
        elif obj.type == "CAMERA":
            entry["camera"] = {"lens": obj.data.lens, "sensor_width": obj.data.sensor_width,
                               "clip_end": obj.data.clip_end, "is_scene_camera": scene.camera == obj}
        elif obj.type == "LIGHT":
            entry["light"] = {"light_type": obj.data.type, "energy": obj.data.energy,
                              "color": clean(obj.data.color), "size": getattr(obj.data, "size", None)}
        elif obj.type == "ARMATURE":
            entry["armature"] = {"bones": len(obj.data.bones), "pose_bones": len(obj.pose.bones),
                                 "actions": [action.name for action in bpy.data.actions]}
        elif obj.type == "EMPTY":
            entry["empty_display_type"] = obj.empty_display_type
        if obj.constraints:
            entry["constraints"] = [{"name": c.name, "type": c.type, "influence": c.influence}
                                    for c in obj.constraints]
        return entry

    def collection_tree(collection, depth: int = 0) -> dict:
        return {
            "name": collection.name,
            "objects": [obj.name for obj in collection.objects],
            "children": [collection_tree(child, depth + 1) for child in collection.children],
            "exclude": collection.hide_viewport,
        }

    objects = [obj for obj in bpy.data.objects if ONLY is None or obj.name == ONLY or obj.name.startswith(ONLY)]
    warnings: list[str] = []
    for obj in objects:
        if not obj.users_collection:
            warnings.append(f"{obj.name}: created but not linked into any collection (invisible in renders)")
        if any(abs(component - 1.0) > 1e-4 for component in obj.scale):
            warnings.append(f"{obj.name}: unapplied scale {clean(obj.scale)} - apply before export (Ctrl+A)")
        if any(abs(component) > 1e-4 for component in obj.rotation_euler) and obj.parent is None:
            warnings.append(f"{obj.name}: unapplied rotation on a root object")
        if obj.type == "MESH":
            evaluated = obj.evaluated_get(depsgraph)
            mesh = evaluated.to_mesh() if evaluated else None
            if mesh is not None:
                try:
                    stats = mesh_stats(mesh, obj.matrix_world)
                finally:
                    evaluated.to_mesh_clear()
                if not stats["finite_vertices"]:
                    warnings.append(f"{obj.name}: NaN/Inf vertex coordinates")
                if not stats["watertight"] and obj.modifiers and any(
                        modifier.type == "BOOLEAN" for modifier in obj.modifiers):
                    warnings.append(f"{obj.name}: boolean result is not watertight ({stats['boundary_edges']} boundary edges)")
        for slot in getattr(obj.data, "materials", []) if obj.data else []:
            if slot is None:
                warnings.append(f"{obj.name}: empty material slot")
    for image in bpy.data.images:
        path = bpy.path.abspath(image.filepath)
        if path and not os.path.exists(path):
            warnings.append(f"image '{image.name}' points at a missing file: {path}")

    report = {
        "meta": {
            "blender": bpy.app.version_string,
            "background": bpy.app.background,
            "file": bpy.data.filepath or None,
            "scene": scene.name,
            "frame": scene.frame_current,
            "fps": scene.render.fps,
            "engine": scene.render.engine,
            "available_engines": [item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items],
            "unit_system": settings.system,
            "scale_length": settings.scale_length,
            "length_unit": settings.length_unit,
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
            "view_transform": scene.view_settings.view_transform,
        },
        "totals": {
            "objects": len(bpy.data.objects),
            "meshes": len(bpy.data.meshes),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
            "collections": len(bpy.data.collections),
            "vertices": sum(len(mesh.vertices) for mesh in bpy.data.meshes),
            "polygons": sum(len(mesh.polygons) for mesh in bpy.data.meshes),
        },
        "collections": [collection_tree(scene.collection)],
        "objects": [describe_object(obj) for obj in objects],
        "warnings": warnings,
    }
    print(json.dumps(report, indent=2 if PRETTY else None, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
