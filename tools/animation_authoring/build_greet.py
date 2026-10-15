"""Author the face-side greeting from the user's 5.37-second video in Blender 5.2.

Only frame 1 of the imported Humanoid supplies the shared neutral pose.
No motion from the rejected greeting is used. Reference motion: 1.0-3.0 seconds.
Cloth curves are also exported as local quaternion offsets for the web player.
"""
import bpy
import json
import math
import struct
from pathlib import Path
from mathutils import Matrix, Quaternion, Vector

OUT = Path(bpy.data.filepath).parent if bpy.data.filepath else Path(__file__).parent
REFERENCE = json.loads((OUT.parents[1]/'tools'/'animation_authoring'/'greet.reference.json').read_text(encoding='utf-8'))
arm = bpy.data.objects['Armature']
scene = bpy.context.scene
source = bpy.data.actions.get('Humanoid')
if source is None:
    raise RuntimeError('Import the original greet VRMA first (Humanoid action)')
arm.animation_data.action = source
for p in arm.pose.bones:
    p.matrix_basis = Matrix.Identity(4)
scene.frame_set(1)
bpy.context.view_layer.update()
neutral = {p.name: p.matrix_basis.copy() for p in arm.pose.bones}
world0 = {p.name: p.matrix.copy() for p in arm.pose.bones}


def smooth(a, b, f):
    t = max(0.0, min(1.0, (f-a)/(b-a)))
    return t*t*(3-2*t)


def rotation(axis, degrees):
    return Quaternion(axis, math.radians(degrees))


def keyed(points, f):
    """Ease between observed poses, rather than driving the wave with a sine."""
    if f <= points[0][0]:
        return points[0][1]
    for (a, va), (b, vb) in zip(points, points[1:]):
        if f <= b:
            return va + (vb-va)*smooth(a, b, f)
    return points[-1][1]


def reference_value(name, source_frame):
    """Monotone cubic Hermite: dense observations with continuous velocity."""
    points = REFERENCE[name]
    def tangent(i):
        if i == 0 or i == len(points)-1:
            return 0.0
        left = (points[i][1]-points[i-1][1])/(points[i][0]-points[i-1][0])
        right = (points[i+1][1]-points[i][1])/(points[i+1][0]-points[i][0])
        return 2*left*right/(left+right) if left*right > 0 else 0.0
    if source_frame <= points[0][0]: return points[0][1]
    for i, ((a,va),(b,vb)) in enumerate(zip(points,points[1:])):
        if source_frame <= b:
            t=(source_frame-a)/(b-a)
            return (2*t**3-3*t*t+1)*va+(t**3-2*t*t+t)*(b-a)*tangent(i)+(-2*t**3+3*t*t)*vb+(t**3-t*t)*(b-a)*tangent(i+1)
    return points[-1][1]


def local_pose(pb):
    args = dict(parent_matrix=pb.parent.matrix,
                parent_matrix_local=pb.bone.parent.matrix_local) if pb.parent else {}
    return pb.bone.convert_local_to_pose(pb.matrix, pb.bone.matrix_local, invert=True, **args)


rig = arm.copy()
rig.data = arm.data.copy()
rig.name = '__GREET_SOLVER'
scene.collection.objects.link(rig)
rig.animation_data_clear()
rig.data.animation_data_clear()
created = [rig]
rig_data = rig.data


def target(name, matrix):
    obj = bpy.data.objects.new('__GREET_' + name, None)
    scene.collection.objects.link(obj)
    obj.matrix_world = arm.matrix_world @ matrix
    created.append(obj)
    return obj


def ik(end, obj):
    c = rig.pose.bones[end].constraints.new('IK')
    c.target = obj
    c.chain_count = 2
    c.iterations = 256
    c.use_stretch = False


def orient(bone, obj):
    c = rig.pose.bones[bone].constraints.new('COPY_ROTATION')
    c.target = obj
    c.owner_space = c.target_space = 'WORLD'


for knee, foot in [('69.joint_RightKneeD', '70.joint_RightFootD'),
                   ('73.joint_LeftKneeD', '74.joint_LeftFootD')]:
    obj = target(foot, world0[foot])
    ik(knee, obj)
    orient(foot, obj)
right = '31.joint_RightWrist'
left = '49.joint_LeftWrist'
hand = target('RightHand', world0[right])
left_hand = target('LeftHand', world0[left])
ik('42.joint_LeftElbow', left_hand)
orient(right, hand)
head = target('Head', world0['15.joint_Head'])
orient('15.joint_Head', head)

