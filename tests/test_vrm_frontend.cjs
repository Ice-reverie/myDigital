const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function frontend() {
  const element = () => ({
    handlers: {}, attributes: {},
    classList: { toggle() {} },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, handler) { this.handlers[name] = handler; },
    querySelectorAll() { return []; }, scrollIntoView() {},
    children: [], appendChild(child) { this.children.push(child); child.parent = this; }, remove() { this.parent.children = this.parent.children.filter(child => child !== this); }, replaceChildren() { this.children = []; }, focus() {}, disabled: false,
  });
  const elements = new Map();
  const service = { ...element(), dataset: { service: '预约门诊' } };
  const classes = new Set();
  const sandbox = {
    document: {
      querySelectorAll() { return [service]; },
      documentElement: { classList: { toggle(name, force) {
        if (force !== undefined) { if (force) classes.add(name); else classes.delete(name); return force; }
        if (classes.has(name)) { classes.delete(name); return false; }
        classes.add(name); return true;
      } } },
      getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
      createElement: element,
    },
    window: {}, console: { warn() {}, error() {} },
    THREE: { WebGLRenderer: class { constructor() { throw new Error('No WebGL'); } } },
    fetch: async () => ({ ok: true, json: async () => ({ tts_available: false }) }),
    performance: { now: () => 500 },
    SpeechSynthesisUtterance: class { constructor(text) { this.text = text; } },
    atob: (value) => Buffer.from(value, 'base64').toString('binary'),
    setTimeout, clearTimeout, AbortController,
  };
  const context = vm.createContext(sandbox);
  const source = fs.readFileSync(path.join(__dirname, '../vrm_demo/static/js/VRMCharacter.js'), 'utf8');
  // Browser imports are the only substitution; the real startup and handlers run.
  vm.runInContext(source.replace(/^import .*;\r?\n/gm, ''), context);
  return { context, sandbox, elements, service, classes, run: (code) => vm.runInContext(code, context) };
}

// Real Three.js sampling, with a deterministic speech clock and a tiny rig.
async function replyMotionFixture() {
  const f = frontend();
  f.sandbox.testThree = require('three');
  f.run(`THREE=testThree;
    testBone=new THREE.Object3D();testBone.name='MotionTestBone';
    currentVrm={scene:new THREE.Group(),expressionManager:{expressions:[],getValue(){return 0},setValue(){}}};
    currentVrm.scene.add(testBone);
    modelPose=[{name:'spine',node:testBone,rotation:testBone.quaternion.clone(),position:testBone.position.clone()}];
    clip=new THREE.AnimationClip('Explain_Gentle',10,[new THREE.VectorKeyframeTrack(testBone.uuid+'.position',[0,5,10],[0,0,0,1,0,0,0,0,0])]);
    createVRMAnimationClip=()=>clip;
    filteredSceneAnimation=()=>({expressionTracks:{preset:new Map(),custom:new Map()}});
    getAnimationCatalog=async()=>({explain:[{id:'explain_1',secondary:false}]});
    getSceneAnimation=async()=>({});
    updateIdle=()=>true;
    now=0;tick=delta=>{restoreModelPose();updateSceneAnimation(delta);};
    queueReplyMotion('explain',speechGeneration);`);
  await new Promise(resolve => setImmediate(resolve));
  return f;
}

test('reply gesture waits for actual browser speech start, including delayed TTS', async () => {
  const f = await replyMotionFixture();
  assert.equal(f.run('scenePlayback'), null);
  let utterance;
  f.sandbox.window.speechSynthesis = {speak(value){utterance=value;}};
  const playing = f.run("speakWithBrowser('正在讲解')");
  assert.equal(f.run('scenePlayback'), null, 'queued speech is not audible yet');
  utterance.onstart();
  assert.equal(f.run('scenePlayback.name'), 'explain');
  utterance.onend();
  await playing;
  f.run('endReplyMotion();tick(.34);');
  assert.equal(f.run('scenePlayback'), null);
});

test('Web Audio starts the gesture after decoding and uses the source playback clock', async () => {
  const f = await replyMotionFixture();
  let finishDecode, source;
  f.sandbox.makeSource=()=>{source={connect(){},disconnect(){},start(){},stop(){}};return source;};
  f.sandbox.decode=()=>new Promise(resolve=>{finishDecode=resolve;});
  f.run(`audioContext={state:'running',currentTime:7,destination:{},decodeAudioData:decode,
    createBufferSource:makeSource,createAnalyser(){return {connect(){},disconnect(){},frequencyBinCount:128};}};`);
  const playing=f.run("playSegments([{audio:'AQ==',text:'测试'}],'female',false)");
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.run('scenePlayback'),null);
  finishDecode({duration:2});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.run('scenePlayback.name'),'explain');
  f.run('audioContext.currentTime=8;tick(.34);');
  assert.equal(f.run('scenePlayback.elapsed'),1);
  f.run('audioContext.currentTime=12;');
  source.onended();await playing;
  assert.equal(f.run('replyMotion.elapsed'),2,'end callback delay is not counted as speech');
  f.run('endReplyMotion();tick(.34);');
  assert.equal(f.run('scenePlayback'),null);
});

test('speech clock drives long gestures, freezes through buffering, then returns to idle', async () => {
  const f = await replyMotionFixture();
  f.run('token=startReplyMotionSegment(speechGeneration,()=>now);now=4;tick(.34);');
  assert.equal(f.run('scenePlayback.elapsed'), 4);
  assert.ok(Math.abs(f.run('testBone.position.x') - .8) < 1e-6);
  f.run('now=12;tick(.01);'); // Delayed rendering must still follow audio time.
  assert.equal(f.run('scenePlayback.elapsed'), 2, '10-second clip loops while speech continues');
  f.run('finishReplyMotionSegment(token);now=40;tick(.34);');
  assert.equal(f.run('scenePlayback.elapsed'), 2, 'buffering does not consume gesture time');
  assert.equal(f.run('testBone.position.x'), 0, 'buffering eases into idle');
  f.run('now=0;token=startReplyMotionSegment(speechGeneration,()=>now);now=3;tick(.34);');
  assert.equal(f.run('scenePlayback.elapsed'), 5, 'next sentence continues cumulative audio time');
  f.run('endReplyMotion();tick(.17);');
  assert.ok(f.run('testBone.position.x') > 0 && f.run('testBone.position.x') < 1);
  f.run('tick(.17);');
  assert.equal(f.run('scenePlayback'), null);
  assert.equal(f.run('testBone.position.x'), 0);
});

test('interruptions and late animation loads cannot restart a completed reply gesture', async () => {
  const f = await replyMotionFixture();
  f.run('token=startReplyMotionSegment(speechGeneration,()=>now);now=4;tick(.34);stopCurrentSpeech();tick(.34);');
  assert.equal(f.run('replyMotion'), null);
  assert.equal(f.run('scenePlayback'), null);
  f.run(`getSceneAnimation=()=>new Promise(resolve=>lateMotion=resolve);
    queueReplyMotion('explain',speechGeneration);`);
  await new Promise(resolve => setImmediate(resolve));
  f.run('startReplyMotionSegment(speechGeneration,()=>0);endReplyMotion();lateMotion({});');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.run('scenePlayback'), null);
});

test('text-only replies and reduced motion never start a speech gesture', async () => {
  const f = await replyMotionFixture();
  f.run('fetchSpeechPart=async part=>part;');
  const result = await f.run("playReplySegments([{text:'仅显示文字'}],{},speechGeneration)");
  assert.equal(result.failed, 1);
  assert.equal(f.run('replyMotion'), null);
  assert.equal(f.run('scenePlayback'), null);
  f.run("motionReduced=true;queueReplyMotion('explain',speechGeneration);startReplyMotionSegment(speechGeneration,()=>0);");
  assert.equal(f.run('replyMotion'), null);
  assert.equal(f.run('scenePlayback'), null);
});

test('large text toggles reversibly with an accessible pressed state', () => {
  const f = frontend();
  const button = f.elements.get('font-size-btn');
  button.handlers.click();
  assert.ok(f.classes.has('large-text'));
  assert.equal(button.attributes['aria-pressed'], 'true');
  button.handlers.click();
  assert.equal(f.classes.has('large-text'), false);
  assert.equal(button.attributes['aria-pressed'], 'false');
});

test('full-body framing fits both portrait and landscape without excessive empty space', () => {
  for (const aspect of [0.4, 1, 2]) {
    const f = frontend();
    f.run(`THREE.Vector3 = class {};
      THREE.MathUtils = {degToRad: (degrees) => degrees * Math.PI / 180};
      avatarBounds = {
        getSize() { return {x:0.7, y:1.7, z:0.3}; },
        getCenter() { return {x:0, y:0.85, z:0}; },
      };
      camera = { fov:30, aspect:${aspect}, position:{set(x,y,z){this.x=x;this.y=y;this.z=z;}}, updateProjectionMatrix(){} };
      controls = { target:{copy(value){Object.assign(this,value);}}, update(){} };
      fitAvatar();`);
    const camera = f.run('camera');
    const nearestDepth = camera.position.z - 0.15;
    const visibleHeight = 2 * nearestDepth * Math.tan(Math.PI / 12);
    const occupancy = Math.max(1.7 / visibleHeight, 0.7 / (visibleHeight * aspect));
    assert.ok(occupancy <= 1 && occupancy > 0.85);
    assert.equal(camera.position.y, 0.85);
    assert.ok(f.run('controls.minDistance') < camera.position.z * 0.5);
    const fullBodyDistance = camera.position.z;
    f.run('camera.position.z = controls.minDistance; fitAvatar();');
    assert.equal(camera.position.z, fullBodyDistance);
  }
});

