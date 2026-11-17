"""3D explainer: self-locking (wedge-locking) washers. Blender (bpy) script.

usage: python washer.py SHOT FRAMES OUTDIR [--scale 0.75] [--samples 16] [--frame N]
Each shot builds its own scene and renders FRAMES frames at 24 fps (1080x1920 * scale)."""
import bpy, bmesh, math, sys, os
from mathutils import Vector, Euler

A = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
SHOT = int(A[0]); FRAMES = int(A[1]); OUT = A[2]
def opt(k, d): return type(d)(A[A.index(k) + 1]) if k in A else d
SCALE = opt("--scale", 0.75); SAMPLES = opt("--samples", 16); ONLY = opt("--frame", -1)
START = opt("--start", 1); END = opt("--end", 0)
FPS = 24
TAU = 2 * math.pi

# ---------------------------------------------------------------- scene setup
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"; sc.cycles.samples = SAMPLES; sc.cycles.use_denoising = True
try: sc.cycles.denoiser = "OPENIMAGEDENOISE"
except Exception: pass
sc.render.resolution_x = int(1080 * SCALE); sc.render.resolution_y = int(1920 * SCALE)
sc.render.fps = FPS; sc.frame_start = 1; sc.frame_end = FRAMES
sc.render.image_settings.file_format = "JPEG"; sc.render.image_settings.quality = 92
sc.view_settings.view_transform = "AgX" if "AgX" in [v.identifier for v in bpy.types.ColorManagedViewSettings.bl_rna.properties["view_transform"].enum_items] else "Filmic"
sc.cycles.max_bounces = 4; sc.render.use_persistent_data = True

world = bpy.data.worlds.new("w"); sc.world = world; world.use_nodes = True
bg = world.node_tree.nodes["Background"]; bg.inputs[0].default_value = (0.012, 0.014, 0.02, 1); bg.inputs[1].default_value = 1.0


def mat(name, color, metal=1.0, rough=0.32, emit=None):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1); b.inputs["Metallic"].default_value = metal; b.inputs["Roughness"].default_value = rough
    return m


STEEL = mat("steel", (0.62, 0.63, 0.66), 1.0, 0.28)
DARK = mat("darksteel", (0.25, 0.26, 0.28), 1.0, 0.38)
GOLD = mat("wedge", (0.95, 0.72, 0.18), 1.0, 0.30)        # brand gold for the wedge-lock pair
PLATE = mat("plate", (0.32, 0.36, 0.42), 0.9, 0.45)
WOOD = mat("wood", (0.33, 0.20, 0.11), 0.0, 0.55)
RED = mat("red", (0.85, 0.12, 0.10), 0.0, 0.5)


def link(ob):
    sc.collection.objects.link(ob); return ob


def mesh_obj(name, verts, faces, m, smooth=False):
    me = bpy.data.meshes.new(name); me.from_pydata(verts, [], faces); me.update()
    ob = link(bpy.data.objects.new(name, me)); ob.data.materials.append(m)
    if smooth:
        for p in me.polygons: p.use_smooth = True
    return ob


def annulus(name, r0, r1, ztop, zbot, m, nth=360, nr=6, parent=None):
    """Closed ring; ztop(theta, r) / zbot(theta, r) give the face heights (cams, teeth...)."""
    V, F = [], []
    rs = [r0 + (r1 - r0) * i / (nr - 1) for i in range(nr)]
    def idx(face, i, j): return face * nth * nr + (i % nth) * nr + j
    for face, zf in ((0, ztop), (1, zbot)):
        for i in range(nth):
            th = TAU * i / nth
            for r in rs:
                V.append((r * math.cos(th), r * math.sin(th), zf(th, r)))
    for i in range(nth):
        for j in range(nr - 1):
            F.append((idx(0, i, j), idx(0, i + 1, j), idx(0, i + 1, j + 1), idx(0, i, j + 1)))
            F.append((idx(1, i, j), idx(1, i, j + 1), idx(1, i + 1, j + 1), idx(1, i + 1, j)))
        F.append((idx(0, i, nr - 1), idx(0, i + 1, nr - 1), idx(1, i + 1, nr - 1), idx(1, i, nr - 1)))   # outer wall
        F.append((idx(0, i, 0), idx(1, i, 0), idx(1, i + 1, 0), idx(0, i + 1, 0)))                      # inner wall
    ob = mesh_obj(name, V, F, m)
    if parent: ob.parent = parent
    return ob


