import { createHospitalRoomKit } from './hospital-room-kit.js?v=1';

/** A glazed, turquoise guidance hall built from real metre-scale geometry. */
export function createGuidanceRoom(THREE) {
  const kit = createHospitalRoomKit(THREE, {
    name: 'guidance-architecture', floorTint: 0xebf7fa, lightColor: 0xeefbff,
  });
  const { group, keep, mesh, box, cylinder, tube, roundedBlock, label, canvasTexture, plant } = kit;
  const white = kit.material({ color: 0xf4f6f5, roughness: .32, metalness: .025 });
  const paint = kit.material({ color: 0xe9eeee, roughness: .82 });
  const teal = kit.material({ color: 0x55b5c1, roughness: .26, metalness: .10 });
  const deepTeal = kit.material({ color: 0x197d89, roughness: .36, metalness: .06 });
  const aqua = kit.material({ color: 0x81c9d1, roughness: .50, metalness: .025 });
  const silver = kit.material({ color: 0xc5d3d7, roughness: .25, metalness: .84 });
  const charcoal = kit.material({ color: 0x35494c, roughness: .61, metalness: .10 });
  const glass = keep(new THREE.MeshPhysicalMaterial({
    color: 0xb2e7ed, transparent: true, opacity: .12, depthWrite: false,
    roughness: .055, metalness: .03, clearcoat: 1, side: THREE.DoubleSide,
  }));
  const aquaGlass = keep(new THREE.MeshPhysicalMaterial({
    color: 0x5dbcca, transparent: true, opacity: .40, depthWrite: false,
    roughness: .16, metalness: .09, clearcoat: 1, side: THREE.DoubleSide,
  }));
  const light = keep(new THREE.MeshBasicMaterial({ color: 0xfff5e3 }));
  const daylight = keep(new THREE.MeshBasicMaterial({ color: 0xeaf7fd }));
  const breathingLight = kit.material({
    color: 0xc7f7f6, emissive: 0x69d5df, emissiveIntensity: .18,
    roughness: .34, metalness: .035,
  });

  // White ceiling and recessed circular coves, visible under the fixed main view.
  box(12, .18, 18, paint, 0, 3.18, -3.0);
  box(.18, 3.10, 16, paint, -5.7, 1.55, -3.0);
  box(11.4, 3.10, .18, paint, 0, 1.55, -10.5);
  function ceilingRing(x, z, radius) {
    cylinder(radius + .13, radius + .13, .09, white, x, 3.055, z, group, 80);
    const cove = mesh(new THREE.TorusGeometry(radius, .048, 8, 88), light, x, 3.002, z);
    cove.rotation.x = Math.PI / 2;
    cove.castShadow = false;
    cylinder(radius - .08, radius - .08, .024, paint, x, 3.020, z, group, 80);
  }
  ceilingRing(.15, -2.40, 1.58);
  ceilingRing(.55, -7.85, .90);
  for (let z = 1.4; z > -10; z -= 2.0) {
    for (const x of [-3.7, 2.85]) {
      cylinder(.075, .075, .028, silver, x, 3.025, z, group, 20);
      cylinder(.063, .063, .008, light, x, 3.005, z, group, 20).castShadow = false;
    }
  }
  box(.025, .018, 14.4, light, 3.21, 3.011, -2.4).castShadow = false;

  // The broad curved glazing is actual cylindrical architecture, with visible
  // edge trims and an opaque core behind the frosted glass, rather than an image.
  function curvedGlassColumn(x, z, radius) {
    const column = new THREE.Group(); column.position.set(x, 0, z); group.add(column);
    cylinder(radius * .91, radius * .91, 3.04, white, 0, 1.52, 0, column, 72);
    const pane = mesh(new THREE.CylinderGeometry(radius, radius, 2.87, 80, 1, true), aquaGlass, 0, 1.56, 0, column);
    pane.castShadow = false;
    cylinder(radius + .011, radius + .011, .105, silver, 0, .101, 0, column, 80);
    cylinder(radius + .008, radius + .008, .037, silver, 0, 3.0, 0, column, 80);
    const edgeGlow = mesh(new THREE.TorusGeometry(radius + .012, .009, 6, 80), breathingLight, 0, 2.973, 0, column);
    edgeGlow.rotation.x = Math.PI / 2; edgeGlow.castShadow = false;
    for (const angle of [-.93, .61, 2.1]) {
      const px = Math.sin(angle) * (radius + .006), pz = Math.cos(angle) * (radius + .006);
      cylinder(.009, .009, 2.88, silver, px, 1.56, pz, column, 8);
    }
    return column;
  }
  curvedGlassColumn(-3.18, -.40, 1.15);
  curvedGlassColumn(-3.45, -5.10, .87);

  // Central reception and its gently curved, cyan inlaid front fascia.
  const reception = new THREE.Group(); reception.position.set(.30, 0, -5.26); group.add(reception);
  roundedBlock(3.73, .12, 1.10, .46, silver, 0, .085, 0, reception);
  roundedBlock(3.69, .81, 1.08, .45, white, 0, .55, 0, reception);
  roundedBlock(2.28, .65, .045, .025, teal, 0, .56, .548, reception);
  roundedBlock(3.86, .12, 1.22, .49, white, 0, 1.0, 0, reception);
  box(2.67, .012, .01, light, 0, .928, .562, reception).castShadow = false;
  box(2.27, .018, .015, silver, 0, .249, .574, reception);
  // Workstations, document stand and small desk plant keep the counter inhabited.
  function monitor(x, z, angle = 0) {
    const workstation = new THREE.Group(); workstation.position.set(x, 1.07, z);
    workstation.rotation.y = angle; reception.add(workstation);
    roundedBlock(.30, .025, .19, .055, silver, 0, .015, 0, workstation);
    box(.038, .16, .030, silver, 0, .091, -.023, workstation);
    const casing = box(.44, .29, .041, white, 0, .28, -.042, workstation);
    casing.rotation.x = -.09;
    box(.13, .018, .005, silver, 0, .278, -.018, workstation);
  }
  monitor(-.74, -.07, -.16);
  monitor(.90, -.09, .14);
  label('服务咨询', 'INFORMATION', .31, .15, '#286f78', '#ffffff', -.13, 1.16, .24, reception);
  const paperTray = roundedBlock(.27, .018, .20, .015, white, .22, 1.073, .05, reception);
  paperTray.rotation.y = -.14;
  const deskPlant = plant(1.53, -.025, .36, reception); deskPlant.position.y = 1.065;
  plant(-2.26, -3.60, .87);
  plant(2.51, -5.22, .90);

  // Layered back wall: frosted turquoise wings surround a solid white sign panel.
  roundedBlock(3.92, 2.94, .26, .10, white, .30, 1.47, -6.72);
  for (const x of [-1.87, 2.47]) {
    box(.47, 2.96, .16, teal, x, 1.48, -6.72);
    const pane = box(.51, 2.95, .045, aquaGlass, x, 1.48, -6.605); pane.castShadow = false;
    box(.024, 2.91, .034, silver, x + .255, 1.48, -6.571);
  }
  box(3.88, .018, .035, light, .30, 2.935, -6.548).castShadow = false;
  // Keep the physical sign in the clear upper-right part of the wall, outside
  // the central avatar silhouette in the main camera view.
  for (const [dx, dy] of [[0, .12], [-.12, 0], [.12, 0], [0, -.12]]) {
    box(.115, .115, .057, teal, 1.55 + dx, 2.72 + dy, -6.539);
  }
  label('导诊中心', 'GUIDANCE & INFORMATION', 1.20, .38, '#296570', 'transparent', 1.55, 2.33, -6.555);

  // Service corridors continue behind the reception wall and glazed piers.
  for (const x of [-1.98, 2.82]) {
    box(.27, 3.04, .42, white, x, 1.52, -8.36);
    box(.29, .10, .44, silver, x, .07, -8.36);
    box(.023, .10, 2.7, teal, x, 1.01, -9.0).castShadow = false;
  }
  for (const x of [-4.5, 3.60]) {
    box(.13, 2.64, .08, silver, x, 1.32, -9.93);
    box(1.27, .085, .08, silver, x + .67, 2.60, -9.93);
    box(1.23, 2.58, .06, glass, x + .67, 1.31, -9.93).castShadow = false;
    label('诊疗服务', 'CLINIC', .77, .20, '#257785', '#f2f8f7', x + .67, 2.31, -9.879);
  }
  for (const [x, z] of [[-1.62, -3.75], [3.28, -3.70], [3.28, -7.50]]) {
    box(.38, 3.1, .49, white, x, 1.55, z);
    box(.40, .09, .52, silver, x, .06, z);
  }
  plant(-4.34, -8.64, .80);
  plant(2.73, -8.6, .76);

  // Tall side windows, slim mullions, and an outdoor garden beyond the glazing.
  const windowX = 4.32;
  for (let z = 3.2; z >= -10; z -= 1.8) {
    box(.15, 3.06, .068, silver, windowX, 1.53, z);
    const pane = mesh(new THREE.PlaneGeometry(1.73, 2.95), glass, windowX + .025, 1.55, z - .90);
    pane.rotation.y = -Math.PI / 2; pane.castShadow = false;
    box(.025, 4.5, 1.90, daylight, 6.20, 2.0, z - .90).castShadow = false;
  }
  box(.18, .14, 16, white, windowX, .10, -3.0);
  box(.16, .095, 16, silver, windowX, 3.045, -3.0);
  box(.085, .05, 16, silver, windowX - .032, 2.18, -3.0);
  box(.055, .038, 16, silver, windowX - .048, 1.01, -3.0);
  // Actual leaf silhouettes, with no scenic billboards in the room or garden.
  const leafMaterial = kit.material({ color: 0x74964e, roughness: .82, side: THREE.DoubleSide });
  const stem = kit.material({ color: 0x77755c, roughness: .93 });
  const leafGeometry = keep(new THREE.SphereGeometry(1, 6, 4));
  const leaves = new THREE.InstancedMesh(leafGeometry, leafMaterial, 720);
  leaves.layers.set(1); leaves.castShadow = false; leaves.receiveShadow = true;
  leaves.name = 'guidance-garden-leaves'; group.add(leaves);
  const transform = new THREE.Object3D();
  let seed = 2121, leafIndex = 0;
  const random = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);
  for (let tree = 0; tree < 6; tree++) {
    const x = 5.10 + random() * .24, z = 1.9 - tree * 1.96;
    tube([x, 0, z], [x - .08, 2.32, z + .02], .024, stem);
    for (let branch = 0; branch < 5; branch++) {
      const angle = branch * 2.39;
      const end = [x + Math.cos(angle) * .40, 1.26 + branch * .24, z + Math.sin(angle) * .51];
      tube([x - .03, .85 + branch * .20, z], end, .009, stem);
      for (let leaf = 0; leaf < 24; leaf++) {
        transform.position.set(end[0] + (random() - .5) * .52, end[1] + (random() - .5) * .52, end[2] + (random() - .5) * .60);
        transform.scale.set(.09 + random() * .07, .008, .025 + random() * .018);
        transform.rotation.set((random() - .5) * .5, random() * Math.PI * 2, (random() - .5) * .65);
        transform.updateMatrix(); leaves.setMatrixAt(leafIndex++, transform.matrix);
      }
    }
  }
  leaves.instanceMatrix.needsUpdate = true;
  leaves.computeBoundingSphere();

  // Turquoise upholstered chairs share a continuous polished metal support rail.
  const seats = new THREE.Group(); seats.position.set(3.76, 0, -.50); seats.rotation.y = -Math.PI / 2; group.add(seats);
  for (let index = 0; index < 5; index++) {
    const x = (index - 2) * .65;
    roundedBlock(.59, .095, .55, .075, aqua, x, .465, 0, seats);
    const back = roundedBlock(.58, .085, .57, .075, aqua, x, .79, -.26, seats);
    back.rotation.x = Math.PI / 2 - .13;
    tube([x, .43, -.24], [x, .72, -.29], .021, silver, seats);
    if (index === 0 || index === 4) {
      tube([x, .36, -.1], [x, .058, -.22], .026, silver, seats);
      tube([x, .36, -.1], [x, .058, .24], .026, silver, seats);
      box(.12, .029, .54, silver, x, .031, .01, seats);
    }
  }
  tube([-1.59, .365, -.10], [1.59, .365, -.10], .033, silver, seats);
  for (const x of [-1.62, -.98, -.33, .33, .98, 1.62]) {
    tube([x, .46, .16], [x, .66, .16], .019, silver, seats);
    tube([x, .66, .16], [x, .67, -.23], .019, silver, seats);
    tube([x, .67, -.23], [x, .42, -.24], .019, silver, seats);
  }
  plant(3.63, -3.28, .93);
  plant(3.70, 2.37, 1.02);

  // The small real screen has a slowly travelling indicator; no patient data.
  const screenTexture = canvasTexture(512, 256, (ctx, w, h) => {
    ctx.fillStyle = '#173f48'; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#c2f2f0'; ctx.font = '500 48px "Microsoft YaHei", sans-serif';
    ctx.textAlign = 'center'; ctx.fillText('服务导航', w / 2, 88);
    ctx.fillStyle = '#c0e3e5'; ctx.font = '27px "Microsoft YaHei", sans-serif';
    ctx.fillText('咨询 · 预约 · 科室查询', w / 2, 156);
    ctx.fillStyle = '#41747b'; ctx.fillRect(40, 208, w - 80, 6);
  });
  const screenMaterial = keep(new THREE.MeshBasicMaterial({ map: screenTexture, toneMapped: false }));
  box(.53, .277, .045, charcoal, 1.38, 1.228, -5.086);
  mesh(new THREE.PlaneGeometry(.495, .246), screenMaterial, 1.38, 1.228, -5.06).castShadow = false;
  const indicator = box(.12, .007, .003, light, 1.23, 1.146, -5.056);
  indicator.name = 'guidance-service-indicator'; indicator.castShadow = false;
  indicator.userData.keepSeparate = true;

  return kit.finish(elapsed => {
    indicator.position.x = 1.38 + Math.sin(elapsed * .45) * .15;
    breathingLight.emissiveIntensity = .18 + Math.sin(elapsed * .42) * .035;
  });
}
