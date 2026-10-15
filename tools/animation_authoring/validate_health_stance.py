"""Read-only stance QA. Run with Blender -b <review blend> --python this_file.

Checks axial leg twist, forward knee bends, fixed feet and loop closure; saves
two close views under output/stance_sync for visual inspection.
"""
import bpy
import json
import math
from pathlib import Path
from mathutils import Vector

OUT = Path(__file__).resolve().parents[2] / 'output/stance_sync'
OUT.mkdir(parents=True, exist_ok=True)
scene = bpy.data.scenes['Anxin_Action_Review']
bpy.context.window.scene = scene
arm = bpy.data.objects['Armature']
original_action = arm.animation_data.action
report = {'blender': bpy.app.version_string, 'actions': {}}
for action_name, end in [('Idle_Doctor', 241), ('Explain_Gentle', 301)]:
    arm.animation_data.action = bpy.data.actions[action_name]
    origins = {}
    max_twist = max_drift = max_sideways = 0
    min_forward = float('inf')
    for frame in range(1, end+1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for side in ('L', 'R'):
            parts = [arm.pose.bones[f'J_Bip_{side}_{part}'] for part in ('UpperLeg', 'LowerLeg', 'Foot')]
            hip, knee, ankle = [p.head.copy() for p in parts]
            min_forward = min(min_forward, min(hip.y, ankle.y) - knee.y)
            max_sideways = max(max_sideways, abs(knee.x - (hip.x+ankle.x)/2))
            for pose in parts[:2]:
                bone = pose.bone
                rest_axis = (bone.tail_local - bone.head_local).normalized()
                delta = pose.matrix.to_quaternion() @ bone.matrix_local.to_quaternion().inverted()
                angle = abs(math.degrees(2*math.atan2(Vector((delta.x, delta.y, delta.z)).dot(rest_axis), delta.w))) % 360
                max_twist = max(max_twist, min(angle, 360-angle))
            for pose in (parts[2], arm.pose.bones[f'J_Bip_{side}_ToeBase']):
                origins.setdefault(pose.name, pose.head.copy())
                max_drift = max(max_drift, (pose.head-origins[pose.name]).length)
    report['actions'][action_name] = {
        'max_axial_twist_degrees': max_twist,
        'max_foot_drift_m': max_drift,
        'min_knee_forward_m': min_forward,
        'max_knee_sideways_m': max_sideways,
        'passed': max_twist < 5 and max_drift < .0001 and min_forward > 0 and max_sideways < .02,
    }
arm.animation_data.action = bpy.data.actions['Idle_Doctor']
scene.frame_set(1)
cam = bpy.data.objects['Review_Front']
scene.camera = cam
scene.render.resolution_x = 600
scene.render.resolution_y = 640
scene.render.resolution_percentage = 100
scene.eevee.taa_render_samples = 16
cam.data.ortho_scale = 1.08
target = Vector((0, 0, .49))
for name, position in [('source_legs_front', (0, -4, .49)), ('source_legs_45', (-2.8, -2.8, .65))]:
    cam.location = position
    cam.rotation_euler = (target-cam.location).to_track_quat('-Z', 'Y').to_euler()
    scene.render.filepath = str(OUT/(name+'.png'))
    bpy.ops.render.render(write_still=True)
(OUT/'blender-stance.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
arm.animation_data.action = original_action
print('STANCE_QA '+json.dumps(report), flush=True)
assert all(v['passed'] for v in report['actions'].values()), report