# Palm orientation calibrated from the actual finger bases, not assumed bone axes.
forward = (arm.pose.bones['124.joint_RightMiddle1'].head-world0[right].translation).normalized()
width = (arm.pose.bones['126.joint_RightPinky1'].head-arm.pose.bones['123.joint_RightIndex1'].head).normalized()
normal = width.cross(forward).normalized()
width = forward.cross(normal).normalized()
old_frame = Matrix((width, forward, normal)).transposed()

humans = {b.node.bone_name for b in arm.data.vrm_addon_extension.vrm1.humanoid.human_bones.human_bone_name_to_human_bone().values() if b.node.bone_name}
names = sorted(humans | {'283.!Root'})
cloth = [p.name for p in arm.pose.bones if 'AmiceB' in p.name or 'joint____0_' in p.name]
samples = []
cloth_values = {n: [] for n in cloth}
# Retain every source frame at fractional Blender frames as well as every output
# frame: 30fps reference + 24fps playback yield 145 distinct authored poses.
author_frames = sorted(set(range(73)) | {round((sf-24)*24/30,6) for sf in range(24,115)})
try:
    for f in author_frames:
        sf = 24 + f*30/24
        envelope = smooth(27,44,sf)*(1-smooth(74,96,sf))
        # The reference opens the quiet arm during the lift, then lets it settle.
        left_envelope = keyed([(24,0),(29,.12),(34,.55),(39,1),(45,.85),(51,.6),(72,.6),(84,.25),(98,0),(114,0)],sf)
        weight = smooth(29,48,sf)*(1-smooth(75,98,sf))
        for p in rig.pose.bones:
            p.matrix_basis = neutral[p.name]
        root = rig.pose.bones['283.!Root']
        root.location = neutral[root.name].translation + root.bone.matrix_local.to_3x3().inverted() @ Vector((.034*weight, 0, -.009*weight))
        rig.pose.bones['13.joint_HipMaster'].rotation_quaternion = neutral['13.joint_HipMaster'].to_quaternion() @ rotation((0, 0, 1), -1.5*weight)
        breathing = .6*math.sin(2*math.pi*f/60)*envelope
        for bn, amount, lean in [('11.joint_Torso', .25*breathing, 4), ('12.joint_Torso2', breathing, 3)]:
            rig.pose.bones[bn].rotation_quaternion = neutral[bn].to_quaternion() @ rotation((0, 0, 1), lean*weight) @ rotation((1, 0, 0), amount)
        # One gentle held inclination, independent of the wrist's wave rhythm.
        mat = (rotation((0, 1, 0), -4*weight) @ world0['15.joint_Head'].to_quaternion()).to_matrix().to_4x4()
        mat.translation = world0['15.joint_Head'].translation
        head.matrix_world = arm.matrix_world @ mat
        spread = smooth(33,43,sf)*(1-smooth(75,91,sf))
        for bn in humans:
            if any(part in bn for part in ('Index', 'Middle', 'Ring', 'Pinky', 'Thumb')):
                sign = 1 if 'Right' in bn else -1
                curl = 3 if 'Right' in bn else 4
                pb=rig.pose.bones[bn]
                pb.rotation_quaternion = neutral[bn].to_quaternion() @ rotation((1, 0, 0), sign*curl*envelope)
                if 'Right' in bn and bn.endswith('1'):
                    splay = next((v for part,v in [('Index',5),('Middle',0),('Ring',-3),('Pinky',-8)] if part in bn),0)
                    axis=world0[bn].to_quaternion().inverted() @ normal
                    pb.rotation_quaternion = pb.rotation_quaternion @ rotation(axis,splay*spread)
        # Explicit low-elbow FK avoids pole-vector flips as the hand folds upward.
        # Preserve bone lengths while tracking the reference's elbow/wrist arcs.
        bpy.context.view_layer.update()
        upper = rig.pose.bones['19.joint_RightArm']
        lower = rig.pose.bones['24.joint_RightElbow']
        rest_direction = world0[lower.name].translation-world0[upper.name].translation
        base_angle = math.atan2(-rest_direction.x,-rest_direction.z)
        angle = base_angle+math.radians(reference_value('upperArm',sf)-22)
        depth = rest_direction.normalized().y-.10*envelope
        projection = math.sqrt(1-depth*depth)
        direction = Vector((-math.sin(angle)*projection,depth,-math.cos(angle)*projection))
        turn = rotation((0,1,0), reference_value('upperArm',sf)-22)
        uq = (turn @ rest_direction).rotation_difference(direction) @ turn @ world0[upper.name].to_quaternion()
        um = uq.to_matrix().to_4x4(); um.translation = upper.head
        upper.matrix = um
        bpy.context.view_layer.update()
        rest_direction = world0[right].translation-world0[lower.name].translation
        base_angle = math.atan2(-rest_direction.x,-rest_direction.z)
        angle = base_angle+math.radians(reference_value('forearm',sf)-26)
        depth = rest_direction.normalized().y-.18*envelope
        projection = math.sqrt(1-depth*depth)
        direction = Vector((-math.sin(angle)*projection,depth,-math.cos(angle)*projection))
        turn = rotation((0,1,0), reference_value('forearm',sf)-26)
        lq = (turn @ rest_direction).rotation_difference(direction) @ turn @ world0[lower.name].to_quaternion()
        lm = lq.to_matrix().to_4x4(); lm.translation = lower.head
        lower.matrix = lm
        # Palm rotation has its own observed timeline, lagging the forearm lift.
        angle = math.radians(reference_value('palm',sf))
        palm_forward=Vector((-math.sin(angle),0,-math.cos(angle)))
        palm_normal=Vector((0,1,0))
        palm_width=palm_forward.cross(palm_normal).normalized()
        palm_frame=Matrix((palm_width,palm_forward,palm_normal)).transposed()
        desired_q=(palm_frame @ old_frame.transposed() @ world0[right].to_3x3()).to_quaternion()
        palm_weight=smooth(27,36,sf)*(1-smooth(86,98,sf))
        q=world0[right].to_quaternion().slerp(desired_q,palm_weight)
        mat = q.to_matrix().to_4x4()
        mat.translation = world0[right].translation
        hand.matrix_world = arm.matrix_world @ mat
        mat = world0[left].copy()
        mat.translation += Vector((.045, -.014, .025))*left_envelope + Vector((.012,0,0))*weight
        left_hand.matrix_world = arm.matrix_world @ mat
        bpy.context.view_layer.update()
        ev = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
        samples.append({n: neutral[n].copy() if f in (0, 72) else local_pose(ev.pose.bones[n]) for n in names})
        for n in cloth:
            if 'AmiceB' in n:
                segment = int(n[-1])-1
                delay = 2 + segment*.25
                def pulse(start, end):
                    t=(f-start-delay)/(end-start)
                    return math.sin(math.pi*t)**2 if 0<t<1 else 0.0
                movement = pulse(3, 25)-.65*pulse(40, 65)
                angle = (1.0+.6*segment)*movement
                side = 1 if ' R ' in n else -.75
                q = rotation((1, 0, 0), angle) @ rotation((0, 0, 1), .25*side*angle)
            else:
                side = math.cos(int(n.rsplit('_', 1)[1])*2*math.pi/10)
                q = rotation((0, 0, 1), 1.6*side*smooth(7, 24, f)*(1-smooth(42, 67, f)))
            if f in (0, 72):
                q = Quaternion()
            cloth_values[n].append(q)
