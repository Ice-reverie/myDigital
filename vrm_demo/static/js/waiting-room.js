import { createHospitalRoomKit } from './hospital-room-kit.js?v=1';

/** A quiet, warm waiting room, built from furniture and architectural geometry. */
export function createWaitingRoom(THREE) {
  const kit = createHospitalRoomKit(THREE, {
    name: 'waiting-architecture', floorTint: 0xfff7e9, lightColor: 0xfff3d9,
  });
  const { group, keep, mesh, box, cylinder, tube, roundedBlock, label, canvasTexture, plant, material } = kit;
  const ivory = material({ color: 0xf4f1e9, roughness: .71 });
  const porcelain = material({ color: 0xfffcf5, roughness: .27, metalness: .025 });
  const sage = material({ color: 0x84ad96, roughness: .69 });
  const sageDark = material({ color: 0x3b705c, roughness: .57 });
  const wallGreen = material({ color: 0xbdcdbb, roughness: .8 });
  const brushed = material({ color: 0xc4c9c2, metalness: .75, roughness: .33 });
  const darkMetal = material({ color: 0x63766b, metalness: .50, roughness: .47 });
  const graphite = material({ color: 0x33423b, roughness: .76 });
  const light = keep(new THREE.MeshBasicMaterial({ color: 0xfff4d9 }));
  const glass = keep(new THREE.MeshPhysicalMaterial({
    color: 0xd4e2d4, roughness: .30, metalness: .015,
    transparent: true, opacity: .30, depthWrite: false, side: THREE.DoubleSide,
  }));

  // Fine oak grain is a surface material; the cabinet and rounded joinery are geometry.
  const oakMap = canvasTexture(512, 1024, (ctx, w, h) => {
    ctx.fillStyle = '#d9bd92'; ctx.fillRect(0, 0, w, h);
    let seed = 811;
    const random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
    for (let i = 0; i < 530; i++) {
      const x = random() * w;
      ctx.strokeStyle = `rgba(${random() > .55 ? '139,101,58' : '255,242,203'},${.025 + random() * .065})`;
      ctx.lineWidth = .4 + random() * 1.1;
      ctx.beginPath(); ctx.moveTo(x, 0);
      ctx.bezierCurveTo(x - 4 + random() * 8, h * .34, x - 5 + random() * 10, h * .68, x + random() * 4, h);
      ctx.stroke();
    }
  });
  oakMap.wrapS = oakMap.wrapT = THREE.RepeatWrapping;
  oakMap.repeat.set(1.25, 1.5);
  const oak = material({ color: 0xffffff, map: oakMap, roughness: .50, metalness: .012 });
  const oakLine = material({ color: 0xc5a879, roughness: .63 });

  // A low ceiling and real recessed panels soften the scale of the space.
  box(10.2, .16, 13.3, ivory, .8, 3.13, -2.2);
  for (const z of [-5.7, -3.5, -1.3, .9, 3.1]) {
    box(9.9, .09, .19, porcelain, .8, 3.015, z);
    for (const x of [-2.9, .25, 3.45]) {
      cylinder(.105, .105, .028, brushed, x, 3.005, z + .45, group, 24);
      cylinder(.084, .084, .012, light, x, 2.986, z + .45, group, 24).castShadow = false;
    }
    box(2.0, .025, .15, light, .6, 3.030, z + .82).castShadow = false;
  }
  for (const x of [-1.25, 2.1]) {
    box(.55, .018, .55, brushed, x, 3.025, -4.6);
    for (let i = 0; i < 9; i++) box(.48, .022, .018, ivory, x, 3.007, -4.815 + i * .052);
  }

  // Frosted glazing and the timber handrail extend along the left waiting seats.
  box(.17, 3.1, 12.0, ivory, -4.12, 1.55, -2.2);
  box(.13, .16, 12.0, brushed, -4.015, .095, -2.2);
  for (const z of [-5.0, -2.55, -.10, 2.35]) {
    box(.12, 3.08, .22, porcelain, -3.98, 1.54, z + 1.03);
    box(.036, 2.42, 1.88, brushed, -3.99, 1.68, z);
    box(.043, 2.33, 1.77, glass, -3.96, 1.68, z).castShadow = false;
    box(.055, .046, 1.83, brushed, -3.919, 2.06, z);
    box(.07, .13, 1.91, porcelain, -3.912, .52, z);
  }
  box(.15, .15, 11.5, oak, -3.91, .99, -2.22);
  for (let z = -6.9; z < 3.1; z += 1.45) box(.18, .025, .038, brushed, -3.91, .92, z);
  box(.53, 3.1, .52, porcelain, -2.96, 1.55, -5.27);
  box(.55, .16, .54, brushed, -2.96, .10, -5.27);
  box(.38, 2.88, .05, wallGreen, -2.43, 1.48, -6.0);

  function waitingChair(x, z, angle = Math.PI / 2 - .10) {
    const chair = new THREE.Group(); chair.position.set(x, 0, z); chair.rotation.y = angle; group.add(chair);
    roundedBlock(.60, .13, .57, .10, sage, 0, .485, 0, chair);
    roundedBlock(.57, .018, .54, .095, sageDark, 0, .424, 0, chair);
    const back = roundedBlock(.60, .115, .67, .09, sage, 0, .84, -.235, chair);
    back.rotation.x = Math.PI / 2 - .14;
    const backFrame = roundedBlock(.62, .037, .69, .085, brushed, 0, .845, -.285, chair);
    backFrame.rotation.x = Math.PI / 2 - .14;
    for (const side of [-1, 1]) {
      tube([side * .27, .33, -.24], [side * .27, 1.15, -.32], .016, brushed, chair);
      tube([side * .34, .48, .19], [side * .34, .72, .19], .024, brushed, chair);
      tube([side * .34, .72, .19], [side * .34, .72, -.20], .024, brushed, chair);
      tube([side * .34, .72, -.20], [side * .27, .48, -.25], .021, brushed, chair);
      roundedBlock(.062, .035, .29, .025, sageDark, side * .34, .748, -.01, chair);
    }
    box(.56, .058, .08, brushed, 0, .39, -.02, chair);
    box(.082, .31, .075, brushed, 0, .22, -.025, chair);
    roundedBlock(.11, .046, .56, .032, brushed, 0, .056, -.02, chair);
    for (const zFoot of [-.235, .195]) box(.12, .027, .076, graphite, 0, .023, zFoot, chair);
  }
  // Linked seats follow the wall. Their backs, armrests and floor shoes are modelled.
  for (let i = 0; i < 7; i++) waitingChair(-2.15, -4.90 + i * .79);
  tube([-2.15, .36, -5.18], [-2.15, .36, -.10], .026, brushed);

  // Two clinic doors are openings in the rear wall, with a modest corridor beyond.
  const rearZ = -6.24;
  box(3.27, 3.10, .18, ivory, -2.405, 1.55, rearZ);
  box(.66, 3.10, .18, ivory, .68, 1.55, rearZ);
  box(3.50, 3.10, .18, ivory, 3.955, 1.55, rearZ);
  box(2.97, .64, .18, ivory, .71, 2.78, rearZ);
  box(9.7, 3.1, .15, ivory, .8, 1.55, -8.5);
  box(.12, 3.1, 2.1, wallGreen, -1.22, 1.55, -7.4);
  box(.12, 3.1, 2.1, wallGreen, 2.75, 1.55, -7.4);
  box(3.82, .18, .06, oak, .78, 1.0, -8.4);
  box(3.78, .15, .06, brushed, .78, .09, -8.4);
  const movingDoors = [];
  for (const [x, index] of [[-.23, 1], [1.61, 2]]) {
    const frameWidth = 1.12;
    for (const side of [-1, 1]) box(.062, 2.46, .15, brushed, x + side * frameWidth / 2, 1.23, rearZ + .035);
    box(1.18, .058, .15, brushed, x, 2.47, rearZ + .035);
    box(1.17, .035, .16, brushed, x, .027, rearZ + .035);
    box(1.24, .39, .13, brushed, x, 2.685, rearZ + .08);
    label(`诊室 ${index}`, 'DEMONSTRATION', 1.15, .31, '#ffffff', '#4d806b', x, 2.685, rearZ + .154);
    const hinge = new THREE.Group(); hinge.name = `waiting-clinic-door-${index}`;
    hinge.position.set(x - .515, 0, rearZ + .055);
    hinge.userData.keepSeparate = true; group.add(hinge);
    box(1.02, 2.39, .072, oak, .51, 1.24, 0, hinge);
    box(.145, .66, .081, brushed, .635, 1.55, .005, hinge);
    box(.106, .609, .085, glass, .635, 1.55, .011, hinge).castShadow = false;
    box(.032, .115, .018, brushed, .907, 1.035, .052, hinge);
    tube([.907, 1.06, .06], [.791, 1.06, .09], .012, brushed, hinge);
    for (const y of [.33, 1.23, 2.1]) cylinder(.013, .013, .09, brushed, .007, y, .04, hinge, 12);
    movingDoors.push(hinge);
    const plaqueX = x + .765;
    box(.22, .34, .025, brushed, plaqueX, 1.63, rearZ + .113);
    label('演示诊室', 'DEMO', .196, .295, '#537566', '#f3f6f0', plaqueX, 1.63, rearZ + .129);
  }
  // Timber rails and stainless lower guards continue between the door frames.
  box(1.64, .13, .10, oak, -1.92, 1.0, rearZ + .14);
  box(1.64, .13, .075, brushed, -1.92, .09, rearZ + .14);
  box(.51, .13, .10, oak, .68, 1.0, rearZ + .14);
  box(.51, .13, .075, brushed, .68, .09, rearZ + .14);

  // Suspended wayfinding uses a physical frame, with real supporting rods.
  const signX = .67, signZ = -4.8;
  box(2.89, .59, .14, brushed, signX, 2.585, signZ);
  label('候 诊 区', 'WAITING AREA · DEMO', 2.72, .48, '#ffffff', '#427761', signX, 2.585, signZ + .095);
  for (const x of [signX - 1.11, signX + 1.11]) cylinder(.015, .015, .24, brushed, x, 2.918, signZ, group, 12);

  // Curved oak reception and matching overhead joinery frame the right side.
  const desk = new THREE.Group(); desk.position.set(3.45, 0, -2.7); group.add(desk);
  roundedBlock(3.55, .135, 1.65, .66, brushed, 0, .083, 0, desk);
  roundedBlock(3.53, .89, 1.63, .65, oak, 0, .59, 0, desk);
  roundedBlock(3.65, .065, 1.74, .69, porcelain, 0, 1.06, 0, desk);
  roundedBlock(3.17, .22, 1.35, .51, porcelain, .075, 1.19, -.11, desk);
  roundedBlock(3.22, .045, 1.38, .52, porcelain, .075, 1.319, -.11, desk);
  // Subtle vertical grooves add depth even when the warm grain is seen at an angle.
  for (let x = -1.12; x <= 1.12; x += .074) box(.006, .84, .004, oakLine, x, .59, .817, desk);
  for (const side of [-1, 1]) {
    for (let i = 1; i <= 14; i++) {
      const a = i / 14 * Math.PI / 2;
      const px = side * (1.115 + Math.sin(a) * .653);
      const pz = .165 + Math.cos(a) * .653;
      cylinder(.003, .003, .84, oakLine, px, .59, pz, desk, 5);
    }
  }
  label('温馨服务', 'CARE & INFORMATION', .80, .24, '#4e7862', 'transparent', -.52, .67, .846, desk);
  roundedBlock(3.94, .31, 1.95, .79, oak, 3.55, 2.94, -2.77);
  roundedBlock(3.84, .025, 1.85, .74, light, 3.55, 2.768, -2.77).castShadow = false;
  roundedBlock(3.46, .055, 1.48, .60, porcelain, 3.55, 2.737, -2.77);
  box(3.9, 3.0, .20, ivory, 4.2, 1.5, -5.28);
  box(.11, .90, 2.9, porcelain, 5.31, .5, -3.66);
  const monitor = new THREE.Group(); monitor.position.set(3.03, 1.12, -2.99); monitor.rotation.y = -.15; group.add(monitor);
  roundedBlock(.42, .025, .25, .04, graphite, 0, .022, 0, monitor);
  box(.055, .19, .045, darkMetal, 0, .123, -.025, monitor);
  box(.67, .40, .050, graphite, 0, .38, -.052, monitor);
  box(.52, .017, .008, darkMetal, 0, .27, -.021, monitor);
  label('演示咨询台', 'INFORMATION', .44, .16, '#537565', '#fffdf8', 2.33, 1.40, -2.39).rotation.x = -.10;
  cylinder(.046, .041, .12, sageDark, 2.67, 1.382, -2.37);
  for (let i = 0; i < 4; i++) tube([2.649 + i * .012, 1.37, -2.37], [2.635 + i * .019, 1.52, -2.37], .003, graphite);

  // Small health-information screen: content deliberately has no real queue numbers.
  const screenMap = canvasTexture(512, 704, (ctx, w, h) => {
    ctx.fillStyle = '#faf9ef'; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#447962'; ctx.fillRect(0, 0, w, 117);
    ctx.fillStyle = '#ffffff'; ctx.font = '600 47px "Microsoft YaHei", sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('温馨提示', w / 2, 78);
    const rows = ['请安静候诊', '注意手部卫生', '有需要请咨询'];
    rows.forEach((text, i) => {
      ctx.fillStyle = '#e6eee0'; ctx.fillRect(27, 165 + i * 135, w - 54, 103);
      ctx.fillStyle = '#496953'; ctx.font = '36px "Microsoft YaHei", sans-serif'; ctx.fillText(text, w / 2, 231 + i * 135);
    });
    ctx.fillStyle = '#71846b'; ctx.font = '26px "Microsoft YaHei", sans-serif'; ctx.fillText('演示信息 · 非现场叫号', w / 2, 647);
  });
  const screenMaterial = keep(new THREE.MeshBasicMaterial({ map: screenMap, toneMapped: false }));
  box(.75, 1.01, .045, brushed, -1.67, 1.92, -6.105);
  mesh(new THREE.PlaneGeometry(.692, .952), screenMaterial, -1.67, 1.92, -6.078).castShadow = false;
  const activity = box(.205, .012, .008, sageDark, -1.88, 1.475, -6.067);
  activity.userData.keepSeparate = true; activity.castShadow = false;

  const plants = [plant(-3.21, -4.63, 1.08), plant(-1.09, -5.56, .79), plant(2.48, -4.54, 1.25)];
  const counterPlant = plant(4.21, -2.88, .47); counterPlant.position.y = 1.34; plants.push(counterPlant);
  const leaves = [];
  for (const p of plants) {
    p.traverse(object => {
      if (!object.isInstancedMesh) return;
      object.userData.keepSeparate = true;
      leaves.push(object);
    });
  }

  return kit.finish(elapsed => {
    // A brief, gentle clinic-door cycle reveals the actual corridor behind it.
    const phase = elapsed % 39;
    let open = 0;
    if (phase > 17 && phase < 20) open = .5 - .5 * Math.cos((phase - 17) / 3 * Math.PI);
    else if (phase >= 20 && phase < 25) open = 1;
    else if (phase >= 25 && phase < 28) open = .5 + .5 * Math.cos((phase - 25) / 3 * Math.PI);
    movingDoors[1].rotation.y = -.31 * open;
    leaves.forEach((leaf, index) => {
      leaf.rotation.z = Math.sin(elapsed * .48 + index * .61) * .006;
      leaf.rotation.x = Math.sin(elapsed * .37 + index * .43) * .003;
    });
    activity.scale.x = .65 + (Math.sin(elapsed * .72) + 1) * .175;
  });
}
