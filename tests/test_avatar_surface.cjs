const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const THREE = require('three');
const { MToonMaterial } = require('@pixiv/three-vrm');

const source = fs.readFileSync(path.join(__dirname, '../vrm_demo/static/js/avatar-surface.js'), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.replace(/^export /gm, ''), context);
const tune = vm.runInContext('tuneAvatarSurface', context);
const createFootContact = vm.runInContext('createFootContact', context);
const createAvatarShadowProxy = vm.runInContext('createAvatarShadowProxy', context);

function material(name) {
  const value = new MToonMaterial();
  value.name = name;
  value.color.setRGB(1, 1, 1);
  value.shadeColorFactor.setRGB(0.97, 0.81, 0.86);
  value.map = new THREE.Texture();
  value.shadeMultiplyTexture = value.map;
  return value;
}
function avatar(materials) {
  return { scene: { traverse(visit) {
    visit({});
    materials.forEach(value => visit({ material: value }));
  } } };
}

test('recognizes skin names in the optional AstraYao model instead of a stale avatar name',
  {skip: !fs.existsSync(path.join(__dirname, '../models/characters/AstraYao.vrm')) && 'AstraYao is not in the current avatar catalog'}, () => {
  const binary = fs.readFileSync(path.join(__dirname, '../models/characters/AstraYao.vrm'));
  const metadata = JSON.parse(binary.toString('utf8', 20, 20 + binary.readUInt32LE(12)));
  const sourceMaterials = metadata.materials.map(entry => material(entry.name));
  assert.equal(tune(avatar(sourceMaterials), 'AstraYao'), 3);
  const faceMesh = metadata.meshes.find(mesh => mesh.primitives.some(p => p.targets?.length));
  const faceMaterials = faceMesh.primitives.map(p => metadata.materials[p.material].name);
  assert.ok(faceMaterials.includes('0._'));
  assert.ok(!metadata.materials.some(m => m.name === '2._ko'));
  for (const value of sourceMaterials) value.dispose();
});

test('softens skin contrast while retaining the color atlas, surface detail and subtle shading', () => {
  for (const name of ['0._', '15.hada', '16.hada2']) {
    const skin = material(name);
    const map = skin.map;
    const color = skin.color.clone();
    const emissive = skin.emissive.clone();
    tune(avatar([skin]), 'AstraYao');
    assert.strictEqual(skin.map, map);
    assert.strictEqual(skin.shadeMultiplyTexture, map);
    assert.ok(skin.color.equals(color));
    assert.ok(skin.emissive.equals(emissive));
    assert.ok(skin.shadeColorFactor.g > 0.9 && skin.shadeColorFactor.g < skin.color.g);
    assert.ok(skin.shadingToonyFactor > 0 && skin.shadingToonyFactor < 0.5);
    assert.ok(skin.shadingShiftFactor >= 0 && skin.shadingShiftFactor < 0.2);
    skin.dispose();
  }
});

test('does not modify AstraYao eyes, lips, hair, clothing or similarly named materials', () => {
  const excluded = ['1._2', '2.kuchi_', '3.shirome', '4.mayu', '6.matsuge', '7.kouzetsu',
    '8._', '9.me', '10.mekou', '11.mekage', '12.karada', '14.karada2', '17._', '18._+', '0._custom'];
  for (const name of excluded) {
    const value = material(name);
    const before = value.toJSON();
    assert.equal(tune(avatar([value]), 'AstraYao'), 0);
    assert.deepEqual(value.toJSON(), before);
    value.dispose();
  }
});

test('unknown and uploaded avatars keep their authored appearance even if names collide', () => {
  for (const id of ['schoolGirl', 'AstraYao_custom', '', undefined]) {
    const value = material('0._');
    const before = value.toJSON();
    assert.equal(tune(avatar([value]), id), 0);
    assert.deepEqual(value.toJSON(), before);
    value.dispose();
  }
});

test('known Lumine skin remains supported without applying the AstraYao mapping', () => {
  for (const id of ['Lumine', 'Lumine_companion']) {
    const skin = material('2._ko');
    const other = material('0._');
    assert.equal(tune(avatar([skin, other]), id), 1);
    assert.ok(skin.shadingToonyFactor < 0.5);
    assert.equal(other.shadingToonyFactor, 0.9);
    skin.dispose(); other.dispose();
  }
});