test('service entry sends the intended request without requiring typing', () => {
  const f = frontend();
  let request;
  f.sandbox.captureRequest = (value, newService) => { request = { value, newService }; };
  f.run('sendMessage = captureRequest;');
  f.service.handlers.click();
  assert.deepEqual(request, { value: '预约门诊', newService: true });
});

test('missing and undecodable sentences fall back in order without repeating successful audio', async () => {
  const f = frontend();
  const events = [];
  f.sandbox.window.speechSynthesis = {
    speak(utterance) {
      events.push(`speech:${utterance.text}`);
      utterance.onstart();
      setTimeout(() => { events.push(`end:${utterance.text}`); utterance.onend(); }, 5);
    },
  };
  f.sandbox.record = (value) => events.push(value);
  f.run(`audioContext = {
    state: 'running',
    async decodeAudioData(bytes) { if (new Uint8Array(bytes)[0] === 0) throw Error('bad MP3'); return {}; },
  };
  playAudioWithVisemes = async () => { record('audio'); };`);
  const result = await f.run(`playSegments([
    { text: 'first', audio: 'AQ==' },
    { text: 'second', audio: '' },
    { text: 'third', audio: 'AA==' },
    { text: 'fourth', audio: 'AQ==' },
  ])`);
  assert.deepEqual(events, ['audio', 'speech:second', 'end:second', 'speech:third', 'end:third', 'audio']);
  assert.equal(result.played, 4);
  assert.equal(result.failed, 0);
  assert.equal(f.run('speaking || browserSpeaking'), false);
});

test('all audio failures use browser speech and absence of both reports failure', async () => {
  const f = frontend();
  f.run(`audioContext = { state: 'running', async decodeAudioData() { throw Error('decode'); } };`);
  let spoken = 0;
  f.sandbox.window.speechSynthesis = { speak(u) { spoken++; u.onstart(); u.onend(); } };
  assert.equal((await f.run(`playSegments([{text:'fallback', audio:'AA=='}])`)).played, 1);
  assert.equal(spoken, 1);
  delete f.sandbox.window.speechSynthesis;
  assert.equal((await f.run(`playSegments([{text:'unavailable', audio:'AA=='}])`)).failed, 1);
});

test('sending consecutive messages restarts speech after stopping the previous reply', async () => {
  const f=frontend(); const spoken=[];
  f.sandbox.window.speechSynthesis={cancel(){},speak(u){spoken.push(u.text);u.onstart();u.onend();}};
  f.sandbox.fetch=async()=>({ok:true,json:async()=>({reply:'新的回复',context:{},segments:[{text:'新的回复'}]})});
  f.run('handleAction=()=>{};');
  await f.run("sendMessage('你好')");
  await f.run("sendMessage('再说一次')");
  assert.deepEqual(spoken,['新的回复','新的回复']);
  assert.equal(f.run('playbackStopped || speaking || browserSpeaking'),false);
});

test('3D room and avatar share depth and projection while their lighting uses separate passes', () => {
  const f = frontend();
  const passes = [];
  let clears = 0;
  f.sandbox.testThree = require('three');
  f.sandbox.recordPass = (mask, background, autoClear) => passes.push({ mask, background, autoClear });
  f.sandbox.recordClear = () => { clears += 1; };
  f.run(`
    THREE = testThree;
    camera = new THREE.PerspectiveCamera();
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0xeaf3fa);
    const savedBackground = scene.background;
    renderer = { clear: recordClear, render(s,c) { recordPass(c.layers.mask, Boolean(s.background), this.autoClear); } };
    hospitalRenderMode = 'three';
    renderHospitalFrame();
  `);
  assert.equal(clears, 1);
  assert.deepEqual(passes, [
    {mask: 2, background: true, autoClear: false},
    {mask: 1, background: false, autoClear: false},
  ]);
  assert.equal(f.run('scene.background === savedBackground'), true);
  f.run("hospitalRenderMode = 'image'; scene.background = null; renderHospitalFrame();");
  assert.deepEqual(passes.at(-1), {mask: 1, background: false, autoClear: true});
});

test('3D eye-level view keeps the whole avatar clear of desktop and mobile controls', () => {
  for (const [width, height, dock] of [[1374,1063,540], [1078,815,490], [390,780,290], [320,632,315]]) {
    const f = frontend();
    f.sandbox.testThree = require('three');
    Object.assign(f.elements.get('stage'), {clientWidth:width,clientHeight:height});
    f.sandbox.document.querySelector = () => ({getBoundingClientRect:()=>({height:dock})});
    f.run(`
      THREE = testThree;
      camera = new THREE.PerspectiveCamera(30, ${width/height}, .1, 80);
      avatarBounds = new THREE.Box3(new THREE.Vector3(-.3,0,-.15),new THREE.Vector3(.3,1.7,.15));
      controls = {target:new THREE.Vector3(), update(){camera.lookAt(this.target); camera.updateMatrixWorld();}};
      fitHospitalView();
    `);
    const head = f.run('new THREE.Vector3(0,1.7,0).project(camera).y');
    const foot = f.run('new THREE.Vector3(0,0,0).project(camera).y');
    const headY = (1-head)*height/2, footY = (1-foot)*height/2;
    const top = width <=760 ?165:36;
    const bottom = width <=760 ?dock+72:50;
    assert.ok(headY >= top-12, `${width}: head at ${headY}`);
    assert.ok(footY <= height-bottom+12, `${width}: feet at ${footY}`);
    assert.ok(footY > headY && f.run('controls.minDistance < controls.maxDistance'));
    assert.ok(f.run('camera.position.y > 1.7 * .85 && camera.position.y < 1.7 * .95'), 'viewer is near eye height');
    assert.ok(f.run('Math.abs(camera.getWorldDirection(new THREE.Vector3()).y) < 1e-10'), 'level optical axis');
    // At the viewer\'s eye height, points at different depths share the same
    // screen height. This catches waist-height framing disguised with a tilt.
    assert.ok(f.run(`Math.abs(new THREE.Vector3(0,camera.position.y,-3).project(camera).y
      - new THREE.Vector3(0,camera.position.y,0).project(camera).y) < 1e-10`));
    f.run('camera.position.set(1,.5,2); controls.target.set(.2,.8,0); fitHospitalView();');
    assert.ok(f.run('Math.abs(camera.getWorldDirection(new THREE.Vector3()).y) < 1e-10'), 'reset restores eye-level perspective');
  }
});

test('growing service controls reframe the 3D avatar even when canvas size stays fixed', () => {
  const f = frontend();
  let notify;
  let dockHeight = 280;
  const values = {};
  f.sandbox.ResizeObserver = class { constructor(callback) { notify = callback; } observe() {} };
  f.sandbox.document.querySelector = () => ({getBoundingClientRect:()=>({height:dockHeight})});
  f.sandbox.document.documentElement.style = {setProperty:(name,value)=>{values[name]=value;}};
  f.run('reframes=0; fitAvatar=()=>reframes++; bindUI(); hospitalRenderMode="three"');
  notify();
  dockHeight = 365;
  notify();
  assert.equal(values['--dock-height'], '365px');
  assert.equal(f.run('reframes'), 2);
  f.run('hospitalRenderMode="image"');
  notify();
  assert.equal(f.run('reframes'), 2);
});

function roomFrontend() {
  const f = frontend();
  f.sandbox.testThree = require('three');
  f.sandbox.document.documentElement.dataset = {};
  f.sandbox.document.getElementById('scene-status').textContent = '';
  f.run(`THREE=testThree; scene=new THREE.Scene(); renderer={}; resizeStage=()=>{};
    hospitalSceneCatalog={waiting3d:{name:'候诊区',comparison:'waiting'},guidance3d:{name:'智慧导诊',comparison:'guidance'},waiting:{comparison:'waiting3d'}};`);
  return f;
}

