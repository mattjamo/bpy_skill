"""Head-on + profile shots of the Pac-Man ball, with a pixel check on each render.

    python scripts/bridge_send.py --file shot_views.py
Re-usable because preview.py orbits around world Z, and this model's *face* points along +X.
"""

import json
import math
import os
import sys
import tempfile

from mathutils import Vector

# Output folder: BRIDGE_OPTS (live session), then `-- --dir PATH`, then the temp dir.
_opt = (globals().get("BRIDGE_OPTS") or {}).get("dir")
_rest = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
DIR = _opt or (_rest[_rest.index("--dir") + 1] if "--dir" in _rest else os.path.join(tempfile.gettempdir(), "blender-preview"))
SHOTS = {
    "front": (Vector((2.3, 0.0, 0.15)), "camera down -X: the mouth opens at the viewer, eyes above it"),
    "side": (Vector((0.0, -2.3, 0.15)), "camera down +Y: shows the hinge is lateral (jaws up/down)"),
    "three_quarter": (Vector((1.8, -1.5, 0.9)), "classic product angle"),
}


def main() -> int:
    import bpy
    from bpy_extras.object_utils import world_to_camera_view as proj

    scene = bpy.context.scene
    previous = (scene.camera, scene.render.engine, scene.render.filepath,
                scene.render.resolution_x, scene.render.resolution_y, scene.world,
                scene.view_settings.view_transform)
    engines = [i.identifier for i in scene.render.bl_rna.properties["engine"].enum_items]
    created = []
    result = {}
    try:
        scene.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in engines else previous[1]
        scene.render.resolution_x = scene.render.resolution_y = 900
        scene.render.image_settings.file_format = "PNG"
        scene.view_settings.view_transform = "Standard"

        world = bpy.data.worlds.new("ShotWorld")
        if not getattr(world, "use_nodes", True):
            world.use_nodes = True
        background = world.node_tree.nodes.get("Background")
        background.inputs[0].default_value = (0.30, 0.30, 0.34, 1.0)
        background.inputs[1].default_value = 1.0
        scene.world = world
        created.append(world)

        for name, energy, rotation in (("Key", 3.5, (0.9, 0.0, 3.5)), ("Fill", 1.0, (-0.6, 0.0, -2.1))):
            light_data = bpy.data.lights.new("Shot" + name, 'SUN')
            light_data.energy = energy
            light = bpy.data.objects.new("Shot" + name, light_data)
            light.rotation_euler = rotation
            scene.collection.objects.link(light)
            created.append(light)

        camera_data = bpy.data.cameras.new("ShotCam")
        camera_data.clip_start = 0.001
        camera = bpy.data.objects.new("ShotCam", camera_data)
        scene.collection.objects.link(camera)
        scene.camera = camera
        created.extend([camera, camera_data])

        target = Vector((0.0, 0.0, 0.0))
        half = math.radians(PARAMS["mouth_degrees"] / 2.0)
        radius = PARAMS["radius"]
        for name, (position, note) in SHOTS.items():
            camera.location = position
            camera.rotation_euler = (target - position).to_track_quat("-Z", "Y").to_euler()
            bpy.context.view_layer.update()

            path = os.path.join(DIR, f"shot_{name}.png")
            scene.render.filepath = path
            bpy.ops.render.render(write_still=True)

            check = {"note": note, "exists": os.path.exists(path)}
            if check["exists"]:
                image = bpy.data.images.load(path)
                try:
                    pixels = image.pixels[:]
                    background_pixel = pixels[0:3]
                    step = 28
                    touched = sum(1 for offset in range(0, len(pixels), step)
                                  if sum(abs(a - b) for a, b in zip(pixels[offset:offset + 3], background_pixel)) > 0.02)
                    check["coverage"] = round(touched / max(1, len(pixels) // step), 4)
                finally:
                    bpy.data.images.remove(image)
                # Is the eye above the mouth *in this view*? Project into image space.
                eye = bpy.data.objects.get(f"{PARAMS['name']}_Eye_L")
                if eye is not None:
                    centre = sum((eye.matrix_world @ vertex.co for vertex in eye.data.vertices), Vector()) / len(eye.data.vertices)
                    projected_eye = proj(scene, camera, centre)
                    lip = proj(scene, camera, Vector((radius * math.cos(half), 0.0, radius * math.sin(half))))
                    middle = proj(scene, camera, target)
                    check["eye_above_lip"] = round(projected_eye.y - lip.y, 3)
                    check["eye_above_centre"] = round(projected_eye.y - middle.y, 3)
                    check["eye_centred_x"] = round(projected_eye.x, 3)
            result[name] = check
    finally:
        scene.camera = previous[0]
        scene.render.engine, scene.render.filepath = previous[1], previous[2]
        scene.render.resolution_x, scene.render.resolution_y = previous[3], previous[4]
        scene.world = previous[5]
        scene.view_settings.view_transform = previous[6]
        for block in created:
            if getattr(block, "name", None) in bpy.data.objects:
                bpy.data.objects.remove(block, do_unlink=True)
            elif getattr(block, "name", None) in bpy.data.worlds:
                bpy.data.worlds.remove(block)
            elif getattr(block, "name", None) in bpy.data.cameras:
                bpy.data.cameras.remove(block)
            elif getattr(block, "name", None) in bpy.data.lights:
                bpy.data.lights.remove(block)
        bpy.data.orphans_purge(do_recursive=True)

    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
