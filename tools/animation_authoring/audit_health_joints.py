"""Read-only joint audit of the two review Actions; never save the blend."""
import bpy
import json
import math
from pathlib import Path
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

OUT=Path(__file__).resolve().parents[2]/'models/animations/review_health/joint_audit_v2'
OUT.mkdir(parents=True,exist_ok=True)
scene=bpy.data.scenes['Anxin_Action_Review']
bpy.context.window.scene=scene
arm=bpy.data.objects['Armature'];body=bpy.data.objects['Body']
previous={'action':arm.animation_data.action,'frame':scene.frame_current,'camera':scene.camera,'x':scene.render.resolution_x,'y':scene.render.resolution_y,'percent':scene.render.resolution_percentage,'path':scene.render.filepath,'override':bpy.context.view_layer.material_override,'exposure':scene.view_settings.exposure}
report={'blender':bpy.app.version_string,'method':'All integer frames. Wrist bend is the angle between elbow-to-wrist and wrist-to-middle-knuckle; forearm roll uses local-Y swing/twist decomposition. Angles are rig measurements, not anatomical diagnoses.','actions':{},'rendered_frames':[]}

def degrees(q):
    q.normalize()
    return math.degrees(2*math.atan2(Vector((q.x,q.y,q.z)).length,abs(q.w)))

def metrics():
    result={}
    for side in ['L','R']:
        u,l,h,m=[arm.pose.bones['J_Bip_'+side+'_'+suffix] for suffix in ['UpperArm','LowerArm','Hand','Middle1']]
        d=(h.head-l.head).normalized();finger=(m.head-h.head).normalized()
        carried=l.matrix.to_quaternion()@l.bone.matrix_local.to_quaternion().inverted()@h.bone.matrix_local.to_quaternion()
        delta=carried.inverted()@h.matrix.to_quaternion();axis=carried.inverted()@d
        angle=2*math.atan2(Vector((delta.x,delta.y,delta.z)).dot(axis),delta.w)
        angle=(angle+math.pi)%(2*math.pi)-math.pi
        result[side]={
            'wrist_axis_bend_deg':math.degrees(d.angle(finger)),
            'wrist_residual_twist_deg':math.degrees(angle),
            'forearm_local_roll_deg':math.degrees(l.rotation_quaternion.to_swing_twist('Y')[1]),
            'elbow_flex_deg':math.degrees((l.head-u.head).angle(h.head-l.head)),
        }
    return result

cam_data=bpy.data.cameras.new('__JointAuditCamera')
cam=bpy.data.objects.new('__JointAuditCamera',cam_data);scene.collection.objects.link(cam)
mat=bpy.data.materials.new('__JointAuditClay');mat.use_nodes=True
shader=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
shader.inputs['Base Color'].default_value=(.39,.48,.51,1)
shader.inputs['Roughness'].default_value=.85
cam_data.type='ORTHO';scene.camera=cam

