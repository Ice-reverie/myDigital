"""Run inside the connected Blender after importing characters/Lumine.vrm.

Authors a reusable Blender action, samples its quaternions for the web player,
and adds standard expression bindings to a separate copy of the source VRM.
"""
import bpy
import json
import math
import struct
import hashlib
from pathlib import Path
from mathutils import Euler, Quaternion, Matrix, Vector

ROOT = Path('C:/Users/18246/Desktop/DigitalHelper/models')
arm = bpy.data.objects['Armature']
scene = bpy.context.scene
scene.render.fps = 30
scene.frame_start, scene.frame_end = 1, 241
mapping = {b.bone: b.node.bone_name for b in arm.data.vrm_addon_extension.vrm0.humanoid.human_bones if b.node.bone_name}
source = (ROOT / 'characters/Lumine.vrm').read_bytes()
json_size = struct.unpack_from('<I', source, 12)[0]
gltf = json.loads(source[20:20 + json_size])
node_indices = {node.get('name'): i for i, node in enumerate(gltf['nodes'])}
parents = {child: i for i, node in enumerate(gltf['nodes']) for child in node.get('children', [])}

def world_matrix(i):
    node = gltf['nodes'][i]
    q = node.get('rotation', [0, 0, 0, 1])
    local = Matrix.LocRotScale(Vector(node.get('translation', [0, 0, 0])), Quaternion((q[3], *q[:3])), Vector(node.get('scale', [1, 1, 1])))
    return world_matrix(parents[i]) @ local if i in parents else local

def canonical_to_blender(q):
    return Quaternion((q.w, -q.x, q.z, q.y))

def pose_world_rotation(bone, q):
    rest = bone.bone.matrix_local.to_quaternion()
    bone.rotation_mode = 'QUATERNION'
    bone.rotation_quaternion = rest.inverted() @ q @ rest

# Small breathing and weight changes; feet counter-rotate to avoid rocking.
def pose(t):
    a = math.sin(2 * math.pi * t / 8)
    b = math.sin(2 * math.pi * t / 4)
    return {
        'spine': (.012*b, 0, .010*a), 'chest': (.014*b, .012*a, -.006*a),
        'neck': (0, .012*a, 0), 'head': (.012*b, .035*a, -.010*a),
        'leftUpperArm': (.035+.012*b, .025, 1.23+.025*a),
        'rightUpperArm': (.045-.012*b, -.025, -1.23+.022*a),
        'leftLowerArm': (0, -.12-.018*b, -.04), 'rightLowerArm': (0, .14+.018*b, .04),
        'leftHand': (.025, 0, .045), 'rightHand': (-.02, 0, -.04),
        'leftUpperLeg': (-.013-.006*a, 0, .006), 'rightUpperLeg': (-.013+.006*a, 0, -.006),
        'leftLowerLeg': (.026+.012*a, 0, 0), 'rightLowerLeg': (.026-.012*a, 0, 0),
        'leftFoot': (-.013-.006*a, 0, -.006), 'rightFoot': (-.013+.006*a, 0, .006),
    }

secondary = []
for bone in arm.pose.bones:
    name = bone.name
    if 'HairS' in name or 'AmiceB' in name or ('joint____' in name and int(name.rsplit('_', 1)[-1]) < 4):
        if name in node_indices:
            secondary.append(bone)

arm.animation_data_create()
arm.animation_data.action = bpy.data.actions.new('Lumine_Soft_Idle_8s')
for frame in range(1, 242, 6):
    t = (frame - 1) / 30
    for name, angles in pose(t).items():
        bone = arm.pose.bones[mapping[name]]
        pose_world_rotation(bone, canonical_to_blender(Euler(angles, 'XYZ').to_quaternion()))
        bone.keyframe_insert(data_path='rotation_quaternion', frame=frame, group=name)
    for index, bone in enumerate(secondary):
        phase = index * .53
        amplitude = .035 if 'HairS' in bone.name else .014
        # Independent, phase-shifted light breeze; never drives breast bones.
        q = Euler((amplitude * math.sin(2*math.pi*t/4 + phase),
                   amplitude*.3*math.sin(2*math.pi*t/8 + phase),
                   amplitude*.6*math.sin(2*math.pi*t/8 + phase)), 'XYZ').to_quaternion()
        pose_world_rotation(bone, q)
        bone.keyframe_insert(data_path='rotation_quaternion', frame=frame, group='Hair and fabric')

