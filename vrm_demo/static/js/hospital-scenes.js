// Scene selection is independent of chat, voice and the optional avatar renderer.
export const HOSPITAL_SCENES = Object.freeze({
  outpatient3d: { name: '门诊大厅 · 3D', image: './assets/scenes/outpatient.png', renderer: 'three', comparison: 'outpatient', light: 0xfffaf5, rim: 0xd5e7ff },
  waiting3d: { name: '温馨候诊区 · 3D', image: './assets/scenes/waiting.png', renderer: 'three', comparison: 'waiting', light: 0xfff6e7, rim: 0xd1e8d9 },
  guidance3d: { name: '智慧导诊 · 3D', image: './assets/scenes/guidance.png', renderer: 'three', comparison: 'guidance', light: 0xefffff, rim: 0xbde9ed },
  outpatient: { name: '门诊大厅 · 原图', image: './assets/scenes/outpatient.png', comparison: 'outpatient3d', light: 0xf5f9ff, rim: 0xc5dcff },
  waiting: { name: '温馨候诊区 · 原图', image: './assets/scenes/waiting.png', comparison: 'waiting3d', light: 0xfff6e7, rim: 0xd1e8d9 },
  guidance: { name: '智慧导诊 · 原图', image: './assets/scenes/guidance.png', comparison: 'guidance3d', light: 0xefffff, rim: 0xbde9ed },
});
export const SCENE_STORAGE_KEY = 'anxin.scene';

// Loading first and committing last prevents a failed or stale selection from
// replacing the visible scene or the preference saved in this browser.
export class SceneSelection {
  constructor({ load, commit, read, write, notify = () => {} }) {
    Object.assign(this, { load, commit, read, write, notify });
    this.current = null;
    this.request = 0;
  }

  async select(id, persist = true) {
    if (!Object.hasOwn(HOSPITAL_SCENES, id)) return false;
    const request = ++this.request;
    if (id === this.current) {
      this.notify('ready', id);
      return true;
    }
    this.notify('loading', id);
    let image;
    try { image = await this.load(HOSPITAL_SCENES[id].image); }
    catch {
      if (request === this.request) this.notify('error', id);
      return false;
    }
    if (request !== this.request) return false;
    this.commit(id, image);
    this.current = id;
    let saved = true;
    if (persist) {
      try { this.write(id); } catch { saved = false; }
    }
    this.notify(saved ? 'ready' : 'unsaved', id);
    return true;
  }

  async restore() {
    let id;
    try { id = this.read(); } catch { /* Storage may be unavailable in private mode. */ }
    if (!Object.hasOwn(HOSPITAL_SCENES, id)) id = 'outpatient3d';
    const pending = this.select(id, false);
    const request = this.request;
    if (!await pending && request === this.request && id !== 'outpatient3d') await this.select('outpatient3d', false);
  }
}

export function scenePose(seconds, pointer = { x: 0, y: 0 }, reduced = false) {
  if (reduced) return { x: 0, y: 0, tilt: 0, scale: 1.035, light: 1 };
  const x = Math.max(-1, Math.min(1, pointer.x));
  const y = Math.max(-1, Math.min(1, pointer.y));
  return {
    x: Math.sin(seconds / 9) * 9 - x * 12,
    y: Math.sin(seconds / 12) * 4 - y * 7,
    tilt: x * .35,
    scale: 1.04 + Math.sin(seconds / 16) * .005,
    light: 1 + Math.sin(seconds / 11) * .022,
  };
}

function loadSceneImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    const timer = setTimeout(() => reject(new Error('Scene load timeout')), 12000);
    image.onload = async () => {
      try { await image.decode(); resolve(image); } catch (error) { reject(error); }
      finally { clearTimeout(timer); }
    };
    image.onerror = () => { clearTimeout(timer); reject(new Error('Scene unavailable')); };
    image.src = url;
  });
}