finally:
    for obj in created:
        bpy.data.objects.remove(obj, do_unlink=True)
    if rig_data.users == 0:
        bpy.data.armatures.remove(rig_data)

# Keyframe insertion selects Blender 5.2 action slots and channelbags automatically.
for name in ('DH_greet', 'DHX_greet', 'DHC_greet'):
    previous = bpy.data.actions.get(name)
    if previous:
        bpy.data.actions.remove(previous, do_unlink=True)
body = bpy.data.actions.new('DH_greet')
body.use_fake_user = True
arm.animation_data.action = body
previous_quaternions = {}
for index, (f, poses) in enumerate(zip(author_frames, samples)):
    for n, matrix in poses.items():
        p = arm.pose.bones[n]
        p.rotation_mode = 'QUATERNION'
        q=matrix.to_quaternion()
        if n in previous_quaternions and q.dot(previous_quaternions[n]) < 0:
            q.negate()
        previous_quaternions[n]=q.copy()
        p.rotation_quaternion = q
        p.keyframe_insert('rotation_quaternion', frame=f, group=n)
        if n == '283.!Root':
            p.location = matrix.translation
            p.keyframe_insert('location', frame=f, group=n)
    for n, qs in cloth_values.items():
        p = arm.pose.bones[n]
        p.rotation_mode = 'QUATERNION'
        p.rotation_quaternion = neutral[n].to_quaternion() @ qs[index]
        p.keyframe_insert('rotation_quaternion', frame=f, group='Clothing')

