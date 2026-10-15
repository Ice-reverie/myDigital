"""Render front/45-degree review videos without modifying the saved character.

Run: blender -b models/animations/review_health/Anxin_Health_Actions.blend
     --python tools/animation_authoring/render_health_review.py
PNG sequences are disposable files under output/health_animation_render_final.
"""
import bpy
import json
import math
from pathlib import Path
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'models/animations/review_health'
TEMP=ROOT/'output/health_animation_render_final'
scene=bpy.data.scenes['Anxin_Action_Review']
bpy.context.window.scene=scene
source=bpy.data.objects['Armature']
copy=source.copy();copy.data=source.data.copy();copy.name='Preview_45_Armature'
scene.collection.objects.link(copy)
for obj in list(scene.objects):
    if obj.type!='MESH' or obj.parent!=source:continue
    duplicate=obj.copy();duplicate.name='Preview_45_'+obj.name
    scene.collection.objects.link(duplicate);duplicate.parent=copy
    for modifier in duplicate.modifiers:
        if modifier.type=='ARMATURE' and modifier.object==source:modifier.object=copy
source.location.x=-.56
copy.location.x=.58;copy.rotation_mode='XYZ';copy.rotation_euler.z=math.radians(45)
camera=bpy.data.objects['Review_Front'];scene.camera=camera
camera.location=(0,-5,1.02)
camera.rotation_euler=(Vector((0,0,1.02))-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.ortho_scale=3.05
scene.render.resolution_x=960;scene.render.resolution_y=680
scene.render.resolution_percentage=100
scene.eevee.taa_render_samples=24
scene.render.image_settings.file_format='PNG'
scene.render.image_settings.color_mode='RGB'
scene.render.image_settings.compression=15
scene.render.fps=30;scene.render.fps_base=1
scene.render.use_file_extension=True

for name,x in [('FRONT',-.56),('45 DEG',.58)]:
    curve=bpy.data.curves.new('Review_'+name,'FONT');curve.body=name
    curve.align_x='CENTER';curve.size=.065
    label=bpy.data.objects.new('Review_'+name,curve);scene.collection.objects.link(label)
    label.location=(x,-.02,1.99);label.rotation_euler=(math.pi/2,0,0)
    material=bpy.data.materials.get('Review_Label')
    if not material:
        material=bpy.data.materials.new('Review_Label');material.diffuse_color=(.06,.10,.15,1)
    curve.materials.append(material)

def action_set(name):
    for rig in [source,copy]:
        rig.animation_data_create();rig.animation_data.action=bpy.data.actions[name]

for name,end in [('Idle_Doctor',240),('Explain_Gentle',300)]:
    action_set(name)
    folder=TEMP/name;folder.mkdir(parents=True,exist_ok=True)
    for frame in range(1,end+1):
        path=folder/f'{frame:04d}.png'
        scene.frame_set(frame);bpy.context.view_layer.update()
        scene.render.filepath=str(path)
        bpy.ops.render.render(write_still=True)
        if frame in [1,108]:
            image=bpy.data.images.get('Render Result')
            image.save_render(str(OUT/(name+('_overview.png' if frame==1 else '_gesture.png'))),scene=scene)
        if frame%30==0:print(f'HEALTH_PROGRESS {name} {frame}/{end}',flush=True)

# A real NLA 10-frame crossfade, at the shared boundary pose.  The saved
# Actions remain separate; this temporary preview scene is never saved.
for rig in [source,copy]:
    rig.animation_data.action=None
    for track in list(rig.animation_data.nla_tracks):rig.animation_data.nla_tracks.remove(track)
    track=rig.animation_data.nla_tracks.new();track.name='Preview_Idle'
    strip=track.strips.new('Idle end',1,bpy.data.actions['Idle_Doctor'])
    strip.action_frame_start=181;strip.action_frame_end=241;strip.frame_start=1;strip.frame_end=61
    strip.extrapolation='HOLD_FORWARD'
    track=rig.animation_data.nla_tracks.new();track.name='Preview_Explain'
    strip=track.strips.new('Explain in/out',51,bpy.data.actions['Explain_Gentle'])
    strip.action_frame_start=1;strip.action_frame_end=301;strip.frame_start=51;strip.frame_end=351
    strip.extrapolation='NOTHING';strip.blend_in=10;strip.blend_out=10
    track=rig.animation_data.nla_tracks.new();track.name='Preview_Idle_Return'
    strip=track.strips.new('Idle return',341,bpy.data.actions['Idle_Doctor'])
    strip.action_frame_start=1;strip.action_frame_end=61;strip.frame_start=341;strip.frame_end=401
    strip.extrapolation='NOTHING';strip.blend_in=10

# Reuse the interior frames of the independently rendered clip. Render only
# the two boundaries and the short idle lead-in/out using actual NLA blending.
import shutil
folder=TEMP/'Transition_10f';folder.mkdir(parents=True,exist_ok=True)
for frame in range(1,401):
    path=folder/f'{frame:04d}.png'
    if 62<=frame<=340:
        shutil.copyfile(TEMP/'Explain_Gentle'/f'{frame-50:04d}.png',path)
    else:
        scene.frame_set(frame);bpy.context.view_layer.update();scene.render.filepath=str(path)
        bpy.ops.render.render(write_still=True)
    if frame%30==0:print(f'HEALTH_PROGRESS Transition_10f {frame}/400',flush=True)
(TEMP/'render_complete.json').write_text(json.dumps({'fps':30,'views':['front','45 degrees'],'frames':{'Idle_Doctor':240,'Explain_Gentle':300,'Transition_10f':400}},indent=2),encoding='utf-8')
print('HEALTH_RENDER_COMPLETE',flush=True)
