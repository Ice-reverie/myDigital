"""Author two additive review assets on the imported schoolBoy rig in Blender.

Run in Anxin_Action_Review after importing the unchanged source VRM.  Nothing
here changes the application's animation catalog or any existing Action.
"""
import bpy
import json
import math
from pathlib import Path
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'models/animations/review_health'
OUT.mkdir(parents=True, exist_ok=True)
scene = bpy.data.scenes['Anxin_Action_Review']
bpy.context.window.scene = scene
arm = next(o for o in scene.objects if o.type == 'ARMATURE')
mapping = {b.bone: b.node.bone_name for b in arm.data.vrm_addon_extension.vrm0.humanoid.human_bones if b.node.bone_name}
rest = {b.name: b.matrix_local.copy() for b in arm.data.bones}
parents = {b.name: b.parent.name if b.parent else None for b in arm.data.bones}
scene.render.fps = 30
scene.render.fps_base = 1
scene.unit_settings.system = 'METRIC'


def rotation(axis, degrees):
    return Quaternion(Vector(axis).normalized(), math.radians(degrees))


def ease(value):
    t = max(0.0, min(1.0, value))
    return t*t*t*(10+t*(-15+6*t))


def envelope(frame, start, peak, hold, end):
    return ease((frame-start)/(peak-start)) * (1-ease((frame-hold)/(end-hold)))


def basis(forward, normal):
    y = Vector(forward).normalized()
    x = y.cross(Vector(normal)).normalized()
    z = x.cross(y).normalized()
    return Matrix((x, y, z)).transposed()


def palm_rest(side):
    wrist = rest[mapping[side+'Hand']]
    forward = rest[mapping[side+'MiddleProximal']].translation-wrist.translation
    across = rest[mapping[side+'IndexProximal']].translation-rest[mapping[side+'LittleProximal']].translation
    normal = forward.cross(across) if side == 'left' else across.cross(forward)
    return basis(forward, normal)


palms = {side: palm_rest(side) for side in ('left', 'right')}
normals = {side: palms[side].col[2].copy() for side in palms}


def palm_quaternion(side, forward, normal):
    return (basis(forward, normal) @ palms[side].transposed() @ rest[mapping[side+'Hand']].to_3x3()).to_quaternion()


