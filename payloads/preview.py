"""Fast, deterministic preview renders so the agent can look at what it just built.

Adds a temporary camera + lighting rig that frames the target objects, renders, then restores the
scene exactly as it was.  Works in all three contexts: pip `bpy`, headless
(`blender -b -P payloads/preview.py -- --out ...`), and inside the live bridge (send as code).

Two verified gotchas this file handles for you:
  * **Workbench does not exist in Blender 5.x** - the engine enum contains only BLENDER_EEVEE. The
    engine is chosen from a preference list of what this build actually offers, and reported.
  * **A preview needs its own lighting.** A metallic part in the default black world renders pure
    black in EEVEE, which looks exactly like "my model is missing". This payload always installs a
    temporary world + sun + fill and removes them afterwards.

Options (after '--'):
    --out PATH      file prefix or image path         (default <temp>/bpy_preview.png)
    --angles N      1, 2, 4 or 6 azimuth steps        (default 1)
    --size N        long-edge resolution in px        (default 900)
    --engine NAME   preference, falls back silently-listed (see engine_used in the output)
    --prefix NAME   only frame objects whose name starts with NAME
    --no-rig        keep the scene's own world/lights instead of adding a preview rig
    --keep-camera   leave the preview camera and rig in the scene
    --no-verify     skip the pixel-level framing check
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
# Inside the live bridge there is no argv of its own, so options arrive as BRIDGE_OPTS.
OPTS = globals().get("BRIDGE_OPTS") or {}


def _arg(flag: str, default):
    key = flag.lstrip("-")
    if key in OPTS:
        return OPTS[key]
    return ARGS[ARGS.index(flag) + 1] if flag in ARGS else default


def available_engines(scene) -> list[str]:
    return [item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items]


def pick_engine(scene, preferred: str) -> tuple[str, bool]:
    """Return (engine_used, was_fallback). Never silently render with something else."""
    options = available_engines(scene)
    if preferred in options:
        return preferred, False
    for candidate in (preferred, "BLENDER_WORKBENCH", "BLENDER_EEVEE", "CYCLES"):
        if candidate in options:
            return candidate, True
    return scene.render.engine, True


def verify_image(bpy, path: str) -> dict:
    """Programmatic visual check, so a model without eyes can still verify a render.

    Catches an empty or clipped frame without waiting for a human: coverage is the sampled fraction
    of pixels that differ from the corner (background) pixel.
    """
    image = bpy.data.images.load(path)                     # load() accepts (filepath, check_existing) only
    try:
        width, height = image.size[0], image.size[1]
        if width < 2 or height < 2:
            return {"ok": False, "error": "image has no pixels"}
        pixels = image.pixels[:]                            # RGBA floats, bottom-up
        background = pixels[0:3]
        step = max(1, (width * height) // 40000) * 4        # sample at most ~40k pixels
        touched = sampled = 0
        min_x = min_y = 10**9
        max_x = max_y = -1
        for offset in range(0, len(pixels), step):
            index = offset // 4
            colour = pixels[offset:offset + 3]
            sampled += 1
            if sum(abs(a - b) for a, b in zip(colour, background)) > 0.02:
                touched += 1
                y, x = divmod(index, width)
                min_x, max_x = min(min_x, x), max(max_x, x)
                min_y, max_y = min(min_y, y), max(max_y, y)
        coverage = touched / max(1, sampled)
        sampled_values = pixels[0::4001]
        stats = {"min": round(min(sampled_values), 4), "max": round(max(sampled_values), 4),
                 "mean": round(sum(sampled_values) / len(sampled_values), 4)}
        hint = None
        if stats["max"] - stats["min"] < 0.01:
            hint = ("image is a single flat value: the frame is blank. A scene with no light and no "
                    "world (or a fully metallic part in a black world) renders exactly like this")
        elif coverage < 0.03:
            hint = ("frame is essentially empty: either the camera is outside/inside the model, "
                    "clip_start clips it, or the model renders black (metallic material in a black "
                    "world with no rig - keep the preview rig on)")
        return {
            "ok": True,
            "size": [width, height],
            "coverage": round(coverage, 4),
            "pixel_stats": stats,
            "subject_bbox": [min_x, min_y, max_x, max_y] if touched else None,
            "framing": "too_close" if coverage > 0.92 else "too_small" if coverage < 0.03 else "ok",
            **({"hint": hint} if hint else {}),
        }
    finally:
        bpy.data.images.remove(image)


def main() -> int:
    import bpy
    from mathutils import Vector

    out = _arg("--out", os.path.join(tempfile.gettempdir(), "bpy_preview"))
    angles = max(1, min(6, int(_arg("--angles", 1))))
    size = int(_arg("--size", 900))
    wanted_engine = _arg("--engine", "BLENDER_WORKBENCH")
    prefix = _arg("--prefix", None)
    use_rig = "--no-rig" not in ARGS
    keep_extras = "--keep-camera" in ARGS
    do_verify = "--no-verify" not in ARGS

    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()

    targets = [obj for obj in scene.objects
               if obj.type == "MESH" and not obj.hide_render and not obj.hide_viewport
               and (prefix is None or obj.name.startswith(prefix))]
    if not targets:
        print(json.dumps({"ok": False, "error": "no renderable mesh objects found",
                          "engines": available_engines(scene)}))
        return 1

    points: list = []
    for obj in targets:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            points.extend(obj.matrix_world @ Vector(vertex.co) for vertex in mesh.vertices)
        finally:
            evaluated.to_mesh_clear()
    if not points:
        print(json.dumps({"ok": False, "error": "target meshes have no vertices"}))
        return 1
    center = sum(points, Vector()) / len(points)
    radius = max((point - center).length for point in points)

    engine, engine_fallback = pick_engine(scene, wanted_engine)
    previous = {
        "camera": scene.camera,
        "engine": scene.render.engine,
        "filepath": scene.render.filepath,
        "resolution_x": scene.render.resolution_x,
        "resolution_y": scene.render.resolution_y,
        "resolution_percentage": scene.render.resolution_percentage,
        "film_transparent": scene.render.film_transparent,
        "view_transform": scene.view_settings.view_transform,
        "world": scene.world,
    }

    created: list = []
    camera = None
    try:
        camera_data = bpy.data.cameras.new("PreviewCam")
        camera_data.lens = 50.0
        camera_data.clip_start = max(0.0001, radius / 500.0)     # millimetre-scale parts sit closer
        camera_data.clip_end = max(1000.0, radius * 500.0)
        camera = bpy.data.objects.new("PreviewCam", camera_data)
        scene.collection.objects.link(camera)
        scene.camera = camera
        created.append(camera)

        if use_rig:
            world = bpy.data.worlds.new("PreviewWorld")
            if not getattr(world, "use_nodes", True):        # deprecated in 5.1, removed in 6.0
                world.use_nodes = True
            background = world.node_tree.nodes.get("Background")
            background.inputs[0].default_value = (0.35, 0.35, 0.38, 1.0)
            background.inputs[1].default_value = 1.0
            scene.world = world
            created.append(world)
            for name, kind, energy, rotation in (
                ("PreviewKey", 'SUN', 4.0, (math.radians(52), 0, math.radians(35))),
                ("PreviewFill", 'SUN', 1.2, (math.radians(-35), 0, math.radians(-120))),
            ):
                light_data = bpy.data.lights.new(name, kind)
                light_data.energy = energy
                light = bpy.data.objects.new(name, light_data)
                light.rotation_euler = rotation
                scene.collection.objects.link(light)
                created.append(light)
            if hasattr(scene, "display"):                             # Workbench shading (Blender 4.x)
                scene.display.shading.light = 'STUDIO'
                scene.display.shading.color_type = 'OBJECT'
                scene.display.shading.show_cavity = True

        scene.render.engine = engine
        scene.render.resolution_percentage = 100
        if scene.render.resolution_x >= scene.render.resolution_y:
            scene.render.resolution_x, scene.render.resolution_y = size, round(size * 9 / 16)
        else:
            scene.render.resolution_x, scene.render.resolution_y = round(size * 9 / 16), size
        scene.render.film_transparent = False
        scene.render.image_settings.file_format = "PNG"
        scene.view_settings.view_transform = "Standard"
        bpy.context.view_layer.update()

        # Frame the bounding sphere with the camera's real horizontal FOV plus a margin.
        fov = 2.0 * math.atan(camera_data.sensor_width / 2.0 / camera_data.lens)
        distance = radius / math.tan(fov / 2.0) * 1.15

        root, extension = os.path.splitext(out)
        outputs: list[str] = []
        for index in range(angles):
            azimuth = math.radians(45.0 + index * (360.0 / angles))
            offset = Vector((math.cos(azimuth), math.sin(azimuth), 0.45)).normalized()
            camera.location = center + offset * distance
            # to_track_quat aligns the given local axis with the vector, so use camera->target with -Z.
            # Using (camera.location - center) looks the opposite way and yields an empty frame.
            camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
            bpy.context.view_layer.update()

            target = out if extension else (f"{root}.png" if angles == 1 else f"{root}_{index:02d}.png")
            scene.render.filepath = target
            bpy.ops.render.render(write_still=True)
            outputs.append(target if os.path.exists(target) else scene.render.filepath)
    finally:
        # Restore first, purge second: orphans_purge() frees the previous world the moment the
        # temporary one stops referencing it, and assigning a freed StructRNA raises ReferenceError.
        scene.camera = previous["camera"]
        scene.render.engine = previous["engine"]
        scene.render.filepath = previous["filepath"]
        scene.render.resolution_x = previous["resolution_x"]
        scene.render.resolution_y = previous["resolution_y"]
        scene.render.resolution_percentage = previous["resolution_percentage"]
        scene.render.film_transparent = previous["film_transparent"]
        scene.view_settings.view_transform = previous["view_transform"]
        scene.world = previous["world"]
        if not keep_extras:
            for block in created:
                if block.name in bpy.data.objects:
                    bpy.data.objects.remove(block, do_unlink=True)
                elif block.name in bpy.data.worlds:
                    bpy.data.worlds.remove(block)
            bpy.data.orphans_purge(do_recursive=True)

    checks = ({path: verify_image(bpy, path) for path in outputs if os.path.exists(path)}
              if do_verify else {})
    print(json.dumps({
        "ok": bool(outputs) and all(os.path.exists(path) for path in outputs),
        "outputs": [os.path.abspath(path) for path in outputs],
        "engine_requested": wanted_engine,
        "engine_used": engine,
        "engine_fallback": engine_fallback,
        "engines_available": available_engines(scene),
        "rig": use_rig,
        "framed_objects": [obj.name for obj in targets],
        "center": [round(component, 4) for component in center],
        "radius": round(radius, 4),
        "angles": angles,
        "checks": checks,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