test('late 3D room loads remain hidden after a newer scene wins and reuse their cache', async () => {
  const f = roomFrontend();
  let finishWaiting, finishGuidance, loads = 0;
  f.sandbox.loadWaiting = () => {loads++; return new Promise(resolve => {finishWaiting=resolve;});};
  f.sandbox.loadGuidance = () => new Promise(resolve => {finishGuidance=resolve;});
  f.run('hospitalRoomLoaders.waiting3d=loadWaiting; hospitalRoomLoaders.guidance3d=loadGuidance; selectedHospitalId="waiting3d"');
  const first = f.run('syncHospitalRenderer()');
  f.run('selectedHospitalId="guidance3d"');
  const second = f.run('syncHospitalRenderer()');
  const THREE = require('three');
  const waiting = {group:new THREE.Group(),floorY:0}, guidance = {group:new THREE.Group(),floorY:0};
  finishGuidance(guidance); await second;
  finishWaiting(waiting); await first;
  assert.equal(guidance.group.visible, true);
  assert.equal(waiting.group.visible, false);
  assert.equal(f.run('activeHospitalRoom'), guidance);
  assert.match(f.elements.get('scene-status').textContent, /智慧导诊/);
  f.run('selectedHospitalId="waiting3d"'); await f.run('syncHospitalRenderer()');
  assert.equal(loads, 1);
  assert.equal(waiting.group.visible, true);
  assert.equal(guidance.group.visible, false);
  f.run('selectedHospitalId="waiting"'); await f.run('syncHospitalRenderer()');
  assert.equal(waiting.group.visible, false);
  assert.equal(f.run('hospitalRenderMode'), 'image');
  assert.equal(f.elements.get('scene-compare-btn').textContent, '查看3D场景');
});

test('failed 3D loads report the fallback and allow retry; unavailable WebGL never reports success', async () => {
  const f = roomFrontend();
  f.sandbox.failedRoom = () => Promise.reject(new Error('module unavailable'));
  f.run('hospitalRoomLoaders.waiting3d=failedRoom; selectedHospitalId="waiting3d"');
  await f.run('syncHospitalRenderer()');
  assert.equal(f.run('hospitalRenderMode'), 'image');
  assert.equal(f.run('hospitalRoomPromises.has("waiting3d")'), false);
  assert.match(f.elements.get('scene-status').textContent, /再次选择/);
  f.sandbox.loadedRoom = {group:new (require('three').Group)(),floorY:0};
  f.run('hospitalRoomLoaders.waiting3d=()=>Promise.resolve(loadedRoom)');
  await f.run('syncHospitalRenderer()');
  assert.equal(f.run('hospitalRenderMode'), 'three');
  f.run('selectedHospitalId="guidance3d"; renderer=null');
  await f.run('syncHospitalRenderer()');
  assert.equal(f.run('hospitalRenderMode'), 'image');
  assert.match(f.elements.get('scene-status').textContent, /3D渲染暂不可用/);
});

test('chat shows text and unlocks controls before speech synthesis finishes', async () => {
  const f = frontend();
  let finishSpeech;
  const requests = [];
  f.sandbox.fetch = (url, options) => {
    requests.push({url, body: JSON.parse(options.body)});
    if (url === '/api/chat') return Promise.resolve({ok:true, json:async()=>({
      reply:'文字先到了。', action:null, context:{}, segments:[{text:'文字先到了。'}]
    })});
    return new Promise(resolve => { finishSpeech = resolve; });
  };
  f.run('handleAction=()=>{}');
  const pending = f.run("sendMessage('你好')");
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.elements.get('send-btn').disabled, false);
  assert.equal(f.elements.get('history-messages').children.length, 3);
  assert.equal(requests[0].body.include_audio, false);
  assert.equal('history' in requests[0].body, false);
  assert.equal(requests[1].url, '/api/tts');
  finishSpeech({ok:true, json:async()=>({segments:[{text:'文字先到了。'}]})});
  await pending;
});

test('next sentence starts synthesizing while the current sentence plays', async () => {
  const f = frontend();
  let finishSecond;
  const requests = [];
  let utterance;
  f.sandbox.window.speechSynthesis = {cancel(){}, speak(value){utterance=value; value.onstart();}};
  f.sandbox.fetch = (url, options) => {
    requests.push(JSON.parse(options.body).text);
    if (requests.length === 1) return Promise.resolve({ok:true, json:async()=>({segments:[{text:'第一句'}]})});
    return new Promise(resolve => {finishSecond = resolve;});
  };
  const pending = f.run("playReplySegments([{text:'第一句'},{text:'第二句'}],{voice_gender:'female'},speechGeneration)");
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(requests, ['第一句', '第二句']);
  assert.equal(utterance.text, '第一句');
  finishSecond({ok:true, json:async()=>({segments:[{text:'第二句'}]})});
  utterance.onend();
  await new Promise(resolve => setImmediate(resolve));
  utterance.onend();
  const result = await pending;
  assert.equal(result.played, 2);
  assert.equal(result.failed, 0);
});

test('retry resends the failed request without duplicating the user message', async () => {
  const f = frontend();
  const chatBodies = [];
  f.sandbox.fetch = (url, options) => {
    if (url === '/api/tts') return Promise.resolve({ok:true, json:async()=>({segments:[{text:'好的'}]})});
    chatBodies.push(JSON.parse(options.body));
    if (chatBodies.length === 1) return Promise.reject(Error('offline'));
    return Promise.resolve({ok:true, json:async()=>({reply:'好的', context:{}, segments:[{text:'好的'}]})});
  };
  f.run('handleAction=()=>{}');
  await f.run("sendMessage('预约门诊', true)");
  const retry = f.elements.get('quick-replies').children[0];
  assert.equal(retry.textContent, '重新尝试');
  await retry.handlers.click();
  assert.deepEqual(chatBodies.map(body => body.text), ['预约门诊', '预约门诊']);
  assert.deepEqual(chatBodies.map(body => body.context), [{}, {}]);
  assert.equal(f.elements.get('history-messages').children.length, 4);
});

test('cancelled old speech cannot unlock a newer chat request', async () => {
  const f = frontend();
  let secondChat;
  let chats = 0;
  f.sandbox.fetch = (url, options) => {
    if (url === '/api/chat') {
      chats++;
      if (chats === 2) return new Promise(resolve => {secondChat = resolve;});
      return Promise.resolve({ok:true, json:async()=>({reply:'第一条回复', context:{}, segments:[{text:'第一句'}]})});
    }
    if (chats === 1) return new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(Error('aborted')));
    });
    return Promise.resolve({ok:true, json:async()=>({segments:[{text:'第二句'}]})});
  };
  f.run('handleAction=()=>{}');
  const old = f.run("sendMessage('第一条')");
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.elements.get('send-btn').disabled, false);
  const current = f.run("sendMessage('第二条')");
  await old;
  assert.equal(f.elements.get('send-btn').disabled, true);
  secondChat({ok:true, json:async()=>({reply:'第二条回复', context:{}, segments:[{text:'第二句'}]})});
  await current;
  assert.equal(f.elements.get('send-btn').disabled, false);
});

test('cancelled browser speech settles without callbacks and late events cannot stop a new reply', async () => {
  const f=frontend();const utterances=[];
  f.sandbox.window.speechSynthesis={cancel(){},speak(u){utterances.push(u);u.onstart();}};
  const old=f.run("playSegments([{text:'旧句'},{text:'不得播报'}])");
  f.run('stopCurrentSpeech();');
  const fresh=f.run("playSegments([{text:'新句'}])");
  utterances[0].onend();utterances[0].onstart();
  assert.equal(f.run('speaking && browserSpeaking'),true);
  utterances[1].onend();
  assert.equal((await old).played,0);
  assert.equal((await fresh).played,1);
  assert.deepEqual(utterances.map(u=>u.text),['旧句','新句']);
});

test('stale audio decoding cannot play or clear a replacement reply', async () => {
  const f=frontend();let release;const utterances=[];
  f.sandbox.decodePending=new Promise(resolve=>{release=resolve;});
  f.sandbox.window.speechSynthesis={cancel(){},speak(u){utterances.push(u);u.onstart();}};
  f.run("audioContext={state:'running',decodeAudioData(){return decodePending;}}; playAudioWithVisemes=()=>{throw Error('stale audio must not start');};");
  const old=f.run("playSegments([{audio:'AQ==',text:'旧音频'}])");
  await new Promise(resolve=>setImmediate(resolve));
  f.run('stopCurrentSpeech();');
  const fresh=f.run("playSegments([{text:'新回复'}])");
  release({});await old;
  assert.equal(f.run('speaking && browserSpeaking'),true);
  assert.deepEqual(utterances.map(u=>u.text),['新回复']);
  utterances[0].onend();await fresh;
});

test('stopped Web Audio settles and its late end event preserves newer visemes', async () => {
  const f=frontend();const sources=[];
  f.sandbox.makeSource=()=>{const s={connect(){},disconnect(){},start(){},stop(){}};sources.push(s);return s;};
  f.run("audioContext={currentTime:0,destination:{},createBufferSource:makeSource,createAnalyser(){return {connect(){},disconnect(){},frequencyBinCount:128};}};");
  const old=f.run('playAudioWithVisemes({},[])');
  f.run('stopCurrentSpeech();playbackStopped=false;');
  const fresh=f.run('playAudioWithVisemes({},[])');
  const current=f.run('currentVisemes');
  sources[0].onended();
  assert.equal(f.run('currentVisemes'),current);
  assert.equal(await old,false);
  sources[1].onended();assert.equal(await fresh,true);
  assert.equal(f.run('currentVisemes'),null);
});

