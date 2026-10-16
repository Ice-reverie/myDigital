"""Offline: transport/parser tests, routing doubles, optional actual StateGraph.

No school API or business database writes. Run from the project root:
python -B -m unittest discover -s tests -p 'test_agent_knowledge_generation.py' -v
"""
import importlib.util
import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from vrm_demo.agent.knowledge_generation import (KnowledgeClient, EventParser, evidence_for_prompt,
                                                PROFILE, MAX_OUTPUT_TOKENS)
from vrm_demo.agent.conversation import run_conversation
from vrm_demo.agent.conversation_policy import validate_grounded, ReplyRejected
from vrm_demo.agent.conversation_text import TextClient
from vrm_demo.agent.llm import ModelFailure

CONFIG = {'key': 'test-secret-never-print', 'base': 'https://gateway.invalid/v1', 'model': 'test'}
CHUNKS = [
    {'source_id': 'booking-guide.md#chunk-1', 'title': '模拟预约操作说明',
     'text': '# 模拟预约操作说明\n先选择时段，再明确确认。待确认预约不会占用名额。确认后才会写入演示数据库。不产生真实医院挂号记录。'},
    {'source_id': 'service-scope.md#chunk-1', 'title': '服务范围', 'text': '可以查询预约流程，也可以查询科室信息。这里仅提供虚构服务说明。'},
    {'source_id': 'other.md#chunk-1', 'title': '其他资料', 'text': '这里是另一份预约说明，本例不发送这一份资料。'},
]


def grounded():
    return json.dumps({'answer': '先选择时段并明确确认，才会写入演示数据库。',
                       'citations': [{'source_id': CHUNKS[0]['source_id'],
                                      'quote': '待确认预约不会占用名额。'}], 'abstain': False}, ensure_ascii=False)


def whole(text=None, finish='stop', **extra):
    return {'choices': [{'message': {'content': text if text is not None else grounded(), **extra},
                         'finish_reason': finish}]}


def event(content='', finish=None, **extra):
    return ('data: ' + json.dumps({'choices': [{'index': 0, 'delta': {'content': content, **extra},
                                              'finish_reason': finish}]}, ensure_ascii=False) + '\n\n').encode()


