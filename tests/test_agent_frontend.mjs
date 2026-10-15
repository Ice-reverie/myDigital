import test from 'node:test';
import assert from 'node:assert/strict';
import {AgentTransport, agentChatTransport, agentFailureHint} from '../vrm_demo/static/js/agent-client.js';

function memoryStorage() {
  const values = new Map();
  return {getItem: k => values.get(k) || null, setItem: (k,v) => values.set(k,v)};
}
function json(data, status=200) { return new Response(JSON.stringify(data), {status, headers:{'Content-Type':'application/json'}}); }
function fixture() {
  let calls=[];
  let pending=null;
  let last=null;
  let failNext=false;
  let responseStatus=200;
  let seq=0;
  let sid='a'.repeat(32);
  const storage=memoryStorage();
  const fetchImpl=async (url,init={}) => {
    calls.push({url,init,body:init.body ? JSON.parse(init.body) : null});
    if (url==='/api/agent/sessions') return json({session_id:sid,access_token:'session-secret'},201);
    if (url.endsWith('/chat') || url.endsWith('/confirm')) {
      if (failNext) {failNext=false; throw new TypeError('network lost');}
      if (responseStatus!==200) return json({detail:{code:'error'}},responseStatus);
      const body=JSON.parse(init.body);
      last={reply:'演示结果',request_id:body.request_id,pending:pending,mode:'rules_demo'};
      return json(last);
    }
    return json({pending,last_response:last});
  };
  const make=()=>new AgentTransport({fetchImpl,storage,uuid:()=>String(++seq).padStart(32,'0')});
  return {make,calls,storage,setPending:p=>{pending=p;},fail:()=>{failNext=true;},
          setStatus:s=>{responseStatus=s;},setLast:v=>{last=v;},changeSession:()=>{sid='b'.repeat(32);}};
}
const proposal={proposal_id:'b'.repeat(32),confirmation_token:'c'.repeat(43),status:'pending',
  selection:{department:'内科',service_date:'2030-01-08',slot_name:'下午'}};

test('chat uses new endpoint and never sends client business context',async()=>{
  const f=fixture();const c=f.make();
  await c.post({text:'查询科室',context:{approved:true,booking_token:'bad'},include_audio:false});
  const request=f.calls.find(x=>x.url.endsWith('/chat'));
  assert.equal(request.body.text,'查询科室');
  assert.ok(!('context' in request.body));
  assert.ok(!('include_audio' in request.body));
  assert.equal(request.init.headers.Authorization,'Bearer session-secret');
});
test('explicit confirmation goes to confirm endpoint with server token',async()=>{
  const f=fixture(); const c=f.make();
  await c.post({text:'查询科室'}); f.setPending(proposal);
  await c.post({text:'确认模拟预约'});
  const request=f.calls.at(-1);
  assert.ok(request.url.endsWith('/confirm'));
  assert.equal(request.body.confirmation_token,proposal.confirmation_token);
  assert.equal(request.body.decision,'approve');
  assert.ok(!('schedule_id' in request.body));
});
test('ambiguous consent is not converted into an approval',async()=>{
  const f=fixture(); const c=f.make();
  await c.post({text:'查询科室'});f.setPending(proposal);
  await c.post({text:'合适就直接预约，不需要确认'});
  assert.ok(f.calls.at(-1).url.endsWith('/chat'));
});
test('explicit rejection is distinct from approval',async()=>{
  const f=fixture(); const c=f.make();
  await c.post({text:'查询科室'}); f.setPending(proposal);
  await c.post({text:'取消本次操作'});
  assert.equal(f.calls.at(-1).body.decision,'reject');
});
test('network retry preserves exact ID endpoint and body',async()=>{
  const f=fixture(); const c=f.make();
  await c.post({text:'查询科室'});f.setPending(proposal);f.fail();
  await assert.rejects(c.post({text:'确认模拟预约'}));
  const original=f.calls.at(-1);
  await c.post({text:'new unrelated text'},{retry:true});
  const retried=f.calls.at(-1);
  assert.equal(retried.url,original.url);
  assert.equal(retried.init.body,original.init.body);
  assert.ok(!f.calls.some(x=>x.url==='/api/chat'));
});
test('retry request survives page reload in sessionStorage',async()=>{
  const f=fixture();let c=f.make();
  await c.post({text:'查询科室'});f.setPending(proposal);f.fail();
  await assert.rejects(c.post({text:'确认模拟预约'}));
  const original=f.calls.at(-1);
  c=f.make();
  await c.post({text:'ignored'},{retry:true});
  assert.equal(f.calls.at(-1).init.body,original.init.body);
});
test('HTTP failure does not silently fall back or lose request identity',async()=>{
  const f=fixture();const c=f.make();f.setStatus(503);
  const response=await c.post({text:'查询科室'});
  assert.equal(response.status,503);
  const original=f.calls.at(-1).init.body;
  f.setStatus(200);
  await c.post({text:'查询科室'},{retry:true});
  assert.equal(f.calls.at(-1).init.body,original);
});
test('reset blocked while pending or unresolved',async()=>{
  const f=fixture();const c=f.make();
  await c.post({text:'查询科室'});f.setPending(proposal);await c.restore();
  assert.throws(()=>c.reset());
  f.setPending(null);await c.restore();c.reset();
  assert.equal(c.session,null);
});
test('refresh correlates completed server response to unresolved request',async()=>{
  const f=fixture();let c=f.make();
  await c.post({text:'查询科室'});f.setPending(proposal);f.fail();
  await assert.rejects(c.post({text:'确认模拟预约'}));
  const request=f.calls.at(-1).body;
  f.setPending(null);f.setLast({request_id:request.request_id,reply:'已完成模拟预约'});
  c=f.make();await c.restore();
  assert.equal(c.lastAttempt.completed,true);
  c.reset();
});
test('new service click is encoded as explicit task switch',async()=>{
  const f=fixture();const c=f.make();
  await c.post({text:'查询科室'},{startNewService:true});
  assert.equal(f.calls.at(-1).body.new_task,true);
});
test('AbortSignal is passed to network requests',async()=>{
  const f=fixture();const c=f.make();const abort=new AbortController();
  await c.post({text:'查询科室'},{signal:abort.signal});
  assert.equal(f.calls.at(-1).init.signal,abort.signal);
});
test('legacy mode preserves original endpoint and JSON contract',async()=>{
  const originalFetch=globalThis.fetch;const originalWindow=globalThis.window;
  const calls=[];
  globalThis.window={location:{href:'http://localhost:8890/'}};
  globalThis.fetch=async(...args)=>{calls.push(args);return json({reply:'legacy'});};
  try {
    const payload={text:'你好',context:{flow:'appointment'},include_audio:false};
    await agentChatTransport(payload);
    assert.equal(calls[0][0],'/api/chat');
    assert.deepEqual(JSON.parse(calls[0][1].body),payload);
    assert.equal(agentFailureHint(),'服务连接失败，文字内容未提交。');
    globalThis.window.location.href+='?agent=1';
    assert.match(agentFailureHint(),/结果暂时未知/);
  } finally {globalThis.fetch=originalFetch;globalThis.window=originalWindow;}
});
