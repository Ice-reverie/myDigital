const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(root, 'vrm_demo/static/js/avatar-stance.js'), 'utf8').replace(/^export /gm, ''), context);
const createStance = vm.runInContext('createForwardStance', context);
const applyStance = vm.runInContext('applyForwardStanceToClip', context);

function buffer(file, withoutTextures = false) {
  const input = fs.readFileSync(path.join(root, file));
  if (!withoutTextures) return input.buffer.slice(input.byteOffset, input.byteOffset + input.length);
  // Load the real rig, skin and rest proportions in Node; only texture decoding
  // needs the browser. Keep all bone/skin/mesh data byte-for-byte intact.
  const size = input.readUInt32LE(12), doc = JSON.parse(input.subarray(20, 20 + size));
  delete doc.images;delete doc.textures;
  doc.materials = doc.materials?.map(material => ({name:material.name}));
  if (doc.extensions?.VRM?.materialProperties) doc.extensions.VRM.materialProperties = [];
  const bytes = Buffer.from(JSON.stringify(doc)), json = Buffer.alloc(Math.ceil(bytes.length / 4) * 4, 32);
  bytes.copy(json);
  const binary = input.subarray(28 + size), output = Buffer.alloc(28 + json.length + binary.length);
  output.write('glTF');output.writeUInt32LE(2, 4);output.writeUInt32LE(output.length, 8);
  output.writeUInt32LE(json.length, 12);output.writeUInt32LE(0x4e4f534a, 16);json.copy(output, 20);
  output.writeUInt32LE(binary.length, 20 + json.length);output.writeUInt32LE(0x004e4942, 24 + json.length);
  binary.copy(output, 28 + json.length);
  return output.buffer.slice(output.byteOffset, output.byteOffset + output.length);
}

test('real avatars keep forward knees and planted feet through both retargeted health actions', async () => {
  const THREE = await import('three');
  const {GLTFLoader} = await import('three/addons/loaders/GLTFLoader.js');
  const {VRMLoaderPlugin, VRMUtils} = await import('@pixiv/three-vrm');
  const {VRMAnimationLoaderPlugin, createVRMAnimationClip} = await import('@pixiv/three-vrm-animation');
  global.ProgressEvent ||= class {constructor(type, data) {Object.assign(this, data);}};
  const loader = new GLTFLoader().register(parser => new VRMAnimationLoaderPlugin(parser));
  const animations = await Promise.all(['Idle_Doctor', 'explain_1'].map(async name =>
    (await loader.parseAsync(buffer(`models/animations/${name}.vrma`), '')).userData.vrmAnimations[0]));
  for (const id of ['schoolBoy', 'doctorBoy', 'schoolGirl', 'studentGirl']) {
    const gltf = await new GLTFLoader().register(parser => new VRMLoaderPlugin(parser))
      .parseAsync(buffer(`models/characters/${id}.vrm`, true), '');
    const vrm = gltf.userData.vrm;VRMUtils.rotateVRM0(vrm);vrm.lookAt = null;
    const get = name => vrm.humanoid.getRawBoneNode(name);
    const point = name => get(name).getWorldPosition(new THREE.Vector3());
    const settle = () => {vrm.update(0);vrm.scene.updateMatrixWorld(true);};
    settle();
    const stance = createStance(THREE, vrm);
    const originalFoot = Object.fromEntries(['left', 'right'].map(side => [side, {
      ankle:point(side + 'Foot'), toe:point(side + 'Toes'),
      rotation:get(side + 'Foot').getWorldQuaternion(new THREE.Quaternion()),
    }]));
    let commonPose;
    for (const animation of animations) {
      const clip = createVRMAnimationClip(animation, vrm);
      const upper = clip.tracks.filter(track => /Spine|Chest|Head|Arm|Hand|Finger/i.test(track.name));
      applyStance(THREE, clip, stance);
      assert.ok(upper.every(track => clip.tracks.includes(track)), 'upper-body tracks are untouched');
      const mixer = new THREE.AnimationMixer(vrm.scene);mixer.clipAction(clip).play();
      for (const time of [0, .9, 2.5, 3.6, 6, clip.duration - .001, clip.duration, clip.duration * 3 + .1]) {
        mixer.setTime(time);settle();
        const pose = [];
        for (const side of ['left', 'right']) {
          const hip = point(side + 'UpperLeg'), knee = point(side + 'LowerLeg'), ankle = point(side + 'Foot');
          const toe = point(side + 'Toes'), label = `${id}/${side}/${time}`;
          assert.ok(Math.abs(knee.x - hip.x) < .0001, `${label}: knee splays sideways`);
          assert.ok(Math.abs(ankle.x - hip.x) < .0001, `${label}: foot must sit below hip`);
          assert.ok(knee.z > Math.max(hip.z, ankle.z), `${label}: knee must bend forward`);
          const bend = hip.clone().sub(knee).angleTo(ankle.clone().sub(knee));
          assert.ok(Math.abs(180 - THREE.MathUtils.radToDeg(bend) - 10) < .05, `${label}: relaxed knee bend`);
          assert.ok(Math.abs(ankle.y - originalFoot[side].ankle.y) < .0001, `${label}: ankle floor height`);
          assert.ok(Math.abs(toe.y - originalFoot[side].toe.y) < .0001, `${label}: toe floor height`);
          assert.ok(get(side + 'Foot').getWorldQuaternion(new THREE.Quaternion()).angleTo(originalFoot[side].rotation) < .0001, `${label}: foot orientation`);
          pose.push(...hip.toArray(), ...knee.toArray(), ...ankle.toArray(), ...toe.toArray());
        }
        commonPose ||= pose;
        assert.ok(pose.every((value, index) => Math.abs(value - commonPose[index]) < .0001), `${id}: stance is common across actions and loops`);
      }
      mixer.stopAllAction();mixer.uncacheRoot(vrm.scene);
    }
    VRMUtils.deepDispose(vrm.scene);
  }
});

test('a non-humanoid asset remains unchanged', async () => {
  const THREE = await import('three');
  assert.equal(createStance(THREE, {}), null);
  const clip = new THREE.AnimationClip('custom', 1, []);
  assert.equal(applyStance(THREE, clip, null), clip);
});