class Bytes(httpx.SyncByteStream):
    def __init__(self, pieces): self.pieces = pieces
    def __iter__(self):
        for p in self.pieces:
            if isinstance(p, Exception): raise p
            yield p


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'DIGITALHELPER_KNOWLEDGE_STREAM': 'true'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.seen = []
    def client(self, handler):
        def dispatch(req):
            self.seen.append(json.loads(req.content)); return handler(req)
        return KnowledgeClient(SimpleNamespace(config=CONFIG, transport=httpx.MockTransport(dispatch)))
    def run_client(self, client):
        return client.complete([{'role': 'user', 'content': 'fixed-test'}], time.monotonic() + 5)
    def test_normal_sse_and_split_utf8(self):
        raw = event(grounded()[:7]) + event(grounded()[7:], 'stop') + b'data: [DONE]\n\n'
        c = self.client(lambda _: httpx.Response(200, headers={'content-type': 'text/event-stream'},
                    stream=Bytes([raw[i:i+1] for i in range(len(raw))])))
        self.assertEqual(self.run_client(c), grounded())
        self.assertTrue(self.seen[0]['stream']); self.assertNotIn('tools', self.seen[0])
        self.assertTrue(c.diagnostics['content_received']); self.assertEqual(c.diagnostics['transport'], 'sse')
    def test_gateway_ignores_stream_returns_json(self):
        c = self.client(lambda _: httpx.Response(200, json=whole()))
        self.assertEqual(self.run_client(c), grounded())
        self.assertEqual(c.diagnostics['transport'], 'json_response')
    def test_reasoning_is_not_answer_or_diagnostics(self):
        raw = event(None, reasoning_content='private-reasoning-marker') + event(grounded(), 'stop')
        c = self.client(lambda _: httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=raw))
        self.assertEqual(self.run_client(c), grounded())
        self.assertNotIn('private-reasoning-marker', json.dumps(c.diagnostics))
    def test_no_stop_never_returns_partial(self):
        for end in (b'', b'data: [DONE]\n\n'):
            c = self.client(lambda _, end=end: httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=event('partial') + end))
            with self.assertRaises(ModelFailure) as error: self.run_client(c)
            self.assertEqual(error.exception.code, 'incomplete')
    def test_length_rejected_even_if_text_looks_json(self):
        c = self.client(lambda _: httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=event(grounded(), 'length')))
        with self.assertRaises(ModelFailure) as error: self.run_client(c)
        self.assertEqual(error.exception.code, 'incomplete')
    def test_timeout_after_partial_no_retry_or_partial_success(self):
        c = self.client(lambda _: httpx.Response(200, headers={'content-type': 'text/event-stream'},
                    stream=Bytes([event('partial'), httpx.ReadTimeout('RAW_SECRET')])) )
        with self.assertRaises(ModelFailure) as error: self.run_client(c)
        self.assertEqual(error.exception.code, 'read_timeout'); self.assertEqual(len(self.seen), 1)
        self.assertTrue(c.diagnostics['content_received']); self.assertNotIn('RAW_SECRET', str(error.exception))
    def test_timeout_before_headers_diagnostic(self):
        def fail(_): raise httpx.ReadTimeout('RAW_SECRET')
        c = self.client(fail)
        with self.assertRaises(ModelFailure): self.run_client(c)
        self.assertFalse(c.diagnostics['headers_received']); self.assertFalse(c.diagnostics['response_started'])
    def test_http_error_never_retries(self):
        for status in (400, 401, 403, 429, 500):
            with self.subTest(status=status):
                self.seen.clear(); c = self.client(lambda _, status=status: httpx.Response(status, text='RAW_SECRET'))
                with self.assertRaises(ModelFailure) as error: self.run_client(c)
                self.assertEqual(error.exception.http_status, status); self.assertEqual(len(self.seen), 1)
                self.assertNotIn('RAW_SECRET', str(error.exception))
    def test_unsolicited_tool_delta_rejected(self):
        c = self.client(lambda _: httpx.Response(200, headers={'content-type': 'text/event-stream'},
                    content=event('', tool_calls=[{'id': 'x'}])))
        with self.assertRaises(ModelFailure) as error: self.run_client(c)
        self.assertEqual(error.exception.code, 'invalid_tool_calls')
    def test_body_limit(self):
        c = self.client(lambda _: httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=b'x'*262145))
        with self.assertRaises(ModelFailure) as error: self.run_client(c)
        self.assertEqual(error.exception.code, 'response_limit')
    def test_output_text_limit(self):
        p = EventParser()
        with self.assertRaises(ModelFailure): p.feed(event('x'*10001))
    def test_bad_json_event(self):
        p = EventParser()
        with self.assertRaises(ModelFailure): p.feed(b'data: BAD\n\n')
    def test_bad_choice_shape(self):
        p = EventParser()
        with self.assertRaises(ModelFailure): p.feed(b'data: {"choices":"bad"}\n\n')
    def test_no_complete_event_is_not_success(self):
        p = EventParser(); p.feed(event('x', 'stop').rstrip(b'\n'))
        self.assertIsNone(p.answer)
    def test_crlf_comments_and_usage(self):
        p = EventParser(); p.feed(b': heartbeat\r\n\r\ndata: {"choices":[],"usage":{}}\r\n\r\n')
        p.feed(event('ok', 'stop').replace(b'\n', b'\r\n')); self.assertEqual(p.answer, 'ok')
    def test_expired_budget_no_network(self):
        c = self.client(lambda _: self.fail('must not request'))
        with self.assertRaises(ModelFailure) as error: c.complete([], time.monotonic() - 1)
        self.assertEqual(error.exception.code, 'budget_exceeded')
    def test_disabled_switch_uses_old_nonstream(self):
        c = self.client(lambda _: httpx.Response(200, json=whole()))
        with patch.dict(os.environ, {'DIGITALHELPER_KNOWLEDGE_STREAM': 'false'}):
            self.assertEqual(self.run_client(c), grounded())
        self.assertFalse(self.seen[0]['stream'])
    def test_json_tools_rejected(self):
        c = self.client(lambda _: httpx.Response(200, json=whole(tool_calls=[{'id':'fake'}])))
        with self.assertRaises(ModelFailure): self.run_client(c)
    def test_secret_prompt_not_in_diagnostics(self):
        c = self.client(lambda _: httpx.Response(200, json=whole()))
        c.complete([{'role':'user','content':'PRIVATE_USER'}], time.monotonic()+5)
        d=json.dumps(c.diagnostics)
        for private in ('PRIVATE_USER', CONFIG['key'], CONFIG['base'], grounded()): self.assertNotIn(private,d)
    def test_read_limit_stays_30(self):
        def h(request):
            self.assertEqual(request.extensions['timeout']['read'],30.0)
            return httpx.Response(200,json=whole())
        c=self.client(h);c.complete([],time.monotonic()+60)


