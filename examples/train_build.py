import bpy, math, bmesh
from mathutils import Vector

# wipe scene for a clean rebuild
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
for block_list in (bpy.data.meshes, bpy.data.materials, bpy.data.collections):
    for b in list(block_list):
        if b.users == 0:
            block_list.remove(b)

# ---------- helpers ----------
def get_coll(name):
    c = bpy.data.collections.get(name)
    if not c:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c

LOCO = get_coll("Train")

def mat(name, color, metallic=0.0, rough=0.5, emissive=None):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    if emissive:
        b.inputs["Emission Color"].default_value = (*emissive, 1)
        b.inputs["Emission Strength"].default_value = 8.0
    return m

M_BODY   = mat("LocoBody",  (0.02, 0.06, 0.04), 0.1, 0.35)   # dark bottle green
M_TRIM   = mat("LocoTrim",  (0.45, 0.02, 0.02), 0.1, 0.4)    # red trim
M_BLACK  = mat("IronBlack", (0.02, 0.02, 0.02), 0.6, 0.45)   # boiler/frame black
M_STEEL  = mat("Steel",     (0.55, 0.55, 0.58), 1.0, 0.3)
M_BRASS  = mat("Brass",     (0.8, 0.55, 0.15), 1.0, 0.25)
M_WOOD   = mat("WoodSleeper",(0.15, 0.08, 0.04), 0.0, 0.8)
M_BALLAST= mat("Ballast",   (0.28, 0.26, 0.24), 0.0, 0.95)
M_GROUND = mat("Ground",    (0.05, 0.12, 0.03), 0.0, 0.95)
M_GLASS  = mat("Glass",     (0.6, 0.75, 0.85), 0.0, 0.1)
M_LIGHT  = mat("HeadLight", (0.9, 0.9, 0.8), 0.0, 0.2, emissive=(1.0, 0.95, 0.75))
M_COAL   = mat("Coal",      (0.01, 0.01, 0.01), 0.2, 0.8)

def link(obj, coll=LOCO):
    for c in obj.users_collection:
        c.objects.unlink(obj)
    coll.objects.link(obj)

def finish(obj, material, smooth=False, bevel=0.0):
    obj.data.materials.clear()
    obj.data.materials.append(material)
    if smooth:
        for p in obj.data.polygons:
            p.use_smooth = True
    if bevel > 0:
        b = obj.modifiers.new("Bevel", 'BEVEL')
        b.width = bevel
        b.segments = 2
        b.limit_method = 'ANGLE'
    return obj

def box(name, size, loc, material, coll=LOCO):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = (size[0], size[1], size[2])
    bpy.ops.object.transform_apply(scale=True)
    link(o, coll)
    return finish(o, material)

def cyl(name, r, depth, loc, rot=(0,0,0), material=M_BLACK, smooth=True, verts=32, coll=LOCO):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, vertices=verts,
                                        location=loc, rotation=rot)
    o = bpy.context.active_object
    o.name = name
    link(o, coll)
    return finish(o, material, smooth=smooth)

RY = math.radians(90)   # rotate cylinder axis Z->Y  (axles along Y)
RX = math.radians(90)   # rotate cylinder axis Z->X  (boiler along X)

# ---------- track ----------
TRK = get_coll("Track")
TRACK_LEN = 40.0
GAUGE = 1.435
SLEEP_TOP = 0.14
RAIL_H = 0.18
RAIL_TOP = SLEEP_TOP + RAIL_H           # 0.32

bpy.ops.mesh.primitive_plane_add(size=120, location=(0, 0, 0))
g = bpy.context.active_object; g.name = "Ground"; link(g, TRK); finish(g, M_GROUND)

box("Ballast", (TRACK_LEN, 3.6, 0.12), (0, 0, 0.06), M_BALLAST, TRK)

n_sl = int(TRACK_LEN / 0.65)
for i in range(n_sl):
    x = -TRACK_LEN/2 + 0.3 + i * (TRACK_LEN / n_sl)
    box(f"Sleeper {i:03d}", (0.26, 2.6, SLEEP_TOP), (x, 0, SLEEP_TOP/2), M_WOOD, TRK)

