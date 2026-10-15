"""Numerical loop, planted-foot and evaluated surface checks in Blender."""
import bpy
import json
import math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_ray_tri

OUT=Path(__file__).resolve().parents[2]/'models/animations/review_health'
scene=bpy.context.scene
arm=bpy.data.objects['Armature']
body=bpy.data.objects['Body']
previous_action=arm.animation_data.action
previous_frame=scene.frame_current


def curves(action):
    return [fc for la in action.layers for st in la.strips for cb in st.channelbags for fc in cb.fcurves]


def pose():
    return {p.name:p.matrix_basis.copy() for p in arm.pose.bones}


def difference(a,b):
    return max(abs(a[n][i][j]-b[n][i][j]) for n in a for i in range(4) for j in range(4))


hand_groups={side:{g.index for g in body.vertex_groups if g.name.startswith('J_Bip_'+letter+'_') and any(p in g.name for p in ['Hand','Index','Middle','Ring','Little','Thumb'])} for side,letter in [('left','L'),('right','R')]}
trunk_groups={g.index for g in body.vertex_groups if any(n in g.name for n in ['Hips','Spine','Chest'])}
sets={**hand_groups,'trunk':trunk_groups}
members={name:{v.index for v in body.data.vertices if sum(g.weight for g in v.groups if g.group in indices)>.7} for name,indices in sets.items()}
body.data.calc_loop_triangles()
tris={name:[tuple(t.vertices) for t in body.data.loop_triangles if all(v in ids for v in t.vertices)] for name,ids in members.items()}


def surface_report():
    evaluated=body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh=evaluated.to_mesh()
    verts=[body.matrix_world@v.co for v in mesh.vertices]
    trees={name:BVHTree.FromPolygons(verts,faces,all_triangles=True) for name,faces in tris.items()}

    def intersects(ta,tb):
        for a,b in [(ta,tb),(tb,ta)]:
            for j in range(3):
                p,q=verts[a[j]],verts[a[(j+1)%3]]
                ray=q-p
                hit=intersect_ray_tri(*(verts[k] for k in b),ray,p,True)
                if hit is None:continue
                fraction=(hit-p).dot(ray)/max(ray.length_squared,1e-16)
                if 1e-4<fraction<1-1e-4:return True
        return False

    counts={}
    for a,b in [('left','right'),('left','trunk'),('right','trunk')]:
        candidates=trees[a].overlap(trees[b])
        counts[a+'_'+b]=sum(intersects(tris[a][i],tris[b][j]) for i,j in candidates)
    distances=[]
    for i in members['right']:
        near=trees['left'].find_nearest(verts[i])
        if near[0] is not None:distances.append(near[3])
    counts['minimum_hand_surface_distance_mm']=min(distances)*1000 if distances else None
    evaluated.to_mesh_clear()
    return counts


