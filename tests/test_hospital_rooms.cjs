const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const vm = require('node:vm');
const { buildSync } = require('esbuild');
const THREE = require('three');

// Real geometry, transforms and materials; only browser drawing and image I/O
// are replaced. Bundling in memory resolves the production ES module imports.
const roomModules = [
  ['waiting-room.js', 'createWaitingRoom'],
  ['guidance-room.js', 'createGuidanceRoom'],
].map(([file, factory]) => ({
  file, factory,
  source: buildSync({ entryPoints: [path.join(__dirname, '../vrm_demo/static/js', file)],
    bundle: true, format: 'cjs', platform: 'node', write: false }).outputFiles[0].text,
}));

function harness(module) {
  const resources = new Map();
  const pending = [];
  const register = resource => {
    if (resources.has(resource)) return resource;
    const record = { disposals: 0 };
    resources.set(resource, record);
    resource.addEventListener('dispose', () => { record.disposals++; });
    return resource;
  };
  const trackedThree = { ...THREE };
  for (const [name, Type] of Object.entries(THREE)) {
    if (typeof Type !== 'function' || !Type.prototype) continue;
    if (!(Type === THREE.BufferGeometry || Type.prototype instanceof THREE.BufferGeometry ||
          Type === THREE.Material || Type.prototype instanceof THREE.Material ||
          Type === THREE.Texture || Type.prototype instanceof THREE.Texture ||
          Type === THREE.WebGLRenderTarget || Type.prototype instanceof THREE.WebGLRenderTarget)) continue;
    trackedThree[name] = new Proxy(Type, {
      construct(Target, args) { return register(Reflect.construct(Target, args)); },
    });
  }
  trackedThree.TextureLoader = class {
    load(url, loaded, progress, failed) {
      const texture = register(new THREE.Texture());
      pending.push({ texture, loaded, failed });
      return texture;
    }
  };
  const drawing = Object.fromEntries(['fillRect', 'clearRect', 'beginPath', 'ellipse',
    'fill', 'fillText', 'moveTo', 'lineTo', 'bezierCurveTo', 'stroke', 'arc', 'closePath']
    .map(name => [name, () => {}]));
  const document = { createElement(tag) {
    assert.equal(tag, 'canvas');
    return { width: 0, height: 0, getContext(kind) {
      assert.equal(kind, '2d');
      return { ...drawing };
    } };
  } };
  const exports = {};
  const context = vm.createContext({ document, module: { exports }, exports, console });
  vm.runInContext(module.source, context, { filename: module.file });
  const room = context.module.exports[module.factory](trackedThree);
  return { room, resources,
    resolveTextures() { for (const request of pending.splice(0)) request.loaded(request.texture); },
    failTextures() { for (const request of pending.splice(0)) request.failed(new Error('Image unavailable')); },
    shadowTarget() { return register(new THREE.WebGLRenderTarget(16, 16)); },
  };
}

function visualState(room) {
  room.group.updateMatrixWorld(true);
  const entries = [];
  room.group.traverse(object => {
    entries.push([object.uuid, ...object.matrixWorld.elements]);
    if (object.isInstancedMesh) entries.push(Array.from(object.instanceMatrix.array));
    for (const material of [object.material].flat().filter(Boolean)) {
      entries.push([material.uuid, material.opacity, material.emissiveIntensity]);
    }
  });
  return JSON.stringify(entries);
}