for side in (-1, 1):
    y = side * GAUGE/2
    box(f"Rail {side}", (TRACK_LEN, 0.07, RAIL_H), (0, y, SLEEP_TOP + RAIL_H/2), M_STEEL, TRK)
    box(f"Railfoot {side}", (TRACK_LEN, 0.2, 0.03), (0, y, SLEEP_TOP + 0.015), M_STEEL, TRK)

AXLE_Z = RAIL_TOP   # wheel bottoms touch rail top

# ---------- wheels ----------
def wheel(name, x, r, wy, w=0.14, spoke_boxes=3):
    """One axle with a wheel on EACH side at y = +/- wy."""
    cyl(name + "_axle", 0.06, 2*(wy + w), (x, 0, AXLE_Z), rot=(RY,0,0),
        material=M_STEEL, verts=12)
    for side in (-1, 1):
        yc = side * wy
        p = f"{name} {'L' if side > 0 else 'R'}"
        # steel tyre (outer rim band)
        cyl(p + "_tyre", r, w, (x, yc, AXLE_Z), rot=(RY,0,0), material=M_STEEL, verts=40)
        # black disc recessed inside the tyre
        cyl(p + "_disc", r*0.80, w*0.55, (x, yc, AXLE_Z), rot=(RY,0,0), material=M_BLACK, verts=40)
        # painted hub
        cyl(p + "_hub", r*0.24, w+0.05, (x, yc, AXLE_Z), rot=(RY,0,0), material=M_TRIM, verts=20)
        # full-length spokes: each box crosses the hub, so 3 boxes = 8 spokes
        for k in range(spoke_boxes + 1):
            a = k * math.pi / (spoke_boxes + 1)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(x, yc, AXLE_Z))
            s = bpy.context.active_object; s.name = f"{p}_sp{k}"
            s.scale = (2*r*0.78, w*0.5, 0.06)
            s.rotation_euler = (0, a, 0)
            bpy.ops.object.transform_apply(scale=True, rotation=True)
            link(s); finish(s, M_BLACK)

DRIVERS = [0.6, 2.4, 4.2]        # big driving wheels
DR_R = 0.55
LEADERS = [6.2, 7.1]
LD_R = 0.30
DR_WY = 0.95                     # wheel-plane half-spacing
LD_WY = 0.90

for x in DRIVERS:
    wheel(f"Driver {x}", x, DR_R, DR_WY, w=0.14)
for x in LEADERS:
    wheel(f"Leader {x}", x, LD_R, LD_WY, w=0.10)

# coupling rods outboard of the wheels + brass crank pins
ROD_Y = DR_WY + 0.07 + 0.07
CRANK_Z = AXLE_Z + DR_R * 0.55
for side in (-1, 1):
    box(f"CouplingRod {'L' if side>0 else 'R'}",
        (DRIVERS[-1]-DRIVERS[0]+0.3, 0.04, 0.08),
        ((DRIVERS[0]+DRIVERS[-1])/2, side*ROD_Y, CRANK_Z), M_STEEL)
    for x in DRIVERS:
        cyl(f"CrankPin {x} {'L' if side>0 else 'R'}", 0.05, 0.14,
            (x, side*(ROD_Y - 0.03), CRANK_Z), rot=(RY,0,0), material=M_BRASS, verts=12)

# small trailing wheels under the cab
wheel("Trailing", -2.2, 0.35, DR_WY, w=0.12)

# ---------- locomotive body ----------
FRAME_TOP = AXLE_Z + DR_R + 0.06          # ~0.93
box("Frame", (10.4, 1.6, 0.18), (2.1, 0, FRAME_TOP - 0.09), M_BLACK)

# boiler
BOILER_Z = FRAME_TOP + 0.75 + 0.18        # centre of boiler

# boiler barrel: cylinder along X
bpy.ops.mesh.primitive_cylinder_add(radius=0.75, depth=6.2, vertices=40,
                                    location=(3.6, 0, BOILER_Z), rotation=(0, RX, 0))
bo = bpy.context.active_object; bo.name = "Boiler"; link(bo); finish(bo, M_BLACK, smooth=True)

# boiler bands
for bx in (1.2, 2.6, 4.0, 5.4):
    cyl(f"Band {bx}", 0.77, 0.12, (bx, 0, BOILER_Z), rot=(0, RX, 0), material=M_TRIM, verts=40)