try:
    for name,end in [('Idle_Doctor',241),('Explain_Gentle',301)]:
        arm.animation_data.action=bpy.data.actions[name];rows=[];last={};max_step={}
        for frame in range(1,end+1):
            scene.frame_set(frame);bpy.context.view_layer.update()
            rows.append({'frame':frame,**metrics()})
            for bone in ['J_Bip_'+side+'_'+part for side in ['L','R'] for part in ['UpperArm','LowerArm','Hand','UpperLeg','LowerLeg','Foot']]+['J_Bip_C_Head','J_Bip_C_Neck']:
                q=arm.pose.bones[bone].matrix.to_quaternion().normalized()
                if bone in last:
                    step=degrees(last[bone].rotation_difference(q))
                    if step>max_step.get(bone,{}).get('degrees',-1):max_step[bone]={'frame':frame,'degrees':step}
                last[bone]=q
        summary={side:{metric:{'min':min((row[side][metric],row['frame']) for row in rows),'max':max((row[side][metric],row['frame']) for row in rows)} for metric in rows[0][side]} for side in ['L','R']}
        report['actions'][name]={'ranges':summary,'largest_frame_steps':max_step,'samples':rows}
    scene.render.resolution_x=640;scene.render.resolution_y=640;scene.render.resolution_percentage=100
    shots=[('Idle_Doctor',1,'wrist_front'),('Idle_Doctor',1,'wrist_side'),('Idle_Doctor',1,'wrist_top'),('Idle_Doctor',1,'legs_front'),('Idle_Doctor',1,'legs_back'),('Explain_Gentle',50,'wrist_side'),('Explain_Gentle',62,'wrist_side'),('Explain_Gentle',108,'arm_oblique'),('Explain_Gentle',210,'arm_oblique'),('Explain_Gentle',255,'wrist_side'),('Explain_Gentle',108,'arm_back'),('Explain_Gentle',210,'arm_back')]
    shots += [('Idle_Doctor',1,'arm_back'),('Explain_Gentle',62,'arm_back'),('Explain_Gentle',243,'arm_back')]
    for name,frame,view in shots:
        arm.animation_data.action=bpy.data.actions[name];scene.frame_set(frame);bpy.context.view_layer.update()
        wrist=arm.pose.bones['J_Bip_R_Hand'].head.copy()
        if view=='wrist_front':
            target=Vector((0,-.2,1.075));pos=target+Vector((0,-2,.16));scale=.56
        elif view=='wrist_top':
            target=Vector((0,-.22,1.06));pos=target+Vector((0,-.15,1.8));scale=.58
        elif view.startswith('legs_'):
            target=Vector((0,0,.53));pos=target+Vector((0,-2 if view=='legs_front' else 2,.05));scale=1.14
        elif view=='wrist_side':
            target=wrist+Vector((-.04,.015,.035));pos=target+Vector((-1.1,-1,.35));scale=.48
        elif view=='arm_back':
            target=Vector((-.17,-.15,1.32));pos=target+Vector((-1.2,1.2,.25));scale=.85
        else:
            target=Vector((-.17,-.15,1.32));pos=target+Vector((-1.2,-1.4,.25));scale=.85
        cam.location=pos;cam.rotation_euler=(target-pos).to_track_quat('-Z','Y').to_euler();cam_data.ortho_scale=scale
        for mode in (['original','clay'] if view in ['wrist_side','arm_oblique','arm_back'] else ['original']):
            bpy.context.view_layer.material_override=mat if mode=='clay' else None
            scene.view_settings.exposure=-2 if mode=='clay' else previous['exposure']
            filename=f'{name}_F{frame:03d}_{view}_{mode}.png'
            scene.render.filepath=str(OUT/filename);bpy.ops.render.render(write_still=True)
            projected={}
            for side in ['L','R']:
                for suffix in ['UpperArm','LowerArm','Hand','Middle1']:
                    bone='J_Bip_'+side+'_'+suffix
                    p=world_to_camera_view(scene,cam,arm.matrix_world@arm.pose.bones[bone].head)
                    projected[bone]=[p.x*640,(1-p.y)*640]
            report['rendered_frames'].append({'file':filename,'action':name,'frame':frame,'view':view,'mode':mode,'joint_pixels':projected})
finally:
    arm.animation_data.action=previous['action'];scene.frame_set(previous['frame']);scene.camera=previous['camera']
    scene.render.resolution_x=previous['x'];scene.render.resolution_y=previous['y'];scene.render.resolution_percentage=previous['percent'];scene.render.filepath=previous['path']
    bpy.context.view_layer.material_override=previous['override']
    scene.view_settings.exposure=previous['exposure']
    bpy.data.objects.remove(cam,do_unlink=True);bpy.data.cameras.remove(cam_data);bpy.data.materials.remove(mat)
(OUT/'measurements.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
# Bounds for this gentle gesture and this rig, not medical range-of-motion limits.
for action_name,data in report['actions'].items():
    for side,ranges in data['ranges'].items():
        assert ranges['wrist_axis_bend_deg']['max'][0]<32,(action_name,side,ranges)
        assert max(abs(ranges['wrist_residual_twist_deg'][k][0]) for k in ['min','max'])<20,(action_name,side,ranges)
        assert max(abs(ranges['forearm_local_roll_deg'][k][0]) for k in ['min','max'])<80,(action_name,side,ranges)
    assert max(v['degrees'] for v in data['largest_frame_steps'].values())<3,data['largest_frame_steps']
result={'ranges':{name:data['ranges'] for name,data in report['actions'].items()},'largest_frame_steps':{name:sorted(data['largest_frame_steps'].items(),key=lambda x:x[1]['degrees'],reverse=True)[:4] for name,data in report['actions'].items()},'rendered_images':len(report['rendered_frames'])}