expr = bpy.data.actions.new('DHX_greet')
expr.use_fake_user = True
arm.data.animation_data.action = expr
presets = arm.data.vrm_addon_extension.vrm1.expressions.preset
happy = presets.happy
if not happy.morph_target_binds:
    for shape, weight in [('34.口角上げ', .5), ('39.にこり', .2)]:
        bind = happy.morph_target_binds.add()
        bind.node.mesh_object_name = 'U_Char_1'
        bind.index = shape
        bind.weight = weight
for f in author_frames:
    sf = 24+f*30/24
    for name in ['happy', 'aa', 'ih', 'ou', 'ee', 'oh', 'sad', 'surprised', 'relaxed', 'blink']:
        value = keyed([(24,0),(29,.05),(38,.65),(45,.75),(73,.75),(90,.25),(109,.05),(114,0)],sf) if name == 'happy' else 0.0
        if name == 'blink': value = reference_value('blink',sf)
        if name == 'happy' and f >= 68:
            value = .05*(1-smooth(68, 72, f))
        e = getattr(presets, name)
        e.preview = value
        e.keyframe_insert('preview', frame=f)

def curves(action):
    return [fc for layer in action.layers for strip in layer.strips for cb in strip.channelbags for fc in cb.fcurves]

for ac in (body, expr):
    for fc in curves(ac):
        for k in fc.keyframe_points:
            k.interpolation = 'BEZIER'
            k.handle_left_type = k.handle_right_type = 'AUTO_CLAMPED'
        fc.update()
cloth_action = body.copy()
cloth_action.name = 'DHC_greet'
cloth_action.use_fake_user = True
for layer in cloth_action.layers:
    for strip in layer.strips:
        for cb in strip.channelbags:
            for fc in list(cb.fcurves):
                if not any('"'+n+'"' in fc.data_path for n in cloth):
                    cb.fcurves.remove(fc)
scene.render.fps = 24
scene.render.fps_base = 1
scene.frame_start, scene.frame_end = 0, 72
scene.frame_set(30)
bpy.context.view_layer.update()
raw = (OUT.parent/'characters'/'Lumine_companion.vrm').read_bytes()
gltf = json.loads(raw[20:20+struct.unpack_from('<I', raw, 12)[0]])
node_ids = {node.get('name'): i for i, node in enumerate(gltf['nodes'])}
parents = {child: i for i, node in enumerate(gltf['nodes']) for child in node.get('children', [])}
def node_world(i):
    n = gltf['nodes'][i]
    q = n.get('rotation', [0,0,0,1])
    m = Matrix.LocRotScale(Vector(n.get('translation', [0,0,0])), Quaternion((q[3],*q[:3])), Vector(n.get('scale', [1,1,1])))
    return node_world(parents[i]) @ m if i in parents else m
tracks = []
for n, qs in cloth_values.items():
    rest = arm.data.bones[n].matrix_local.to_quaternion()
    basis = node_world(node_ids[n]).to_quaternion()
    values = []
    for f, q in zip(author_frames,qs):
        if f != int(f):
            continue
        world_q = rest @ q @ rest.inverted()
        gltf_q = Quaternion((world_q.w, world_q.x, world_q.z, -world_q.y))
        delta = basis.inverted() @ gltf_q @ basis
        delta.normalize()
        values.extend((delta.x, delta.y, delta.z, delta.w))
    values[:4] = values[-4:] = [0,0,0,1]
    tracks.append(dict(nodeName=n, values=values))
secondary = dict(version=1, fps=24, duration=3, tracks=tracks)
(OUT/'greet_1.secondary.json').write_text(json.dumps(secondary, separators=(',', ':')), encoding='utf-8')
bpy.app.driver_namespace['greet_build'] = dict(arm=arm, neutral=neutral, world0=world0, body=body, expr=expr, cloth=cloth, out=OUT)
result = dict(body=body.name, expressions=expr.name, cloth_tracks=len(cloth), authored_poses=len(author_frames), reference_range=REFERENCE['sourceRange'], reference_observations=sum(len(REFERENCE[k]) for k in ('upperArm','forearm','palm','blink')))