# smokebox front
cyl("SmokeboxDoor", 0.80, 0.16, (6.78, 0, BOILER_Z), rot=(0, RX, 0), material=M_BLACK, verts=40)
cyl("SmokeboxHinge", 0.1, 0.3, (6.88, 0, BOILER_Z + 0.55), rot=(0, RX, 0), material=M_STEEL, verts=12)

# smokebox saddle + chimney
box("ChimneyBase", (0.7, 0.7, 0.35), (5.9, 0, BOILER_Z + 0.82), M_BLACK)
cyl("Chimney", 0.24, 0.75, (5.9, 0, BOILER_Z + 1.35), material=M_BLACK, verts=24)
cyl("ChimneyLip", 0.30, 0.12, (5.9, 0, BOILER_Z + 1.75), material=M_BRASS, verts=24)

# steam dome + sand domes
for dx, dr in ((2.9, 0.34), (4.7, 0.26)):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=dr, segments=28, ring_count=16,
                                         location=(dx, 0, BOILER_Z + 0.68))
    d = bpy.context.active_object; d.name = f"Dome {dx}"; link(d)
    d.scale = (1.2, 1, 0.9)
    bpy.ops.object.transform_apply(scale=True)
    finish(d, M_BRASS if dx == 2.9 else M_TRIM, smooth=True)

# bell between domes
cyl("Bell", 0.15, 0.25, (3.8, 0, BOILER_Z + 0.9), material=M_BRASS, verts=20)

# headlight on smokebox front
cyl("HeadlightHousing", 0.22, 0.25, (6.95, 0, BOILER_Z + 0.95), rot=(0, RX, 0), material=M_BRASS, verts=24)
cyl("HeadlightLens", 0.17, 0.04, (7.09, 0, BOILER_Z + 0.95), rot=(0, RX, 0), material=M_LIGHT, verts=24)

# handrails
for side in (-1, 1):
    cyl(f"Handrail {side}", 0.025, 5.6, (3.7, side*0.78, BOILER_Z + 0.15), rot=(0, RX, 0),
        material=M_STEEL, verts=8)
    for hx in (1.2, 6.0):
        cyl(f"HandrailPost {side} {hx}", 0.03, 0.5, (hx, side*0.78, BOILER_Z + 0.0), rot=(0,0,0),
            material=M_STEEL, verts=8)

# running plate
box("RunningPlate", (6.6, 2.5, 0.08), (3.5, 0, FRAME_TOP + 0.02), M_BLACK)

# cab
CAB_X0, CAB_X1 = -1.6, 0.9
CAB_CX = (CAB_X0 + CAB_X1)/2
box("Cab", (CAB_X1-CAB_X0, 2.7, 2.1), (CAB_CX, 0, FRAME_TOP + 1.15), M_BODY)
# cab windows (slightly protruding dark glass panes)
for side in (-1, 1):
    box(f"CabWindow {side}", (1.2, 0.06, 0.85), (CAB_CX + 0.15, side*1.38, FRAME_TOP + 1.55), M_GLASS)
box("CabWindowFront", (0.12, 1.9, 0.8), (CAB_X1 + 0.03, 0, FRAME_TOP + 1.55), M_GLASS)
# roof with overhang
box("CabRoof", (CAB_X1-CAB_X0+0.9, 3.0, 0.12), (CAB_CX + 0.25, 0, FRAME_TOP + 2.28), M_TRIM)

# tender jib / drawbar
box("Drawbar", (1.2, 0.25, 0.12), (-2.1, 0, FRAME_TOP - 0.25), M_BLACK)