def sample(action_name, frame):
    duration = 240 if action_name == 'Idle_Doctor' else 300
    if frame == duration+1:
        frame = 1.0
    t = (frame-1)/30
    explain = action_name == 'Explain_Gentle'
    breath = .5-.5*math.cos(2*math.pi*(frame-1)/(150 if explain else 120))
    active = envelope(frame, 30, 80, 225, 273) if explain else 0
    lean = 1.35*active
    nod = envelope(frame, 86, 101, 104, 129)*3.0 if explain else 0
    slow = math.sin(2*math.pi*(frame-1)/duration)
    local = {name: Quaternion() for name in rest}
    poses = {}

    def local_world_axis(semantic, axis, degrees):
        name = mapping[semantic]
        r = rest[name].to_quaternion()
        local[name] = r.inverted() @ rotation(axis, degrees) @ r

    local_world_axis('spine', (1,0,0), .45*lean-.20*breath)
    local_world_axis('chest', (1,0,0), .35*lean-.40*breath)
    local_world_axis('upperChest', (1,0,0), .20*lean-.23*breath)
    local_world_axis('neck', (1,0,0), -.45*lean+.30*breath+.25*nod)
    head_rest = rest[mapping['head']].to_quaternion()
    local[mapping['head']] = head_rest.inverted() @ rotation((1,0,0), -.35*lean+.28*breath+.75*nod) @ rotation((0,0,1), .55*slow*(1-.6*active)) @ head_rest
    for side, sign in [('left',1), ('right',-1)]:
        local_world_axis(side+'Shoulder', (0,1,0), sign*(.6-.10*breath))

    hip_location=rest[mapping['hips']].to_quaternion().inverted() @ Vector((0,0,-.007))

    def update(name):
        parent = parents[name]
        delta=local[name].to_matrix().to_4x4()
        if name==mapping['hips']:delta.translation=hip_location
        poses[name] = (poses[parent] @ rest[parent].inverted() @ rest[name] if parent else rest[name]) @ delta

    for name in rest:
        update(name)

    chest_name = mapping['upperChest']
    chest_delta = poses[chest_name] @ rest[chest_name].inverted()
    left_wrist = Vector((.105,-.176,1.047))
    right_wrist = Vector((-.097,-.222,1.073))
    # The separation phase clears the supporting hand before the forearm lifts.
    waypoints = [
        (1, right_wrist), (30, right_wrist),
        (42, Vector((-.106,-.240,1.096))),
        (75, Vector((-.188,-.298,1.229))),
        (108, Vector((-.215,-.371,1.237))),
        (135, Vector((-.211,-.360,1.232))),
        (180, Vector((-.218,-.357,1.234))),
        (210, Vector((-.280,-.366,1.238))),
        (225, Vector((-.265,-.345,1.228))),
        (250, Vector((-.146,-.273,1.151))),
        (267, Vector((-.103,-.231,1.083))),
        (277, right_wrist), (301, right_wrist),
    ]

    def path(f):
        if f <= waypoints[0][0]: return waypoints[0][1].copy()
        if f >= waypoints[-1][0]: return waypoints[-1][1].copy()
        # Cubic Hermite with shared tangents gives continuous arcs through poses.
        for i, ((a, va),(b, vb)) in enumerate(zip(waypoints,waypoints[1:])):
            if f > b: continue
            def tangent(j):
                if j == 0 or j == len(waypoints)-1 or j in (1,10):
                    return Vector((0,0,0))
                prev, here, nxt = waypoints[j-1], waypoints[j], waypoints[j+1]
                return (nxt[1]-prev[1])/(nxt[0]-prev[0])*.75
            u=(f-a)/(b-a)
            return (2*u**3-3*u*u+1)*va+(u**3-2*u*u+u)*(b-a)*tangent(i)+(-2*u**3+3*u*u)*vb+(u**3-u*u)*(b-a)*tangent(i+1)

    hand_open = envelope(frame, 34, 94, 218, 277) if explain else 0
    right_wrist = path(frame) if explain else right_wrist
    left_wrist.y-=.04
    right_wrist.y-=.0415
    wrist_targets = {'left':chest_delta @ left_wrist,'right':chest_delta @ right_wrist}
    for side, sign in [('left',1),('right',-1)]:
        upper, lower, hand = [mapping[side+s] for s in ('UpperArm','LowerArm','Hand')]
        s = poses[upper].translation.copy()
        w = wrist_targets[side]
        l1=(rest[lower].translation-rest[upper].translation).length
        l2=(rest[hand].translation-rest[lower].translation).length
        axis=(w-s).normalized(); distance=(w-s).length
        a=(l1*l1-l2*l2+distance*distance)/(2*distance)
        h=math.sqrt(max(0,l1*l1-a*a))
        pole=Vector((sign*(.20+.14*hand_open*(side=='right')),.045,1.105))
        pole_dir=pole-s-axis*(pole-s).dot(axis)
        e=s+axis*a+pole_dir.normalized()*h
        d1=(e-s).normalized();d2=(w-e).normalized()
        r1=(rest[lower].translation-rest[upper].translation).normalized()
        r2=(rest[hand].translation-rest[lower].translation).normalized()
        hinge=r1.cross(r2).normalized()
        desired_hinge=d1.cross(d2).normalized()
        uq=(basis(d1,desired_hinge) @ basis(r1,hinge).transposed() @ rest[upper].to_3x3()).to_quaternion()
        base_hand=palm_quaternion(side,(-sign*.96,-.015,-.28),(0,1,.10))
        if side == 'right':
            offer=palm_quaternion(side,(.50,-.85,.14),(0,-.25,1))
            base_hand=base_hand.slerp(offer,hand_open)
        hq=chest_delta.to_quaternion() @ base_hand
        hinge_lq=(basis(d2,desired_hinge) @ basis(r2,hinge).transposed() @ rest[lower].to_3x3()).to_quaternion()
        # Animate pronation explicitly; projecting an interpolated palm normal
        # near the forearm axis creates a visually abrupt twist.
        roll=11.5 if side=='left' else -6.4+153.2*hand_open
        lq=rotation(d2,roll) @ hinge_lq
        for name,q in [(upper,uq),(lower,lq),(hand,hq)]:
            parent=parents[name]
            parent_rest_to_bone=rest[parent].inverted() @ rest[name]
            local[name]=parent_rest_to_bone.to_quaternion().inverted() @ poses[parent].to_quaternion().inverted() @ q
            local[name].normalize()
            update(name)
        for digit, amounts in [('Index',(12,23,14)),('Middle',(15,26,16)),('Ring',(18,29,18)),('Little',(22,32,21)),('Thumb',(9,13,9))]:
            for part,amount in zip(('Proximal','Intermediate','Distal'),amounts):
                name=mapping.get(side+digit+part)
                if not name: continue
                f=(rest[name].to_3x3() @ Vector((0,1,0))).normalized()
                axis=f.cross(normals[side]).normalized()
                curl=amount*(.35+.10*hand_open) if side=='right' else amount
                # Tiny changes only while the presenting hand is free.
                if side=='right': curl += .45*math.sin(t*2+len(digit)) * hand_open
                local[name]=rotation(rest[name].to_quaternion().inverted() @ axis,curl)
    # Fixed wider stance, relaxed knees, unchanged foot orientation and height.
    for side,sign in [('left',1),('right',-1)]:
        upper,lower,foot=[mapping[side+s] for s in ('UpperLeg','LowerLeg','Foot')]
        s=poses[upper].translation.copy()
        w=rest[foot].translation+Vector((sign*.045,0,0))
        r1=(rest[lower].translation-rest[upper].translation)
        r2=(rest[foot].translation-rest[lower].translation)
        d=(w-s).length;axis=(w-s).normalized()
        a=(r1.length_squared-r2.length_squared+d*d)/(2*d)
        h=math.sqrt(max(0,r1.length_squared-a*a))
        pole=Vector((sign*.10,-.22,.56))-s
        e=s+axis*a+(pole-axis*pole.dot(axis)).normalized()*h
        hinge=r1.cross(r2).normalized();desired=(e-s).cross(w-e).normalized()
        for name,q in [(upper,(basis(e-s,desired)@basis(r1,hinge).transposed()@rest[upper].to_3x3()).to_quaternion()),(lower,(basis(w-e,desired)@basis(r2,hinge).transposed()@rest[lower].to_3x3()).to_quaternion()),(foot,rest[foot].to_quaternion())]:
            parent=parents[name]
            local[name]=(rest[parent].inverted()@rest[name]).to_quaternion().inverted()@poses[parent].to_quaternion().inverted()@q
            local[name].normalize();update(name)
    blink=0.0
    blinks=[(48,50,54),(158,160,165)] if not explain else [(50,52,57),(157,159,164),(252,254,259)]
    for start,closed,end in blinks:
        if start<=frame<=closed: blink=max(blink,ease((frame-start)/(closed-start)))
        elif closed<frame<=end: blink=max(blink,1-ease((frame-closed)/(end-closed)))
    return local, blink, .12, hip_location


