"""Validate the evaluated repaired action, including weighted distal helpers."""
import bpy
import json
import math
from pathlib import Path
from mathutils import Vector

b=bpy.app.driver_namespace['twist_repair'];a=bpy.data.objects['Armature'];s=bpy.context.scene
end=s.frame_end;qa=dict(b['report']);qa.update(feet_mm=0,endpoint_error=0,distal_twist_measured=0,max_quarter_frame_degrees=0)
previous={}
for i in range(end*4+1):
    f=i/4;s.frame_set(int(f),subframe=f-int(f));bpy.context.view_layer.update()
    for name in ['70.joint_RightFootD','74.joint_LeftFootD']:
        p=a.pose.bones[name];r=b['rest'][name];tip=r@(p.bone.matrix_local.inverted()@p.bone.tail_local)
        qa['feet_mm']=max(qa['feet_mm'],(p.head-r.translation).length*1000,(p.tail-tip).length*1000)
    for p in a.pose.bones:
        q=p.rotation_quaternion.copy()
        if p.name in previous:qa['max_quarter_frame_degrees']=max(qa['max_quarter_frame_degrees'],math.degrees(previous[p.name].rotation_difference(q).angle))
        previous[p.name]=q
        if f in (0,end):qa['endpoint_error']=max(qa['endpoint_error'],max(abs(p.matrix_basis[j][k]-b['neutral'][p.name][j][k]) for j in range(4) for k in range(4)))
    for h,l,t in [('31.joint_RightWrist','24.joint_RightElbow','25.joint_RightHandTwist'),('49.joint_LeftWrist','42.joint_LeftElbow','43.joint_LeftHandTwist')]:
        hand=a.pose.bones[h];helper=a.pose.bones[t]
        carried=helper.matrix.to_quaternion()@b['rest'][t].to_quaternion().inverted()@b['rest'][h].to_quaternion()
        delta=carried.inverted()@hand.matrix.to_quaternion()
        axis=carried.inverted()@(hand.head-a.pose.bones[l].head).normalized()
        angle=2*math.atan2(Vector((delta.x,delta.y,delta.z)).dot(axis),delta.w)
        angle=(angle+math.pi)%(2*math.pi)-math.pi
        qa['distal_twist_measured']=max(qa['distal_twist_measured'],abs(math.degrees(angle)))
qa['bezier']=all(k.interpolation=='BEZIER' for la in a.animation_data.action.layers for st in la.strips for cb in st.channelbags for fc in cb.fcurves for k in fc.keyframe_points)
assert qa['feet_mm']<.1 and qa['endpoint_error']<1e-5,qa
assert qa['distal_twist_measured']<25,qa
assert qa['max_quarter_frame_degrees']<10 and qa['bezier'],qa
path=Path(bpy.data.filepath).parents[2]/'tools'/'animation_authoring'/(b['name']+'.twist-validation.json')
path.write_text(json.dumps(qa,indent=2),encoding='utf-8')
b['qa']=qa;s.frame_set(0);result=qa
