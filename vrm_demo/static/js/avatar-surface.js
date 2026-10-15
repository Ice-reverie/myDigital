// These names were checked against the shipped AstraYao VRM's primitives and
// texture coordinates: 0._ is the face, hada / hada2 are exposed body skin.
// Other face primitives share the texture atlas but contain eyes, lips or teeth.
const ASTRA_SKIN = new Set(['0._', '15.hada', '16.hada2']);
const LUMINE_IDS = new Set(['Lumine', 'Lumine_companion']);

/** Soften known skin materials at runtime, leaving the model file untouched. */
export function tuneAvatarSurface(vrm, avatarId) {
  const names = avatarId === 'AstraYao' ? ASTRA_SKIN
    : LUMINE_IDS.has(avatarId) ? new Set(['2._ko']) : null;
  if (!names || !vrm?.scene?.traverse) return 0;

  const seen = new Set();
  let count = 0;
  vrm.scene.traverse(object => {
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    for (const material of materials) {
      if (!material || seen.has(material)) continue;
      seen.add(material);
      if (!names.has(material.name) || !material.shadeColorFactor?.setRGB
        || !Number.isFinite(material.shadingToonyFactor)
        || !Number.isFinite(material.shadingShiftFactor)) continue;

      const lit = material.color;
      if (!lit || ![lit.r, lit.g, lit.b].every(Number.isFinite)) continue;
      // MToon blends two texture-multiplied colors. Keep a faint warm shade,
      // replacing the source's strong pink multiplier, with a wider transition.
      // All factors are in linear color space. Textures and their UVs are kept.
      material.shadeColorFactor.setRGB(lit.r * 0.98, lit.g * 0.955, lit.b * 0.94);
      material.shadingToonyFactor = 0.28;
      material.shadingShiftFactor = 0.08;
      if (Number.isFinite(material.giEqualizationFactor)) material.giEqualizationFactor = 0.95;
      count += 1;
    }
  });
  return count;
}

/**
 * Sample each shoe's sole once, then follow those skinned vertices during idle.
 * Call update AFTER vrm.update() and animation changes. This pins the lowest
 * support point, rather than ankle bones whose height does not include a shoe.
 */