export function createHospitalScenes({ reduced = false, onChange = () => {} } = {}) {
  const root = document.documentElement;
  const room = document.getElementById('hospital-room');
  const status = document.getElementById('scene-status');
  const picker = document.getElementById('scene-options');
  const choices = [...document.querySelectorAll('[data-scene-choice]')];
  const help = document.getElementById('help-dialog');
  const images = new Map();
  let currentImage = room.querySelector('img');
  let frame = null;
  let lastTime = null;
  let seconds = 0;
  let dragging = false;
  const pointer = { x: 0, y: 0 };
  const target = { x: 0, y: 0 };
  const removals = new Set();

  const selection = new SceneSelection({
    load: (url) => {
      if (!images.has(url)) images.set(url, loadSceneImage(url).catch(error => { images.delete(url); throw error; }));
      return images.get(url);
    },
    read: () => window.localStorage.getItem(SCENE_STORAGE_KEY),
    write: (id) => window.localStorage.setItem(SCENE_STORAGE_KEY, id),
    commit: (id, loaded) => {
      const previous = currentImage;
      const next = loaded.cloneNode();
      next.alt = '';
      next.className = 'scene-image';
      next.draggable = false;
      room.appendChild(next);
      currentImage = next;
      // Establish the transition start without adding another animation loop.
      next.getBoundingClientRect();
      next.classList.add('is-visible');
      previous?.classList.remove('is-visible');
      const timer = setTimeout(() => { previous?.remove(); removals.delete(timer); }, reduced ? 0 : 1000);
      removals.add(timer);
      root.dataset.scene = id;
      choices.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.sceneChoice === id)));
    },
    notify: (state, id) => {
      picker.setAttribute('aria-busy', String(state === 'loading'));
      choices.forEach(button => button.classList.toggle('is-loading', state === 'loading' && button.dataset.sceneChoice === id));
      const name = HOSPITAL_SCENES[id].name;
      status.textContent = state === 'loading' ? `正在切换到${name}…` :
        state === 'error' ? `${name}暂时无法载入，已保留原场景。请再点一次重试。` :
        state === 'unsaved' ? `已切换到${name}；当前浏览器无法保存，下次打开将使用默认场景。` :
        `当前场景：${name}。选择会在本浏览器保留。`;
      // Notify the renderer after the image status, including an explicit
      // re-selection. A failed optional 3D load can then retry and report its
      // own loading/error state without being overwritten by image readiness.
      if (state === 'ready' || state === 'unsaved') onChange(HOSPITAL_SCENES[id], id);
    },
  });

  const draw = () => {
    const pose = scenePose(seconds, pointer, reduced);
    room.style.transform = `translate3d(${pose.x.toFixed(2)}px,${pose.y.toFixed(2)}px,0) scale(${pose.scale.toFixed(4)}) rotateY(${pose.tilt.toFixed(3)}deg)`;
    room.style.filter = `brightness(${pose.light.toFixed(4)})`;
  };
  const tick = (now) => {
    frame = null;
    if (reduced || document.hidden) return;
    if (lastTime !== null && now - lastTime < 1000 / 30) { frame = requestAnimationFrame(tick); return; }
    const delta = lastTime === null ? 0 : Math.min((now - lastTime) / 1000, .08);
    lastTime = now;
    // Keep the settings dialog still while the user makes a choice.
    if (!help.open && root.dataset.renderMode !== 'three') {
      seconds += delta;
      const alpha = 1 - Math.exp(-delta * 3);
      pointer.x += (target.x - pointer.x) * alpha;
      pointer.y += (target.y - pointer.y) * alpha;
      draw();
    }
    frame = requestAnimationFrame(tick);
  };
  const resume = () => {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    lastTime = null;
    root.classList.toggle('scene-paused', document.hidden);
    if (!reduced && !document.hidden) frame = requestAnimationFrame(tick);
  };
  const resetPointer = () => { target.x = 0; target.y = 0; };
  const move = (event) => {
    if (event.pointerType !== 'mouse' || dragging || help.open || reduced) return;
    target.x = event.clientX / Math.max(window.innerWidth, 1) * 2 - 1;
    target.y = event.clientY / Math.max(window.innerHeight, 1) * 2 - 1;
  };
  const down = () => { dragging = true; resetPointer(); };
  const up = () => { dragging = false; resetPointer(); };
  const handlers = choices.map(button => {
    const handler = () => selection.select(button.dataset.sceneChoice);
    button.addEventListener('click', handler);
    return [button, handler];
  });
  window.addEventListener('pointermove', move, { passive: true });
  window.addEventListener('pointerdown', down, { passive: true });
  window.addEventListener('pointerup', up, { passive: true });
  window.addEventListener('blur', up);
  document.documentElement.addEventListener('pointerleave', resetPointer);
  document.addEventListener('visibilitychange', resume);
  selection.restore();
  draw();
  resume();
  return {
    selection,
    setReducedMotion(value) { reduced = value; pointer.x = pointer.y = 0; resetPointer(); draw(); resume(); },
    dispose() {
      selection.request += 1;
      if (frame !== null) cancelAnimationFrame(frame);
      for (const timer of removals) clearTimeout(timer);
      handlers.forEach(([button, handler]) => button.removeEventListener('click', handler));
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerdown', down);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('blur', up);
      document.documentElement.removeEventListener('pointerleave', resetPointer);
      document.removeEventListener('visibilitychange', resume);
    },
  };
}
