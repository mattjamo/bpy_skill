# Materials, lighting and rendering

Two different jobs, two different settings: **preview** (fast, must show the shape - see
`references/verify-and-preview.md`) and **quality still** (pretty, `scripts/render_still.py`).

## Materials (nodes are the only supported path)

```python
def make_material(bpy, name, base_color, metallic=0.0, roughness=0.5):
    material = bpy.data.materials.new(name)
    if not getattr(material, "use_nodes", True):     # deprecated in 5.1, removed in 6.0
        material.use_nodes = True
    tree = material.node_tree
    bsdf = tree.nodes.get("Principled BSDF") or next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    for socket, value in (("Metallic", metallic), ("Roughness", roughness)):
        if socket in bsdf.inputs:                    # names change between versions: test membership
            bsdf.inputs[socket].default_value = value
    return material
```

* Socket **names**, not indices, and always membership-tested. The full measured 5.1 list is in
  `references/api-reality.md` (Principled section). Renames that break old snippets: `Specular` ->
  `Specular IOR Level`, `Transmissive` -> `Transmission Weight`, `Subsurface` -> `Subsurface Weight`,
  `Emission` -> `Emission Color` + `Emission Strength`, plus new `Coat *`, `Sheen *`, `Thin Film *`.
* `material.node_tree.nodes["Principled BSDF"]` raises `KeyError` if the node was renamed/localised - prefer
  `.get(...)` plus a `type == 'BSDF_PRINCIPLED'` fallback.
* Assign to `obj.data.materials` (mesh slots). For multi-material meshes set `polygon.material_index` and keep
  the slot order documented; `material_offset`/`material_offset_rim` on Solidify extend that order to rims.
* Image textures: `tex = bpy.data.images.load(path)`, `node = tree.nodes.new('ShaderNodeTexImage')`,
  `node.image = tex`; link `tex.outputs['Color'] -> bsdf.inputs['Base Color']`. UVs must exist
  (`mesh.uv_layers`) or the exporter/renderer shows a flat colour. After changing nodes:
  `bpy.context.view_layer.update()`.
* Principled is the only shader that survives export. Anything custom (mix shaders, procedural noise, geometry
  nodes attribute drives) is lost in glTF/OBJ/STL - bake to image textures if the target needs the look.
* `material.use_backface_culling`, `blend_method`/`show_transparent_backface` and
  `material.use_transparency`-era properties were renamed/removed across 4.x-5.x; check
  `props(bpy.types.Material)` before touching them.

## Lighting that makes geometry readable

For shape judgement you want *directional shading plus ambient*, not realism:

```python
world = bpy.data.worlds.new("PreviewWorld")           # payloads/preview.py installs this
if not getattr(world, "use_nodes", True):
    world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
bg.inputs[0].default_value = (0.35, 0.35, 0.38, 1.0)   # grey ambient so nothing is pure black
bg.inputs[1].default_value = 1.0
scene.world = world

key = bpy.data.lights.new("Key", 'SUN'); key.energy = 4.0     # W/m^2
fill = bpy.data.lights.new("Fill", 'SUN'); fill.energy = 1.2
```

* **A metallic part in the default black world renders pure black.** This is the #1 reason an agent believes
  its model disappeared (`coverage 0.0`, `pixel_stats` flat). Metals have no diffuse term: with no world and no
  light there is nothing to reflect.
* Light types `'SUN' 'POINT' 'AREA' 'SPOT'`; useful props: `energy`, `color`, `angle` (sun spread, radians),
  `shape`/`size`/`size_y` (area), `spot_size`/`spot_blend`, `shadow_soft_size` (point), and per-light
  `light.data.use_shadow`-style toggles vary by version - verify with `props(type(light.data))`.
* Camera looks: `camera_data.lens`, `.clip_start`, `.clip_end` (millimetre parts need a small `clip_start`),
  `.sensor_width`, `camera_data.dof.use_dof`, `.dof.aperture_fstop`, `.dof.focus_object`.
* A 3-point rig (key 4.0, fill 1.2 from the opposite side, grey world) is enough to judge form; HDRI
  (`world.use_nodes` + `ShaderNodeTexEnvironment` + `env.image = bpy.data.images.load(hdri)`) is nicer for
  metals but a 20 MB download you should not fetch without asking.

## Render settings

Engines are whatever this build offers - measured on 5.1: `['BLENDER_EEVEE']` (Workbench is gone; 4.x has
`BLENDER_WORKBENCH` and `BLENDER_EEVEE_NEXT`; Cycles is an extension and absent under `--factory-startup`).
Pick from the enum, report the fallback, see `references/api-reality.md` §2.

Measured `SceneEEVEE` writable properties (first 18, alphabetical): `bokeh_max_size`, `bokeh_neighbor_max`,
`bokeh_overblur`, `bokeh_threshold`, `clamp_surface_direct`, `clamp_surface_indirect`,
`clamp_volume_direct`, `clamp_volume_indirect`, `direct_light_intensity`, `fast_gi_bias`, `fast_gi_distance`,
`fast_gi_method`, `fast_gi_quality`, `fast_gi_ray_count`, `fast_gi_resolution`, `fast_gi_step_count`,
`fast_gi_thickness_far`, `fast_gi_thickness_near` - and further down the usual `taa_render_samples`,
`ray_tracing_method`, `use_raytracing`, `use_shadows`, `use_gtao`, `use_ssr`, `use_volumetric_eval`. Run
`props(bpy.types.SceneEEVEE)` on the user's build for the authoritative list; do not copy 4.x setting names
blindly.

`SceneRender` writable props measured: `engine`, `filepath`, `film_transparent`, `resolution_*`,
`image_settings.*`, `fps`, `fps_base`, `border_min_x/max_x/min_y/max_y` (region render),
`use_persistent_data`, `compositor_device`/`compositor_precision`/`compositor_denoise_*`,
`dither_intensity`, `filter_size`.

Colour management: `scene.view_settings.view_transform` is `"AgX"` by default in 5.x;
**`view_transform.enum_items` returns `['NONE']` under `--factory-startup`** (that enum is populated
dynamically), so set it inside `try/except` and never validate against the enum. `"Standard"` is the right
choice for technical previews where you want readable mid-greys instead of filmic compression.
`scene.render.film_transparent = True` for a transparent PNG (with `image_settings.file_format = 'PNG'` and
`image_settings.color_mode = 'RGBA'`).

## Quality stills with `scripts/render_still.py`

```bash
python scripts/blender_run.py --open model.blend --script scripts/render_still.py -- \
       --engine BLENDER_EEVEE --output C:/m/quality --resolution 800 450
# also: --samples N (Cycles), --frames S E --animation, --still-frame N, --transparent, --use-gpu
```

Measured on Blender 5.1: renders and saves (800 x 450 PNG, `Saved: ...quality.png`, exit 0). It installs a
material if the objects have none, and its framing is tight (measured `coverage 0.91`) - use it for the final
image and `payloads/preview.py` when you need to *judge* geometry from several angles.

Animation: set `scene.frame_start/frame_end`, keyframe via
`obj.keyframe_points_insert`-style data API or `obj.rotation_euler = ...; obj.keyframe_insert("rotation_euler",
frame=n)`, then `bpy.ops.render.render(animation=True)` or `--animation`. For deterministic results with
physics/simulations, bake first (`bpy.ops.ptcache.bake_all(bake=True)`) - and note `--factory-startup` wipes
user add-ons, so simulation add-ons will not be present.
