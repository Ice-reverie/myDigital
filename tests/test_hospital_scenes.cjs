const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../vrm_demo/static/js/hospital-scenes.js'), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.replace(/^export /gm, ''), context);
const SceneSelection = vm.runInContext('SceneSelection', context);
const pose = vm.runInContext('scenePose', context);

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function harness(overrides = {}) {
  const commits = [], writes = [], notices = [];
  const selection = new SceneSelection({
    load: async url => url,
    commit: id => commits.push(id),
    read: () => null,
    write: id => writes.push(id),
    notify: (state, id) => notices.push([state, id]),
    ...overrides,
  });
  return { selection, commits, writes, notices };
}

test('restores a saved scene without writing the preference again', async () => {
  const h = harness({ read: () => 'waiting' });
  await h.selection.restore();
  assert.deepEqual(h.commits, ['waiting']);
  assert.deepEqual(h.writes, []);
});

test('unknown saved values and blocked storage safely use the default scene', async () => {
  for (const read of [() => 'https://unknown.example/scene', () => '__proto__', () => { throw Error('blocked'); }]) {
    const h = harness({ read });
    await h.selection.restore();
    assert.deepEqual(h.commits, ['outpatient3d']);
    assert.equal(await h.selection.select('unknown'), false);
  }
});

test('a failed image retains the old scene and can be retried', async () => {
  let fail = false;
  const h = harness({ load: async url => { if (fail) throw Error('offline'); return url; } });
  await h.selection.select('outpatient');
  fail = true;
  assert.equal(await h.selection.select('waiting'), false);
  assert.equal(h.selection.current, 'outpatient');
  assert.deepEqual(h.writes, ['outpatient']);
  assert.deepEqual(h.notices.at(-1), ['error', 'waiting']);
  fail = false;
  assert.equal(await h.selection.select('waiting'), true);
  assert.deepEqual(h.writes, ['outpatient', 'waiting']);
});

test('rapid selections commit only the latest result, even when loads finish out of order', async () => {
  const first = deferred(), second = deferred();
  const h = harness({ load: url => url.includes('waiting') ? first.promise : second.promise });
  const a = h.selection.select('waiting');
  const b = h.selection.select('guidance');
  second.resolve('guidance image');
  assert.equal(await b, true);
  first.resolve('waiting image');
  assert.equal(await a, false);
  assert.deepEqual(h.commits, ['guidance']);
  assert.deepEqual(h.writes, ['guidance']);
});

test('returning to the visible scene cancels an outstanding switch', async () => {
  const pending = deferred();
  const h = harness({ load: url => url.includes('waiting') ? pending.promise : Promise.resolve(url) });
  await h.selection.select('outpatient');
  const a = h.selection.select('waiting');
  await h.selection.select('outpatient');
  pending.resolve('waiting image');
  assert.equal(await a, false);
  assert.deepEqual(h.commits, ['outpatient']);
  assert.deepEqual(h.notices.at(-1), ['ready', 'outpatient']);
});

test('a failed restored scene falls back without replacing its saved preference', async () => {
  const h = harness({ read: () => 'waiting', load: async url => {
    if (url.includes('waiting')) throw Error('offline');
    return url;
  } });
  await h.selection.restore();
  assert.deepEqual(h.commits, ['outpatient3d']);
  assert.deepEqual(h.writes, []);
});

test('a stale failed restoration cannot override a newer explicit scene selection', async () => {
  const pending = deferred();
  const h = harness({ read: () => 'waiting', load: url => url.includes('waiting') ? pending.promise : Promise.resolve(url) });
  const restored = h.selection.restore();
  await h.selection.select('guidance');
  pending.reject(Error('offline'));
  await restored;
  assert.deepEqual(h.commits, ['guidance']);
  assert.deepEqual(h.notices.at(-1), ['ready', 'guidance']);
});

test('saving failures leave the new scene usable and clearly report the unsaved preference', async () => {
  const h = harness({ write: () => { throw Error('quota'); } });
  assert.equal(await h.selection.select('guidance'), true);
  assert.equal(h.selection.current, 'guidance');
  assert.deepEqual(h.notices.at(-1), ['unsaved', 'guidance']);
});