export function createFootContact(THREE, vrm) {
  const root = vrm?.scene;
  const samples = [];
  const supportSamples = [[], []];
  let disposed = false;
  const point = new THREE.Vector3();
  const getBone = name => vrm?.humanoid?.getRawBoneNode?.(name);
  const feet = [new Set([getBone('leftFoot'), getBone('leftToes')].filter(Boolean)),
    new Set([getBone('rightFoot'), getBone('rightToes')].filter(Boolean))];
  const candidates = [[], []];

  function refreshMatrices() {
    root.parent?.updateWorldMatrix(true, false);
    root.updateMatrixWorld(true);
  }

  if (root?.traverse && feet.some(bones => bones.size)) {
    refreshMatrices();
    root.traverse(mesh => {
      if (!mesh.isSkinnedMesh || !mesh.getVertexPosition || !mesh.skeleton) return;
      const geometry = mesh.geometry;
      const skinIndex = geometry.getAttribute('skinIndex');
      const skinWeight = geometry.getAttribute('skinWeight');
      const positions = geometry.getAttribute('position');
      if (!skinIndex || !skinWeight || !positions) return;
      const boneSide = mesh.skeleton.bones.map(bone => feet[0].has(bone) ? 0 : feet[1].has(bone) ? 1 : -1);
      if (boneSide.every(side => side < 0)) return;
      // glTF primitives may share an attribute buffer; inspect only this
      // primitive's referenced vertices, not another material's hidden geometry.
      const index = geometry.getIndex();
      const count = index ? index.count : positions.count;
      const start = Math.max(0, geometry.drawRange.start);
      const end = Math.min(count, start + geometry.drawRange.count);
      const visited = new Set();
      for (let i = start; i < end; i += 1) {
        const vertex = index ? index.getX(i) : i;
        if (visited.has(vertex)) continue;
        visited.add(vertex);
        const influence = [0, 0];
        for (let joint = 0; joint < 4; joint += 1) {
          const side = boneSide[skinIndex.getComponent(vertex, joint)];
          if (side >= 0) influence[side] += skinWeight.getComponent(vertex, joint);
        }
        const side = influence[0] >= influence[1] ? 0 : 1;
        if (influence[side] < 0.35) continue;
        mesh.getVertexPosition(vertex, point).applyMatrix4(mesh.matrixWorld);
        if (![point.x, point.y, point.z].every(Number.isFinite)) continue;
        candidates[side].push({ mesh, vertex, x:point.x, y:point.y, z:point.z });
      }
    });

    for (const [side, foot] of candidates.entries()) {
      if (!foot.length) continue;
      let low = foot[0], high = low.y;
      for (const entry of foot) {
        if (entry.y < low.y) low = entry;
        high = Math.max(high, entry.y);
      }
      const band = Math.max(0.01, Math.min(0.04, (high - low.y) * 0.18));
      const sole = foot.filter(entry => entry.y <= low.y + band);
      const selected = new Set([low]);
      // Eight horizontal extrema include both heels and toes, and catch a foot
      // rolling sideways. A single minimum-Y vertex would float after rotation.
      for (let direction = 0; direction < 8; direction += 1) {
        const x = Math.cos(direction * Math.PI / 4), z = Math.sin(direction * Math.PI / 4);
        let support = sole[0], score = -Infinity;
        for (const entry of sole) {
          const next = entry.x * x + entry.z * z;
          if (next > score) { support = entry; score = next; }
        }
        selected.add(support);
      }
      supportSamples[side] = [...selected];
      samples.push(...selected);
    }
  }

  // A small ambient-occlusion approximation supplements directional shadows
  // in the bright room. Its footprint follows the very same shoe vertices as
  // grounding; a lifted shoe fades instead of leaving a fixed dark ellipse.
  const group = new THREE.Group();
  group.name = 'avatar-foot-contact';
  group.layers.set(1);
  const contactGeometry = samples.length ? new THREE.PlaneGeometry(1, 1) : null;
  const contactMaterials = [];
  const contacts = supportSamples.map(foot => {
    if (!foot.length) return null;
    const material = new THREE.ShaderMaterial({
      transparent: true, depthTest: true, depthWrite: false, side: THREE.DoubleSide,
      toneMapped: false,
      uniforms: { opacity: { value: 0.4 } },
      vertexShader: `varying vec2 contactUv;
        void main() { contactUv = uv;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
      fragmentShader: `varying vec2 contactUv; uniform float opacity;
        void main() {
          float radius = length((contactUv - 0.5) * 2.0);
          float feather = exp(-1.8 * radius * radius) * (1.0 - smoothstep(0.6, 1.0, radius));
          gl_FragColor = vec4(0.035, 0.045, 0.055, opacity * feather);
        }`,
    });
    contactMaterials.push(material);
    const contact = new THREE.Mesh(contactGeometry, material);
    contact.name = 'shoe-ambient-occlusion';
    contact.layers.set(1);
    contact.matrixAutoUpdate = false;
    contact.frustumCulled = false;
    contact.renderOrder = 2;
    contact.castShadow = false;
    contact.receiveShadow = false;
    group.add(contact);
    return contact;
  });
  const worldContact = new THREE.Matrix4(), inverseGroup = new THREE.Matrix4();
  const axisU = new THREE.Vector3(), axisV = new THREE.Vector3(), normal = new THREE.Vector3(0, 1, 0);
  const footprintScale = new THREE.Vector3();

  function updateContactShadows(floorY) {
    group.updateWorldMatrix(true, false);
    inverseGroup.copy(group.matrixWorld).invert();
    for (let side = 0; side < contacts.length; side += 1) {
      const contact = contacts[side];
      if (!contact) continue;
      const foot = supportSamples[side];
      let centerX = 0, centerZ = 0, lowest = Infinity;
      for (const sample of foot) {
        sample.mesh.getVertexPosition(sample.vertex, point).applyMatrix4(sample.mesh.matrixWorld);
        sample.currentX = point.x; sample.currentZ = point.z;
        centerX += point.x; centerZ += point.z;
        lowest = Math.min(lowest, point.y);
      }
      centerX /= foot.length; centerZ /= foot.length;
      let xx = 0, zz = 0, xz = 0;
      for (const sample of foot) {
        const x = sample.currentX - centerX, z = sample.currentZ - centerZ;
        xx += x * x; zz += z * z; xz += x * z;
      }
      const angle = 0.5 * Math.atan2(2 * xz, xx - zz);
      const cosine = Math.cos(angle), sine = Math.sin(angle);
      let minU = Infinity, maxU = -Infinity, minV = Infinity, maxV = -Infinity;
      for (const sample of foot) {
        const x = sample.currentX - centerX, z = sample.currentZ - centerZ;
        const u = x * cosine + z * sine, v = x * sine - z * cosine;
        minU = Math.min(minU, u); maxU = Math.max(maxU, u);
        minV = Math.min(minV, v); maxV = Math.max(maxV, v);
      }
      const gap = Math.max(0, lowest - floorY);
      const opacity = 0.4 * Math.pow(Math.max(0, 1 - gap / 0.14), 2);
      contact.visible = opacity > 0.001;
      contact.material.uniforms.opacity.value = opacity;
      axisU.set(cosine, 0, sine); axisV.set(sine, 0, -cosine);
      footprintScale.set(Math.max(0.09, maxU - minU) * 1.6 + 0.04 + gap * 0.4,
        Math.max(0.045, maxV - minV) * 1.8 + 0.04 + gap * 0.4, 1);
      worldContact.makeBasis(axisU, axisV, normal).scale(footprintScale);
      worldContact.setPosition(centerX + cosine * (minU + maxU) / 2 + sine * (minV + maxV) / 2,
        floorY + 0.006, centerZ + sine * (minU + maxU) / 2 - cosine * (minV + maxV) / 2);
      contact.matrix.multiplyMatrices(inverseGroup, worldContact);
      contact.matrixWorldNeedsUpdate = true;
    }
    group.updateMatrixWorld(true);
  }

  return {
    group,
    get sampleCount() { return samples.length; },
    update(floorY = 0) {
      if (!samples.length || !Number.isFinite(floorY)) return false;
      refreshMatrices();
      let lowest = Infinity;
      for (const { mesh, vertex } of samples) {
        mesh.getVertexPosition(vertex, point).applyMatrix4(mesh.matrixWorld);
        lowest = Math.min(lowest, point.y);
      }
      // Convert a world-height correction to root-local Y. This also works
      // under a scaled parent, while keeping the root's X and Z unchanged.
      const parentYScale = root.parent ? root.parent.matrixWorld.elements[5] : 1;
      if (!Number.isFinite(lowest) || Math.abs(parentYScale) < 1e-6) return false;
      root.position.y += (floorY - lowest) / parentYScale;
      root.updateMatrixWorld(true);
      updateContactShadows(floorY);
      return true;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      samples.length = 0;
      supportSamples.forEach(foot => { foot.length = 0; });
      group.removeFromParent(); group.clear();
      contactGeometry?.dispose();
      for (const material of contactMaterials) material.dispose();
      contactMaterials.length = 0;
    },
  };
}

/**
 * Keep the character's shadow in the room pass while lighting its visible
 * surfaces in a separate pass. Geometry, textures and skeletons stay shared;
 * only the invisible proxy materials belong to this controller.
 */
export function createAvatarShadowProxy(THREE, vrm) {
  const group = new THREE.Group();
  group.name = 'avatar-room-shadow';
  group.layers.set(1);
  const pairs = [];
  const materials = new Map();
  const inverseGroup = new THREE.Matrix4();
  let disposed = false;

  function shadowMaterial(source) {
    if (!source?.clone) return null;
    if (!materials.has(source)) {
      const copy = source.clone();
      copy.colorWrite = false;
      copy.depthWrite = false;
      // WebGLShadowMap derives its own depth material, retaining this map and
      // alphaTest. The room's color pass writes neither pixels nor depth.
      materials.set(source, copy);
    }
    return materials.get(source);
  }

  vrm?.scene?.traverse(source => {
    if (!source.isMesh || !source.geometry || !source.material) return;
    if (source.isSkinnedMesh && !source.skeleton) return;
    const material = Array.isArray(source.material)
      ? source.material.map(shadowMaterial) : shadowMaterial(source.material);
    if (!material || (Array.isArray(material) && material.some(value => !value))) return;
    const proxy = source.isSkinnedMesh
      ? new THREE.SkinnedMesh(source.geometry, material) : new THREE.Mesh(source.geometry, material);
    proxy.name = `shadow:${source.name}`;
    proxy.layers.set(1);
    proxy.matrixAutoUpdate = false;
    proxy.castShadow = true;
    proxy.receiveShadow = false;
    proxy.frustumCulled = false;
    if (source.isSkinnedMesh) {
      // Do not call bind() without an explicit bind matrix: it would recompute
      // inverses on the shared skeleton and disturb the visible character.
      proxy.skeleton = source.skeleton;
      proxy.bindMode = source.bindMode;
      proxy.bindMatrix.copy(source.bindMatrix);
      proxy.bindMatrixInverse.copy(source.bindMatrixInverse);
    }
    group.add(proxy);
    pairs.push({ source, proxy });
  });

  function update() {
    if (disposed) return;
    vrm?.scene?.parent?.updateWorldMatrix(true, false);
    vrm?.scene?.updateMatrixWorld(true);
    group.updateWorldMatrix(true, false);
    inverseGroup.copy(group.matrixWorld).invert();
    for (const { source, proxy } of pairs) {
      proxy.matrix.multiplyMatrices(inverseGroup, source.matrixWorld);
      proxy.matrixWorldNeedsUpdate = true;
      proxy.visible = true;
      for (let ancestor = source; ancestor; ancestor = ancestor.parent) {
        if (!ancestor.visible) { proxy.visible = false; break; }
      }
      if (source.isSkinnedMesh) {
        proxy.bindMatrix.copy(source.bindMatrix);
        proxy.bindMatrixInverse.copy(source.bindMatrixInverse);
      }
      if (source.morphTargetInfluences && proxy.morphTargetInfluences) {
        for (let i = 0; i < source.morphTargetInfluences.length; i += 1) {
          proxy.morphTargetInfluences[i] = source.morphTargetInfluences[i];
        }
      }
      const sourceMaterials = Array.isArray(source.material) ? source.material : [source.material];
      const proxyMaterials = Array.isArray(proxy.material) ? proxy.material : [proxy.material];
      for (let i = 0; i < sourceMaterials.length; i += 1) {
        proxyMaterials[i].visible = sourceMaterials[i].visible;
        proxyMaterials[i].alphaTest = sourceMaterials[i].alphaTest;
        proxyMaterials[i].opacity = sourceMaterials[i].opacity;
      }
    }
    group.updateMatrixWorld(true);
  }

  update();
  return {
    group,
    update,
    dispose() {
      if (disposed) return;
      disposed = true;
      group.removeFromParent();
      group.clear();
      for (const material of materials.values()) material.dispose();
      materials.clear();
      pairs.length = 0;
    },
  };
}