test('browser speech errors resolve and clear the speaking state', async () => {
  const f = frontend();
  f.sandbox.window.speechSynthesis = { speak(u) { u.onstart(); u.onerror(); } };
  assert.equal(await f.run(`speakWithBrowser('failed')`), false);
  assert.equal(f.run('speaking || browserSpeaking'), false);
});

function avatar(f) {
  const values = {};
  f.sandbox.values = values;
  f.run(`currentVrm = {
    expressionManager: { setValue(name, value) { values[name] = value; } },
    humanoid: { getNormalizedBoneNode() { return null; } }, update() {},
  };`);
  return values;
}

test('no timeline uses energy; silence closes the mouth; expired cues do not linger', () => {
  const f = frontend();
  const values = avatar(f);
  f.run(`audioContext = { currentTime: 0.2 }; currentVisemes = {
    timeline: [], startTime: 0, lastIndex: -1, lastTarget: null, lastOpen: 0, smoothOpen: 0,
    analyser: { getByteTimeDomainData(samples) { samples.fill(180); } }, samples: new Uint8Array(16),
  }; updateAvatar(0.016);`);
  assert.ok(['aa', 'ih', 'ou', 'ee', 'oh'].some((v) => values[v] > 0));
  f.run(`currentVisemes.analyser.getByteTimeDomainData = (s) => s.fill(128);
    for (let i = 0; i < 80; i++) updateAvatar(0.016);`);
  assert.ok(['aa', 'ih', 'ou', 'ee', 'oh'].every((v) => (values[v] || 0) < 0.03));
  f.run(`currentVisemes.timeline = [{start:0, end:0.1, viseme:'aa'}]; updateAvatar(0.016);`);
  assert.ok(['aa', 'ih', 'ou', 'ee', 'oh'].every((v) => values[v] === 0));
});

test('browser speech animates the mouth and resets it on completion', async () => {
  const f = frontend();
  const values = avatar(f);
  let utterance;
  f.sandbox.window.speechSynthesis = { speak(u) { utterance = u; u.onstart(); } };
  const playback = f.run(`speakWithBrowser('hello')`);
  f.run('updateAvatar(0.016)');
  assert.ok(['aa', 'ih', 'ou', 'ee', 'oh'].some((v) => values[v] > 0));
  utterance.onend();
  assert.equal(await playback, true);
  assert.ok(['aa', 'ih', 'ou', 'ee', 'oh'].every((v) => values[v] === 0));
});


test('recent bubbles stay limited while history retains every message', () => {
  const f = frontend();
  f.run("addMessage('first', true); addMessage('reply', false); addMessage('second', true);");
  assert.equal(f.elements.get('messages').children.length, 2);
  assert.equal(f.elements.get('history-messages').children.length, 4);
  assert.equal(f.elements.get('messages').children[1].children[1].textContent, 'second');
});

test('motion control pauses ambient and avatar motion reversibly', () => {
  const f = frontend();
  const button = f.elements.get('motion-btn');
  button.handlers.click();
  assert.equal(f.run('motionReduced'), true);
  assert.ok(f.classes.has('motion-reduced'));
  assert.equal(button.attributes['aria-pressed'], 'true');
  button.handlers.click();
  assert.equal(f.run('motionReduced'), false);
  assert.equal(f.classes.has('motion-reduced'), false);
});

test('gaze input is bounded and centered for pointer tracking', () => {
  const f = frontend();
  f.run('setGazePointer(500, 250, 1000, 500)');
  assert.equal(f.run('gazePointer.x'), 0);
  assert.equal(f.run('gazePointer.y'), 0);
  f.run('setGazePointer(2000, -20, 1000, 500)');
  assert.equal(f.run('gazePointer.x'), 1);
  assert.equal(f.run('gazePointer.y'), -1);
});

test('idle sampling wraps at the loop boundary and reduced motion freezes its clock', () => {
  const f = frontend();
  assert.equal(f.run('idleSample(8, 8, 30).index'), 0);
  assert.equal(f.run('idleSample(7.99, 8, 30).index'), 239);
  f.run('idleAnimation = { duration:8, fps:30, time:2, tracks:[] }; motionReduced = true; updateIdle(.05)');
  assert.equal(f.run('idleAnimation.time'), 2);
  f.run('motionReduced = false; updateIdle(.05)');
  assert.equal(f.run('idleAnimation.time'), 2.05);
});

test('authored idle republishes held tracks, closes its loop and owns fingers', () => {
  const f=frontend();
  f.run(`samples=[];bone={quaternion:{fromArray(v){this.value=v[0]}}};face={weight:0};
    idleAnimation={authored:true,time:7.99,duration:8,sampler:{bindings:[
      {target:bone,property:'quaternion',interpolant:{evaluate(t){samples.push(t);return [.25,0,0,1]}}},
      {target:face,property:'weight',interpolant:{evaluate(){return [.12]}}}]}};
    idleHands=[{offset:{setFromAxisAngle(){throw Error('must not overwrite authored fingers')}}}];
    updateIdle(.02);updateIdleHands(.02);`);
  assert.ok(Math.abs(f.run('idleAnimation.time')-.01)<1e-10);
  f.run('bone.quaternion.value=9;face.weight=1;scenePlayback={};updateIdle(1);');
  assert.equal(f.run('bone.quaternion.value'),.25);
  assert.equal(f.run('face.weight'),.12);
  assert.ok(Math.abs(f.run('idleAnimation.time')-.01)<1e-10);
  f.run('scenePlayback=null;motionReduced=true;updateIdle(2);');
  assert.equal(f.run('samples.at(-1)'),0);
});

test('new idle loads reject stale avatars and safely fall back on failure', async () => {
  const f=frontend();
  f.run(`currentVrm={};modelLoadId=3;fallbacks=0;
    createIdleSampler=()=>({duration:8,bindings:[]});
    getIdleAnimation=()=>new Promise(resolve=>finishIdle=resolve);
    loadLegacyIdle=async()=>{fallbacks++};`);
  const stale=f.run('loadDefaultIdle({},currentVrm,3,false)');
  f.run('modelLoadId=4;finishIdle({});');await stale;
  assert.equal(f.run('idleAnimation'),null);
  f.run("getIdleAnimation=async()=>{throw Error('offline')};");
  await f.run('loadDefaultIdle({},currentVrm,4,false)');
  assert.equal(f.run('fallbacks'),1);
  f.run('getIdleAnimation=async()=>({});');
  await f.run('loadDefaultIdle({},currentVrm,4,false)');
  assert.equal(f.run('idleAnimation.authored'),true);
  assert.equal(f.run('idleAnimation.duration'),8);
});

test('authored idle pauses automatic face writers while live speech keeps its mouth', () => {
  const f=frontend();const values=avatar(f);
  f.run(`idleAnimation={authored:true,time:0,duration:8,sampler:{bindings:[]}};
    currentVrm.lookAt={target:{}};blinks=0;updateBlink=()=>blinks++;
    browserSpeaking=true;updateAvatar(.016);`);
  assert.ok(values.aa>0 || values.ih>0 || values.ou>0 || values.ee>0 || values.oh>0);
  assert.equal(f.run('blinks'),0);
  assert.equal(f.run('currentVrm.lookAt.target'),null);
  f.run('motionReduced=true;updateAvatar(.016);');
  assert.equal(f.run('blinks'),1);
});

test('ten-frame transitions blend expressions toward authored idle instead of zero', () => {
  const f=frontend();
  f.run(`face={weight:.12};currentVrm={expressionManager:{getValue(){return face.weight},setValue(n,v){face.weight=v}}};
    scenePlayback={elapsed:10-HEALTH_TRANSITION_SECONDS/2,duration:10,transition:HEALTH_TRANSITION_SECONDS,
      expressions:['happy'],fromExpressions:new Map([['happy',.12]]),bases:[],from:new Map(),
      bindings:[{target:face,proxy:{weight:.4},property:'weight'}]};
    mixer={update(){}};updateSceneAnimation(0);`);
  assert.ok(Math.abs(f.run('face.weight')-.26)<1e-10);
});

test('body clip timing follows elapsed seconds even when physics frames are capped', () => {
  const f=frontend();avatar(f);
  f.run(`steps=[];updateIdle=t=>{steps.push(['idle',t]);return true};
    updateSceneAnimation=t=>steps.push(['action',t]);
    currentVrm.update=t=>steps.push(['physics',t]);
    updateAvatar(.05,.4);`);
  assert.deepEqual(JSON.parse(f.run('JSON.stringify(steps)')),
    [['idle',.4],['action',.4],['physics',.05]]);
});

test('blinking closes then reopens both eyes and schedules the next blink', () => {
  const f = frontend();
  const values = avatar(f);
  f.run('nextBlinkAt = 100; updateBlink(100); updateBlink(220)');
  assert.equal(values.blink, 1);
  f.run('updateBlink(341)');
  assert.equal(values.blink, 0);
  assert.ok(f.run('nextBlinkAt') >= 2541);
});


