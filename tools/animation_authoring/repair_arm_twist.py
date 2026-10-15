"""Run once on an original authored action, before exporting VRMA.

Redistribute palm axial rotation into humanoid forearms and existing weighted
twist helpers. Preserve elbow/wrist positions; limit wrist swing to 40 degrees.
Do not run twice on an already repaired action. Reload the original or rebuild.
"""
import bpy
import json
import math
import struct
from pathlib import Path
from mathutils import Matrix, Quaternion, Vector

scene=bpy.context.scene
arm=bpy.data.objects['Armature']
action=arm.animation_data.action
if action.get('arm_twist_repair'):
    raise RuntimeError('Already repaired. Rebuild the original action before applying this pass.')
out=Path(bpy.data.filepath).parent
name='explain_2' if 'explain_2' in action.name else 'greet_1'
end=168 if name=='explain_2' else 72
curves=lambda ac:[f for l in ac.layers for s in l.strips for c in s.channelbags for f in c.fcurves]
times=sorted({float(k.co.x) for f in curves(action) for k in f.keyframe_points})
scene.frame_set(0);bpy.context.view_layer.update()
neutral={p.name:p.matrix_basis.copy() for p in arm.pose.bones}
rest={p.name:p.matrix.copy() for p in arm.pose.bones}
chains=[('Right','19.joint_RightArm','24.joint_RightElbow','31.joint_RightWrist'),('Left','37.joint_LeftArm','42.joint_LeftElbow','49.joint_LeftWrist')]
helpers=[p.name for p in arm.pose.bones if 'HandTwist' in p.name or 'ArmTwist' in p.name]
changed=helpers+[n for _,u,l,h in chains for n in (u,l,h)]
samples=[];angles={};previous={};report={'before_wrist_twist':0,'distal_sleeve_to_palm_twist':0,'max_wrist_swing':0,'max_forearm_roll':0,'max_hand_position_error_mm':0}
def local(p):
    args=dict(parent_matrix=p.parent.matrix,parent_matrix_local=p.bone.parent.matrix_local) if p.parent else {}
    return p.bone.convert_local_to_pose(p.matrix,p.bone.matrix_local,invert=True,**args)
def set_world(p,q,position):
    m=q.to_matrix().to_4x4();m.translation=position;p.matrix=m
for frame in times:
    scene.frame_set(int(frame),subframe=frame-int(frame));bpy.context.view_layer.update()
    originals={n:arm.pose.bones[n].matrix.copy() for n in changed}
    for side,u,l,h in chains:
        upper,lower,hand=[arm.pose.bones[n] for n in (u,l,h)]
        uq,lq,hq=[originals[n].to_quaternion() for n in (u,l,h)]
        axis=(originals[h].translation-originals[l].translation).normalized()
        carried=lq@rest[l].to_quaternion().inverted()@rest[h].to_quaternion()
        relative=carried.inverted()@hq
        local_axis=carried.inverted()@axis
        projection=Vector((relative.x,relative.y,relative.z)).dot(local_axis)
        angle=2*math.atan2(projection,relative.w)
        angle=(angle+math.pi)%(2*math.pi)-math.pi
        if side in angles:
            angle+=round((angles[side]-angle)/(2*math.pi))*2*math.pi
        angles[side]=angle
        report['before_wrist_twist']=max(report['before_wrist_twist'],abs(math.degrees(angle)))
        report['distal_sleeve_to_palm_twist']=max(report['distal_sleeve_to_palm_twist'],abs(math.degrees(angle))*.1)
        # Remove axial rotation from the wrist, retaining only a soft bend.
        twist=Quaternion(local_axis,angle)
        swing=twist.inverted()@relative
        if swing.w<0:swing.negate()
        swing_axis,swing_angle=swing.to_axis_angle()
        swing=Quaternion(swing_axis,min(swing_angle,math.radians(40)))
        report['max_wrist_swing']=max(report['max_wrist_swing'],min(math.degrees(swing_angle),40))
        upper_angle=max(-math.radians(18),min(math.radians(18),angle*.12))
        upper_axis=(originals[l].translation-originals[u].translation).normalized()
        set_world(upper,Quaternion(upper_axis,upper_angle)@uq,originals[u].translation)
        bpy.context.view_layer.update()
        # This rig's twist helpers are siblings, not a serial bone chain.
        # Keep the elbow-weighted parent near its original orientation; the
        # distal helpers carry increasing roll toward the palm.
        parent_share=.15
        set_world(lower,Quaternion(axis,angle*parent_share)@lq,originals[l].translation)
        bpy.context.view_layer.update()
        set_world(hand,Quaternion(axis,angle)@carried@swing,originals[h].translation)
        bpy.context.view_layer.update()
        report['max_forearm_roll']=max(report['max_forearm_roll'],abs(math.degrees(angle)))
        report['max_hand_position_error_mm']=max(report['max_hand_position_error_mm'],(hand.head-originals[h].translation).length*1000)
        for n in helpers:
            if side not in n:continue
            p=arm.pose.bones[n]
            is_forearm='HandTwist' in n
            parent=l if is_forearm else u
            child=h if is_forearm else l
            segment=rest[child].translation-rest[parent].translation
            fraction=(rest[n].translation-rest[parent].translation).dot(segment)/segment.length_squared
            # The main helper carries the distal sleeve; other helpers follow
            # their measured placement along the actual weighted limb.
            if n.endswith('Twist'):fraction=.9
            fraction=max(.15,min(.9,fraction))
            amount=angle if is_forearm else upper_angle
            bone_axis=rest[n].to_quaternion().inverted()@segment.normalized()
            p.matrix_basis=neutral[n]
            p.rotation_mode='QUATERNION'
            inherited=parent_share if is_forearm else 1.0
            p.rotation_quaternion=neutral[n].to_quaternion()@Quaternion(bone_axis,(fraction-inherited)*amount)
    bpy.context.view_layer.update()
    samples.append({n:neutral[n].copy() if frame in (0,end) else local(arm.pose.bones[n]) for n in changed})
