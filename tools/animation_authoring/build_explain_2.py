"""Standalone left-hand presentation, authored from the supplied 30fps video.

Run inside the Lumine source in Blender 5.2. This never changes web integration.
"""
import bpy
import json
import math
import struct
from pathlib import Path
from mathutils import Matrix, Quaternion, Vector

NAME='explain_2'
OUT=Path(bpy.data.filepath).parent
REFERENCE_PATH=OUT.parents[1]/'tools'/'animation_authoring'/'present_left.reference.json'
REF=json.loads(REFERENCE_PATH.read_text(encoding='utf-8'))
arm=bpy.data.objects['Armature']
scene=bpy.context.scene
scene.name='Explain_2_Authoring'
arm.animation_data.action=bpy.data.actions['Humanoid']
for p in arm.pose.bones:
    p.rotation_mode='QUATERNION'
    p.matrix_basis=Matrix.Identity(4)
scene.frame_set(1)
bpy.context.view_layer.update()
neutral={p.name:p.matrix_basis.copy() for p in arm.pose.bones}
world={p.name:p.matrix.copy() for p in arm.pose.bones}
humans={b.node.bone_name for b in arm.data.vrm_addon_extension.vrm1.humanoid.human_bones.human_bone_name_to_human_bone().values() if b.node.bone_name}
names=sorted(humans|{'283.!Root'})
secondary=[p.name for p in arm.pose.bones if any(s in p.name for s in ['AmiceB','joint____0_','HairS'])]
frames=sorted(set(range(169))|{round(sf*24/30,6) for sf in range(211)})

def smooth(a,b,t):
    x=max(0,min(1,(t-a)/(b-a)))
    return x*x*(3-2*x)

def observed(name,t):
    points=REF[name]
    def slope(i):
        if i in (0,len(points)-1): return 0
        l=(points[i][1]-points[i-1][1])/(points[i][0]-points[i-1][0])
        r=(points[i+1][1]-points[i][1])/(points[i+1][0]-points[i][0])
        return 2*l*r/(l+r) if l*r>0 else 0
    if t<=points[0][0]: return points[0][1]
    for i,((a,va),(b,vb)) in enumerate(zip(points,points[1:])):
        if t<=b:
            u=(t-a)/(b-a)
            return (2*u**3-3*u*u+1)*va+(u**3-2*u*u+u)*(b-a)*slope(i)+(-2*u**3+3*u*u)*vb+(u**3-u*u)*(b-a)*slope(i+1)
    return points[-1][1]

def rot(axis,degree):
    return Quaternion(axis,math.radians(degree))

def local_pose(p):
    parent=dict(parent_matrix=p.parent.matrix,parent_matrix_local=p.bone.parent.matrix_local) if p.parent else {}
    return p.bone.convert_local_to_pose(p.matrix,p.bone.matrix_local,invert=True,**parent)

rig=arm.copy();rig.data=arm.data.copy();rig.name='__EXPLAIN2_SOLVER'
scene.collection.objects.link(rig)
rig.animation_data_clear();rig.data.animation_data_clear()
created=[rig];rig_data=rig.data

def target(name,matrix):
    obj=bpy.data.objects.new('__EXPLAIN2_'+name,None)
    scene.collection.objects.link(obj);obj.matrix_world=arm.matrix_world@matrix
    created.append(obj)
    return obj

def orient(bone,obj):
    c=rig.pose.bones[bone].constraints.new('COPY_ROTATION')
    c.target=obj;c.owner_space=c.target_space='WORLD'

def ik(bone,obj):
    c=rig.pose.bones[bone].constraints.new('IK')
    c.target=obj;c.chain_count=2;c.iterations=256;c.use_stretch=False

for knee,foot in [('69.joint_RightKneeD','70.joint_RightFootD'),('73.joint_LeftKneeD','74.joint_LeftFootD')]:
    obj=target(foot,world[foot]);ik(knee,obj);orient(foot,obj)