test('shared materials are tuned once and repeated application is stable', () => {
  const skin = material('0._');
  const vrm = avatar([[skin], skin, [skin, null]]);
  assert.equal(tune(vrm, 'AstraYao'), 1);
  const shade = skin.shadeColorFactor.clone();
  tune(vrm, 'AstraYao');
  assert.ok(skin.shadeColorFactor.equals(shade));
  skin.dispose();
});

test('shade respects a nonwhite lit tint and ignores unsupported material objects', () => {
  const skin = material('0._');
  skin.color.setRGB(0.8, 0.7, 0.6);
  assert.equal(tune(avatar([skin, { name: '0._' }, null]), 'AstraYao'), 1);
  for (const key of ['r', 'g', 'b']) {
    assert.ok(skin.shadeColorFactor[key] < skin.color[key]);
    assert.ok(skin.shadeColorFactor[key] > skin.color[key] * 0.9);
  }
  assert.equal(tune(null, 'AstraYao'), 0);
  skin.dispose();
});

function footFixture() {
  const root = new THREE.Group();
  const hips = new THREE.Bone();
  const leftFoot = new THREE.Bone(), rightFoot = new THREE.Bone();
  const leftToes = new THREE.Bone(), rightToes = new THREE.Bone();
  hips.add(leftFoot, rightFoot);
  leftFoot.add(leftToes); rightFoot.add(rightToes);
  leftFoot.position.set(-0.15, 0.1, 0);
  rightFoot.position.set(0.15, 0.1, 0);
  leftToes.position.z = rightToes.position.z = 0.12;
  root.add(hips);
  const positions = [], indices = [], weights = [];
  for (const [side, x] of [[0, -0.15], [1, 0.15]]) {
    for (const y of [0, 0.14]) {
      for (const localX of [-0.05, 0.05]) {
        for (const z of [-0.1, 0.2]) {
          positions.push(x + localX, y, z);
          indices.push(z > 0 ? side + 3 : side + 1, 0, 0, 0);
          weights.push(1, 0, 0, 0);
        }
      }
    }
  }
  // A long costume point below the feet must not determine the standing height.
  positions.push(0, -0.3, 0);
  indices.push(0, 0, 0, 0); weights.push(1, 0, 0, 0);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(indices, 4));
  geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute(weights, 4));
  geometry.setIndex(Array.from({ length: positions.length / 3 }, (_, i) => i));
  const mesh = new THREE.SkinnedMesh(geometry, new THREE.MeshBasicMaterial());
  root.add(mesh);
  root.updateMatrixWorld(true);
  mesh.bind(new THREE.Skeleton([hips, leftFoot, rightFoot, leftToes, rightToes]));
  const bones = { leftFoot, rightFoot, leftToes, rightToes };
  const vrm = { scene: root, humanoid: { getRawBoneNode(name) { return bones[name]; } } };
  function minimumSole() {
    root.updateMatrixWorld(true);
    const vector = new THREE.Vector3();
    return Math.min(...[0, 1, 2, 3, 8, 9, 10, 11].map(index =>
      mesh.getVertexPosition(index, vector).applyMatrix4(mesh.matrixWorld).y));
  }
  return { root, hips, mesh, bones, vrm, minimumSole };
}

test('contact follows animated foot and toe geometry without changing the horizontal position', () => {
  const h = footFixture();
  const contact = createFootContact(THREE, h.vrm);
  assert.ok(contact.sampleCount >= 4 && contact.sampleCount <= 18);
  h.root.position.set(2.5, 0.7, -3);
  h.hips.position.y = 0.13;
  h.bones.leftFoot.rotation.x = 0.18;
  h.bones.rightToes.rotation.x = -0.16;
  assert.equal(contact.update(0.02), true);
  assert.ok(Math.abs(h.minimumSole() - 0.02) < 1e-6);
  assert.equal(h.root.position.x, 2.5);
  assert.equal(h.root.position.z, -3);
  h.hips.position.y = -0.08;
  h.bones.leftFoot.rotation.x = -0.1;
  h.bones.rightToes.rotation.x = 0.25;
  contact.update(0.02);
  assert.ok(Math.abs(h.minimumSole() - 0.02) < 1e-6);
});