def saw(th, n):            # 0..1 ramp repeated n times around
    x = (th * n / TAU) % 1.0
    return x


def cylinder(name, r, h, m, verts=64, z0=0.0, bevel=0.0):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=h, location=(0, 0, z0 + h / 2))
    ob = bpy.context.active_object; ob.name = name; ob.data.materials.append(m)
    if bevel:
        bv = ob.modifiers.new("b", "BEVEL"); bv.width = bevel; bv.segments = 2
    for p in ob.data.polygons: p.use_smooth = verts > 12
    return ob


# geometry (metres, M24-ish joint scaled up for the camera)
R_BOLT = 0.012; PITCH = 0.003; BOLT_TOP = 0.034
def nut(z0, m=STEEL):
    o = cylinder("nut", 0.021, 0.019, m, verts=6, z0=z0, bevel=0.0015)
    o.data.polygons.foreach_set("use_smooth", [False] * len(o.data.polygons))
    h = cylinder("nuthole", R_BOLT * 1.02, 0.03, m, z0=z0 - 0.005)
    bo = o.modifiers.new("hole", "BOOLEAN"); bo.object = h; bo.operation = "DIFFERENCE"; h.hide_render = True; h.hide_viewport = True
    return o


def bolt(top):
    shank = cylinder("shank", R_BOLT, top + 0.06, DARK, z0=-0.06)
    # thread look: bump from a wave texture along Z
    m = mat("thread", (0.42, 0.43, 0.46), 1.0, 0.35)
    nt = m.node_tree; wave = nt.nodes.new("ShaderNodeTexWave"); wave.wave_type = "BANDS"; wave.bands_direction = "Z"
    wave.inputs["Scale"].default_value = 1 / PITCH / 9.5
    bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.6
    nt.links.new(wave.outputs["Fac"], bump.inputs["Height"]); nt.links.new(bump.outputs["Normal"], nt.nodes["Principled BSDF"].inputs["Normal"])
    shank.data.materials[0] = m
    return shank


def plates():
    p1 = link(bpy.data.objects.new("p1", None))
    for z0, name in ((-0.04, "lower"), (-0.02, "upper")):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, z0 + 0.01)); b = bpy.context.active_object
        b.scale = (0.16, 0.10, 0.02); b.name = name; b.data.materials.append(PLATE)
        bv = b.modifiers.new("b", "BEVEL"); bv.width = 0.0015; bv.segments = 2
        h = cylinder(name + "h", R_BOLT * 1.1, 0.05, PLATE, z0=-0.05); h.hide_render = True; h.hide_viewport = True
        bo = b.modifiers.new("hole", "BOOLEAN"); bo.object = h; bo.operation = "DIFFERENCE"
    return [bpy.data.objects["lower"], bpy.data.objects["upper"]]


def floor():
    bpy.ops.mesh.primitive_plane_add(size=4, location=(0, 0, -0.0401)); f = bpy.context.active_object; f.data.materials.append(WOOD)
    return f


def split_washer(z0):
    """Helical split spring washer: rectangular section, gap at theta=0, ends offset in Z."""
    gap = 0.25
    def zt(th, r): return z0 + 0.0035 + 0.002 * (th / TAU)
    def zb(th, r): return z0 + 0.002 * (th / TAU)
    V, F = [], []
    n = 200; r0, r1 = R_BOLT * 1.05, 0.025
    for i in range(n + 1):
        th = gap + (TAU - 2 * gap) * i / n
        for (r, zf) in ((r0, zb), (r1, zb), (r1, zt), (r0, zt)):
            V.append((r * math.cos(th), r * math.sin(th), zf(th, r)))
    for i in range(n):
        a, b = 4 * i, 4 * (i + 1)
        for k in range(4):
            F.append((a + k, a + (k + 1) % 4, b + (k + 1) % 4, b + k))
    F.append((0, 3, 2, 1)); a = 4 * n; F.append((a, a + 1, a + 2, a + 3))
    return mesh_obj("split", V, F, STEEL)


