"""Independent-process VRMA reimport and timestamp/pose/face verification."""
import bpy
import json
import math
import struct
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'models/animations/review_health'
scene=bpy.data.scenes['Anxin_Action_Review'];bpy.context.window.scene=scene
source=bpy.data.objects['Armature']
mapping={b.bone:b.node.bone_name for b in source.data.vrm_addon_extension.vrm0.humanoid.human_bones if b.node.bone_name}

def curves(action):
    return [fc for la in action.layers for st in la.strips for cb in st.channelbags for fc in cb.fcurves]

def read_glb(path):
    data=path.read_bytes();size,kind=struct.unpack_from('<II',data,12)
    assert kind==0x4E4F534A
    doc=json.loads(data[20:20+size]);offset=20+size
    length,kind=struct.unpack_from('<II',data,offset);assert kind==0x004E4942
    return doc,data[offset+8:offset+8+length]

report={}
for name,duration in [('Idle_Doctor',8),('Explain_Gentle',10)]:
    rig=source.copy();rig.data=source.data.copy();rig.name='Reimport_'+name
    scene.collection.objects.link(rig);rig.animation_data_clear();rig.data.animation_data_clear()
    extension=rig.data.vrm_addon_extension;extension.spec_version='1.0'
    bones={k.value:v for k,v in extension.vrm1.humanoid.human_bones.human_bone_name_to_human_bone().items()}
    for semantic,bone_name in mapping.items():
        if semantic.endswith('ThumbProximal'):semantic=semantic.replace('ThumbProximal','ThumbMetacarpal')
        elif semantic.endswith('ThumbIntermediate'):semantic=semantic.replace('ThumbIntermediate','ThumbProximal')
        bones[semantic].node.bone_name=bone_name
    for obj in scene.objects:obj.select_set(False)
    rig.select_set(True);bpy.context.view_layer.objects.active=rig
    status=bpy.ops.import_scene.vrma(filepath=str(OUT/(name+'.vrma')),armature_object_name=rig.name)
    assert status=={'FINISHED'},status
    imported=rig.animation_data.action
    doc,blob=read_glb(OUT/(name+'.vrma'))
    spans=[]
    for sampler in doc['animations'][0]['samplers']:
        accessor=doc['accessors'][sampler['input']];view=doc['bufferViews'][accessor['bufferView']]
        offset=view.get('byteOffset',0)+accessor.get('byteOffset',0)
        times=struct.unpack_from('<'+'f'*accessor['count'],blob,offset)
        spans.append([min(times),max(times)])
    source.animation_data.action=bpy.data.actions[name]
    max_rotation=0;max_position=0;by_frame={}
    for frame in [1,30,50,61,75,108,135,180,210,240,duration*30+1]:
        if frame>duration*30+1:continue
        scene.frame_set(frame);bpy.context.view_layer.update()
        expected={bone:source.pose.bones[bone].matrix.copy() for bone in mapping.values()}
        # This installed importer places timestamp zero at Blender F1.
        scene.frame_set(frame);bpy.context.view_layer.update()
        errors=[]
        for bone,matrix in expected.items():
            actual=rig.pose.bones[bone].matrix
            max_position=max(max_position,(actual.translation-matrix.translation).length*1000)
            a=actual.to_quaternion().normalized();b=matrix.to_quaternion().normalized()
            max_rotation=max(max_rotation,math.degrees(2*math.acos(min(1,abs(a.dot(b))))))
            errors.append(((actual.translation-matrix.translation).length*1000,bone))
        by_frame[str(frame)]=sorted(errors,reverse=True)[:3]
    expressions=doc['extensions']['VRMC_vrm_animation'].get('expressions',{})
    report[name]={'import_status':list(status),'import_frame_range':list(imported.frame_range),'timestamp_spans':sorted(set(tuple(s) for s in spans)), 'humanoid_bones':len(mapping),'max_sampled_joint_position_error_mm':max_position,'max_sampled_joint_angle_error_deg':max_rotation,'expression_mapping':expressions,'source_vrm_version':source.data.vrm_addon_extension.spec_version}
    assert all(abs(a)<1e-6 and abs(b-duration)<1e-5 for a,b in spans),spans
    report[name]['by_frame']=by_frame
    assert max_position<1.0,report[name]
    assert max_rotation<.25,report[name]
    assert 'blink' in expressions.get('preset',{}) and 'happy' in expressions.get('preset',{})
(OUT/'vrma_roundtrip.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2),flush=True)