def fcurves(action):
    return [fc for layer in action.layers for strip in layer.strips for bag in strip.channelbags for fc in bag.fcurves]


def build_actions():
    arm.animation_data_create()
    for original in bpy.data.actions:
        original.use_fake_user=True
    arm['anxin_blink']=0.0
    arm['anxin_smile']=.12
    keys=bpy.data.objects['Face'].data.shape_keys
    for suffix,prop in [('Fcl_EYE_Close','anxin_blink'),('Fcl_MTH_Up','anxin_smile')]:
        key=next(k for k in keys.key_blocks if k.name.endswith(suffix))
        if keys.animation_data:
            existing=next((d for d in keys.animation_data.drivers if d.data_path==key.path_from_id('value')),None)
            if existing: keys.driver_remove(existing.data_path)
        fc=key.driver_add('value');driver=fc.driver;driver.type='AVERAGE'
        var=driver.variables.new();var.name='amount';var.type='SINGLE_PROP'
        var.targets[0].id=arm;var.targets[0].data_path='["'+prop+'"]'
    for action_name,end in [('Idle_Doctor',241),('Explain_Gentle',301)]:
        old=bpy.data.actions.get(action_name)
        if old and old.get('anxin_review_generated'):
            bpy.data.actions.remove(old,do_unlink=True)
        elif old:
            raise RuntimeError('Refusing to overwrite existing '+action_name)
        action=bpy.data.actions.new(action_name);action.use_fake_user=True
        action['anxin_review_generated']=True
        action['fps']=30;action['duration_seconds']=(end-1)/30
        action['playback_frames']=f'1-{end-1}'
        action['closing_keyframe']=end
        action['source_model']='schoolBoy.vrm'
        action.use_frame_range=True;action.frame_start=1;action.frame_end=end
        action.use_cyclic=True
        arm.animation_data.action=action
        frames=sorted(set(range(1,end+1,3))|{end,48,50,54,158,160,165} if end==241 else set(range(1,end+1,3))|{end,30,42,50,52,57,75,108,135,157,159,164,180,210,225,250,252,254,259,267,277})
        previous={}
        for frame in frames:
            poses,blink,smile,hip_location=sample(action_name,frame)
            for name,q in poses.items():
                if name in previous and q.dot(previous[name])<0:q.negate()
                previous[name]=q.copy()
                p=arm.pose.bones[name];p.rotation_mode='QUATERNION';p.rotation_quaternion=q
                p.location=(0,0,0);p.scale=(1,1,1)
                p.keyframe_insert('rotation_quaternion',frame=frame,group=name)
                if name==mapping['hips']:
                    p.location=hip_location
                    p.keyframe_insert('location',frame=frame,group=name)
            for prop,value in [('anxin_blink',blink),('anxin_smile',smile)]:
                arm[prop]=value;arm.keyframe_insert(data_path='["'+prop+'"]',frame=frame,group='Face: blink and slight smile')
        for fc in fcurves(action):
            points=fc.keyframe_points
            for i,k in enumerate(points):
                k.interpolation='BEZIER';k.handle_left_type=k.handle_right_type='FREE'
                if i in (0,len(points)-1):
                    slope=(points[1].co.y-points[-2].co.y)/((points[1].co.x-1)+(end-points[-2].co.x))
                else:
                    left=(k.co.y-points[i-1].co.y)/(k.co.x-points[i-1].co.x)
                    right=(points[i+1].co.y-k.co.y)/(points[i+1].co.x-k.co.x)
                    slope=2*left*right/(left+right) if left*right>0 else 0
                dl=(k.co.x-points[i-1].co.x)/3 if i else (points[1].co.x-k.co.x)/3
                dr=(points[i+1].co.x-k.co.x)/3 if i<len(points)-1 else (k.co.x-points[i-1].co.x)/3
                k.handle_left=(k.co.x-dl,k.co.y-slope*dl)
                k.handle_right=(k.co.x+dr,k.co.y+slope*dr)
            fc.modifiers.new('CYCLES')
            fc.update()
    arm.animation_data.action=bpy.data.actions['Idle_Doctor']
    scene.frame_start=1;scene.frame_end=240;scene.frame_set(1)
    bpy.context.view_layer.update()