left='49.joint_LeftWrist';right='31.joint_RightWrist'
left_target=target('LeftPalm',world[left]);orient(left,left_target)
right_target=target('QuietRightHand',world[right]);ik('24.joint_RightElbow',right_target)
head_target=target('Head',world['15.joint_Head']);orient('15.joint_Head',head_target)

# Build an actual palm basis from this rig's finger bases.
finger=(arm.pose.bones['93.joint_LeftMiddle1'].head-world[left].translation).normalized()
width=(arm.pose.bones['95.joint_LeftPinky1'].head-arm.pose.bones['92.joint_LeftIndex1'].head).normalized()
normal=width.cross(finger).normalized();width=finger.cross(normal).normalized()
old_palm=Matrix((width,finger,normal)).transposed()

def palm_rotation(forward,up):
    forward=Vector(forward).normalized()
    width=forward.cross(Vector(up)).normalized()
    normal=width.cross(forward).normalized()
    basis=Matrix((width,forward,normal)).transposed()
    return (basis@old_palm.transposed()@world[left].to_3x3()).to_quaternion()

gather_q=palm_rotation((-.45,-.18,.87),(0,1,0))
offer_q=palm_rotation((.94,-.28,.18),(0,0,1))
samples=[];secondary_values={n:[] for n in secondary};previous_palm_delta=None
try:
    for frame in frames:
        sf=frame*30/24
        weight=observed('weight',sf)
        presence=smooth(0,20,sf)*(1-smooth(183,210,sf))
        breath=.65*math.sin(2*math.pi*frame/60)*presence
        for p in rig.pose.bones:p.matrix_basis=neutral[p.name]
        root=rig.pose.bones['283.!Root']
        shift=Vector((-.011*weight,0,-.004*weight))
        root.location=neutral[root.name].translation+root.bone.matrix_local.to_3x3().inverted()@shift
        rig.pose.bones['13.joint_HipMaster'].rotation_quaternion=neutral['13.joint_HipMaster'].to_quaternion()@rot((0,0,1),.65*weight)
        for name,lean,b in [('11.joint_Torso',-.8,.3),('12.joint_Torso2',-.7,1)]:
            rig.pose.bones[name].rotation_quaternion=neutral[name].to_quaternion()@rot((0,0,1),lean*weight)@rot((1,0,0),b*breath)
        glance=smooth(35,44,sf)*(1-smooth(49,61,sf))
        head_q=rot((0,0,1),2*glance)@rot((0,1,0),1.2*weight)@world['15.joint_Head'].to_quaternion()
        mat=head_q.to_matrix().to_4x4();mat.translation=world['15.joint_Head'].translation
        head_target.matrix_world=arm.matrix_world@mat

        # The forearm lifts before opening outward. No straight hand-position lerp.
        bpy.context.view_layer.update()
        for name,end,curve,baseline,depth_amount in [
            ('37.joint_LeftArm','42.joint_LeftElbow','upper',19,.05),
            ('42.joint_LeftElbow',left,'forearm',25,.30)]:
            p=rig.pose.bones[name]
            original=world[end].translation-world[name].translation
            angle_delta=observed(curve,sf)-baseline
            angle=math.atan2(original.x,-original.z)+math.radians(angle_delta)
            depth=original.normalized().y-depth_amount*observed('palmLift',sf)
            projection=math.sqrt(1-depth*depth)
            direction=Vector((math.sin(angle)*projection,depth,-math.cos(angle)*projection))
            turn=rot((0,1,0),-angle_delta)
            q=(turn@original).rotation_difference(direction)@turn@world[name].to_quaternion()
            mat=q.to_matrix().to_4x4();mat.translation=p.head;p.matrix=mat
            bpy.context.view_layer.update()
        # Carry the palm with the bending forearm before supinating it.
        # A world-space rest-to-gather slerp counter-rotates the wrist during lift.
        carried=rig.pose.bones['42.joint_LeftElbow'].matrix.to_quaternion()@world['42.joint_LeftElbow'].to_quaternion().inverted()@world[left].to_quaternion()
        # Spread the depth-ambiguous supination over the lift/open sequence.
        opening=(.2*observed('openPalm',sf)+.8*smooth(37,58,sf)*(1-smooth(148,170,sf)))*observed('palmLift',sf)
        palm_delta=carried.inverted()@offer_q
        if (previous_palm_delta is None and palm_delta.w<0) or (previous_palm_delta is not None and previous_palm_delta.dot(palm_delta)<0):palm_delta.negate()
        previous_palm_delta=palm_delta.copy()
        axis,angle=palm_delta.to_axis_angle()
        q=carried@Quaternion(axis,angle*opening)
        q=rot((1,0,0),observed('wristRoll',sf))@q
        mat=q.to_matrix().to_4x4();mat.translation=world[left].translation
        left_target.matrix_world=arm.matrix_world@mat
        quiet=observed('rightOpen',sf)
        mat=world[right].copy();mat.translation+=Vector((-.020,-.012,.009))*quiet
        right_target.matrix_world=arm.matrix_world@mat

        # Per-finger delay/curl rather than a single rigid hand pose.
        for n in humans:
            if not any(s in n for s in ['Index','Middle','Ring','Pinky','Thumb']):continue
            p=rig.pose.bones[n]
            if 'Left' in n:
                delay=next((v for k,v in [('Index',0),('Middle',.3),('Ring',.65),('Pinky',1.0),('Thumb',.4)] if k in n),0)
                amount=observed('curl',sf-delay)
                factor=.65 if 'Thumb' in n else .75 if n.endswith('3') else 1.0
                axis=world[n].to_quaternion().inverted()@width
                p.rotation_quaternion=neutral[n].to_quaternion()@rot(axis,amount*factor)
            else:
                p.rotation_quaternion=neutral[n].to_quaternion()@rot((1,0,0),3*quiet)
        bpy.context.view_layer.update()
        evaluated=rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
        samples.append({n:neutral[n].copy() if frame in (0,168) else local_pose(evaluated.pose.bones[n]) for n in names})
        for n in secondary:
            if 'AmiceB' in n:
                segment=int(n[-1])-1;delay=2+.4*segment
                def pulse(start,end):
                    t=(frame-start-delay)/(end-start)
                    return math.sin(math.pi*t)**2 if 0<t<1 else 0
                side=1 if ' L ' in n else .5
                angle=(.8+.45*segment)*side*(pulse(28,51)-.7*pulse(119,147))
                q=rot((1,0,0),angle)@rot((0,0,1),.22*angle)
            elif 'HairS' in n:
                side=1 if ' L ' in n else -1
                q=rot((1,0,0),.4*math.sin(2*math.pi*(frame-3)/68)*presence)@rot((0,0,1),side*.3*math.sin(2*math.pi*(frame-5)/83)*presence)
            else:
                side=math.cos(int(n.rsplit('_',1)[1])*2*math.pi/10)
                q=rot((0,0,1),-.9*side*observed('weight',max(0,sf-3)))
            secondary_values[n].append(Quaternion() if frame in (0,168) else q)