report={'blender':bpy.app.version_string,'fps':scene.render.fps,'fps_base':scene.render.fps_base,'actions':{},'common_start_pose_max_error':0,'surface_check':'Triangle-edge intersection on evaluated hand and trunk surfaces; garment seams excluded by vertex weights.'}
first_start=None
try:
    for name,end in [('Idle_Doctor',241),('Explain_Gentle',301)]:
        action=bpy.data.actions[name];arm.animation_data.action=action
        scene.frame_set(1);bpy.context.view_layer.update()
        start=pose()
        feet={n:arm.pose.bones[n].matrix.copy() for n in ['Root','J_Bip_C_Hips','J_Bip_L_Foot','J_Bip_R_Foot','J_Bip_L_ToeBase','J_Bip_R_ToeBase']}
        if first_start is None:first_start=start
        else:report['common_start_pose_max_error']=difference(start,first_start)
        qa={'duration_seconds':(end-1)/30,'playback_frames':[1,end-1],'closure_frame':end,'fixed_bones_max_translation_mm':0,'fixed_bones_max_matrix_error':0,'max_half_frame_rotation_degrees':0,'endpoint_pose_error':0,'curve_endpoint_error':0,'curve_seam_derivative_error':0,'surfaces':{}}
        previous={}
        for i in range((end-1)*2+1):
            f=1+i/2
            scene.frame_set(int(f),subframe=f-int(f));bpy.context.view_layer.update()
            for n,m in feet.items():
                actual=arm.pose.bones[n].matrix
                qa['fixed_bones_max_translation_mm']=max(qa['fixed_bones_max_translation_mm'],(actual.translation-m.translation).length*1000)
                qa['fixed_bones_max_matrix_error']=max(qa['fixed_bones_max_matrix_error'],max(abs(actual[r][c]-m[r][c]) for r in range(4) for c in range(4)))
            for p in arm.pose.bones:
                q=p.matrix.to_quaternion()
                if p.name in previous:
                    dot=min(1,abs(q.dot(previous[p.name])))
                    qa['max_half_frame_rotation_degrees']=max(qa['max_half_frame_rotation_degrees'],math.degrees(2*math.acos(dot)))
                previous[p.name]=q
        qa['endpoint_pose_error']=difference(start,pose())
        for fc in curves(action):
            qa['curve_endpoint_error']=max(qa['curve_endpoint_error'],abs(fc.evaluate(1)-fc.evaluate(end)))
            a,b=fc.keyframe_points[0],fc.keyframe_points[-1]
            slope_a=(a.handle_right.y-a.co.y)/(a.handle_right.x-a.co.x)
            slope_b=(b.co.y-b.handle_left.y)/(b.co.x-b.handle_left.x)
            qa['curve_seam_derivative_error']=max(qa['curve_seam_derivative_error'],abs(slope_a-slope_b))
        frames=[1,50,61,121,160,181,241] if end==241 else [1,30,42,50,61,75,108,135,180,210,225,250,267,277,301]
        frames=sorted(set(frames)|set(range(1,end+1,6))|(set(range(30,56))|set(range(250,279)) if end==301 else set()))
        for f in frames:
            scene.frame_set(f);bpy.context.view_layer.update();qa['surfaces'][str(f)]=surface_report()
        qa['sampled_surface_intersections']=sum(s[k] for s in qa['surfaces'].values() for k in ['left_right','left_trunk','right_trunk'])
        qa['bezier_curves']=all(k.interpolation=='BEZIER' for fc in curves(action) for k in fc.keyframe_points)
        qa['cycles_modifiers']=all(any(m.type=='CYCLES' for m in fc.modifiers) for fc in curves(action))
        report['actions'][name]=qa
        assert qa['fixed_bones_max_translation_mm']<.01,qa
        assert qa['endpoint_pose_error']<1e-5,qa
        assert qa['curve_endpoint_error']<1e-6,qa
        assert qa['curve_seam_derivative_error']<1e-5,qa
        assert qa['max_half_frame_rotation_degrees']<5,qa
        assert qa['sampled_surface_intersections']==0,qa
    assert report['common_start_pose_max_error']<1e-5,report
    arm.animation_data.action=bpy.data.actions['Idle_Doctor'];scene.frame_set(1)
    bpy.context.view_layer.update()
    evaluated=body.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=evaluated.to_mesh()
    ground=bpy.data.objects['Review_Ground']
    report['review_floor_height_m']=(ground.matrix_world@ground.data.vertices[0].co).z
    report['shoe_surface_min_z_m']={}
    for side,letter in [('left','L'),('right','R')]:
        groups={g.index for g in body.vertex_groups if g.name in ['J_Bip_'+letter+'_Foot','J_Bip_'+letter+'_ToeBase']}
        ids=[v.index for v in body.data.vertices if sum(g.weight for g in v.groups if g.group in groups)>.9]
        report['shoe_surface_min_z_m'][side]=min((body.matrix_world@mesh.vertices[i].co).z for i in ids)
    evaluated.to_mesh_clear()
    report['shoe_floor_gap_mm']={k:(v-report['review_floor_height_m'])*1000 for k,v in report['shoe_surface_min_z_m'].items()}
    report['packed_texture_count']=sum(1 for i in bpy.data.images if i.packed_file)
    report['preserved_original_actions']=[a.name for a in bpy.data.actions if not a.get('anxin_review_generated')]
    report['runtime_integration']='Not changed; pending user review'
    assert all(abs(v)<.01 for v in report['shoe_floor_gap_mm'].values()),report['shoe_floor_gap_mm']
finally:
    arm.animation_data.action=previous_action
    scene.frame_set(previous_frame)
(OUT/'validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
result=report