face = bpy.data.objects['U_Char_1']
keys = face.data.shape_keys.key_blocks
for name in ['2.ウィンク', '3.ウィンク右']:
    for frame, value in [(1,0),(77,0),(81,1),(86,0),(173,0),(177,1),(182,0),(241,0)]:
        keys[name].value = value
        keys[name].keyframe_insert(data_path='value', frame=frame)

tracks = [{'bone':name, 'values':[]} for name in pose(0)]
tracks += [{'node':node_indices[b.name], 'name':b.name, 'values':[]} for b in secondary]
for frame in range(1, 242):
    scene.frame_set(frame)
    for track in tracks:
        name = mapping[track['bone']] if 'bone' in track else track['name']
        bone = arm.pose.bones[name]
        rest = bone.bone.matrix_local.to_quaternion()
        q = rest @ bone.rotation_quaternion @ rest.inverted()
        if 'bone' in track:
            values = [-q.x, q.z, q.y, q.w]
        else:
            gltf_q = Quaternion((q.w, q.x, q.z, -q.y))
            basis = world_matrix(track['node']).to_quaternion()
            delta = basis.inverted() @ gltf_q @ basis
            values = [delta.x, delta.y, delta.z, delta.w]
        track['values'].extend(round(v, 7) for v in values)

payload = {'version':1, 'name':'Lumine Soft Idle', 'duration':8, 'fps':30,
           'sourceSha256':hashlib.sha256(source).hexdigest(), 'tracks':tracks}
(ROOT / 'animations/Lumine_idle.json').write_text(json.dumps(payload, separators=(',', ':')), encoding='utf-8')

# Keep original buffers/materials intact; expose existing wink and vowel shapes.
face_mesh = next(i for i,m in enumerate(gltf['meshes']) if len(m['primitives'][0].get('targets', [])) == len(keys) - 1)
names = [key.name for key in keys][1:]
gltf['meshes'][face_mesh].setdefault('extras', {})['targetNames'] = names
groups = gltf['extensions']['VRM']['blendShapeMaster']['blendShapeGroups']
bindings = {'blink':['2.ウィンク','3.ウィンク右'], 'blink_l':['2.ウィンク'], 'blink_r':['3.ウィンク右'],
            'a':['20.あ'], 'i':['21.い'], 'u':['22.う'], 'e':['24.え'], 'o':['23.お']}
for preset, shapes in bindings.items():
    groups.append({'name':preset,'presetName':preset,'binds':[{'mesh':face_mesh,'index':names.index(n),'weight':100} for n in shapes], 'materialValues':[], 'isBinary':False})
vrm = gltf['extensions']['VRM']
for key in ['lookAtHorizontalInner','lookAtHorizontalOuter','lookAtVerticalDown','lookAtVerticalUp']:
    vrm['firstPerson'][key] = {'curve':[0,0,0,1,1,1,1,0], 'xRange':90, 'yRange':12 if 'Horizontal' in key else 8}
encoded = json.dumps(gltf,separators=(',', ':'),ensure_ascii=False).encode('utf-8')
encoded += b' ' * (-len(encoded) % 4)
tail = source[20 + json_size:]
output = struct.pack('<III',0x46546c67,2,20+len(encoded)+len(tail))+struct.pack('<II',len(encoded),0x4e4f534a)+encoded+tail
(ROOT / 'characters/Lumine_companion.vrm').write_bytes(output)
scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / 'animations/Lumine_idle.blend'))
result = {'tracks':len(tracks),'secondaryBones':len(secondary),'frames':241,'expressions':list(bindings),'files':['Lumine_idle.blend','Lumine_idle.json','Lumine_companion.vrm']}
