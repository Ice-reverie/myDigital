"""Export review-only VRMA clips using an isolated temporary VRM 1 rig."""
import bpy
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'models/animations/review_health'
scene=bpy.context.scene
source=bpy.data.objects['Armature']
original_action=source.animation_data.action
original_frame=scene.frame_current
original_range=(scene.frame_start,scene.frame_end)
mapping={b.bone:b.node.bone_name for b in source.data.vrm_addon_extension.vrm0.humanoid.human_bones if b.node.bone_name}


def make_export_rig():
    rig=source.copy();rig.data=source.data.copy();rig.name='__Health_Export_Rig'
    scene.collection.objects.link(rig)
    rig.animation_data_clear();rig.data.animation_data_clear()
    ext=rig.data.vrm_addon_extension
    ext.spec_version='1.0'
    bones={k.value:v for k,v in ext.vrm1.humanoid.human_bones.human_bone_name_to_human_bone().items()}
    for name,bone_name in mapping.items():
        if name.endswith('ThumbProximal'):name=name.replace('ThumbProximal','ThumbMetacarpal')
        elif name.endswith('ThumbIntermediate'):name=name.replace('ThumbIntermediate','ThumbProximal')
        bones[name].node.bone_name=bone_name
    return rig


rig=make_export_rig()
created_actions=[]
exports=[]
try:
    for obj in scene.objects:obj.select_set(False)
    rig.select_set(True);bpy.context.view_layer.objects.active=rig
    for name,end in [('Idle_Doctor',241),('Explain_Gentle',301)]:
        rig.animation_data_create();rig.animation_data.action=bpy.data.actions[name]
        rig.data.animation_data_create()
        facial=bpy.data.actions.new('__Export_'+name+'_Face');created_actions.append(facial)
        rig.data.animation_data.action=facial
        curves=[fc for la in bpy.data.actions[name].layers for st in la.strips for cb in st.channelbags for fc in cb.fcurves]
        for prop,preset in [('anxin_blink','blink'),('anxin_smile','happy')]:
            fc=next(f for f in curves if f.data_path=='["'+prop+'"]')
            expression=getattr(rig.data.vrm_addon_extension.vrm1.expressions.preset,preset)
            for frame in range(1,end+1):
                expression.preview=fc.evaluate(frame)
                expression.keyframe_insert('preview',frame=frame)
        scene.frame_start=1;scene.frame_end=end
        scene.frame_set(1);bpy.context.view_layer.update()
        path=OUT/(name+'.vrma')
        status=bpy.ops.export_scene.vrma(filepath=str(path),armature_object_name=rig.name)
        if status!={'FINISHED'}:raise RuntimeError(f'{name}: export returned {status}')
        exports.append({'name':name,'path':str(path),'bytes':path.stat().st_size,'duration':(end-1)/30})
finally:
    if bpy.context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    rig_data=rig.data
    bpy.data.objects.remove(rig,do_unlink=True)
    if not rig_data.users:bpy.data.armatures.remove(rig_data)
    for action in created_actions:
        if not action.users:bpy.data.actions.remove(action)
    source.animation_data.action=original_action
    source.select_set(True);bpy.context.view_layer.objects.active=source
    scene.frame_start,scene.frame_end=original_range
    scene.frame_set(original_frame)
(OUT/'exports.json').write_text(json.dumps(exports,indent=2),encoding='utf-8')
result={'exports':exports}