for frame,poses in zip(times,samples):
    for n,m in poses.items():
        p=arm.pose.bones[n];p.rotation_mode='QUATERNION';q=m.to_quaternion()
        if n in previous and previous[n].dot(q)<0:q.negate()
        previous[n]=q.copy();p.rotation_quaternion=q;p.keyframe_insert('rotation_quaternion',frame=frame,group=n)
for f in curves(action):
    for k in f.keyframe_points:k.interpolation='BEZIER';k.handle_left_type=k.handle_right_type='AUTO_CLAMPED'
    f.update()

# Export helper offsets with the same glTF basis conversion as cloth tracks.
raw=(out.parent/'characters'/'Lumine_companion.vrm').read_bytes()
g=json.loads(raw[20:20+struct.unpack_from('<I',raw,12)[0]])
ids={n.get('name'):i for i,n in enumerate(g['nodes'])}
parents={c:i for i,n in enumerate(g['nodes']) for c in n.get('children',[])}
def node_world(i):
    n=g['nodes'][i];q=n.get('rotation',[0,0,0,1])
    m=Matrix.LocRotScale(Vector(n.get('translation',[0,0,0])),Quaternion((q[3],*q[:3])),Vector(n.get('scale',[1,1,1])))
    return node_world(parents[i])@m if i in parents else m
data=json.loads((out/(name+'.secondary.json')).read_text())
data['tracks']=[t for t in data['tracks'] if t['nodeName'] not in helpers]
for n in helpers:
    values=[];r=arm.data.bones[n].matrix_local.to_quaternion();basis=node_world(ids[n]).to_quaternion()
    for f in range(end+1):
        scene.frame_set(f);q=neutral[n].to_quaternion().inverted()@arm.pose.bones[n].rotation_quaternion
        w=r@q@r.inverted();d=basis.inverted()@Quaternion((w.w,w.x,w.z,-w.y))@basis;d.normalize();values.extend((d.x,d.y,d.z,d.w))
    values[:4]=values[-4:]=[0,0,0,1]
    data['tracks'].append(dict(nodeName=n,values=values))
(out/(name+'.secondary.json')).write_text(json.dumps(data,separators=(',',':')),encoding='utf-8')
action.use_fake_user=True
action['arm_twist_repair']=1
cloth_name='DHC_explain_2' if name=='explain_2' else 'DHC_greet'
old=bpy.data.actions.get(cloth_name)
if old:bpy.data.actions.remove(old,do_unlink=True)
cloth_action=action.copy();cloth_action.name=cloth_name;cloth_action.use_fake_user=True
secondary_names={t['nodeName'] for t in data['tracks']}
for layer in cloth_action.layers:
    for strip in layer.strips:
        for bag in strip.channelbags:
            for fc in list(bag.fcurves):
                if not any('"'+n+'"' in fc.data_path for n in secondary_names):bag.fcurves.remove(fc)
scene.frame_set(0)
bpy.app.driver_namespace['twist_repair']=dict(name=name,report=report,neutral=neutral,rest=rest,changed=changed,times=times)
result=report
