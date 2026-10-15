const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {chromium} = require('playwright-core');

const root = path.resolve(__dirname, '../vrm_demo/static');
const avatar = path.resolve(__dirname, '../models/characters/schoolBoy.vrm');
const models = [
  {id:'schoolBoy', label:'校服男生（默认）', voice_gender:'male'},
  {id:'doctorBoy', label:'医生（男）', voice_gender:'male'},
  {id:'schoolGirl', label:'校服女生', voice_gender:'female'},
  {id:'studentGirl', label:'学生女生', voice_gender:'female'},
];
const modelFiles = new Map(models.map(model => [model.id,
  path.resolve(__dirname, `../models/characters/${model.id}.vrm`)]));
const idle = path.resolve(__dirname, '../models/animations/Idle_Doctor.vrma');
const explain = path.resolve(__dirname, '../models/animations/explain_1.vrma');
const greet = path.resolve(__dirname, '../models/animations/greet_1.vrma');
const edge = process.env.BROWSER_EXECUTABLE ||
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';

function silentWav(seconds) {
  const rate=8000, bytes=Math.round(seconds*rate)*2, wav=Buffer.alloc(44+bytes);
  wav.write('RIFF');wav.writeUInt32LE(36+bytes,4);wav.write('WAVEfmt ',8);
  wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);
  wav.writeUInt32LE(rate,24);wav.writeUInt32LE(rate*2,28);wav.writeUInt16LE(2,32);
  wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(bytes,40);
  return wav.toString('base64');
}

function assertForwardStance(state, label) {
  for (const side of ['left', 'right']) {
    const {hip, knee, ankle} = state.legPoints[side];
    assert.ok(Math.abs(hip[0] - knee[0]) < .0002, `${label}/${side}: knee splays sideways`);
    assert.ok(Math.abs(hip[0] - ankle[0]) < .0002, `${label}/${side}: foot splays sideways`);
    assert.ok(knee[2] > Math.max(hip[2], ankle[2]), `${label}/${side}: knee bends forward`);
  }
}