test('each scene reply triggers a variant and honors reduced motion', () => {
  const f = frontend();
  f.run("currentVrm = {}; calls = []; playActionByName = name => calls.push(name); handleAction('booking'); handleAction('booking'); handleAction('confirm'); handleAction('booking');");
  assert.deepEqual(Array.from(f.run('calls')), ['booking','booking','confirm','booking']);
  f.run("motionReduced = true; handleAction('wink');");
  assert.equal(f.run('calls.length'), 4);
});

test('avatar settings fetch catalog and switch the selected model', async () => {
  const f=frontend();
  // Let the startup catalog fail before supplying the successful retry.
  await Promise.resolve(); await Promise.resolve();
  f.sandbox.fetch=async()=>({ok:true,json:async()=>[
    {id:'Lumine_companion',label:'默认',profile:'lumine'},
    {id:'Klee',label:'Klee',profile:'standard'}]});
  await f.run('loadAvatarCatalog()');
  assert.equal(f.elements.get('avatar-select').children.length,2);
  f.elements.get('avatar-select').value='Klee';
  f.run('loadVrm=(...args)=>switched=args');
  f.elements.get('switch-avatar-btn').handlers.click();
  assert.equal(f.run('switched[0]'),'/api/avatars/Klee');
  assert.equal(f.run('switched[3].profile'),'standard');
});

test('standard characters receive humanoid idle without Lumine raw bone tracks', async () => {
  const f=frontend();
  await Promise.resolve(); await Promise.resolve();
  f.sandbox.idleData=JSON.parse(fs.readFileSync(path.join(__dirname,'../models/animations/Lumine_idle.json')));
  f.run(`THREE.Quaternion=class {clone(){return this}};
    currentVrm={humanoid:{getNormalizedBoneNode(){return {quaternion:new THREE.Quaternion()}}}};
    modelLoadId=4;fetch=async()=>({ok:true,json:async()=>idleData});
    parser={getDependency(){throw Error('Must not bind Lumine raw bones')}};`);
  await f.run('loadDefaultIdle({parser},currentVrm,4,false)');
  assert.equal(f.run('idleAnimation.tracks.length'),16);
  assert.equal(f.run('idleAnimation.tracks.every(t=>!!t.bone)'),true);
});

test('original Lumine gets mouth and blink bindings once without overwriting existing presets', async () => {
  const f=frontend();
  f.run(`THREE.Quaternion=class {};
    VRMExpression=class {constructor(name){this.expressionName=name;this.binds=[]} addBind(b){this.binds.push(b)}};
    VRMExpressionMorphTargetBind=class {constructor(options){Object.assign(this,options)}};
    expressions={};face={morphTargetInfluences:Array(43).fill(0)};
    localVrm={scene:{traverse(){},add(){}},expressionManager:{getExpression(n){return expressions[n]},registerExpression(e){expressions[e.expressionName]=e}}};
    localGltf={parser:{json:{nodes:[{mesh:1}]},async getDependency(){return {traverse(fn){fn(face)}}}}};`);
  await f.run("adaptAvatar(localVrm,localGltf,'lumine')");
  assert.equal(f.run('expressions.aa.binds[0].index'),18);
  assert.equal(f.run('expressions.ee.binds[0].index'),22);
  assert.equal(f.run('expressions.blink.binds.length'),2);
  const first=f.run('expressions.aa');
  await f.run("adaptAvatar(localVrm,localGltf,'lumine')");
  assert.equal(f.run('expressions.aa'),first);
});

test('scene replies do not attach actions to the old avatar during switching', () => {
  const f=frontend();
  f.run("currentVrm={};avatarLoading=true;calls=0;playActionByName=()=>calls++;handleAction('greet');");
  assert.equal(f.run('calls'),0);
  f.run("avatarLoading=false;handleAction('greet');");
  assert.equal(f.run('calls'),1);
});

test('idle finger offsets stay bounded, do not accumulate and freeze to a relaxed pose', () => {
  const f=frontend();
  f.run(`class FingerQ { constructor(v=0){this.v=v} copy(q){this.v=q.v;return this} multiply(q){this.v+=q.v;return this} setFromAxisAngle(a,v){this.v=v;return this} }
    finger={quaternion:new FingerQ()};
    idleHands=[{node:finger,rest:new FingerQ(.2),axis:{},angle:.15,amplitude:.015,phase:.4,speed:.8,offset:new FingerQ()}];
    valuesSeen=[];
    for(let i=0;i<1800;i++){updateIdleHands(1/60);valuesSeen.push(finger.quaternion.v);}`);
  const values=Array.from(f.run('valuesSeen'));
  assert.ok(Math.min(...values)>=.335-1e-9 && Math.max(...values)<=.365+1e-9);
  f.run('motionReduced=true;frozenTime=handIdleTime;updateIdleHands(1);');
  assert.ok(Math.abs(f.run('finger.quaternion.v')-.35)<1e-9);
  assert.equal(f.run('handIdleTime'),f.run('frozenTime'));
  f.run('idleHands=[];updateIdleHands(.016);');
});

test('reference hand loop is bounded and has continuous position and velocity at every key', () => {
  const f=frontend(), sample=t=>f.run(`sampleHandIdle(${t})`);
  const period=f.run('HAND_IDLE_CYCLE'), count=f.run('HAND_IDLE_KEYS.length'), epsilon=1e-5;
  for(let i=0;i<=count;i++) {
    const t=i*period/count, at=sample(t);
    assert.ok(Math.abs(sample(t+period)-at)<1e-10);
    const before=(at-sample(t-epsilon))/epsilon, after=(sample(t+epsilon)-at)/epsilon;
    assert.ok(Math.abs(before-after)<.003, `velocity jump at key ${i}`);
  }
  for(let i=0;i<2000;i++) assert.ok(Math.abs(sample(i*period/2000))<=1+1e-10);
});

test('wrist motion preserves body idle and stays bounded over repeated frames', () => {
  const f=frontend();
  f.run(`class WristQ {constructor(v=0){this.v=v} multiply(q){this.v+=q.v;return this} setFromAxisAngle(a,v){this.v=v;return this}}
    wrist={quaternion:new WristQ()};
    idleHands=[{node:wrist,wrist:true,axis:{},swayAxis:{},angle:.05,amplitude:.03,phase:0,sway:.014,offset:new WristQ(),lateral:new WristQ()}];
    wristValues=[];
    for(let i=0;i<1800;i++){wrist.quaternion.v=.2;updateIdleHands(1/60);wristValues.push(wrist.quaternion.v);}`);
  assert.ok(Array.from(f.run('wristValues')).every(v=>v>=.206-1e-9 && v<=.294+1e-9));
  f.run('motionReduced=true;wrist.quaternion.v=.2;updateIdleHands(1);');
  assert.ok(Math.abs(f.run('wrist.quaternion.v')-.25)<1e-10);
});

test('scene animation samples overwrite idle fingers while its exit blends to relaxed fingers', () => {
  const f=frontend();
  f.run(`class Q {constructor(v=0){this.v=v}copy(q){this.v=q.v;return this} slerp(q,t){this.v+=(q.v-this.v)*t;return this}}
    fingerNode={quaternion:new Q(),position:{copy(){return this},lerp(){return this}}};
    currentVrm={expressionManager:{getValue(){return 0}}};
    mixer={update(){}};activeAction={};
    scenePlayback={elapsed:1,duration:3,name:'greet',expressions:[],secondary:[],
      bindings:[{target:fingerNode,proxy:{quaternion:new Q(.8)},property:'quaternion'}],
      bases:[{name:'leftIndexProximal',node:fingerNode,baseRotation:new Q(),basePosition:{copy(){}}}],
      from:new Map([['leftIndexProximal',{rotation:new Q(.15),position:{}}]])};
    fingerNode.quaternion.v=.15;updateSceneAnimation(.016);`);
  assert.equal(f.run('fingerNode.quaternion.v'),.8);
  f.run('scenePlayback.elapsed=2.85;fingerNode.quaternion.v=.15;updateSceneAnimation(0);');
  assert.ok(Math.abs(f.run('fingerNode.quaternion.v')-.475)<1e-8);
});

test('outdated avatar downloads are disposed and failed selection keeps the previous model', async () => {
  const f=frontend();
  f.run(`renderer={};currentVrm={id:'previous'};currentAvatarId='Klee';downloads=[];disposed=[];
    stopSceneAnimation=()=>{};VRMLoaderPlugin=class {};
    VRMUtils={deepDispose(s){disposed.push(s)}};
    GLTFLoader=class {register(){} load(...args){downloads.push(args)}};
    loadVrm('/api/avatars/Anaxa','Anaxa',()=>{},{profile:'standard',id:'Anaxa'});
    loadVrm('/api/avatars/Ratio','Ratio',()=>{},{profile:'standard',id:'Ratio'});`);
  await f.run("downloads[0][1]({scene:'old-download'})");
  assert.deepEqual(Array.from(f.run('disposed')),['old-download']);
  assert.equal(f.run('currentVrm.id'),'previous');
  f.run("downloads[1][3](Error('missing'))");
  assert.equal(f.run('currentVrm.id'),'previous');
  assert.equal(f.run('avatarLoading'),false);
  assert.equal(f.elements.get('avatar-select').value,'Klee');
});

