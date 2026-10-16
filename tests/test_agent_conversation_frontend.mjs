import test from 'node:test';
import assert from 'node:assert/strict';
import {renderAgentSources, installAgentControls, agentChatTransport, agentChatTimeoutMs} from '../vrm_demo/static/js/agent-client.js';

class Element {
  constructor(tag) { this.tagName=tag; this.children=[]; this.textContent=''; this.style={}; this.events={}; this.hidden=false; }
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this.children=children;}
  setAttribute(name,value) {this[name]=value;}
  addEventListener(name,fn) {this.events[name]=fn;}
  set innerHTML(_) {throw new Error('HTML insertion forbidden');}
}
const doc={createElement:tag=>new Element(tag)};
function allText(e) {return (e.textContent||'')+e.children.map(allText).join('\n');}
const source={source_id:'booking-guide.md#chunk-1',title:'预约说明',quote:'待确认预约不会占用名额。'};

test('sources render title identity and quote as text',()=>{
  const host=new Element('details');renderAgentSources(host,[source],doc);
  assert.equal(host.hidden,false);assert.match(allText(host),/预约说明/);
  assert.match(allText(host),/待确认预约不会占用名额/);
});
test('empty sources clear previous task evidence',()=>{
  const host=new Element('details');renderAgentSources(host,[source],doc);renderAgentSources(host,[],doc);
  assert.equal(host.hidden,true);assert.ok(!allText(host).includes('待确认预约不会占用名额'));
});
test('source content cannot create executable HTML or a hyperlink',()=>{
  const host=new Element('details');renderAgentSources(host,[{...source,title:'<img src=x onerror=alert(1)>',quote:'<script>evil</script>'}],doc);
  assert.ok(allText(host).includes('<script>evil</script>'));assert.equal(host.children[1].tagName,'p');
});
test('source count and content length are bounded',()=>{
  const host=new Element('details');renderAgentSources(host,Array.from({length:50},()=>({...source,quote:'x'.repeat(10000)})),doc);
  assert.equal(host.children.length,4);assert.ok(allText(host).length<2500);
});
test('malformed source list is ignored',()=>{
  const host=new Element('details');renderAgentSources(host,{},doc);assert.equal(host.hidden,true);
  renderAgentSources(host,[null,{},12],doc);assert.equal(host.hidden,true);
});
test('UI shows ordinary chat and knowledge instead of generic fallback; preserves timeout',async()=>{
  const help=new Element('dialog'),dock=new Element('div');
  const elements=[help,dock];
  const lookup=(e,id)=> e.id===id ? e : e.children.map(c=>lookup(c,id)).find(Boolean);
  const previous={document:globalThis.document,window:globalThis.window,fetch:globalThis.fetch};
  globalThis.document={createElement:doc.createElement,
    getElementById:id=>id==='help-dialog'?help:elements.map(e=>lookup(e,id)).find(Boolean),
    querySelector:()=>dock};
  globalThis.window={location:{href:'http://localhost:8890/?agent=1'},sessionStorage:{getItem:()=>null,setItem:()=>{}}};
  let next={reply:'我们聊聊吧。',mode:'llm_chat',route:'chat',engine:'langgraph',diagnostics:{reason:'completed'}};
  const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
  globalThis.fetch=async(url,init={})=>{
    if(url.endsWith('/status'))return json({engine:'langgraph',llm_configured:true});
    if(url==='/api/agent/sessions')return json({session_id:'a'.repeat(32),access_token:'never-render-this-token'},201);
    if(url.endsWith('/chat'))return json({...next,request_id:JSON.parse(init.body).request_id});
    return json({last_response:null,pending:null});
  };
  try {
    installAgentControls();await new Promise(resolve=>setTimeout(resolve,0));
    assert.equal(agentChatTimeoutMs(),100000);
    await agentChatTransport({text:'聊聊天'});
    assert.match(allText(help),/普通聊天：大模型生成回复/);
    next={reply:'先选择时段，再确认。',mode:'llm_knowledge',route:'knowledge',engine:'langgraph',sources:[source],diagnostics:{reason:'completed'}};
    await agentChatTransport({text:'怎么预约'});
    assert.match(allText(help),/服务咨询：资料检索＋模型回答/);
    assert.match(allText(dock),/待确认预约不会占用名额/);
    assert.ok(!allText(help).includes('never-render-this-token'));
  } finally {
    Object.assign(globalThis,previous);
  }
});