test('the scene picker preserves renderer status and retries a failed 3D selection', async () => {
  // Run the real DOM integration: its notification order must not replace a
  // renderer's pending/error status with the reference image's ready status.
  const element = () => ({
    dataset: {}, style: {}, attributes: {}, handlers: {}, children: [],
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener(name, handler) { this.handlers[name] = handler; },
    removeEventListener(name) { delete this.handlers[name]; },
    setAttribute(name, value) { this.attributes[name] = value; },
    appendChild(child) { this.children.push(child); child.parent = this; },
    remove() { this.parent.children = this.parent.children.filter(child => child !== this); },
    querySelector() { return this.children[0] || null; },
    getBoundingClientRect() { return {}; },
  });
  const root = element(), room = element(), status = element(), picker = element(), help = element();
  const elements = { 'hospital-room': room, 'scene-status': status, 'scene-options': picker, 'help-dialog': help };
  const choices = ['outpatient3d', 'waiting3d', 'guidance3d', 'outpatient', 'waiting', 'guidance'].map(id => {
    const button = element();
    button.dataset.sceneChoice = id;
    return button;
  });
  const writes = [], attempts = [];
  const restored = deferred();
  let imageLoads = 0;
  const sandbox = {
    document: Object.assign(element(), {
      documentElement: root, hidden: false,
      getElementById: id => elements[id], querySelectorAll: () => choices,
    }),
    window: Object.assign(element(), {
      localStorage: { getItem: () => 'outpatient', setItem: (key, value) => writes.push([key, value]) },
    }),
    Image: class {
      set src(value) { this.url = value; imageLoads += 1; queueMicrotask(() => this.onload()); }
      decode() { return Promise.resolve(); }
      cloneNode() { return element(); }
    },
    setTimeout, clearTimeout,
  };
  const domContext = vm.createContext(sandbox);
  vm.runInContext(source.replace(/^export /gm, ''), domContext);
  const createScenes = vm.runInContext('createHospitalScenes', domContext);
  const scenes = createScenes({ reduced: true, onChange: (mood, id) => {
    if (id !== 'outpatient3d') { restored.resolve(); return; }
    assert.equal(mood.renderer, 'three');
    assert.equal(scenes.selection.current, 'outpatient3d');
    const attempt = deferred();
    attempts.push(attempt);
    status.textContent = 'renderer loading';
    return attempt.promise.then(success => {
      status.textContent = success ? 'renderer ready' : 'renderer failed; retry available';
      root.dataset.renderMode = success ? 'three' : 'image';
    });
  } });

  try {
    await restored.promise;
    const button = choices.find(choice => choice.dataset.sceneChoice === 'outpatient3d');
    assert.equal(await button.handlers.click(), true);
    assert.equal(attempts.length, 1);
    assert.equal(status.textContent, 'renderer loading');
    attempts[0].resolve(false);
    await attempts[0].promise;
    assert.equal(status.textContent, 'renderer failed; retry available');
    assert.equal(root.dataset.renderMode, 'image');

    const imageCount = room.children.length;
    assert.equal(await button.handlers.click(), true);
    assert.equal(attempts.length, 2, 'reselecting must invoke the renderer again');
    assert.equal(status.textContent, 'renderer loading');
    assert.equal(room.children.length, imageCount, 'retry should reuse the committed image');
    assert.equal(imageLoads, 1, 'outpatient and its 3D sample share the cached reference');
    assert.equal(button.attributes['aria-pressed'], 'true');
    assert.deepEqual(writes, [['anxin.scene', 'outpatient3d']]);
    attempts[1].resolve(true);
    await attempts[1].promise;
    assert.equal(status.textContent, 'renderer ready');
    assert.equal(root.dataset.renderMode, 'three');
  } finally { scenes.dispose(); }
});

test('reduced motion is stationary regardless of time or pointer movement', () => {
  const neutral = JSON.stringify(pose(0, { x: 0, y: 0 }, true));
  for (const time of [1, 20, 60, 600]) {
    assert.equal(JSON.stringify(pose(time, { x: 1, y: -1 }, true)), neutral);
  }
});

test('ambient movement stays bounded and reacts to both elapsed time and pointer position', () => {
  assert.notDeepEqual(pose(0), pose(10));
  assert.notDeepEqual(pose(10), pose(10, { x: .5, y: -.5 }));
  for (let t = 0; t < 600; t += 3) {
    const p = pose(t, { x: 10, y: -10 });
    assert.ok(Math.abs(p.x) <= 21 && Math.abs(p.y) <= 11);
    assert.ok(Math.abs(p.tilt) <= .35 && p.scale >= 1.035 && p.scale <= 1.045);
    assert.ok(p.light >= .978 && p.light <= 1.022);
  }
});