test('random variants exclude the last played version and support a single asset', () => {
  const f = frontend();
  f.run("variants = [1,2,3].map(n => ({id:'explain_'+n})); Math.random = () => 0;");
  assert.equal(f.run("chooseVariant('explain',variants).id"), 'explain_1');
  f.run("lastVariant.set('explain','explain_1')");
  assert.equal(f.run("chooseVariant('explain',variants).id"), 'explain_2');
  f.run('Math.random = () => .999');
  assert.equal(f.run("chooseVariant('explain',variants).id"), 'explain_3');
  assert.equal(f.run("chooseVariant('explain',[variants[0]]).id"), 'explain_1');
  assert.throws(() => f.run("chooseVariant('explain',[])"));
});

test('repeated explain replies play both variants and stale loads do not change history', async () => {
  const f = frontend();
  f.run(`currentVrm = {}; played = []; Math.random = () => 0;
    catalogPromise = Promise.resolve({explain:[{id:'explain_1',secondary:false},{id:'explain_2',secondary:false}]});
    getSceneAnimation = async (name,id) => ({id});
    playVrmAnimation = animation => { played.push(animation.id); scenePlayback = {}; };`);
  for (let i=0;i<4;i++) await f.run("playActionByName('explain')");
  assert.deepEqual(Array.from(f.run('played')), ['explain_1','explain_2','explain_1','explain_2']);
  f.run('getSceneAnimation = () => new Promise(resolve => finishOld = resolve)');
  const stale = f.run("playActionByName('explain')");
  await Promise.resolve();
  f.run("modelLoadId++; lastVariant.clear(); finishOld({id:'explain_1'});");
  await stale;
  assert.equal(f.run('lastVariant.size'), 0);
  assert.equal(f.run('played.length'), 4);
});

test('catalog requests are shared, reject unknown variant paths and retry failures', async () => {
  const f = frontend();
  f.run("catalogData = Object.fromEntries(Object.keys(ACTION_LABELS).map(n => [n,[{id:n+'_1',secondary:false}]])); requests=0; fetch=async()=>{requests++; return {ok:true,json:async()=>catalogData};};");
  const a = f.run('getAnimationCatalog()'), b = f.run('getAnimationCatalog()');
  assert.equal(a,b);
  await a;
  assert.equal(f.run('requests'), 1);
  f.run("catalogPromise=null; catalogData.explain[0].id='../characters/avatar';");
  await assert.rejects(f.run('getAnimationCatalog()'));
  f.run("catalogData.explain[0].id='explain_2';");
  assert.equal((await f.run('getAnimationCatalog()')).explain[0].id, 'explain_2');
});

test('numbered body resources have independent caches', async () => {
  const f = frontend();
  f.run('loads=[]; createAnimationLoader=()=>({load(...a){loads.push(a);}});');
  const a=f.run("getSceneAnimation('explain','explain_1')");
  const b=f.run("getSceneAnimation('explain','explain_2')");
  assert.equal(f.run('loads[0][0]'), '/api/animations/explain/explain_1');
  assert.equal(f.run('loads[1][0]'), '/api/animations/explain/explain_2');
  f.run('loads.forEach(a=>a[1]({userData:{vrmAnimations:[{}]}}))');
  await Promise.all([a,b]);
  await assert.rejects(f.run("getSceneAnimation('explain','greet_1')"));
});

test('seven-second explain secondary tracks use their own timeline and return to neutral', () => {
  const f = frontend();
  f.sandbox.explainCloth = JSON.parse(fs.readFileSync(path.join(__dirname,'../models/animations/legacy/explain_2.secondary.json')));
  assert.equal(f.run('validateGreetSecondary(explainCloth).tracks.length'), 49);
  f.run(`defaultAvatar=true; sampleIndex=-1;
    q={clone(){return this},fromArray(a,i){sampleIndex=i;return this},slerp(){return this},multiply(){return this}};
    state={name:'explain',elapsed:7,secondary:[{values:explainCloth.tracks[0].values,fps:24,target:{quaternion:q},current:q,next:q}]};
    updateGreetSecondary(state);`);
  assert.equal(f.run('sampleIndex'),168*4);
});

test('secondary sleeve and twist bones fade with the body during speech gaps', () => {
  const f=frontend();f.sandbox.testThree=require('three');
  f.run(`THREE=testThree;defaultAvatar=true;
    target={quaternion:new THREE.Quaternion()};
    rotation=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),Math.PI/3).toArray();
    state={elapsed:.5,secondary:[{values:[...rotation,...rotation],fps:1,target,current:new THREE.Quaternion(),next:new THREE.Quaternion()}]};
    updateGreetSecondary(state,.5);`);
  assert.ok(Math.abs(f.run('target.quaternion.angleTo(new THREE.Quaternion())')-Math.PI/6)<1e-6);
  f.run('clearGreetSecondary();updateGreetSecondary(state,0);');
  assert.equal(f.run('target.quaternion.angleTo(new THREE.Quaternion())'),0);
});

test('late scene loads and previous-model loads cannot replace current actions', async () => {
  const f = frontend();
  f.run("currentVrm = {}; played = []; pending = {}; getSceneAnimation = name => new Promise(resolve => pending[name] = resolve); playVrmAnimation = (a,l,n) => played.push(n); THREE.LoopOnce = 1;");
  f.run("catalogPromise = Promise.resolve(Object.fromEntries(Object.keys(ACTION_LABELS).map(n => [n,[{id:n+'_1',secondary:false}]])));");
  const old = f.run("playActionByName('greet')");
  await Promise.resolve();
  const fresh = f.run("playActionByName('wink')");
  await Promise.resolve();
  f.run("pending.wink({}); pending.greet({});");
  await Promise.all([old,fresh]);
  assert.deepEqual(Array.from(f.run('played')), ['wink']);
  const changing = f.run("playActionByName('thanks')");
  await Promise.resolve();
  f.run('modelLoadId += 1; pending.thanks({});');
  await changing;
  assert.equal(f.run('played.length'), 1);
});

test('animation cache shares loads and retries failed resources', async () => {
  const f = frontend();
  f.run('loads = []; createAnimationLoader = () => ({ load(...args) { loads.push(args); } });');
  const a = f.run("getSceneAnimation('greet')");
  const b = f.run("getSceneAnimation('greet')");
  assert.equal(a, b);
  f.run("loads[0][1]({ userData:{vrmAnimations:[{duration:3}]} });");
  await a;
  assert.equal(f.run('loads.length'), 1);
  const bad = f.run("getSceneAnimation('thanks')");
  f.run("loads[1][3](new Error('missing'));");
  await assert.rejects(bad);
  const retry = f.run("getSceneAnimation('thanks')");
  assert.equal(f.run('loads.length'), 3);
  f.run("loads[2][1]({userData:{vrmAnimations:[{}]}});");
  await retry;
});

test('full-expression actions keep face tracks; others defer to speech and blink', () => {
  const f = frontend();
  f.run(`sample = { humanoidTracks:{rotation:new Map([['head',{}],['leftEye',{}],['jaw',{}]]),translation:new Map()},
    expressionTracks:{preset:new Map([['aa',{}],['blinkLeft',{}],['happy',{}]]),custom:new Map([['unsupported',{}]])},lookAtTrack:{} };
    model = {expressionManager:{getExpression:n => ['aa','blinkLeft'].includes(n)}};`);
  assert.deepEqual(Array.from(f.run("filteredSceneAnimation(sample,'greet',model).expressionTracks.preset.keys()")),[]);
  assert.deepEqual(Array.from(f.run("filteredSceneAnimation(sample,'greet',model).humanoidTracks.rotation.keys()")),['head']);
  assert.deepEqual(Array.from(f.run("filteredSceneAnimation(sample,'thanks',model).expressionTracks.preset.keys()")),['blinkLeft']);
  assert.deepEqual(Array.from(f.run("filteredSceneAnimation(sample,'thanks',model).humanoidTracks.rotation.keys()")),['head','leftEye']);
  assert.equal(f.run("filteredSceneAnimation(sample,'greet',model).lookAtTrack"),null);
});

test('speech timeline keeps controlling articulation during every facial action', () => {
  for (const action of ['greet','explain','alert','booking','confirm','thanks','wink','preview']) {
    const f = frontend();
    const values = avatar(f);
    f.run(`activeAction={}; scenePlayback={name:'${action}',fullExpression:true,expressions:['blink']};
      updateSceneAnimation=()=>{};
      audioContext={currentTime:.1};
      currentVisemes={startTime:0,timeline:[{start:0,end:.2,viseme:'aa'},{start:.2,end:.4,viseme:'ou'}],lastIndex:-1,smoothOpen:0,
        samples:new Uint8Array(8),analyser:{getByteTimeDomainData(s){s.fill(170);}}};
      updateAvatar(.016);`);
    assert.ok(values.aa > 0, action);
    f.run('audioContext.currentTime=.25; updateAvatar(.016);');
    assert.ok(values.ou > 0, action);
    assert.ok(values.aa > 0, 'brief blend retains previous articulation');
    f.run('audioContext.currentTime=.5; updateAvatar(.016);');
    assert.ok(['aa','ih','ou','ee','oh'].every(v=>values[v]===0));
  }
});