finally:
    for obj in created:bpy.data.objects.remove(obj,do_unlink=True)
    if rig_data.users==0:bpy.data.armatures.remove(rig_data)

# Only these generated Actions are replaced, never existing runtime files.
for n in ['DH_'+NAME,'DHX_'+NAME,'DHC_'+NAME]:
    if bpy.data.actions.get(n):bpy.data.actions.remove(bpy.data.actions[n],do_unlink=True)
body=bpy.data.actions.new('DH_'+NAME);body.use_fake_user=True
arm.animation_data.action=body
previous={}
for index,(frame,poses) in enumerate(zip(frames,samples)):
    for n,m in poses.items():
        p=arm.pose.bones[n];q=m.to_quaternion()
        if n in previous and q.dot(previous[n])<0:q.negate()
        previous[n]=q.copy();p.rotation_quaternion=q
        p.keyframe_insert('rotation_quaternion',frame=frame,group=n)
        if n=='283.!Root':p.location=m.translation;p.keyframe_insert('location',frame=frame,group=n)
    for n,values in secondary_values.items():
        p=arm.pose.bones[n];p.rotation_quaternion=neutral[n].to_quaternion()@values[index]
        p.keyframe_insert('rotation_quaternion',frame=frame,group='Secondary')
expr=bpy.data.actions.new('DHX_'+NAME);expr.use_fake_user=True
arm.data.animation_data.action=expr
presets=arm.data.vrm_addon_extension.vrm1.expressions.preset
# Existing happy binds are reused, with a gentle visible smile at the 0.7 peak.
for bind in presets.happy.morph_target_binds:
    bind.weight=.35 if bind.index=='34.口角上げ' else .12
