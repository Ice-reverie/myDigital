/** Shared physical materials, floor reflections and geometry helpers for hospital rooms. */
export function createHospitalRoomKit(THREE, {name = 'hospital-room', floorTint = 0xffffff, lightColor = 0xfff8e9} = {}) {
  const group = new THREE.Group();
  group.name = name;
  const resources = new Set();
  let disposed = false;
  const roomLayer = 1;
  const keep = resource => { resources.add(resource); return resource; };
  const materials = {};
  const makeMaterial = (name, options) => (materials[name] = keep(new THREE.MeshStandardMaterial(options)));
  const white = makeMaterial('porcelain', { color: 0xf4f7f8, roughness: .29, metalness: .03 });
  const wall = makeMaterial('paint', { color: 0xebeff0, roughness: .86 });
  const blue = makeMaterial('blue', { color: 0x428cce, roughness: .25, metalness: .12 });
  const navy = makeMaterial('navy', { color: 0x186fa9, roughness: .37 });
  const silver = makeMaterial('metal', { color: 0xb9c7cd, roughness: .25, metalness: .82 });
  const darkMetal = makeMaterial('darkMetal', { color: 0x455861, roughness: .39, metalness: .65 });
  const cushion = makeMaterial('cushion', { color: 0x337eaf, roughness: .64, metalness: .015 });
  const black = makeMaterial('graphite', { color: 0x29353b, roughness: .71 });
  const glass = keep(new THREE.MeshPhysicalMaterial({
    color: 0xb8e0ef, roughness: .07, metalness: .03,
    transparent: true, opacity: .12, depthWrite: false, side: THREE.DoubleSide,
    clearcoat: 1, clearcoatRoughness: .05,
  }));
  const lightStrip = keep(new THREE.MeshBasicMaterial({ color: 0xfff9eb }));
  const daylight = keep(new THREE.MeshBasicMaterial({ color: 0xe9f7ff }));

  function mesh(geometry, material, x = 0, y = 0, z = 0, parent = group) {
    const object = new THREE.Mesh(keep(geometry), material);
    object.position.set(x, y, z);
    object.layers.set(roomLayer);
    object.castShadow = true;
    object.receiveShadow = true;
    parent.add(object);
    return object;
  }
  function box(w, h, d, material, x, y, z, parent = group) {
    return mesh(new THREE.BoxGeometry(w, h, d), material, x, y, z, parent);
  }
  function cylinder(radiusTop, radiusBottom, height, material, x, y, z, parent = group, segments = 24) {
    return mesh(new THREE.CylinderGeometry(radiusTop, radiusBottom, height, segments), material, x, y, z, parent);
  }
  function tube(a, b, radius, material, parent = group) {
    const start = new THREE.Vector3(...a);
    const end = new THREE.Vector3(...b);
    const delta = end.clone().sub(start);
    const object = cylinder(radius, radius, delta.length(), material, 0, 0, 0, parent, 8);
    object.position.copy(start.add(end).multiplyScalar(.5));
    object.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize());
    return object;
  }
  function roundedShape(width, depth, radius) {
    const x = -width / 2, y = -depth / 2, r = Math.min(radius, width / 2, depth / 2);
    const shape = new THREE.Shape();
    shape.moveTo(x + r, y);
    shape.lineTo(x + width - r, y);
    shape.quadraticCurveTo(x + width, y, x + width, y + r);
    shape.lineTo(x + width, y + depth - r);
    shape.quadraticCurveTo(x + width, y + depth, x + width - r, y + depth);
    shape.lineTo(x + r, y + depth);
    shape.quadraticCurveTo(x, y + depth, x, y + depth - r);
    shape.lineTo(x, y + r);
    shape.quadraticCurveTo(x, y, x + r, y);
    return shape;
  }
  function roundedBlock(w, h, d, r, material, x, y, z, parent = group) {
    const bevel = Math.min(.022, h * .12);
    const geometry = new THREE.ExtrudeGeometry(roundedShape(w, d, r), {
      depth: h - bevel * 2, bevelEnabled: true, bevelSize: bevel,
      bevelThickness: bevel, bevelSegments: 2, steps: 1, curveSegments: 8,
    });
    geometry.rotateX(-Math.PI / 2);
    return mesh(geometry, material, x, y - h / 2 + bevel, z, parent);
  }
  function canvasTexture(width, height, draw) {
    const canvas = document.createElement('canvas');
    canvas.width = width; canvas.height = height;
    draw(canvas.getContext('2d'), width, height);
    const texture = keep(new THREE.CanvasTexture(canvas));
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = 4;
    return texture;
  }
  function label(text, subtitle, width, height, color, background, x, y, z, parent = group) {
    const texture = canvasTexture(1024, Math.max(128, Math.round(1024 * height / width)), (ctx, w, h) => {
      ctx.fillStyle = background; ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = color; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.font = `600 ${Math.round(h * (subtitle ? .46 : .58))}px "Microsoft YaHei", "Noto Sans SC", sans-serif`;
      ctx.fillText(text, w / 2, h * (subtitle ? .40 : .52));
      if (subtitle) {
        ctx.font = `500 ${Math.round(h * .145)}px Arial, sans-serif`;
        ctx.fillText(subtitle, w / 2, h * .80);
      }
    });
    const material = keep(new THREE.MeshBasicMaterial({ map: texture, toneMapped: false,
      transparent: background === 'transparent', depthWrite: background !== 'transparent' }));
    const object = mesh(new THREE.PlaneGeometry(width, height), material, x, y, z, parent);
    object.castShadow = false;
    return object;
  }

  // A low-contrast terrazzo surface, with actual grout seams and a live reflection.
  let seed = 6143;
  function random() { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; }
  const stoneMap = canvasTexture(512, 512, (ctx, w, h) => {
    ctx.fillStyle = '#dde4e7'; ctx.fillRect(0, 0, w, h);
    for (let i = 0; i < 14000; i++) {
      const value = 174 + Math.floor(random() * 59);
      ctx.fillStyle = `rgba(${value},${value + 5},${Math.min(255, value + 9)},${.12 + random() * .16})`;
      const radius = .3 + random() * 1.4;
      ctx.beginPath(); ctx.ellipse(random() * w, random() * h, radius, radius * .65, random() * 6, 0, Math.PI * 2); ctx.fill();
    }
  });
  stoneMap.wrapS = stoneMap.wrapT = THREE.RepeatWrapping;
  stoneMap.repeat.set(18, 26);
  const stone = makeMaterial('stone', { color: floorTint, map: stoneMap, roughness: .31, metalness: .035, envMapIntensity: .7 });
  stone.onBeforeCompile = shader => {
    shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>',
      '#include <map_fragment>\n diffuseColor.rgb = mix(vec3(0.89, 0.925, 0.95), diffuseColor.rgb, 0.65);');
  };
  stone.customProgramCacheKey = () => 'hospital-fine-stone-v1';
  const textureReady = new Promise(resolve => {
    new THREE.TextureLoader().load('./assets/scenes/outpatient-floor-albedo.png', texture => {
      if (disposed) { texture.dispose(); resolve(false); return; }
      keep(texture);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
      texture.repeat.set(5, 7);
      texture.anisotropy = 4;
      stone.map = texture;
      stone.needsUpdate = true;
      resolve(true);
    }, undefined, () => resolve(false));
  });
  const floor = box(14, .16, 20, stone, 0, -.08, -3);
  floor.castShadow = false;
  floor.userData.keepSeparate = true;
  const grout = makeMaterial('grout', { color: 0xadbcc5, roughness: .8, transparent: true, opacity: .12 });
  for (let x = -7; x <= 7; x += 1.4) {
    const seam = box(.006, .001, 20, grout, x, .001, -3); seam.castShadow = false;
  }
  for (let z = -12; z <= 6; z += 1.4) {
    const seam = box(14, .001, .006, grout, 0, .001, z); seam.castShadow = false;
  }
  // A true planar reflection adds depth to the room on the active render layer.
  // The separate avatar pass is not included; its grounding comes from shadows.
  // This subdued, blurred surface keeps the stone floor from becoming a mirror.
  const reflectionTarget = keep(new THREE.WebGLRenderTarget(768, 512, {
    type: THREE.HalfFloatType, minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter,
  }));
  const reflectionCamera = new THREE.PerspectiveCamera();
  const textureMatrix = new THREE.Matrix4();
  const mirrorMaterial = keep(new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { reflection: { value: reflectionTarget.texture }, textureMatrix: { value: textureMatrix } },
    vertexShader: `
      uniform mat4 textureMatrix;
      varying vec4 reflectionCoord;
      varying vec3 worldPosition;
      void main() {
        vec4 world = modelMatrix * vec4(position, 1.0);
        worldPosition = world.xyz;
        reflectionCoord = textureMatrix * world;
        gl_Position = projectionMatrix * viewMatrix * world;
      }`,
    fragmentShader: `
      uniform sampler2D reflection;
      varying vec4 reflectionCoord;
      varying vec3 worldPosition;
      void main() {
        vec2 uv = reflectionCoord.xy / reflectionCoord.w;
        vec2 spread = vec2(0.0038, 0.0062);
        vec3 reflected = texture2D(reflection, uv).rgb * 0.4;
        reflected += texture2D(reflection, uv + vec2(spread.x, 0.0)).rgb * 0.15;
        reflected += texture2D(reflection, uv - vec2(spread.x, 0.0)).rgb * 0.15;
        reflected += texture2D(reflection, uv + vec2(0.0, spread.y)).rgb * 0.15;
        reflected += texture2D(reflection, uv - vec2(0.0, spread.y)).rgb * 0.15;
        float incidence = abs(normalize(cameraPosition - worldPosition).y);
        float opacity = 0.055 + 0.08 * pow(1.0 - incidence, 2.0);
        gl_FragColor = vec4(reflected, opacity);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  }));
  const reflectionPlane = mesh(new THREE.PlaneGeometry(14, 20), mirrorMaterial, 0, .003, -3);
  reflectionPlane.rotation.x = -Math.PI / 2;
  reflectionPlane.castShadow = false;
  reflectionPlane.receiveShadow = false;
  reflectionPlane.userData.keepSeparate = true;
  let renderingReflection = false;
  const reflectedPosition = new THREE.Vector3();
  const reflectedTarget = new THREE.Vector3();
  const cameraForward = new THREE.Vector3();
  const cameraRotation = new THREE.Quaternion();
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -.005);
  const cameraPlane = new THREE.Plane();
  const clip = new THREE.Vector4();
  const q = new THREE.Vector4();
  reflectionPlane.onBeforeRender = (renderer, renderedScene, camera) => {
    if (disposed || renderingReflection || !camera.isPerspectiveCamera) return;
    camera.getWorldPosition(reflectedPosition);
    if (reflectedPosition.y < .01) return;
    camera.getWorldDirection(cameraForward);
    reflectedTarget.copy(reflectedPosition).add(cameraForward);
    reflectedPosition.y = -reflectedPosition.y;
    reflectedTarget.y = -reflectedTarget.y;
    reflectionCamera.copy(camera, false);
    reflectionCamera.position.copy(reflectedPosition);
    camera.getWorldQuaternion(cameraRotation);
    reflectionCamera.up.set(0, 1, 0).applyQuaternion(cameraRotation);
    reflectionCamera.up.y *= -1;
    reflectionCamera.lookAt(reflectedTarget);
    reflectionCamera.updateMatrixWorld();
    reflectionCamera.matrixWorldInverse.copy(reflectionCamera.matrixWorld).invert();
    textureMatrix.set(.5, 0, 0, .5, 0, .5, 0, .5, 0, 0, .5, .5, 0, 0, 0, 1);
    textureMatrix.multiply(reflectionCamera.projectionMatrix).multiply(reflectionCamera.matrixWorldInverse);
    // Oblique clipping discards geometry below the floor in the reflected view.
    cameraPlane.copy(plane).applyMatrix4(reflectionCamera.matrixWorldInverse);
    clip.set(cameraPlane.normal.x, cameraPlane.normal.y, cameraPlane.normal.z, cameraPlane.constant);
    const projection = reflectionCamera.projectionMatrix.elements;
    q.set((Math.sign(clip.x) + projection[8]) / projection[0],
      (Math.sign(clip.y) + projection[9]) / projection[5], -1, (1 + projection[10]) / projection[14]);
    clip.multiplyScalar(2 / clip.dot(q));
    projection[2] = clip.x; projection[6] = clip.y;
    projection[10] = clip.z + 1; projection[14] = clip.w;
    const target = renderer.getRenderTarget();
    const xr = renderer.xr.enabled;
    const shadowUpdates = renderer.shadowMap.autoUpdate;
    const viewport = renderer.getViewport(new THREE.Vector4());
    renderingReflection = true;
    reflectionPlane.visible = false;
    floor.visible = false;
    try {
      renderer.xr.enabled = false;
      renderer.shadowMap.autoUpdate = false;
      renderer.setRenderTarget(reflectionTarget);
      renderer.clear();
      renderer.render(renderedScene, reflectionCamera);
    } finally {
      reflectionPlane.visible = true;
      floor.visible = true;
      renderer.xr.enabled = xr;
      renderer.shadowMap.autoUpdate = shadowUpdates;
      renderer.setRenderTarget(target);
      renderer.setViewport(viewport);
      renderingReflection = false;
    }
  };

  // Small leaf clusters are instanced geometries, not silhouettes pasted onto glass.
  const leafMaterials = [0x38673d, 0x528549, 0x759b54].map(color => keep(new THREE.MeshStandardMaterial({ color, roughness: .77, side: THREE.DoubleSide })));
  const stemMaterial = makeMaterial('stems', { color: 0x6d7650, roughness: .92 });
  function plant(x, z, size = 1, parent = group) {
    const plantGroup = new THREE.Group(); plantGroup.position.set(x, 0, z); parent.add(plantGroup);
    cylinder(.205 * size, .145 * size, .53 * size, white, 0, .265 * size, 0, plantGroup);
    cylinder(.184 * size, .184 * size, .015 * size, black, 0, .523 * size, 0, plantGroup);
    const leafGeometry = keep(new THREE.SphereGeometry(1, 8, 5));
    const cluster = [0, 1, 2].map(i => {
      const instance = new THREE.InstancedMesh(leafGeometry, leafMaterials[i], 16);
      instance.layers.set(roomLayer); instance.castShadow = true; plantGroup.add(instance); return instance;
    });
    const dummy = new THREE.Object3D();
    for (let i = 0; i < 8; i++) {
      const angle = i * 2.399;
      const height = (.90 + random() * .5) * size;
      const radius = (.14 + random() * .26) * size;
      const end = [Math.cos(angle) * radius, height, Math.sin(angle) * radius];
      tube([0, .47 * size, 0], end, .0065 * size, stemMaterial, plantGroup);
      for (let j = 0; j < 6; j++) {
        const t = .43 + j * .095, side = j % 2 ? 1 : -1;
        const a = angle + side * .86;
        const length = (.16 + random() * .12) * size;
        dummy.position.set(end[0] * t + Math.cos(a) * length * .45, .47 * size + (height - .47 * size) * t, end[2] * t + Math.sin(a) * length * .45);
        dummy.scale.set(length, .012 * size, .040 * size);
        dummy.rotation.set(0, -a, side * .19);
        dummy.updateMatrix(); cluster[(i * 6 + j) % 3].setMatrixAt(Math.floor((i * 6 + j) / 3), dummy.matrix);
      }
    }
    return plantGroup;
  }
  // Bright indirect room light, isolated from the avatar's portrait lighting layer.
  const hemi = new THREE.HemisphereLight(0xf4fbff, 0xb6c7cf, 1.65); group.add(hemi);
  const ambient = new THREE.AmbientLight(0xffffff, .38); group.add(ambient);
  const sun = new THREE.DirectionalLight(lightColor, 2.05);
  sun.position.set(11, 5.5, 2.3); sun.target.position.set(-2, 0, -4); group.add(sun, sun.target);
  sun.castShadow = true; sun.shadow.mapSize.set(1024, 1024);
  Object.assign(sun.shadow.camera, { left: -8, right: 8, top: 8, bottom: -8, near: .3, far: 30 });
  sun.shadow.bias = -.00025; sun.shadow.normalBias = .03; sun.shadow.radius = 3;
  sun.shadow.camera.layers.enable(0); sun.shadow.camera.layers.enable(roomLayer);
  const skylight = new THREE.DirectionalLight(0xdbefff, 1.0);
  skylight.position.set(-2, 2.8, 4); skylight.target.position.set(0, 0, -4); group.add(skylight, skylight.target);
  // This small under-ceiling key makes a clean, close contact shadow at the shoes.
  const contactKey = new THREE.DirectionalLight(lightColor, .65);
  contactKey.position.set(.5, 2.86, 1.10); contactKey.target.position.set(0, 0, 0);
  contactKey.castShadow = true; contactKey.shadow.mapSize.set(1024, 1024);
  Object.assign(contactKey.shadow.camera, { left: -1.4, right: 1.4, top: 1.4, bottom: -1.4, near: .1, far: 5.5 });
  contactKey.shadow.bias = -.00003; contactKey.shadow.normalBias = .004; contactKey.shadow.radius = 2;
  contactKey.shadow.camera.layers.set(roomLayer);
  group.add(contactKey, contactKey.target);
  for (const object of [hemi, ambient, sun, skylight, contactKey]) object.layers.set(roomLayer);


  let finalized = false;
  const material = options => keep(new THREE.MeshStandardMaterial(options));
  function finish(animate = () => {}) {
    if (finalized) throw new Error('Room has already been finalized');
    finalized = true;
    // Every room object is on its own lighting layer. Targets do not render.
    group.traverse(object => { object.layers.set(roomLayer); });
    // Merge fixed architecture by material while retaining moving doors and plants.
    // This makes the detail cost tens of draws rather than hundreds on each pass.
    group.updateMatrixWorld(true);
    const buckets = new Map();
    group.traverse(object => {
      if (!object.isMesh || object.isInstancedMesh || object.material.transparent) return;
      for (let parent = object; parent && parent !== group; parent = parent.parent) {
        if (parent.userData.keepSeparate) return;
      }
      const key = `${object.material.uuid}:${object.castShadow}:${object.receiveShadow}`;
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(object);
    });
    for (const objects of buckets.values()) {
      if (objects.length < 2) continue;
      const positions = [], normals = [], uvs = [], indices = [];
      let offset = 0;
      for (const object of objects) {
        const geometry = object.geometry.clone().applyMatrix4(object.matrixWorld);
        const p = geometry.attributes.position, n = geometry.attributes.normal, uv = geometry.attributes.uv;
        for (let i = 0; i < p.count; i++) {
          positions.push(p.getX(i), p.getY(i), p.getZ(i));
          normals.push(n.getX(i), n.getY(i), n.getZ(i));
          uvs.push(uv ? uv.getX(i) : 0, uv ? uv.getY(i) : 0);
        }
        if (geometry.index) {
          for (let i = 0; i < geometry.index.count; i++) indices.push(geometry.index.getX(i) + offset);
        } else {
          for (let i = 0; i < p.count; i++) indices.push(i + offset);
        }
        offset += p.count;
        geometry.dispose();
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
      geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
      geometry.setIndex(indices);
      const combined = mesh(geometry, objects[0].material);
      combined.castShadow = objects[0].castShadow;
      combined.receiveShadow = objects[0].receiveShadow;
      for (const object of objects) object.removeFromParent();
    }

    let elapsed = 0;
    return {
      group, floorY: 0, textureReady,
      tick(delta, {reduced = false} = {}) {
        if (disposed || reduced || !Number.isFinite(delta)) return;
        const step = Math.max(0, Math.min(delta, .1));
        elapsed += step;
        animate(elapsed, step);
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        group.removeFromParent();
        sun.shadow.map?.dispose();
        contactKey.shadow.map?.dispose();
        for (const resource of resources) resource.dispose?.();
        resources.clear();
      },
    };
  }
  return {group, keep, material, mesh, box, cylinder, tube, roundedBlock, label, canvasTexture, plant, finish};
}