test('browser fallback speaks during full facial actions and resets on error', async () => {
  const f=frontend(); const values=avatar(f); let utterance;
  f.sandbox.window.speechSynthesis={speak(u){utterance=u;u.onstart();}};
  f.run("activeAction={};scenePlayback={name:'explain',fullExpression:true,expressions:[]};updateSceneAnimation=()=>{};");
  const result=f.run("speakWithBrowser('测试')");
  f.run('updateAvatar(.016);');
  assert.ok(Object.values(values).some(v=>v>0));
  utterance.onerror();
  assert.equal(await result,false);
  assert.ok(['aa','ih','ou','ee','oh'].every(v=>values[v]===0));
  assert.ok(Object.values(f.run('mouthWeights')).every(v=>v===0));
});

test('smile mouth overrides are bypassed only during speech and restored on failure', () => {
  const f=frontend(); avatar(f);
  f.run(`smile={overrideMouth:'block'};relaxed={overrideMouth:'blend'};
    currentVrm.expressionManager.expressions=[smile,relaxed];
    observed=[];currentVrm.update=()=>observed.push([smile.overrideMouth,relaxed.overrideMouth]);
    browserSpeaking=true;updateVrmWithSpeechPriority(.016);`);
  assert.deepEqual(Array.from(f.run('observed[0]')),['none','none']);
  assert.equal(f.run('smile.overrideMouth'),'block');
  f.run('browserSpeaking=false;updateVrmWithSpeechPriority(.016);');
  assert.deepEqual(Array.from(f.run('observed[1]')),['block','blend']);
  f.run("browserSpeaking=true;currentVrm.update=()=>{throw Error('test');};");
  assert.throws(()=>f.run('updateVrmWithSpeechPriority(.016)'));
  assert.equal(f.run('relaxed.overrideMouth'),'blend');
});

test('mouth transitions are independent of frame rate and reset at silence', () => {
  const a=frontend(),b=frontend();avatar(a);avatar(b);
  a.run("for(let i=0;i<6;i++)blendSpeechMouth('aa',.7,1/60);");
  b.run("for(let i=0;i<3;i++)blendSpeechMouth('aa',.7,1/30);");
  assert.ok(Math.abs(a.run('mouthWeights.aa')-b.run('mouthWeights.aa'))<1e-8);
  a.run("blendSpeechMouth('ou',.7,1/60);");
  assert.ok(a.run('mouthWeights.ou>0 && mouthWeights.aa>0'));
  a.run('blendSpeechMouth(null,0,.016);');
  assert.ok(Object.values(a.run('mouthWeights')).every(v=>v===0));
});

test('finished actions release mixer, clear expressions and restore base pose', () => {
  const f = frontend();
  f.run(`currentVrm = {scene:{},expressionManager:{setValue(n,v){cleared[n]=v;},getValue(){return 1;}}};
    cleared = {}; stopped = false; restored = 0;
    modelPose = [{node:{quaternion:{copy(){restored++;}},position:{copy(){restored++;}}}, rotation:{},position:{}}];
    scenePlayback = {elapsed:0, duration:.3, bases:[], bindings:[], expressions:['blinkLeft']}; activeAction = {};
    mixer = {update(){},stopAllAction(){stopped=true;},uncacheRoot(){}};
    updateSceneAnimation(.3);`);
  assert.equal(f.run('activeAction'),null);
  assert.equal(f.run('scenePlayback'),null);
  assert.equal(f.run('stopped'),true);
  assert.equal(f.run('cleared.blinkLeft'),0);
  assert.equal(f.run('restored'),2);
});


test('held action samples survive idle writes when the mixer skips unchanged values', () => {
  const f = frontend();
  f.run(`target = {weight:0}; proxy = {weight:0}; cached = false;
    scenePlayback = {elapsed:0, duration:3, bases:[], expressions:[],
      bindings:[{target,proxy,property:'weight'}]};
    mixer = {update(){ if(!cached){ proxy.weight=1; cached=true; } }};
    held=[];
    for(let frame=0;frame<30;frame++){
      target.weight=0;
      updateSceneAnimation(1/60);
      held.push(target.weight);
    }`);
  assert.ok(Array.from(f.run('held')).every(value => value === 1));
});

test('greet keeps reference smile and blink while speech retains mouth ownership', () => {
  const f = frontend();
  f.run(`sample = {humanoidTracks:{rotation:new Map([['head',1],['rightEye',2]]),translation:new Map()},
    expressionTracks:{preset:new Map([['happy',1],['aa',2],['blink',3]]),custom:new Map()}};
    model = {expressionManager:{getExpression(){return true;}}};`);
  assert.equal(f.run("FULL_EXPRESSION_ACTIONS.has('greet')"), false);
  assert.deepEqual(Array.from(f.run("filteredSceneAnimation(sample,'greet',model).expressionTracks.preset.keys()")), ['happy','blink']);
  assert.deepEqual(Array.from(f.run("filteredSceneAnimation(sample,'greet',model).humanoidTracks.rotation.keys()")), ['head']);
});

test('secondary rotations match VRM0 humanoid handedness without mutating source data', () => {
  const f = frontend();
  f.run('sourceTwist=[.2,.3,.4,.5];');
  assert.deepEqual(Array.from(f.run("secondaryValuesForVrm(sourceTwist,{meta:{metaVersion:'0'}})")),[-.2,.3,-.4,.5]);
  assert.deepEqual(Array.from(f.run("secondaryValuesForVrm(sourceTwist,{meta:{metaVersion:'1'}})")),[.2,.3,.4,.5]);
  assert.deepEqual(Array.from(f.run('sourceTwist')),[.2,.3,.4,.5]);
  assert.equal(f.run("secondaryValuesForVrm(sourceTwist,{meta:{metaVersion:'1'}}) === sourceTwist"),false);
});

test('greet cloth assets reject malformed data and non-clothing targets', () => {
  const f = frontend();
  const data = JSON.parse(fs.readFileSync(path.join(__dirname, '../models/animations/greet_1.secondary.json')));
  f.sandbox.clothData = data;
  assert.equal(f.run('validateGreetSecondary(clothData).tracks.length'), 38);
  assert.equal(data.tracks.filter(t => /Twist/.test(t.nodeName)).length, 16);
  for (const mutate of [d => d.fps=30, d => d.tracks[0].values[0]=.5,
    d => d.tracks[0].nodeName='15.joint_Head', d => d.tracks[0].nodeName='25.joint_RightHandTwistInjected', d => d.tracks.push(d.tracks[0]),
    d => d.tracks[0].values[40]=NaN]) {
    const bad = structuredClone(data); mutate(bad); f.sandbox.clothData = bad;
    assert.throws(() => f.run('validateGreetSecondary(clothData)'));
  }
});

test('cloth offsets do not accumulate and clear on cancel, other avatars, and reduced motion', () => {
  const f = frontend();
  f.run(`class Q {
    constructor(v=0){this.v=v;} clone(){return new Q(this.v);} copy(q){this.v=q.v;return this;}
    fromArray(a,i){this.v=a[i];return this;} slerp(q,t){this.v+=(q.v-this.v)*t;return this;}
    multiply(q){this.v+=q.v;return this;}
  }
  clothTarget={quaternion:new Q(.1)};
  values=Array.from({length:292},(_,i)=>i%4===0?.02:0);
  state={name:'greet',elapsed:1,secondary:[{target:clothTarget,values,current:new Q(),next:new Q()}]};
  defaultAvatar=true;
  for(let i=0;i<120;i++){clearGreetSecondary();updateGreetSecondary(state);}`);
  assert.ok(Math.abs(f.run('clothTarget.quaternion.v')-.12)<1e-9);
  f.run('stopSceneAnimation()');
  assert.equal(f.run('clothTarget.quaternion.v'), .1);
  for (const setup of ["defaultAvatar=false", "defaultAvatar=true;motionReduced=true", "motionReduced=false;state.secondary=[]"]) {
    f.run(`${setup};updateGreetSecondary(state)`);
    assert.equal(f.run('clothTarget.quaternion.v'), .1);
  }
});

test('optional cloth failures and stale avatar loads fall back to the body animation', async () => {
  const f = frontend();
  f.sandbox.AbortController = AbortController;
  f.sandbox.fetch = async () => { throw new Error('offline'); };
  assert.deepEqual(Array.from(await f.run('loadGreetSecondary({}, {}, 1)')), []);
  f.sandbox.fetch = async () => ({ok:true,json:async()=>({version:1,fps:24,duration:3,tracks:[]})});
  assert.deepEqual(Array.from(await f.run('loadGreetSecondary({}, {}, -1)')), []);
});