for frame in frames:
    sf=frame*30/24
    for name in ['happy','blink','aa','ih','ou','ee','oh','sad','surprised','relaxed']:
        p=getattr(presets,name);p.preview=observed(name,sf) if name in ('happy','blink') else 0
        p.keyframe_insert('preview',frame=frame)

def curves(action):
    return [fc for la in action.layers for st in la.strips for cb in st.channelbags for fc in cb.fcurves]
for ac in [body,expr]:
    for fc in curves(ac):
        for key in fc.keyframe_points:
            key.interpolation='BEZIER';key.handle_left_type=key.handle_right_type='AUTO_CLAMPED'
        fc.update()
cloth=body.copy();cloth.name='DHC_'+NAME;cloth.use_fake_user=True
for la in cloth.layers:
    for st in la.strips:
        for cb in st.channelbags:
            for fc in list(cb.fcurves):
                if not any('"'+n+'"' in fc.data_path for n in secondary):cb.fcurves.remove(fc)

# VRMA carries humanoid/expression data; these are local glTF nonhuman offsets.
raw=(OUT.parent/'characters'/'Lumine_companion.vrm').read_bytes()
gltf=json.loads(raw[20:20+struct.unpack_from('<I',raw,12)[0]])
ids={n.get('name'):i for i,n in enumerate(gltf['nodes'])}
parents={child:i for i,n in enumerate(gltf['nodes']) for child in n.get('children',[])}
def node_world(i):
    n=gltf['nodes'][i];q=n.get('rotation',[0,0,0,1])
    m=Matrix.LocRotScale(Vector(n.get('translation',[0,0,0])),Quaternion((q[3],*q[:3])),Vector(n.get('scale',[1,1,1])))
    return node_world(parents[i])@m if i in parents else m
tracks=[]
for name,values in secondary_values.items():
    rest=arm.data.bones[name].matrix_local.to_quaternion();basis=node_world(ids[name]).to_quaternion();out=[]
    for frame,q in zip(frames,values):
        if frame!=int(frame):continue
        wq=rest@q@rest.inverted();gq=Quaternion((wq.w,wq.x,wq.z,-wq.y));delta=basis.inverted()@gq@basis;delta.normalize()
        out.extend((delta.x,delta.y,delta.z,delta.w))
    out[:4]=out[-4:]=[0,0,0,1]
    tracks.append(dict(nodeName=name,values=out))
(OUT/(NAME+'.secondary.json')).write_text(json.dumps(dict(version=1,fps=24,duration=7,tracks=tracks),separators=(',',':')),encoding='utf-8')
scene.render.fps=24;scene.render.fps_base=1;scene.frame_start=0;scene.frame_end=168
scene.frame_set(46);bpy.context.view_layer.update()
bpy.app.driver_namespace['explain_2_build']=dict(arm=arm,neutral=neutral,world0=world,body=body,expr=expr,cloth=cloth,out=OUT,frames=frames,secondary=secondary)
result=dict(name=NAME,duration=7,authored_poses=len(frames),secondary_tracks=len(secondary),observations=sum(len(v) for k,v in REF.items() if k in ['upper','forearm','palmLift','openPalm','wristRoll','curl','rightOpen','weight','blink','happy']))
