#!/usr/bin/env python3
"""Build a small scene procedurally and render it - the canonical bpy smoke test.

Runs either as a plain Python process (pip-installed bpy) or inside Blender:

    python  scripts/render_still.py --engine BLENDER_EEVEE --output /tmp/shot.png
    python  scripts/render_still.py --engine CYCLES --samples 64 --animation --frames 1 48
    blender -b --factory-startup --python scripts/render_still.py -- --engine CYCLES

Exit codes: 0 rendered, 2 engine unavailable or render failed, 3 bpy missing.
"""

from __future__ import annotations

import argparse
import os
import sys

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".exr", ".bmp", ".tif", ".tiff"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    # Inside Blender, sys.argv holds the whole command line; user args follow a "--" separator.
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", default=None,
                        help="BLENDER_EEVEE (5.x), BLENDER_EEVEE_NEXT (4.2-4.5), CYCLES, BLENDER_WORKBENCH")
    parser.add_argument("--samples", type=int, default=64, help="Cycles samples (default 64)")
    parser.add_argument("--output", default=os.path.join(os.getcwd(), "bpy_shot"),
                        help="image path (out.png) or path prefix for animations (default ./bpy_shot)")
    parser.add_argument("--resolution", nargs=2, type=int, default=(960, 540), metavar=("W", "H"))
    parser.add_argument("--frames", nargs=2, type=int, default=(1, 90), metavar=("START", "END"))
    parser.add_argument("--animation", action="store_true", help="render the frame range instead of one still")
    parser.add_argument("--still-frame", type=int, default=45, help="frame for the single still")
    parser.add_argument("--transparent", action="store_true", help="transparent film")
    parser.add_argument("--use-gpu", action="store_true", help="ask Cycles for a GPU device")
    return parser.parse_args(argv)


def available_engines(bpy) -> list:
    return [item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]


def build_scene(bpy):
    """Create ground, animated sphere with a node material, area light, camera."""
    bpy.ops.wm.read_factory_settings(use_empty=True)   # drop the default startup cube/camera/light
    scene = bpy.context.scene

    plane = bpy.data.meshes.new("Ground")               # name may be adjusted by Blender - keep the object
    plane.from_pydata([(-6, -6, 0), (6, -6, 0), (6, 6, 0), (-6, 6, 0)], [], [(0, 1, 2, 3)])
    plane.update()
    ground = bpy.data.objects.new("Ground", plane)
    scene.collection.objects.link(ground)               # unlinked data is invisible

    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, location=(0, 0, 1))
    ball = bpy.context.active_object
    ball.name = "Ball"

    material = bpy.data.materials.new("Blue")
    if not getattr(material, "use_nodes", True):     # deprecated in 5.1, removed in 6.0
        material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.1, 0.3, 0.9, 1.0)
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.25
    ball.data.materials.append(material)

    light_data = bpy.data.lights.new("Key", 'AREA')
    light_data.energy = 500
    light_data.size = 4.0
    light = bpy.data.objects.new("Key", light_data)
    light.location = (4, -4, 6)
    scene.collection.objects.link(light)

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 50
    camera = bpy.data.objects.new("Cam", cam_data)
    camera.location = (5.5, -5.5, 3.5)
    camera.rotation_euler = (1.05, 0.0, 0.785)
    scene.collection.objects.link(camera)
    scene.camera = camera

    ball.location[2] = 1.0
    ball.keyframe_insert(data_path="location", frame=1, index=2)
    ball.location[2] = 3.0
    ball.keyframe_insert(data_path="location", frame=45, index=2)
    ball.location[2] = 1.0
    ball.keyframe_insert(data_path="location", frame=90, index=2)

    bpy.context.view_layer.update()
    return scene


def configure_cycles(bpy, scene, samples: int, use_gpu: bool) -> list:
    warnings = []
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    if not use_gpu:
        scene.cycles.device = 'CPU'
        return warnings
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.get_devices()
        if not [device for device in prefs.devices if device.type != 'CPU']:
            scene.cycles.device = 'CPU'
            warnings.append("Cycles reported no GPU device - rendering on CPU")
            return warnings
        for device in prefs.devices:
            device.use = True
        scene.cycles.device = 'GPU'
    except Exception as error:  # noqa: BLE001
        scene.cycles.device = 'CPU'
        warnings.append(f"GPU setup failed ({type(error).__name__}: {error}) - rendering on CPU")
    return warnings


def target_path(output: str) -> str:
    root, extension = os.path.splitext(output)
    return output if extension.lower() in IMAGE_EXTENSIONS else f"{output}.png"


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    try:
        import bpy  # bpy must be imported before mathutils/gpu, and only here
    except Exception as error:  # noqa: BLE001
        print(f"bpy is not importable with this interpreter: {error}", file=sys.stderr)
        print("bpy 5.x needs Python 3.13; bpy 4.5/4.2 LTS need Python 3.11. See scripts/env_check.py", file=sys.stderr)
        return 3

    engines = available_engines(bpy)
    wanted = [args.engine] if args.engine else ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "CYCLES", "BLENDER_WORKBENCH"]
    engine = next((name for name in wanted if name and name in engines), None)
    if engine is None:
        print(f"engine {args.engine!r} unavailable. Registered engines: {engines}", file=sys.stderr)
        print("CYCLES/WORKBENCH come from bundled extensions/add-ons; EEVEE needs a usable GPU context.",
              file=sys.stderr)
        return 2

    scene = build_scene(bpy)
    scene.render.engine = engine
    scene.render.resolution_x, scene.render.resolution_y = args.resolution
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = args.transparent
    scene.render.use_persistent_data = True
    scene.frame_start, scene.frame_end = args.frames

    warnings = configure_cycles(bpy, scene, args.samples, args.use_gpu) if engine == "CYCLES" else []

    if args.animation:
        scene.render.filepath = args.output if "#" in args.output else f"{args.output}####"
        try:
            bpy.ops.render.render(animation=True)
        except Exception as error:  # noqa: BLE001
            print(f"animation render failed with {engine}: {error}", file=sys.stderr)
            return 2
        produced = scene.render.filepath
    else:
        scene.frame_set(min(max(args.still_frame, args.frames[0]), args.frames[1]))
        produced = target_path(args.output)
        scene.render.filepath = produced
        try:
            bpy.ops.render.render(write_still=True)
            bpy.data.images["Render Result"].save_render(filepath=produced, scene=scene)
        except Exception as error:  # noqa: BLE001
            print(f"render failed with {engine}: {error}", file=sys.stderr)
            print("hint: try --engine BLENDER_WORKBENCH (no GPU) or --engine CYCLES on CPU", file=sys.stderr)
            return 2

    for warning in warnings:
        print(f"warning: {warning}")
    exists = "" if os.path.exists(produced) else "  [file not found - check render output path]"
    print(f"engine={engine} resolution={args.resolution[0]}x{args.resolution[1]} "
          f"frames={args.frames[0]}-{args.frames[1]} -> {produced}{exists}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