test('contact has no accumulating offset across idle frames and respects parent scale', () => {
  const h = footFixture();
  const contact = createFootContact(THREE, h.vrm);
  const room = new THREE.Group();
  room.scale.set(2, 3, 2);
  room.position.y = 0.5;
  room.add(h.root);
  h.root.position.y = 0.6;
  contact.update(0);
  const first = h.root.position.y;
  for (let frame = 0; frame < 90; frame += 1) contact.update(0);
  assert.ok(Math.abs(first - h.root.position.y) < 1e-9);
  assert.ok(Math.abs(h.minimumSole()) < 1e-6);
});

test('contact ignores unreferenced vertices in shared primitive attribute buffers', () => {
  const h = footFixture();
  // Add an unused foot-weighted point far below the rendered geometry.
  const old = h.mesh.geometry;
  for (const name of ['position', 'skinIndex', 'skinWeight']) {
    const attribute = old.getAttribute(name);
    const extra = name === 'position' ? [0, -8, 0] : [1, 0, 0, 0];
    const Constructor = attribute.array.constructor;
    old.setAttribute(name, new THREE.BufferAttribute(new Constructor([...attribute.array, ...extra]), attribute.itemSize));
  }
  const contact = createFootContact(THREE, h.vrm);
  contact.update();
  assert.ok(Math.abs(h.minimumSole()) < 1e-6);
});

test('missing foot data and disposed contact controllers leave the avatar untouched', () => {
  const root = new THREE.Group();
  root.position.y = 2;
  assert.equal(createFootContact(THREE, { scene: root }).update(), false);
  assert.equal(root.position.y, 2);
  const h = footFixture();
  const contact = createFootContact(THREE, h.vrm);
  contact.dispose(); contact.dispose();
  h.root.position.y = 3;
  assert.equal(contact.sampleCount, 0);
  assert.equal(contact.update(), false);
  assert.equal(h.root.position.y, 3);
});

test('soft contact shadows follow the sampled shoe footprint on the room layer', () => {
  const h = footFixture();
  const contact = createFootContact(THREE, h.vrm);
  const room = new THREE.Group();
  room.add(contact.group);
  h.root.position.set(2, 0.2, -3);
  h.root.rotation.y = 0.6;
  contact.update(0.04);
  assert.equal(contact.group.layers.mask, 2);
  assert.equal(contact.group.children.length, 2);
  const [left, right] = contact.group.children;
  for (const shadow of [left, right]) {
    const position = shadow.getWorldPosition(new THREE.Vector3());
    assert.ok(Math.abs(position.y - 0.046) < 1e-6);
    assert.ok(Math.abs(position.x - 2) < 0.4 && Math.abs(position.z + 3) < 0.4);
    assert.equal(shadow.layers.mask, 2);
    assert.equal(shadow.material.depthWrite, false);
    assert.equal(shadow.material.transparent, true);
    assert.equal(shadow.castShadow, false);
    assert.equal(shadow.visible, true);
  }
  const leftBefore = left.getWorldPosition(new THREE.Vector3());
  h.bones.leftFoot.position.x -= 0.08;
  contact.update(0.04);
  assert.ok(leftBefore.distanceTo(left.getWorldPosition(new THREE.Vector3())) > 0.05);
  const original = right.getWorldPosition(new THREE.Vector3());
  room.position.set(1, 2, 3);
  contact.update(0.04);
  assert.ok(original.distanceTo(right.getWorldPosition(new THREE.Vector3())) < 1e-6);
  contact.dispose();
});

test('a lifted shoe loses ambient occlusion while the planted shoe keeps contact', () => {
  const h = footFixture();
  const contact = createFootContact(THREE, h.vrm);
  contact.update();
  const [left, right] = contact.group.children;
  const initial = left.material.uniforms.opacity.value;
  h.bones.leftFoot.position.y += 0.06;
  contact.update();
  assert.ok(left.material.uniforms.opacity.value < initial * 0.5);
  assert.ok(right.material.uniforms.opacity.value > 0.29);
  h.bones.leftFoot.position.y += 0.1;
  contact.update();
  assert.equal(left.visible, false);
  assert.equal(right.visible, true);
  contact.dispose();
});

