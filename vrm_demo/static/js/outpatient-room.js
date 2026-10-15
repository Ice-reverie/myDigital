/** A small, fully modelled outpatient hall. All dimensions are in metres. */
export function createOutpatientRoom(THREE) {
  const group = new THREE.Group();
  group.name = 'outpatient-architecture';
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
  const stone = makeMaterial('stone', { color: 0xffffff, map: stoneMap, roughness: .31, metalness: .035, envMapIntensity: .7 });
  stone.onBeforeCompile = shader => {
    shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>',
      '#include <map_fragment>\n diffuseColor.rgb = mix(vec3(0.89, 0.925, 0.95), diffuseColor.rgb, 0.65);');
  };
  stone.customProgramCacheKey = () => 'outpatient-pale-fine-stone-v2';
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

  // Restrained panel joints make the room read as built architecture.
  box(.18, 3.1, 18, wall, -6.45, 1.55, -3);
  box(13, .13, 18, wall, 0, 3.09, -3);
  box(13, .12, .15, white, 0, 2.97, -6.12);
  for (let z = -9.5; z <= 4; z += 1.5) {
    box(12.9, .008, .011, silver, 0, 3.017, z).castShadow = false;
  }
  for (const x of [-4.2, 1.25, 4.3]) {
    box(.012, .01, 17.8, silver, x, 3.012, -3).castShadow = false;
  }
  for (let z = -9; z <= 3; z += 2.6) {
    box(2.42, .065, .3, silver, .45, 2.978, z);
    box(2.30, .015, .24, lightStrip, .45, 2.938, z).castShadow = false;
    for (const x of [-3.8, 3.7]) {
      cylinder(.082, .082, .027, silver, x, 3.0, z, group, 20);
      cylinder(.068, .068, .008, lightStrip, x, 2.982, z, group, 20).castShadow = false;
    }
  }

  // Reception joinery: rounded stone body, blue inlay and brushed steel plinth.
  const beforeReception = new Set(group.children);
  const reception = new THREE.Group(); reception.position.set(-3.8, 0, -2.75); group.add(reception);
  roundedBlock(4.6, .11, 1.46, .59, silver, 0, .08, 0, reception);
  roundedBlock(4.58, .94, 1.43, .59, white, 0, .59, 0, reception);
  roundedBlock(4.60, .19, 1.46, .60, blue, 0, .96, 0, reception);
  roundedBlock(4.75, .065, 1.56, .63, white, 0, 1.10, 0, reception);
  label('门 诊 服 务', 'OUTPATIENT SERVICE', 1.15, .30, '#247eb8', 'transparent', 1.48, .55, .76, reception);
  // A thin warm reveal below the worktop, without a floating halo around the body.
  box(3.62, .012, .008, lightStrip, -.22, 1.044, .746, reception).castShadow = false;

  // The back workspace uses real depth: cupboards, screen, task chairs and stationery.
  box(4.78, 1.52, .17, white, -3.94, 2.19, -4.64);
  box(4.82, .018, .052, lightStrip, -3.94, 1.42, -4.535).castShadow = false;
  box(4.70, .90, .48, white, -3.94, .47, -4.40);
  box(4.85, .05, .59, white, -3.94, .94, -4.38);
  for (let x = -5.9; x <= -2; x += .79) {
    box(.012, .76, .015, silver, x, .48, -4.15);
    box(.20, .016, .035, silver, x + .36, .75, -4.132);
  }
  function monitor(x, z, rotation = 0) {
    const stand = new THREE.Group(); stand.position.set(x, 1.136, z); stand.rotation.y = rotation; group.add(stand);
    roundedBlock(.42, .027, .25, .07, silver, 0, .018, 0, stand);
    box(.056, .22, .045, silver, 0, .13, -.03, stand);
    roundedBlock(.63, .045, .43, .045, white, 0, .36, -.075, stand).rotation.x = Math.PI / 2 - .13;
    box(.21, .028, .008, silver, 0, .36, -.019, stand);
  }
  monitor(-3.8, -2.70, -.15);
  monitor(-5.0, -2.96, .10);
  for (const x of [-5.0, -3.75]) {
    const chair = new THREE.Group(); chair.position.set(x, 0, -3.8); group.add(chair);
    roundedBlock(.53, .08, .51, .07, black, 0, .48, 0, chair);
    const back = roundedBlock(.52, .055, .51, .055, black, 0, .84, -.22, chair);
    back.rotation.x = Math.PI / 2 - .10;
    cylinder(.031, .034, .42, darkMetal, 0, .24, 0, chair);
    for (let a = 0; a < 5; a++) {
      const angle = a * Math.PI * 2 / 5;
      tube([0, .12, 0], [Math.sin(angle) * .31, .07, Math.cos(angle) * .31], .014, silver, chair);
    }
  }
  cylinder(.049, .039, .11, silver, -3.11, 1.19, -2.27);
  for (let i = 0; i < 5; i++) {
    const pen = box(.007, .20, .008, navy, -3.14 + i * .013, 1.24, -2.26);
    pen.rotation.z = (i - 2) * .065;
  }
  label('咨询与预约', 'INFORMATION', .41, .17, '#327dad', '#ffffff', -2.83, 1.22, -2.155).rotation.x = -.12;

  // Slim pillars divide reception and the glazed corridor exactly like the reference.
  box(.60, 3.0, .65, white, -1.5, 1.50, -4.84);
  box(.63, .13, .69, silver, -1.5, .09, -4.84);
  const verticalText = canvasTexture(256, 1024, (ctx, w, h) => {
    ctx.fillStyle = '#edf2f3'; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#197baa'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.font = '500 142px "Microsoft YaHei", sans-serif';
    ['门', '诊', '部', '→'].forEach((text, i) => ctx.fillText(text, w / 2, 153 + i * 220));
  });
  const verticalMaterial = keep(new THREE.MeshBasicMaterial({ map: verticalText, toneMapped: false }));
  mesh(new THREE.PlaneGeometry(.39, 1.43), verticalMaterial, -1.5, 2.07, -4.50).castShadow = false;
  for (const object of group.children) if (!beforeReception.has(object)) object.position.x += .60;

  // Outer glass frame and a corridor visible through it; no painted background wall.
  const beforeCorridor = new Set(group.children);
  const doorZ = -6.03;
  box(8.35, .13, .20, silver, 1.55, 3.11, doorZ);
  box(8.35, .035, .12, darkMetal, 1.55, .025, doorZ);
  for (const x of [-2.60, -.82, 3.72, 5.72]) {
    box(.066, 3.10, .085, silver, x, 1.56, doorZ);
  }
  const panelWidths = [[-1.73, 1.68], [.32, 2.19], [2.59, 2.19], [4.72, 1.91]];
  const movingDoors = [];
  panelWidths.forEach(([x, width], index) => {
    const panel = new THREE.Group(); panel.position.set(x, 0, doorZ); group.add(panel);
    mesh(new THREE.PlaneGeometry(width, 3.02), glass, 0, 1.55, .015, panel).castShadow = false;
    box(width, .06, .048, silver, 0, .09, .017, panel);
    for (const edge of [-1, 1]) box(.035, 2.98, .05, silver, edge * width / 2, 1.55, .016, panel);
    box(width, .105, .015, blue, 0, 1.09, .034, panel).castShadow = false;
    if (index === 1 || index === 2) {
      panel.userData.keepSeparate = true;
      panel.name = index === 1 ? 'outpatient-door-left' : 'outpatient-door-right';
      panel.position.z += .045;
      box(.027, .46, .035, silver, index === 1 ? width / 2 - .13 : -width / 2 + .13, 1.14, .073, panel);
      movingDoors.push({ object: panel, base: x, sign: index === 1 ? -1 : 1 });
    }
  });
  box(4.41, .12, .23, white, 1.45, 3.08, -5.94);
  box(.12, .044, .071, darkMetal, 1.45, 3.005, -5.79);
  label('←  内科诊室', 'INTERNAL MEDICINE', 2.02, .38, '#ffffff', '#237fb9', .29, 2.62, -5.91);
  label('外科诊室  →', 'SURGERY', 2.02, .38, '#ffffff', '#237fb9', 2.59, 2.62, -5.91);
  for (const x of [-.69, 1.3, 1.6, 3.6]) {
    box(.017, .29, .02, silver, x, 2.99, -5.935);
  }
  box(13, 3.4, .20, wall, 0, 1.7, -12.2);
  box(.17, 3.4, 6.0, wall, -2.56, 1.7, -9.13);
  box(.15, 3.4, 6.0, wall, 5.72, 1.7, -9.13);
  for (let z = -7.3; z > -12; z -= 2) {
    box(.18, 3.2, .17, white, -2.46, 1.6, z);
    box(.16, 3.2, .17, white, 5.6, 1.6, z);
    box(8, .055, .13, white, 1.52, 3.15, z);
    box(1.8, .015, .20, lightStrip, 1.5, 3.325, z).castShadow = false;
    box(.045, 2.43, .10, silver, .853, 1.25, z - .89);
    box(.045, 2.43, .10, silver, 2.107, 1.25, z - .89);
    box(1.3, .045, .10, silver, 1.48, 2.443, z - .89);
    box(1.3, .035, .10, silver, 1.48, .052, z - .89);
    box(1.16, 2.29, .11, glass, 1.48, 1.25, z - .82).castShadow = false;
  }
  // Glazed clinic bays in the inner passage.
  for (const x of [-.7, 3.65]) {
    for (let z = -8; z > -12; z -= 2.1) {
      box(.06, 2.84, .06, silver, x, 1.42, z);
      const pane = mesh(new THREE.PlaneGeometry(2.04, 2.79), glass, x, 1.42, z - 1.02);
      pane.rotation.y = Math.PI / 2; pane.castShadow = false;
      box(.025, .10, 2.07, blue, x, 1.09, z - 1.02).castShadow = false;
    }
  }
  const corridor = new THREE.Group();
  const corridorParts = group.children.filter(object => !beforeCorridor.has(object));
  for (const object of corridorParts) corridor.add(object);
  corridor.scale.set(.60, .91, 1);
  corridor.position.x = 1.55 * .40;
  group.add(corridor);

  // Right window wall with the outdoor garden behind actual mullions and glazing.
  const beforeWindows = new Set(group.children);
  box(.26, .17, 17, white, 6.10, 3.02, -3);
  for (let z = 4; z >= -10; z -= 1.85) {
    box(.33, 3.0, .095, silver, 5.97, 1.50, z);
    const pane = mesh(new THREE.PlaneGeometry(1.75, 2.78), glass, 5.90, 1.52, z - .925);
    pane.rotation.y = -Math.PI / 2; pane.castShadow = false;
    // These light apertures are outside the room, not scenic billboards.
    box(.015, 5.0, 2.15, daylight, 7.8, 2.15, z - .925).castShadow = false;
  }
  box(.23, .14, 17.1, white, 5.85, .11, -3);
  box(.13, .09, 17.1, silver, 5.90, 2.92, -3);
  box(.09, .037, 17.1, silver, 5.81, 1.10, -3);
  for (const object of group.children) if (!beforeWindows.has(object)) object.position.x -= 1.45;

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
  plant(3.50, -5.35, 1.1);
  plant(-4.9, -4.20, .76).position.y = .98;
  plant(-1.74, -2.72, .47).position.y = 1.135;
  plant(-4.81, -2.75, .47).position.y = 1.135;
  plant(3.01, -9.23, .85);
  // Fine, individually lit leaves keep the garden airy through the glass. The
  // whole outdoor canopy is one instanced draw, with no solid polygonal crowns.
  const gardenLeaf = keep(new THREE.MeshStandardMaterial({
    color: 0xffffff, roughness: .84, side: THREE.DoubleSide,
    emissive: 0x38501a, emissiveIntensity: .055,
  }));
  const gardenLeafGeometry = keep(new THREE.BufferGeometry());
  gardenLeafGeometry.setAttribute('position', new THREE.Float32BufferAttribute([
    0, 0, 0, -.37, .38, .04, 0, 1, 0, .37, .38, .04, 0, .41, .12,
  ], 3));
  gardenLeafGeometry.setAttribute('uv', new THREE.Float32BufferAttribute([
    .5, 0, 0, .38, .5, 1, 1, .38, .5, .41,
  ], 2));
  gardenLeafGeometry.setIndex([0, 1, 4, 1, 2, 4, 2, 3, 4, 3, 0, 4]);
  gardenLeafGeometry.computeVertexNormals();
  const treeCount = 8, branchesPerTree = 6, leavesPerBranch = 80;
  const gardenCanopy = keep(new THREE.InstancedMesh(gardenLeafGeometry, gardenLeaf,
    treeCount * branchesPerTree * leavesPerBranch));
  gardenCanopy.layers.set(roomLayer);
  gardenCanopy.castShadow = false;
  gardenCanopy.receiveShadow = true;
  gardenCanopy.name = 'outpatient-garden-leaves';
  group.add(gardenCanopy);
  const leafTransform = new THREE.Object3D();
  const leafTint = new THREE.Color();
  let leafIndex = 0;
  for (let i = 0; i < 8; i++) {
    const z = 3 - i * 1.8 + (random() - .5) * .35;
    const trunkX = 5.25 + random() * .26;
    tube([trunkX, -.1, z], [trunkX - .08, 2.09, z + .13], .030, stemMaterial);
    for (let j = 0; j < branchesPerTree; j++) {
      const angle = j * 2.399 + random() * .35;
      const branchX = Math.max(4.91, trunkX + Math.cos(angle) * .34);
      const branchY = 1.52 + random() * 1.05;
      const branchZ = z + Math.sin(angle) * .50;
      tube([trunkX - .03, 1.15 + j * .12, z], [branchX, branchY, branchZ], .010, stemMaterial);
      for (let k = 0; k < leavesPerBranch; k++) {
        const azimuth = random() * Math.PI * 2;
        const height = random() * 2 - 1;
        const radius = Math.cbrt(random());
        const ring = Math.sqrt(1 - height * height) * radius;
        leafTransform.position.set(
          branchX + Math.cos(azimuth) * ring * .28,
          branchY + height * radius * .33,
          branchZ + Math.sin(azimuth) * ring * .38);
        const length = .105 + random() * .105;
        leafTransform.scale.set(length * (.75 + random() * .32), length, length * .72);
        leafTransform.rotation.set((random() - .5) * 1.8, random() * Math.PI * 2, random() * Math.PI * 2);
        leafTransform.updateMatrix();
        gardenCanopy.setMatrixAt(leafIndex, leafTransform.matrix);
        leafTint.setHSL(.20 + random() * .075, .27 + random() * .27, .28 + random() * .23);
        gardenCanopy.setColorAt(leafIndex, leafTint);
        leafIndex++;
      }
    }
  }
  gardenCanopy.instanceMatrix.needsUpdate = true;
  gardenCanopy.instanceColor.needsUpdate = true;
  gardenCanopy.computeBoundingSphere();

  // Metal-framed waiting seats face into the hall rather than directly at the camera.
  function waitingSeat(x, z) {
    const seat = new THREE.Group(); seat.position.set(x, 0, z); seat.rotation.y = -Math.PI / 2 + .06; group.add(seat);
    roundedBlock(.56, .073, .53, .07, cushion, 0, .46, 0, seat);
    const back = roundedBlock(.55, .075, .55, .055, cushion, 0, .80, -.23, seat);
    back.rotation.x = Math.PI / 2 - .12;
    for (const side of [-1, 1]) {
      tube([side * .25, .08, -.26], [side * .25, .65, -.23], .018, silver, seat);
      tube([side * .25, .43, .22], [side * .25, .08, .24], .018, silver, seat);
      tube([side * .32, .68, -.19], [side * .32, .68, .19], .019, silver, seat);
      tube([side * .32, .44, .20], [side * .32, .68, .19], .019, silver, seat);
      tube([side * .32, .68, -.19], [side * .25, .49, -.23], .019, silver, seat);
      box(.095, .023, .39, silver, side * .25, .036, -.015, seat);
    }
    tube([-.27, .39, -.1], [.27, .39, -.1], .023, silver, seat);
  }
  for (let z = -4.12; z <= 2.5; z += .68) waitingSeat(3.85, z);

  // Small physical information screens, with an animated progress line.
  const screenTexture = canvasTexture(256, 512, (ctx, w, h) => {
    ctx.fillStyle = '#eaf5fc'; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#237baa'; ctx.fillRect(0, 0, w, 95);
    ctx.fillStyle = '#ffffff'; ctx.font = '600 27px "Microsoft YaHei", sans-serif'; ctx.textAlign = 'center'; ctx.fillText('门诊服务', w / 2, 55);
    for (let i = 0; i < 5; i++) {
      ctx.fillStyle = i % 2 ? '#d8eaf3' : '#ffffff'; ctx.fillRect(12, 122 + i * 68, w - 24, 56);
      ctx.fillStyle = '#286a94'; ctx.font = '21px "Microsoft YaHei", sans-serif'; ctx.fillText(['咨询导诊', '预约挂号', '科室查询', '健康提醒', '便民服务'][i], w / 2, 158 + i * 68);
    }
  });
  const screenMat = keep(new THREE.MeshBasicMaterial({ map: screenTexture, toneMapped: false }));
  box(.53, 1.01, .048, darkMetal, -4.09, 1.91, -4.52);
  mesh(new THREE.PlaneGeometry(.475, .94), screenMat, -4.09, 1.91, -4.49).castShadow = false;
  const indicator = box(.16, .010, .004, lightStrip, -4.21, 1.483, -4.483); indicator.castShadow = false;
  indicator.userData.keepSeparate = true;

  // Bright indirect room light, isolated from the avatar's portrait lighting layer.
  const hemi = new THREE.HemisphereLight(0xf4fbff, 0xb6c7cf, 1.65); group.add(hemi);
  const ambient = new THREE.AmbientLight(0xffffff, .38); group.add(ambient);
  const sun = new THREE.DirectionalLight(0xfff8e9, 2.05);
  sun.position.set(11, 5.5, 2.3); sun.target.position.set(-2, 0, -4); group.add(sun, sun.target);
  sun.castShadow = true; sun.shadow.mapSize.set(1024, 1024);
  Object.assign(sun.shadow.camera, { left: -8, right: 8, top: 8, bottom: -8, near: .3, far: 30 });
  sun.shadow.bias = -.00025; sun.shadow.normalBias = .03; sun.shadow.radius = 3;
  sun.shadow.camera.layers.enable(0); sun.shadow.camera.layers.enable(roomLayer);
  const skylight = new THREE.DirectionalLight(0xdbefff, 1.0);
  skylight.position.set(-2, 2.8, 4); skylight.target.position.set(0, 0, -4); group.add(skylight, skylight.target);
  // This small under-ceiling key makes a clean, close contact shadow at the shoes.
  const contactKey = new THREE.DirectionalLight(0xffffff, .65);
  contactKey.position.set(.5, 2.86, 1.10); contactKey.target.position.set(0, 0, 0);
  contactKey.castShadow = true; contactKey.shadow.mapSize.set(1024, 1024);
  Object.assign(contactKey.shadow.camera, { left: -1.4, right: 1.4, top: 1.4, bottom: -1.4, near: .1, far: 5.5 });
  contactKey.shadow.bias = -.00003; contactKey.shadow.normalBias = .004; contactKey.shadow.radius = 2;
  contactKey.shadow.camera.layers.set(roomLayer);
  group.add(contactKey, contactKey.target);
  for (const object of [hemi, ambient, sun, skylight, contactKey]) object.layers.set(roomLayer);

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
    group,
    floorY: 0,
    textureReady,
    tick(delta, { reduced = false } = {}) {
      if (disposed || reduced) return;
      elapsed += Math.min(delta, .1);
      // A quiet 34-second automatic-door cycle, with the doorway open only briefly.
      const phase = elapsed % 34;
      let open = 0;
      if (phase > 23 && phase < 25) open = .5 - .5 * Math.cos((phase - 23) / 2 * Math.PI);
      else if (phase >= 25 && phase < 29) open = 1;
      else if (phase >= 29 && phase < 31) open = .5 + .5 * Math.cos((phase - 29) / 2 * Math.PI);
      for (const door of movingDoors) door.object.position.x = door.base + door.sign * open * 1.28;
      indicator.scale.x = .65 + (Math.sin(elapsed * .65) + 1) * .175;
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
