"""Validate the authored greet at quarter-frame intervals before VRMA export."""
import bpy
import json
import math

scene=bpy.context.scene
action_name=globals().get('ACTION_NAME','greet')
end_frame=168 if action_name=='explain_2' else 72
hold_start,hold_end=(60,108) if action_name=='explain_2' else (20,38)
build=bpy.app.driver_namespace[action_name+'_build']
arm=build['arm']
neutral=build['neutral']
world=build['world0']
qa=dict(fps=24,duration=end_frame/24,start_frame=0,end_frame=end_frame,authored_poses=len(build['frames']) if 'frames' in build else 145,
        feet_mm=0,head_hold_degrees=0,endpoint=0,min_elbow=180,min_wrist=180,
        max_quarter_frame_degrees=0)
scene.frame_set(hold_start)
head=arm.pose.bones['15.joint_Head'].matrix.to_quaternion()
previous={}
for i in range(end_frame*4+1):
    f=i/4
    scene.frame_set(int(f),subframe=f-int(f))
    bpy.context.view_layer.update()
    for name in ['70.joint_RightFootD','74.joint_LeftFootD']:
        p=arm.pose.bones[name]
        origin=world[name]
        tip=origin @ (p.bone.matrix_local.inverted() @ p.bone.tail_local)
        qa['feet_mm']=max(qa['feet_mm'],(p.head-origin.translation).length*1000,(p.tail-tip).length*1000)
    if hold_start<=f<=hold_end:
        qa['head_hold_degrees']=max(qa['head_hold_degrees'],math.degrees(head.rotation_difference(arm.pose.bones['15.joint_Head'].matrix.to_quaternion()).angle))
    for names in [('19.joint_RightArm','24.joint_RightElbow','31.joint_RightWrist'),('37.joint_LeftArm','42.joint_LeftElbow','49.joint_LeftWrist')]:
        upper,lower,hand=[arm.pose.bones[n] for n in names]
        qa['min_elbow']=min(qa['min_elbow'],math.degrees((lower.head-upper.head).angle(hand.head-lower.head)))
        qa['min_wrist']=min(qa['min_wrist'],math.degrees((hand.head-lower.head).angle(hand.tail-hand.head)))
    for p in arm.pose.bones:
        q=p.rotation_quaternion.copy()
        if p.name in previous:
            qa['max_quarter_frame_degrees']=max(qa['max_quarter_frame_degrees'],math.degrees(previous[p.name].rotation_difference(q).angle))
        previous[p.name]=q
        if f in (0,end_frame):
            qa['endpoint']=max(qa['endpoint'],max(abs(p.matrix_basis[j][k]-neutral[p.name][j][k]) for j in range(4) for k in range(4)))
qa['bezier']=all(k.interpolation=='BEZIER' for ac in [build['body'],build['expr']] for layer in ac.layers for strip in layer.strips for cb in strip.channelbags for fc in cb.fcurves for k in fc.keyframe_points)
assert qa['feet_mm']<.1,qa
assert qa['head_hold_degrees']<.5,qa
assert qa['endpoint']<1e-5,qa
assert qa['min_elbow']>5 and qa['min_wrist']>2,qa
assert qa['max_quarter_frame_degrees']<8,qa
assert qa['bezier'],qa
build['qa']=qa
(build['out'].parents[1]/'tools'/'animation_authoring'/(action_name+'.validation.json')).write_text(json.dumps(qa,indent=2),encoding='utf-8')
scene.frame_set(0)
result=qa