test('real browser loads four avatars, plays doctor idle and gentle explanation, and survives missing 3D',
  {skip: !fs.existsSync(edge) && 'Set BROWSER_EXECUTABLE to a Chromium browser'}, async () => {
    let unavailable3D = false;
    const server = http.createServer(async (request, response) => {
      const pathname = new URL(request.url, 'http://localhost').pathname;
      const json = (value, status = 200) => {
        response.writeHead(status, {'Content-Type':'application/json; charset=utf-8', 'Cache-Control':'no-store'});
        response.end(JSON.stringify(value));
      };
      if (pathname === '/api/health') return json({status:'ok'});
      if (pathname === '/api/avatars') return json(models.map(model => ({...model, profile:'standard'})));
      if (pathname.startsWith('/api/avatars/')) {
        const file = modelFiles.get(decodeURIComponent(pathname.slice('/api/avatars/'.length)));
        if (!file) return json({detail:'Unknown avatar'}, 404);
        response.writeHead(200, {'Content-Type':'model/gltf-binary'});
        return fs.createReadStream(file).pipe(response);
      }
      if (pathname === '/api/avatar') {
        if (unavailable3D) return json({detail:'Unavailable in smoke test'}, 404);
        response.writeHead(200, {'Content-Type':'model/gltf-binary', 'Cache-Control':'no-store'});
        return fs.createReadStream(avatar).pipe(response);
      }
      if (pathname === '/api/animations/idle') {
        response.writeHead(200, {'Content-Type':'model/gltf-binary'});
        return fs.createReadStream(idle).pipe(response);
      }
      if (pathname === '/api/animations') return json({greet:[{id:'greet_1', secondary:false}],
        explain:[{id:'explain_1', secondary:false}], alert:[], booking:[], confirm:[], thanks:[], wink:[]});
      if (pathname === '/api/animations/explain/explain_1') {
        response.writeHead(200, {'Content-Type':'model/gltf-binary'});
        return fs.createReadStream(explain).pipe(response);
      }
      if (pathname === '/api/animations/greet/greet_1') {
        response.writeHead(200, {'Content-Type':'model/gltf-binary'});
        return fs.createReadStream(greet).pipe(response);
      }
      if (pathname === '/api/chat') {
        let body = '';
        for await (const chunk of request) body += chunk;
        const incoming = JSON.parse(body);
        return json({reply:`收到：${incoming.text}`, action:incoming.text === '你好' ? 'greet' : ['健康查询','长讲解测试'].includes(incoming.text) ? 'explain' : null, context:{},
          quick_replies:[], segments:[{text:`收到：${incoming.text}`}]});
      }
      if (pathname === '/api/tts') {
        let body='';for await (const chunk of request) body+=chunk;
        const {text}=JSON.parse(body);
        await new Promise(resolve=>setTimeout(resolve,250));
        return json({voice_gender:'male', segments:[{text, audio:silentWav(text.includes('长讲解测试') ? 12.2 : 2.4), visemeTimeline:[]}]});
      }
      if (pathname === '/static/js/vrm-dependencies.js' && unavailable3D) {
        response.writeHead(503, {'Content-Type':'text/javascript', 'Cache-Control':'no-store'});
        return response.end('');
      }
      const relative = pathname.startsWith('/static/') ? pathname.slice('/static/'.length) : '';
      const file = path.resolve(root, relative);
      if (!relative || !file.startsWith(root + path.sep) || !fs.existsSync(file)) {
        response.writeHead(404);
        return response.end();
      }
      const type = file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' :
        file.endsWith('.html') ? 'text/html' : 'application/octet-stream';
      response.writeHead(200, {'Content-Type':type, 'Cache-Control':'no-store'});
      if (relative === 'js/VRMCharacter.js') {
        // Test-server-only observations of the actual mixer and Web Audio clock.
        return response.end(fs.readFileSync(file,'utf8') + `\nwindow.avatarQA=()=>({
          action:scenePlayback?.name,phase:scenePlayback?.elapsed,
          voiceTime:currentVisemes ? audioContext.currentTime-currentVisemes.startTime : null,
          legPoints:Object.fromEntries(['left','right'].map(side=>[side,Object.fromEntries(
            [['hip','UpperLeg'],['knee','LowerLeg'],['ankle','Foot']].map(([key,part])=>
              [key,currentVrm.humanoid.getRawBoneNode(side+part).getWorldPosition(new THREE.Vector3()).toArray()]))])),
          legs:Object.fromEntries(['leftUpperLeg','rightUpperLeg','leftLowerLeg','rightLowerLeg'].map(name=>{
            const q=currentVrm.scene.getWorldQuaternion(new THREE.Quaternion()).invert()
              .multiply(getBone(name).getWorldQuaternion(new THREE.Quaternion()));
            return [name,q.toArray()];
          }))
        });`);
      }
      fs.createReadStream(file).pipe(response);
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const browser = await chromium.launch({executablePath:edge, headless:true});
    try {
      for (const broken of [false, true]) {
        unavailable3D = broken;
        const context = await browser.newContext({viewport:{width:1280,height:960}});
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        const bundleResponse = page.waitForResponse(response =>
          new URL(response.url()).pathname === '/static/js/vrm-dependencies.js');
        await page.goto(`http://127.0.0.1:${server.address().port}/static/VRMCharacter.html`);
        assert.equal((await bundleResponse).status(), broken ? 503 : 200);
        if (!broken) {
          try {
            await page.waitForFunction(() => document.getElementById('avatar-placeholder')
              ?.hidden === true, null, {timeout:20000});
          } catch (error) {
            const status = await page.locator('#model-status-title').textContent();
            throw Error(`${error.message}; model status: ${status}; page errors: ${errors.join(' | ')}`);
          }
          assert.equal(await page.locator('#stage canvas').count(), 1);
        }
        // Use keyboard activation: the existing dock continuously floats by 3 px.
        await page.locator('#text-input').fill('测试对话');
        await page.locator('#text-input').press('Enter');
        await page.locator('#messages').getByText('收到：测试对话', {exact:true}).waitFor();
        if (!broken) {
          await page.locator('#help-btn').press('Enter');
          await page.locator('#help-dialog details').evaluate(element => {element.open = true;});
          for (const model of models) {
            await page.locator('#avatar-select').selectOption(model.id);
            await page.locator('#switch-avatar-btn').press('Enter');
            await page.waitForFunction(label => document.getElementById('model-status-title')
              ?.textContent.includes(`${label} 已就绪`), model.label, {timeout:15000});
            assert.match(await page.locator('#model-status-detail').textContent(), /医生接待式待机/);
            assert.match(await page.locator('#avatar-voice-status').textContent(),
              model.voice_gender === 'male' ? /男声/ : /女声/);
            await page.locator('#help-dialog').evaluate(element => element.close());
            const stance = await page.evaluate(()=>window.avatarQA());
            assertForwardStance(stance, model.id+' idle');
            for (const [bone,q] of Object.entries(stance.legs)) {
              const twist=Math.abs(2*Math.atan2(q[1],q[3])*180/Math.PI)%360;
              assert.ok(Math.min(twist,360-twist)<5, `${model.id}/${bone}: axial twist ${twist}`);
            }
            if (process.env.AVATAR_QA_OUTPUT) {
              fs.mkdirSync(process.env.AVATAR_QA_OUTPUT,{recursive:true});
              await page.screenshot({path:path.join(process.env.AVATAR_QA_OUTPUT,model.id+'-idle.png')});
            }
            await page.locator('#text-input').fill('健康查询');
            await page.locator('#text-input').press('Enter');
            await page.waitForFunction(() => document.getElementById('model-status-title')
              ?.textContent === '正在讲解', null, {timeout:5000});
            const synchronized = await page.evaluate(()=>window.avatarQA());
            assertForwardStance(synchronized, model.id+' explanation');
            for (const side of ['left','right']) {
              assert.ok(Math.hypot(...synchronized.legPoints[side].ankle.map((v,i)=>v-stance.legPoints[side].ankle[i]))<.0002,
                model.id+': entering explanation keeps the planted feet');
            }
            assert.notEqual(synchronized.voiceTime,null,'gesture starts only with actual audio');
            assert.ok(Math.abs(synchronized.phase-synchronized.voiceTime)<.15,'body and audio clocks stay together');
            if (process.env.AVATAR_QA_OUTPUT) {
              await page.screenshot({path:path.join(process.env.AVATAR_QA_OUTPUT,model.id+'-speaking.png')});
            }
            await page.waitForFunction(() => document.getElementById('model-status-title')
              ?.textContent === '自然待机', null, {timeout:20000});
            await page.locator('#text-input').fill('你好');
            await page.locator('#text-input').press('Enter');
            try {
              await page.waitForFunction(() => document.getElementById('model-status-title')
                ?.textContent.includes('正在问候'), null, {timeout:3000});
            } catch (error) {
              throw Error(`${model.id}: ${error.message}; status: ${await page.locator('#model-status-title').textContent()}; errors: ${errors.join(' | ')}`);
            }
            await page.locator('#help-btn').press('Enter');
            await page.locator('#help-dialog details').evaluate(element => {element.open = true;});
          }
          await page.locator('#help-dialog').evaluate(element => element.close());
          await page.locator('#text-input').fill('长讲解测试');
          await page.locator('#text-input').press('Enter');
          await page.waitForFunction(()=>window.avatarQA().voiceTime>10.3,null,{timeout:16000});
          const longReply=await page.evaluate(()=>window.avatarQA());
          assert.equal(longReply.action,'explain','a long reply continues after the first clip cycle');
          assert.ok(Math.abs(longReply.phase-longReply.voiceTime%10)<.15);
          // Interrupt real audio in the middle of a gesture, then ensure a
          // text-only response cannot resurrect the cancelled action.
          await page.locator('#text-input').fill('结束测试');
          await page.locator('#text-input').press('Enter');
          await page.waitForFunction(()=>!window.avatarQA().action,null,{timeout:3000});
        }
        assert.deepEqual(errors, []);
        await context.close();
      }
    } finally {
      await browser.close();
      await new Promise(resolve => server.close(resolve));
    }
  });
