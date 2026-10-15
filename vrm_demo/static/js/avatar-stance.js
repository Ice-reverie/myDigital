// A rotation-only VRMA retarget preserves the source's leg splay even when the
// destination has a different rest stance. Solve this quiet standing pose from
// the destination rig instead. Coordinates below are relative to vrm.scene.
export function createForwardStance(THREE, vrm) {
  const humanoid = vrm.humanoid;
  const bone = name => humanoid?.getNormalizedBoneNode(name);
  const names = ['hips', ...['left', 'right'].flatMap(side =>
    ['UpperLeg', 'LowerLeg', 'Foot', 'Toes'].map(part => side + part))];
  if (names.filter(name => !name.endsWith('Toes')).some(name => !bone(name))) return null;
  vrm.scene.updateMatrixWorld(true);
  const inverseRoot = vrm.scene.matrixWorld.clone().invert();
  const matrix = node => inverseRoot.clone().multiply(node.matrixWorld);
  const position = node => new THREE.Vector3().setFromMatrixPosition(matrix(node));
  const quaternion = node => new THREE.Quaternion().setFromRotationMatrix(matrix(node));
  const rest = new Map(names.filter(name => bone(name)).map(name => {
    const node = bone(name);
    return [name, {node, position:position(node), rotation:quaternion(node)}];
  }));
  const forward = new THREE.Vector3(0, 0, vrm.meta?.metaVersion === '0' ? -1 : 1);
  const legs = ['left', 'right'].map(side => {
    const upper = rest.get(side + 'UpperLeg'), lower = rest.get(side + 'LowerLeg');
    const foot = rest.get(side + 'Foot');
    const thigh = lower.position.clone().sub(upper.position);
    const shin = foot.position.clone().sub(lower.position);
    // Foot directly under its own hip. Keep the original floor height/depth.
    const target = foot.position.clone();target.x = upper.position.x;
    const length1 = thigh.length(), length2 = shin.length();
    const span2 = length1 ** 2 + length2 ** 2 + 2 * length1 * length2 * Math.cos(THREE.MathUtils.degToRad(10));
    const depth2 = (target.z - upper.position.z) ** 2;
    const hipOffset = target.y + Math.sqrt(Math.max(0, span2 - depth2)) - upper.position.y;
    return {side, upper, lower, foot, thigh, shin, target, length1, length2, hipOffset};
  });
  // One pelvis height for both legs. Using the lower solution avoids stretching
  // either leg when the destination's left/right proportions differ slightly.
  const drop = new THREE.Vector3(0, Math.min(...legs.map(leg => leg.hipOffset)), 0);
  const hips = rest.get('hips');
  const hipsMatrix = matrix(hips.node);hipsMatrix.setPosition(hips.position.clone().add(drop));
  const hipsPosition = new THREE.Vector3().setFromMatrixPosition(matrix(hips.node.parent).invert().multiply(hipsMatrix));
  const result = new Map([['hips', {node:hips.node, rotation:hips.node.quaternion.clone(), position:hipsPosition}]]);
  for (const leg of legs) {
    const {side, upper, lower, foot, thigh, shin, target, length1, length2} = leg;
    const start = upper.position.clone().add(drop);
    const axis = target.clone().sub(start), distance = axis.length();axis.normalize();
    if (distance < 1e-6 || length1 < 1e-6 || length2 < 1e-6) return null;
    const along = (length1 ** 2 - length2 ** 2 + distance ** 2) / (2 * distance);
    const height = Math.sqrt(Math.max(0, length1 ** 2 - along ** 2));
    const pole = forward.clone().addScaledVector(axis, -forward.dot(axis)).normalize();
    const knee = start.clone().addScaledVector(axis, along).addScaledVector(pole, height);
    // Shortest swings preserve the rig's rest roll; never infer a knee hinge
    // from the near-collinear rest joints (that introduces large axial twists).
    const upperQ = new THREE.Quaternion().setFromUnitVectors(thigh.clone().normalize(), knee.clone().sub(start).normalize()).multiply(upper.rotation);
    const lowerQ = new THREE.Quaternion().setFromUnitVectors(shin.clone().normalize(), target.clone().sub(knee).normalize()).multiply(lower.rotation);
    const world = new Map([[upper.node, upperQ], [lower.node, lowerQ], [foot.node, foot.rotation]]);
    for (const part of ['UpperLeg', 'LowerLeg', 'Foot', 'Toes']) {
      const value = rest.get(side + part);if (!value) continue;
      const q = world.get(value.node) || value.rotation;
      const parentQ = world.get(value.node.parent) || quaternion(value.node.parent);
      result.set(side + part, {node:value.node, rotation:parentQ.clone().invert().multiply(q).normalize()});
    }
  }
  return result;
}

// Only use for the two in-place health actions. Uploaded motions and other
// actions retain their authored root/leg movement.
export function applyForwardStanceToClip(THREE, clip, stance) {
  if (!stance) return clip;
  const replacements = new Map();
  for (const {node, rotation, position} of stance.values()) {
    for (const [property, value, Track] of [['quaternion', rotation, THREE.QuaternionKeyframeTrack], ['position', position, THREE.VectorKeyframeTrack]]) {
      if (!value) continue;
      const values = value.toArray();
      const track = new Track(node.name + '.' + property, [0, clip.duration], [...values, ...values]);
      replacements.set(track.name, track);
    }
  }
  clip.tracks = clip.tracks.filter(track => !replacements.has(track.name)).concat([...replacements.values()]);
  return clip;
}