for (const module of roomModules) {
  test(`${module.file}: real geometry is finite and the avatar stands on the declared floor`, async () => {
    const runtime = harness(module);
    const { room } = runtime;
    runtime.resolveTextures();
    assert.equal(await room.textureReady, true);
    assert.equal(room.floorY, 0);
    room.group.updateMatrixWorld(true);
    const ground = [];
    let hasArchitecture = false;
    room.group.traverse(object => {
      assert.ok(object.matrixWorld.elements.every(Number.isFinite), object.name || object.type);
      if (!object.isMesh) return;
      hasArchitecture = true;
      // Room rendering is isolated on layer 1 from the avatar portrait lights.
      assert.equal(object.layers.mask, 2);
      const { geometry } = object;
      const position = geometry.getAttribute('position');
      assert.ok(position?.count > 0);
      for (const attribute of Object.values(geometry.attributes)) {
        assert.ok(Array.from(attribute.array).every(Number.isFinite), `${object.name}: finite ${attribute.itemSize}-D attributes`);
      }
      if (geometry.index) {
        assert.ok(Array.from(geometry.index.array).every(index => index >= 0 && index < position.count));
      }
      if (object.isInstancedMesh) {
        assert.ok(Array.from(object.instanceMatrix.array).every(Number.isFinite));
      }
      geometry.computeBoundingBox();
      const bounds = geometry.boundingBox.clone().applyMatrix4(object.matrixWorld);
      const size = bounds.getSize(new THREE.Vector3());
      if (size.x > 8 && size.z > 8 && size.y > .01 && size.y < .5 &&
          bounds.min.x < 0 && bounds.max.x > 0 && bounds.min.z < 0 && bounds.max.z > 0 &&
          Math.abs(bounds.max.y - room.floorY) < 1e-6) ground.push(object);
    });
    assert.ok(hasArchitecture);
    assert.ok(ground.some(object => object.receiveShadow), 'A broad, solid floor receives the avatar shadow at Y = 0');
    room.dispose();
  });

  test(`${module.file}: visible motion advances, reduced motion pauses, and disposal stops updates`, () => {
    const runtime = harness(module);
    const { room } = runtime;
    runtime.resolveTextures();
    room.tick(.1);
    const initial = visualState(room);
    for (let i = 0; i < 240; i++) room.tick(.1);
    const moving = visualState(room);
    assert.notEqual(moving, initial, 'At least one rendered transform or material must actually animate');
    for (let i = 0; i < 80; i++) room.tick(.1, { reduced: true });
    assert.equal(visualState(room), moving, 'Reduced motion must pause the complete environment');
    room.tick(NaN); room.tick(Infinity); room.tick(-1);
    assert.equal(visualState(room), moving, 'Invalid or negative frame deltas cannot advance the environment');
    room.tick(.1);
    assert.notEqual(visualState(room), moving, 'Animation resumes after reduced motion is disabled');
    room.dispose();
    const disposed = visualState(room);
    room.tick(.1);
    assert.equal(visualState(room), disposed);
  });

  test(`${module.file}: owned GPU resources are released exactly once without disposing unrelated assets`, () => {
    const runtime = harness(module);
    const { room, resources } = runtime;
    runtime.resolveTextures();
    const scene = new THREE.Scene();
    scene.add(room.group);
    room.group.traverse(object => {
      if (object.isLight && object.castShadow) object.shadow.map = runtime.shadowTarget();
    });
    const externalGeometry = new THREE.BoxGeometry();
    const externalMaterial = new THREE.MeshStandardMaterial();
    const external = new THREE.Mesh(externalGeometry, externalMaterial);
    let externalDisposals = 0;
    externalGeometry.addEventListener('dispose', () => { externalDisposals++; });
    externalMaterial.addEventListener('dispose', () => { externalDisposals++; });
    scene.add(external);
    assert.ok(resources.size > 0);
    room.dispose();
    room.dispose();
    assert.equal(room.group.parent, null);
    assert.equal(external.parent, scene);
    assert.equal(externalDisposals, 0);
    for (const [resource, record] of resources) {
      assert.equal(record.disposals, 1, resource.type || resource.constructor.name);
    }
    externalGeometry.dispose(); externalMaterial.dispose();
  });

  test(`${module.file}: a texture arriving after disposal is released and never revives the room`, async () => {
    const runtime = harness(module);
    runtime.room.dispose();
    runtime.resolveTextures();
    assert.equal(await runtime.room.textureReady, false);
    for (const [resource, record] of runtime.resources) {
      assert.equal(record.disposals, 1, resource.type || resource.constructor.name);
    }
    assert.equal(runtime.room.group.parent, null);
  });

  test(`${module.file}: failed floor-image loading retains a usable procedural floor`, async () => {
    const runtime = harness(module);
    runtime.failTextures();
    assert.equal(await runtime.room.textureReady, false);
    let hasFallback = false;
    runtime.room.group.traverse(object => {
      if (object.isMesh && object.receiveShadow && object.material.map?.isCanvasTexture) hasFallback = true;
    });
    assert.ok(hasFallback, 'A drawable material remains when the image request fails');
    assert.doesNotThrow(() => runtime.room.tick(.1));
    runtime.room.dispose();
  });

  test(`${module.file}: reflection rendering restores the shared renderer even when a render fails`, () => {
    const runtime = harness(module);
    runtime.resolveTextures();
    const scene = new THREE.Scene(); scene.add(runtime.room.group);
    scene.updateMatrixWorld(true);
    const camera = new THREE.PerspectiveCamera(50, 1.4, .05, 80);
    camera.position.set(0, 1.5, 3); camera.lookAt(0, 1, -3);
    camera.layers.set(1); camera.updateMatrixWorld(true);
    let reflection;
    runtime.room.group.traverse(object => {
      if (object.material?.uniforms?.reflection) reflection = object;
    });
    assert.ok(reflection, 'The floor has a live reflection pass');
    const originalTarget = new THREE.WebGLRenderTarget(16, 16);
    const originalViewport = new THREE.Vector4(13, 21, 800, 600);
    let currentTarget = originalTarget;
    const currentViewport = originalViewport.clone();
    let failed = true, renderCalls = 0;
    const renderer = {
      xr: { enabled: true }, shadowMap: { autoUpdate: true },
      getRenderTarget: () => currentTarget,
      setRenderTarget: target => { currentTarget = target; currentViewport.set(0, 0, 768, 512); },
      getViewport: target => target.copy(currentViewport),
      setViewport: viewport => currentViewport.copy(viewport),
      clear() {},
      render(renderedScene, reflectedCamera) {
        renderCalls++;
        assert.equal(renderedScene, scene);
        assert.equal(reflectedCamera.layers.mask, camera.layers.mask);
        assert.ok(reflectedCamera.projectionMatrix.elements.every(Number.isFinite));
        assert.equal(reflection.visible, false);
        assert.equal(renderer.xr.enabled, false);
        assert.equal(renderer.shadowMap.autoUpdate, false);
        reflection.onBeforeRender(renderer, scene, reflectedCamera);
        if (failed) throw new Error('Simulated reflection failure');
      },
    };
    assert.throws(() => reflection.onBeforeRender(renderer, scene, camera), /Simulated reflection failure/);
    assert.equal(currentTarget, originalTarget);
    assert.ok(currentViewport.equals(originalViewport));
    assert.equal(renderer.xr.enabled, true);
    assert.equal(renderer.shadowMap.autoUpdate, true);
    assert.equal(reflection.visible, true);
    failed = false;
    reflection.onBeforeRender(renderer, scene, camera);
    assert.equal(renderCalls, 2, 'The reflection recovers after an error without recursive rendering');
    assert.equal(currentTarget, originalTarget);
    assert.ok(currentViewport.equals(originalViewport));
    runtime.room.dispose(); originalTarget.dispose();
  });
}

test('waiting and guidance rooms own independent geometry, materials, textures and animation clocks', () => {
  const first = harness(roomModules[0]);
  const second = harness(roomModules[1]);
  first.resolveTextures(); second.resolveTextures();
  assert.notStrictEqual(first.room.group, second.room.group);
  for (const resource of first.resources.keys()) assert.ok(!second.resources.has(resource));
  second.room.tick(.1);
  const before = visualState(second.room);
  for (let i = 0; i < 20; i++) first.room.tick(.1);
  first.room.dispose();
  assert.equal(visualState(second.room), before);
  for (const record of second.resources.values()) assert.equal(record.disposals, 0);
  second.room.tick(.1);
  assert.notEqual(visualState(second.room), before);
  second.room.dispose();
});