NCAM, NTEETH, CAM_H, TOOTH_H, WT = 12, 48, 0.0016, 0.0005, 0.0032
def wedge_washer(name, flip):
    """One half of a wedge-lock pair: cams on the inner face, radial teeth on the outer face.
    flip=False: lower washer (teeth down, cams up); True: upper washer (cams down, teeth up)."""
    r0, r1 = R_BOLT * 1.05, 0.021
    cam = lambda th, r: CAM_H * saw(th, NCAM)
    tooth = lambda th, r: TOOTH_H * abs(2 * saw(th, NTEETH) - 1)
    if not flip:
        zt = lambda th, r: WT + cam(th, r); zb = lambda th, r: -tooth(th, r)
    else:
        zt = lambda th, r: WT + CAM_H + tooth(th, r); zb = lambda th, r: cam(th, r)
    return annulus(name, r0, r1, zt, zb, GOLD, nth=720, nr=5)


def light_rig(target=(0, 0, 0)):
    def area(name, loc, energy, size, color=(1, 1, 1)):
        l = bpy.data.lights.new(name, "AREA"); l.energy = energy; l.size = size; l.color = color
        o = link(bpy.data.objects.new(name, l)); o.location = loc
        o.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler(); return o
    area("key", (0.35, -0.35, 0.45), 7, 0.4)
    area("rim", (-0.4, 0.3, 0.25), 6, 0.3, (0.8, 0.88, 1.0))
    area("fill", (0.0, -0.6, 0.05), 1.5, 0.6)


def camera(loc, target, lens=60):
    c = bpy.data.cameras.new("cam"); c.lens = lens; c.clip_start = 0.001; c.dof.use_dof = True; c.dof.aperture_fstop = 16
    o = link(bpy.data.objects.new("cam", c)); o.location = loc; sc.camera = o
    tgt = link(bpy.data.objects.new("tgt", None)); tgt.location = target
    tc = o.constraints.new("TRACK_TO"); tc.target = tgt; tc.track_axis = "TRACK_NEGATIVE_Z"; tc.up_axis = "UP_Y"
    c.dof.focus_object = tgt
    return o, tgt


def key(ob, prop, frame, value):
    setattr(ob, prop, value) if not isinstance(value, (tuple, list)) else setattr(ob, prop, value)
    ob.keyframe_insert(prop, frame=frame)


def every(fn, step=1):
    for f in range(1, FRAMES + 1, step):
        fn(f, (f - 1) / max(1, FRAMES - 1))


def linear_all():
    for ob in bpy.data.objects:
        ad = ob.animation_data
        if ad and ad.action:
            try:
                for fc in ad.action.fcurves:
                    for kp in fc.keyframe_points: kp.interpolation = "LINEAR"
            except Exception:
                pass


# ---------------------------------------------------------------- shots
def joint(washer=None, loosen_turns=0.0, vibrate=True, wedge_spin=0.0):
    floor(); lo, up = plates(); bolt(BOLT_TOP)
    stack = 0.0; parts = []
    if washer == "split":
        parts.append(split_washer(0.0)); stack = 0.0035
    elif washer == "wedge":
        lw = wedge_washer("w_lo", False); uw = wedge_washer("w_up", True); parts += [lw, uw]; stack = WT * 2 + CAM_H + TOOTH_H
    n = nut(stack)
    # vibration: upper plate + parts slide sideways; nut rotates (loosens) and climbs the thread
    def anim(f, t):
        dx = 0.0025 * math.sin(f * 1.9) if vibrate else 0.0
        up.location.x = dx; up.keyframe_insert("location", frame=f)
        ang = -TAU * loosen_turns * t
        n.rotation_euler.z = ang; n.location.z = stack + PITCH * loosen_turns * t; n.location.x = dx * 0.3
        n.keyframe_insert("rotation_euler", frame=f); n.keyframe_insert("location", frame=f)
        for p in parts:
            p.location.x = dx * 0.6; p.keyframe_insert("location", frame=f)
    every(anim)
    return n, parts