test('contact dispose releases its small shadow resources once, leaving avatar resources intact', () => {
  const h = footFixture();
  const contact = createFootContact(THREE, h.vrm);
  let geometryDisposals = 0, materialDisposals = 0, avatarDisposals = 0;
  contact.group.children[0].geometry.addEventListener('dispose', () => geometryDisposals++);
  for (const shadow of contact.group.children) shadow.material.addEventListener('dispose', () => materialDisposals++);
  h.mesh.geometry.addEventListener('dispose', () => avatarDisposals++);
  h.mesh.material.addEventListener('dispose', () => avatarDisposals++);
  const room = new THREE.Scene(); room.add(contact.group);
  contact.dispose(); contact.dispose();
  assert.equal(geometryDisposals, 1);
  assert.equal(materialDisposals, 2);
  assert.equal(avatarDisposals, 0);
  assert.equal(contact.group.parent, null);
});

test('shadow proxies follow shared skeleton poses, model transforms and morphs', () => {
  const h = footFixture();
  const morph = h.mesh.geometry.getAttribute('position').clone();
  morph.setY(0, morph.getY(0) + 0.03);
  h.mesh.geometry.morphAttributes.position = [morph];
  h.mesh.updateMorphTargets();
  const shadows = createAvatarShadowProxy(THREE, h.vrm);
  const room = new THREE.Scene();
  room.add(h.root, shadows.group);
  const proxy = shadows.group.children[0];
  assert.strictEqual(proxy.skeleton, h.mesh.skeleton);
  assert.strictEqual(proxy.geometry, h.mesh.geometry);
  assert.notStrictEqual(proxy.material, h.mesh.material);
  assert.equal(proxy.layers.mask, 2);
  assert.equal(proxy.castShadow, true);
  assert.equal(proxy.material.colorWrite, false);
  assert.equal(proxy.material.depthWrite, false);
  h.root.position.set(1.2, 0.4, -3);
  h.root.rotation.y = 0.4;
  h.bones.leftFoot.rotation.x = 0.2;
  h.mesh.morphTargetInfluences[0] = 0.6;
  shadows.update();
  assert.ok(proxy.matrixWorld.equals(h.mesh.matrixWorld));
  assert.equal(proxy.morphTargetInfluences[0], 0.6);
  const sourceVertex = h.mesh.getVertexPosition(0, new THREE.Vector3()).applyMatrix4(h.mesh.matrixWorld);
  const shadowVertex = proxy.getVertexPosition(0, new THREE.Vector3()).applyMatrix4(proxy.matrixWorld);
  assert.ok(sourceVertex.distanceTo(shadowVertex) < 1e-8);
  shadows.group.position.x = 0.3;
  shadows.update();
  assert.ok(proxy.matrixWorld.equals(h.mesh.matrixWorld));
  shadows.dispose();
});

test('shadow clones preserve transparent cutout silhouettes and inherited visibility', () => {
  const root = new THREE.Group(), parent = new THREE.Group();
  const geometry = new THREE.PlaneGeometry();
  const skin = material('0._');
  skin.alphaTest = 0.5;
  const hair = new THREE.Mesh(geometry, [skin, skin]);
  parent.add(hair); root.add(parent);
  const shadows = createAvatarShadowProxy(THREE, { scene: root });
  const proxy = shadows.group.children[0];
  assert.strictEqual(proxy.material[0], proxy.material[1]);
  assert.strictEqual(proxy.material[0].map, skin.map);
  assert.equal(proxy.material[0].alphaTest, 0.5);
  assert.equal(proxy.material[0].side, skin.side);
  parent.visible = false;
  shadows.update();
  assert.equal(proxy.visible, false);
  parent.visible = true;
  skin.visible = false;
  shadows.update();
  assert.equal(proxy.visible, true);
  assert.equal(proxy.material[0].visible, false);
  shadows.dispose();
});

test('disposing shadows releases only cloned materials, never shared avatar resources', () => {
  const h = footFixture();
  h.mesh.material.map = new THREE.Texture();
  const shadows = createAvatarShadowProxy(THREE, h.vrm);
  const room = new THREE.Scene();
  room.add(shadows.group);
  let proxyDisposals = 0, sourceDisposals = 0;
  shadows.group.children[0].material.addEventListener('dispose', () => proxyDisposals++);
  for (const resource of [h.mesh.material, h.mesh.geometry, h.mesh.material.map]) {
    resource.addEventListener('dispose', () => sourceDisposals++);
  }
  h.mesh.skeleton.dispose = () => sourceDisposals++;
  shadows.dispose(); shadows.dispose(); shadows.update();
  assert.equal(proxyDisposals, 1);
  assert.equal(sourceDisposals, 0);
  assert.equal(shadows.group.parent, null);
  assert.equal(shadows.group.children.length, 0);
});