def setup_review_stage():
    stage=bpy.data.collections.get('Review_Stage')
    if not stage:
        stage=bpy.data.collections.new('Review_Stage');scene.collection.children.link(stage)
    def camera(name,pos,target,scale):
        cam=bpy.data.objects.get(name)
        if not cam:
            cam=bpy.data.objects.new(name,bpy.data.cameras.new(name));stage.objects.link(cam)
        cam.location=pos;cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler()
        cam.data.type='ORTHO';cam.data.ortho_scale=scale;cam.data.lens=70
        return cam
    scene.camera=camera('Review_Front',(0,-5,1.0),(0,0,1.0),2.06)
    camera('Review_45',(-3.5,-3.5,1.35),(0,0,1.0),2.06)
    camera('Review_Hands',(-.52,-1.4,1.26),(0,-.13,1.12),.64)
    if not bpy.data.objects.get('Review_Ground'):
        mesh=bpy.data.meshes.new('Review_Ground')
        mesh.from_pydata([(-200,-200,.0004),(200,-200,.0004),(200,200,.0004),(-200,200,.0004)],[],[(0,1,2,3)])
        ground=bpy.data.objects.new('Review_Ground',mesh);stage.objects.link(ground)
        ground.color=(.79,.84,.86,1)
        mat=bpy.data.materials.new('Review_Ground_Material');mat.diffuse_color=(.79,.84,.86,1);ground.data.materials.append(mat)
    # The unchanged source shoe mesh is 7.495 mm above its bone-space origin.
    # Place the review floor at its measured sole surface, keeping root fixed.
    bpy.data.objects['Review_Ground'].location.z=.0070948
    for name,pos,power,size in [('Review_Key',(-3,-4,5),600,5),('Review_Fill',(3,-3,3),400,5),('Review_Rim',(1,2,4),500,4)]:
        if bpy.data.objects.get(name):continue
        light=bpy.data.lights.new(name,'AREA');light.energy=power;light.shape='DISK';light.size=size
        obj=bpy.data.objects.new(name,light);stage.objects.link(obj);obj.location=pos
        obj.rotation_euler=(Vector((0,0,1))-obj.location).to_track_quat('-Z','Y').to_euler()
    if not scene.world:scene.world=bpy.data.worlds.new('Review_World')
    scene.world.use_nodes=True
    bg=next(n for n in scene.world.node_tree.nodes if n.type=='BACKGROUND')
    bg.inputs['Color'].default_value=(.72,.80,.84,1)
    bg.inputs['Strength'].default_value=.7
    floor=bpy.data.materials['Review_Ground_Material'];floor.use_nodes=True
    bsdf=next(n for n in floor.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value=(.69,.77,.80,1)
    bsdf.inputs['Roughness'].default_value=.9
    scene.render.engine='BLENDER_EEVEE'
    scene.render.resolution_x=540;scene.render.resolution_y=720;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.view_settings.view_transform='Standard'
    scene.view_settings.look='None'
    scene.view_settings.exposure=0;scene.view_settings.gamma=1
    scene.render.film_transparent=False
    for area in (bpy.context.screen.areas if bpy.context.screen else []):
        if area.type=='VIEW_3D':
            area.spaces.active.region_3d.view_perspective='CAMERA'
            area.spaces.active.overlay.show_overlays=False
    for o in scene.objects:o.select_set(False)
    arm.select_set(True);bpy.context.view_layer.objects.active=arm


build_actions()
setup_review_stage()
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'Anxin_Health_Actions.blend'))
result={'actions':[(a.name,list(a.frame_range)) for a in bpy.data.actions],'fps':scene.render.fps,'output':str(OUT)}