test('reference blink does not block live speech and automatic blinking resumes', () => {
  const f = frontend();
  f.run(`currentVrm={update(){}}; activeAction={}; browserSpeaking=true;
    autoBlinks=0; mouthValues={}; updateBlink=()=>autoBlinks++;
    updateIdle=()=>true; updateSceneAnimation=()=>{};
    setExpression=(name,value)=>mouthValues[name]=value;
    scenePlayback={name:'greet',fullExpression:false,expressions:['happy','blink']};
    updateAvatar(1/24);`);
  assert.equal(f.run('autoBlinks'),0);
  assert.ok(Object.values(f.run('mouthValues')).some(v=>v>0));
  f.run('scenePlayback=null;updateAvatar(1/24);');
  assert.equal(f.run('autoBlinks'),1);
});

test('rejected greet clips release the temporary smile expression', () => {
  const f = frontend();
  f.run(`cleanup=[]; currentVrm={expressionManager:{unregisterExpression(){cleanup.push('unregister');}}};
    createGreetSmile=()=>({binds:[{clearAppliedWeight(){cleanup.push('clear');}}],removeFromParent(){cleanup.push('remove');}});
    filteredSceneAnimation=()=>({});
    createVRMAnimationClip=()=>{throw new Error('Invalid clip');};`);
  assert.throws(()=>f.run("playVrmAnimation({},1,'greet')"),/Invalid clip/);
  assert.deepEqual(Array.from(f.run('cleanup')),['clear','unregister','remove']);
  assert.equal(f.run('scenePlayback'),null);
});

test('discovered avatar names support unicode and removed selections fall back', async () => {
  const f=frontend();
  f.sandbox.fetch=async()=>({ok:true,json:async()=>[{id:'新人物 #1',label:'新人物 #1',profile:'standard'}]});
  f.elements.get('avatar-select').value='removed';
  await f.run('loadAvatarCatalog()');
  assert.equal(f.elements.get('avatar-select').value,'新人物 #1');
  f.run('loadVrm=(url)=>selectedUrl=url');
  f.elements.get('switch-avatar-btn').handlers.click();
  assert.equal(f.run('selectedUrl'),'/api/avatars/'+encodeURIComponent('新人物 #1'));
  f.sandbox.fetch=async()=>({ok:true,json:async()=>[]});
  await f.run('loadAvatarCatalog()');
  assert.equal(f.elements.get('avatar-select').disabled,true);
  assert.equal(f.elements.get('switch-avatar-btn').disabled,true);
  assert.equal(f.run('availableAvatars.length'),0);
});

test('older avatar catalog results cannot overwrite a fresh directory scan', async () => {
  const f=frontend();
  let resolveOld;
  f.sandbox.fetch=()=>new Promise(resolve=>{resolveOld=resolve});
  const pending=f.run('loadAvatarCatalog()');
  f.sandbox.fetch=async()=>({ok:true,json:async()=>[{id:'new',label:'new',profile:'standard'}]});
  await f.run('loadAvatarCatalog()');
  resolveOld({ok:true,json:async()=>[{id:'old',label:'old',profile:'standard'}]});
  await pending;
  assert.equal(f.run('availableAvatars[0].id'),'new');
});

test('presenter default selection persists independently of the current avatar and can reset', () => {
  const f=frontend(), saved=new Map();
  f.sandbox.window.localStorage={getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)};
  f.run("availableAvatars=[{id:'Klee',label:'Klee',profile:'standard'}]");
  f.elements.get('avatar-select').value='Klee';
  f.elements.get('set-default-avatar-btn').handlers.click();
  assert.equal(f.run('savedDefaultAvatar()'),'Klee');
  assert.equal(f.run('currentAvatarId'),'schoolBoy');
  f.elements.get('reset-default-avatar-btn').handlers.click();
  assert.equal(f.run('savedDefaultAvatar()'),null);
  f.sandbox.window.localStorage.setItem=()=>{throw new Error('denied')};
  f.elements.get('set-default-avatar-btn').handlers.click();
  assert.match(f.elements.get('default-avatar-status').textContent,/未能保存/);
});

test('startup resolves saved defaults through the catalog and falls back to the school boy', async () => {
  for(const saved of ['Klee','removed','../unsafe',null]) {
    const f=frontend();
    f.sandbox.window.localStorage={getItem:()=>saved};
    f.sandbox.fetch=async()=>({ok:true,json:async()=>[{id:'Klee',label:'Klee',profile:'standard'}]});
    f.run('renderer={}; loadVrm=(...args)=>defaultLoad=args');
    await f.run('initializeDefaultAvatar()');
    assert.equal(f.run('defaultLoad[0]'),saved==='Klee'?'/api/avatars/Klee':'/api/avatars/schoolBoy');
    assert.equal(f.run('defaultLoad[3].profile'),'standard');
    assert.equal(f.run('defaultLoad[3].id'),saved==='Klee'?'Klee':'schoolBoy');
  }
  const f=frontend();
  f.sandbox.window.localStorage={getItem:()=> 'Klee'};
  f.sandbox.fetch=async()=>{throw new Error('offline')};
  f.run('renderer={}; loadVrm=(...args)=>defaultLoad=args');
  await f.run('initializeDefaultAvatar()');
  assert.equal(f.run('defaultLoad[3].id'),'schoolBoy');
});

test('voice overrides are per avatar and auto restores the catalog preset', () => {
  const f=frontend(), store=new Map();
  f.sandbox.window.localStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)};
  f.run("availableAvatars=[{id:'Harumasa',voice_gender:'male'},{id:'AstraYao',voice_gender:'female'}];currentAvatarId='Harumasa';refreshAvatarVoice()");
  assert.equal(f.run('avatarVoice().voice_gender'),'male');
  f.elements.get('avatar-voice-select').value='female';
  f.elements.get('avatar-voice-select').handlers.change();
  f.run("currentAvatarId='AstraYao';refreshAvatarVoice()");
  assert.equal(f.elements.get('avatar-voice-select').value,'auto');
  f.run("currentAvatarId='Harumasa';refreshAvatarVoice()");
  assert.equal(f.elements.get('avatar-voice-select').value,'female');
  f.elements.get('avatar-voice-select').value='auto';
  f.elements.get('avatar-voice-select').handlers.change();
  assert.equal(f.run('avatarVoice().voice_gender'),'male');
});

test('the system default keeps its male voice while the avatar catalog is unavailable', () => {
  const f = frontend();
  f.run('availableAvatars=[]; currentAvatarId=DEFAULT_AVATAR.id; refreshAvatarVoice();');
  assert.equal(f.run('avatarVoice().voice_gender'), 'male');
  f.elements.get('avatar-voice-select').value = 'female';
  assert.equal(f.run('avatarVoice().voice_gender'), 'female');
});

test('browser fallback chooses a matching Chinese voice without changing pitch', async () => {
  const f=frontend(); let utterance;
  f.sandbox.window.speechSynthesis={getVoices:()=>[{name:'Xiaoxiao',lang:'zh-CN'},{name:'Yunxi',lang:'zh-CN'}],speak:u=>{utterance=u;u.onend()}};
  await f.run("speakWithBrowser('hello',speechGeneration,'male')");
  assert.equal(utterance.voice.name,'Yunxi');
  assert.equal(utterance.pitch,undefined);
  await f.run("speakWithBrowser('hello',speechGeneration,'female')");
  assert.equal(utterance.voice.name,'Xiaoxiao');
});

test('late chat audio and actions are discarded after an avatar switch', async () => {
  const f=frontend();let resolveChat, payload;
  f.elements.get('send-btn').disabled=false;
  f.sandbox.fetch=(url,options)=>new Promise(resolve=>{resolveChat=resolve;payload=JSON.parse(options.body)});
  f.run("availableAvatars=[{id:'Harumasa',voice_gender:'male'}];currentAvatarId='Harumasa';refreshAvatarVoice();playCount=0;actionCount=0;playSegments=async()=>{playCount++;return {failed:0}};handleAction=()=>actionCount++");
  const pending=f.run("sendMessage('谢谢')");
  assert.equal(payload.avatar_id,'Harumasa');assert.equal(payload.voice_gender,'male');
  f.run("stopCurrentSpeech();currentAvatarId='AstraYao'");
  resolveChat({ok:true,json:async()=>({reply:'不客气',action:'thanks',segments:[{text:'不客气'}]})});
  await pending;
  assert.equal(f.run('playCount'),0);assert.equal(f.run('actionCount'),0);
});

test('a stale preview cannot restart audio after voice cancellation', async () => {
  const f=frontend();let complete;
  f.sandbox.fetch=()=>new Promise(resolve=>{complete=resolve});
  f.run('played=0;playSegments=async()=>{played++;return {failed:0}}');
  const pending=f.run('previewAvatarVoice()');
  f.run('stopCurrentSpeech()');
  complete({ok:true,json:async()=>({segments:[{text:'hello'}],voice_gender:'female'})});
  await pending;
  assert.equal(f.run('played'),0);
});