class RouteTests(unittest.TestCase):
    engine = 'native'
    def setUp(self):
        self.env = patch.dict(os.environ, {'DIGITALHELPER_KNOWLEDGE_STREAM': 'true'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.seen = []
    def run_query(self, text='怎么预约，确认流程是什么', handler=None, chunks=CHUNKS):
        def dispatch(req):
            p = json.loads(req.content); self.seen.append(p)
            return handler(p) if handler else httpx.Response(200,json=whole())
        def make_response(sid, reply, **kwargs):
            return {'session_id':sid,'reply':reply,'sources':kwargs.pop('sources',[]), **kwargs}
        svc = SimpleNamespace(settings=SimpleNamespace(model_budget=60), engine=self.engine,
                              client=SimpleNamespace(config=CONFIG, transport=httpx.MockTransport(dispatch)),
                              knowledge=SimpleNamespace(search=lambda query,limit:chunks), response=make_response)
        return run_conversation(svc,'test-session',SimpleNamespace(text=text),{},
                                lambda: make_response('test-session','fixed business',mode='llm_tools'))
    def test_valid_knowledge_response_preserves_validator(self):
        r = self.run_query();self.assertEqual(r['mode'],'llm_knowledge');self.assertTrue(r['sources'])
        self.assertEqual(r['diagnostics']['generation_profile'],PROFILE)
    def test_three_retrieved_two_sent(self):
        r = self.run_query(); packet=json.loads(self.seen[0]['messages'][-1]['content'])
        self.assertEqual(len(packet['documents']),2)
        self.assertEqual(r['diagnostics']['retrieved_chunks'],3)
        self.assertEqual(r['diagnostics']['model_events'][0]['evidence_chunks'],2)
        self.assertEqual(self.seen[0]['max_tokens'],MAX_OUTPUT_TOKENS)
    def test_no_truncation_of_sent_documents(self):
        documents=evidence_for_prompt(CHUNKS)
        self.assertEqual(documents[0]['text'],CHUNKS[0]['text'])
    def test_fallback_short_no_markdown_blob(self):
        def timeout(_):raise httpx.ReadTimeout('private')
        r=self.run_query(handler=timeout)
        self.assertEqual(r['mode'],'knowledge_fallback');self.assertLess(len(r['reply']),180)
        self.assertNotIn('# ',r['reply']);self.assertNotIn('booking-guide.md',r['reply'])
        self.assertTrue(r['sources']);self.assertEqual(r['diagnostics']['reason'],'read_timeout')
    def test_invalid_citation_not_accepted(self):
        bad=json.loads(grounded());bad['citations'][0]['source_id']='.env'
        r=self.run_query(handler=lambda _:httpx.Response(200,json=whole(json.dumps(bad))))
        self.assertEqual(r['mode'],'knowledge_fallback');self.assertNotIn('.env',r['reply'])
    def test_source_not_sent_to_model_rejected(self):
        bad=json.loads(grounded());bad['citations']=[{'source_id':CHUNKS[2]['source_id'],'quote':CHUNKS[2]['text']}]
        r=self.run_query(handler=lambda _:httpx.Response(200,json=whole(json.dumps(bad))))
        self.assertEqual(r['mode'],'knowledge_fallback')
    def test_truncated_stream_is_not_answer(self):
        r=self.run_query(handler=lambda _:httpx.Response(200,headers={'content-type':'text/event-stream'},content=event(grounded(),'length')))
        self.assertEqual(r['mode'],'knowledge_fallback');self.assertEqual(r['diagnostics']['reason'],'incomplete')
    def test_chat_still_nonstream(self):
        r=self.run_query(text='陪我聊聊画画',handler=lambda _:httpx.Response(200,json=whole('可以呀，你喜欢画什么？')))
        self.assertEqual(r['mode'],'llm_chat');self.assertFalse(self.seen[0]['stream'])
    def test_business_callback_unchanged(self):
        r=self.run_query(text='查询内科明天下午号源')
        self.assertEqual(r['reply'],'fixed business');self.assertEqual(self.seen,[])
    def test_no_evidence_no_generation(self):
        r=self.run_query(chunks=[]);self.assertEqual(r['mode'],'knowledge_no_evidence');self.assertEqual(self.seen,[])
    def test_stream_complete_runs_citation_validation(self):
        r=self.run_query(handler=lambda _:httpx.Response(200,headers={'content-type':'text/event-stream'},content=event(grounded(),'stop')))
        self.assertEqual(r['mode'],'llm_knowledge');self.assertEqual(r['diagnostics']['model_events'][0]['transport'],'sse')


@unittest.skipUnless(importlib.util.find_spec('langgraph'), 'real LangGraph is not installed')
class LangGraphKnowledgeGenerationTests(RouteTests):
    engine='langgraph'


class LocalSocketTests(unittest.TestCase):
    def test_stream_can_outlive_idle_limit_without_increasing_it(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                p=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(200)
                self.send_header('Content-Type','text/event-stream' if p['stream'] else 'application/json')
                self.end_headers()
                try:
                    if p['stream']:
                        for fragment in ['o','k']:
                            self.wfile.write(event(fragment));self.wfile.flush();time.sleep(.07)
                        self.wfile.write(event('', 'stop'));self.wfile.flush()
                    else:
                        time.sleep(.2);self.wfile.write(json.dumps(whole('ok')).encode());self.wfile.flush()
                except (BrokenPipeError,ConnectionResetError):pass
        try: server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        except OSError as exc:self.skipTest('loopback socket unavailable: '+type(exc).__name__)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            conf={**CONFIG,'base':f'http://127.0.0.1:{server.server_port}/v1'}
            tool=SimpleNamespace(config=conf,transport=None)
            with patch('vrm_demo.agent.conversation_text.MODEL_READ_TIMEOUT_SECONDS',.12):
                with self.assertRaises(ModelFailure) as error: TextClient(tool).complete([],time.monotonic()+3)
                self.assertEqual(error.exception.code,'read_timeout')
            with patch.dict(os.environ,{'DIGITALHELPER_KNOWLEDGE_STREAM':'true'}),patch('vrm_demo.agent.knowledge_generation.MODEL_READ_TIMEOUT_SECONDS',.12):
                self.assertEqual(KnowledgeClient(tool).complete([],time.monotonic()+3),'ok')
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)


if __name__=='__main__':unittest.main()