# cowcatcher (pilot) - A-frame of slats with side plates and cross braces
PBX   = 7.15                     # pilot beam x
XTIP  = 8.30                     # tip x
TOP_Z = AXLE_Z + 0.72
BOT_Z = RAIL_TOP + 0.16          # pilot must clear the railhead
sdx, sdz = XTIP - PBX, BOT_Z - TOP_Z
SLOPE = math.hypot(sdx, sdz)
TH = math.atan2(-sdz, sdx)       # rot about Y tilts local +X down toward the tip
for i in range(7):
    y = -0.66 + i * 0.22
    bpy.ops.mesh.primitive_cube_add(size=1, location=((PBX+XTIP)/2, y, (TOP_Z+BOT_Z)/2))
    s = bpy.context.active_object; s.name = f"PilotSlat {i}"
    s.scale = (SLOPE, 0.05, 0.13)
    s.rotation_euler = (0, TH, 0)
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    link(s); finish(s, M_TRIM)
# side plates: from pilot-beam corners down/forward to the narrow tip
for side in (-1, 1):
    py0, py1 = 0.95 * side, 0.12 * side
    pln = math.hypot(sdx, py1 - py0)
    ang = math.atan2(py1 - py0, sdx)
    bpy.ops.mesh.primitive_cube_add(size=1, location=((PBX+XTIP)/2, (py0+py1)/2, (TOP_Z+BOT_Z)/2))
    s = bpy.context.active_object; s.name = f"PilotSide {'L' if side>0 else 'R'}"
    s.scale = (pln, 0.05, TOP_Z - BOT_Z)
    s.rotation_euler = (0, 0, ang)
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    link(s); finish(s, M_TRIM)
# horizontal cross braces that taper with the A-frame
for t in (0.25, 0.5, 0.75):
    w = 2.0 - 1.7 * t
    box(f"PilotBrace {t}", (0.09, w, 0.09), (PBX + t*sdx + 0.04, 0, TOP_Z + t*sdz), M_BLACK)
# drip tray under the pilot
box("PilotTray", (XTIP - PBX + 0.1, 1.7, 0.05), ((PBX+XTIP)/2, 0, BOT_Z + 0.03), M_BLACK)
# diagonal stays from pilot beam down to the tray front
for side in (-1, 1):
    bpy.ops.mesh.primitive_cube_add(size=1, location=((PBX+XTIP)/2, side*0.80, (TOP_Z+BOT_Z)/2))
    s = bpy.context.active_object; s.name = f"PilotStay {'L' if side>0 else 'R'}"
    s.scale = (SLOPE*1.02, 0.07, 0.07)
    s.rotation_euler = (0, TH, 0)
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    link(s); finish(s, M_BLACK)
box("PilotBeam", (0.15, 2.0, 0.5), (7.15, 0, AXLE_Z + 0.35), M_BLACK)

# buffer / coupling
cyl("Buffer A", 0.12, 0.3, (7.3, 0.6, AXLE_Z + 0.45), rot=(0, RX, 0), material=M_STEEL, verts=16)
cyl("Buffer B", 0.12, 0.3, (7.3, -0.6, AXLE_Z + 0.45), rot=(0, RX, 0), material=M_STEEL, verts=16)

# whistle on cab roof
cyl("Whistle", 0.06, 0.3, (CAB_X1 - 0.4, 0.6, FRAME_TOP + 2.5), material=M_BRASS, verts=12)

# ---------- tender ----------
TEN = get_coll("Tender")
TEN_X1, TEN_X2 = -2.9, -6.9
TCX = (TEN_X1 + TEN_X2)/2
T_WHEELS = (-3.7, -4.7, -5.7)
for x in T_WHEELS:
    wheel(f"TWheel {x}", x, 0.30, LD_WY, w=0.10)
box("TenderFrame", (4.3, 2.2, 0.16), (TCX, 0, FRAME_TOP - 0.10), M_BLACK, TEN)
box("TenderBody",  (4.1, 2.6, 1.7), (TCX, 0, FRAME_TOP + 0.85), M_BODY, TEN)
box("TenderTop",   (4.2, 2.7, 0.1), (TCX, 0, FRAME_TOP + 1.75), M_TRIM, TEN)
# coal pile
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.9,
                                      location=(TCX - 0.3, 0, FRAME_TOP + 1.85))
coal = bpy.context.active_object; coal.name = "CoalPile"; link(coal, TEN)
coal.scale = (1.9, 1.2, 0.55)
bpy.ops.object.transform_apply(scale=True)
finish(coal, M_COAL)
# tender end gates
box("TenderGate L", (0.08, 2.7, 0.6), (TCX - 2.05, 0, FRAME_TOP + 2.05), M_TRIM, TEN)
box("TenderGate R", (0.08, 2.7, 0.6), (TCX + 2.05, 0, FRAME_TOP + 2.05), M_TRIM, TEN)
# drawbar loco<->tender
box("TenderDrawbar", (1.0, 0.25, 0.12), (TEN_X1 - 0.4, 0, FRAME_TOP - 0.25), M_BLACK, TEN)

print("build done:", len(bpy.data.objects), "objects")