def shot1():   # hook: nut shaking loose
    joint(None, loosen_turns=1.2)
    cam, tgt = camera((0.11, -0.17, 0.09), (0, 0, 0.012), 70)
    tgt.location = (0, 0, 0.012)


def shot2():   # transverse vibration, wider
    joint(None, loosen_turns=0.6)
    cam, tgt = camera((0.0, -0.33, 0.12), (0, 0, 0.0), 55)
    def a(f, t):
        cam.location.x = -0.08 + 0.16 * t; cam.keyframe_insert("location", frame=f)
    every(a, 6)


def shot3():   # split spring washer, still loosening
    joint("split", loosen_turns=0.8)
    cam, tgt = camera((0.1, -0.17, 0.035), (0, 0, 0.004), 70)


def shot4():   # wedge pair, exploded and turning
    floor()
    lw = wedge_washer("w_lo", False); uw = wedge_washer("w_up", True)
    for o in (lw, uw): o.location.z = 0.03
    def a(f, t):
        s = min(1, t * 1.6); e = 0.5 - 0.5 * math.cos(math.pi * s)
        uw.location.z = 0.03 + 0.028 * e; uw.rotation_euler.x = math.radians(-35) * e
        lw.location.z = 0.03 - 0.004 * e; lw.rotation_euler.x = math.radians(25) * e
        for o in (lw, uw):
            o.rotation_euler.z = TAU * 0.25 * t; o.keyframe_insert("location", frame=f); o.keyframe_insert("rotation_euler", frame=f)
    every(a, 2)
    camera((0.0, -0.16, 0.07), (0, 0, 0.042), 60)


def shot5():   # the cam trick: upper washer turns loose and has to climb the cams
    floor()
    lw = wedge_washer("w_lo", False); uw = wedge_washer("w_up", True)
    for o in (lw, uw): o.location.z = 0.0
    # simplified bolt + nut above to show the stretch
    n = link(bpy.data.objects.new("nut", None))
    step = TAU / NCAM
    def a(f, t):
        e = min(1, t * 1.25)
        rot = -0.45 * step * e                     # loosening direction
        lift = CAM_H * 0.45 * e                     # riding up the cams
        uw.rotation_euler.z = rot; uw.location.z = lift; n.rotation_euler.z = rot; n.location.z = WT * 2 + CAM_H + TOOTH_H + lift
        for o in (uw, n): o.keyframe_insert("location", frame=f); o.keyframe_insert("rotation_euler", frame=f)
    every(a, 2)
    cam, _ = camera((0.0, -0.12, 0.035), (0, 0, 0.003), 70); cam.data.dof.use_dof = False


def shot6():   # locked joint: vibration, nut does not turn
    joint("wedge", loosen_turns=0.0)
    cam, tgt = camera((0.12, -0.16, 0.08), (0, 0, 0.008), 65)
    def a(f, t):
        ang = math.radians(-25 + 50 * t); r = 0.2
        cam.location = (r * math.sin(ang), -r * math.cos(ang), 0.08); cam.keyframe_insert("location", frame=f)
    every(a, 4)


{1: shot1, 2: shot2, 3: shot3, 4: shot4, 5: shot5, 6: shot6}[SHOT]()
light_rig()
os.makedirs(OUT, exist_ok=True)
frames = [ONLY] if ONLY > 0 else range(START, (END or FRAMES) + 1)
for f in frames:
    sc.frame_set(f)
    sc.render.filepath = os.path.join(OUT, f"f{f:05d}.jpg")
    bpy.ops.render.render(write_still=True)
