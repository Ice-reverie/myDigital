"""Real SQLite/FastAPI tests plus simulated HTTP provider responses.

Run from project root:
  python -B -m unittest discover -s tests -p "test_agent_backend.py" -v
Only explicit LangGraph integration tests skip when the optional dependency is
absent. No real provider calls, hospital calls or user databases are used.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from vrm_demo import database_gateway as db
from vrm_demo.agent.api import mount_agent
from vrm_demo.agent.config import Settings, model_config
from vrm_demo.agent.llm import LLMClient, ModelFailure
from vrm_demo.agent.policy import resolve_date
from vrm_demo.agent.schemas import ChatInput, DecisionInput
from vrm_demo.agent.service import AgentService
from vrm_demo.agent.store import AgentError
from vrm_demo.agent.tools import Toolbox, tool_schemas

NOW=datetime(2030,1,7,10,tzinfo=timezone(timedelta(hours=8)))
ROOT=Path(__file__).resolve().parents[1]

@contextmanager
def open_db(path):
    connection=sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()

def rid():
    return uuid.uuid4().hex

def call(name,args=None,call_id=None):
    return {"role":"assistant","content":"","tool_calls":[{"id":call_id or rid(),"type":"function",
            "function":{"name":name,"arguments":json.dumps(args or {},ensure_ascii=False)}}]}

class ScriptedClient:
    configured=True
    def __init__(self,answers):
        self.answers=list(answers)
        self.seen=[]
    def next(self,messages,schemas,deadline):
        self.seen.append(json.loads(json.dumps(messages)))
        if not self.answers:
            return {"role":"assistant","content":""}
        response=self.answers.pop(0)
        if isinstance(response,Exception):
            raise response
        return response

class Fixture(unittest.TestCase):
    engine="native"
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.business=self.root/'business.sqlite3'
        schema=Path(db.__file__).resolve().parent/'db'/'schema.sqlite.sql'
        with open_db(self.business) as conn:
            conn.executescript(schema.read_text(encoding='utf-8'))
            conn.executemany("INSERT INTO department VALUES(?,?,?,?,?,?,?)",[
                ('internal','内科','一楼','内科演示','09:00-17:00',1,1),
                ('surgery','外科','二楼','外科演示','09:00-17:00',2,1)])
            conn.executemany("INSERT INTO time_slot VALUES(?,?,?,?,?)",[
                ('am','上午','09:00:00','12:00:00',1),('pm','下午','14:00:00','17:00:00',2)])
            conn.execute("INSERT INTO user_base VALUES('demo-001','虚构用户',1)")
            for dept in ('internal','surgery'):
                for day in (8,9):
                    for slot in ('am','pm'):
                        conn.execute("INSERT INTO schedule VALUES(?,?,?,?,?,?,?)",
                                     (f'{dept}:2030-01-{day:02d}:{slot}',dept,f'2030-01-{day:02d}',slot,5,1,'open'))
            conn.execute("INSERT INTO health_record VALUES('r1','demo-001','血压','虚构血压记录：120/80','2030-01-06 10:00:00')")
            conn.execute("INSERT INTO alert VALUES('a1','demo-001','虚构记录待确认','pending','2030-01-06 10:00:00',NULL)")
        self.env=patch.dict(os.environ,{'DIGITALHELPER_DB_ENABLED':'true','DIGITALHELPER_DB_BACKEND':'sqlite',
                                       'DIGITALHELPER_SQLITE_PATH':str(self.business),'DIGITALHELPER_AGENT_ENABLED':'true'})
        self.env.start()
        self.clock=patch.object(db,'now',return_value=NOW)
        self.clock.start()
        self.settings=Settings(self.root/'agent.sqlite3',engine=self.engine,knowledge_path=ROOT/'knowledge'/'agent')
        self.svc=AgentService(self.settings,gateway=db,client=LLMClient(config={}))
        self.session=self.svc.create_session()
        self.sid,self.secret=self.session['session_id'],self.session['access_token']
    def tearDown(self):
        self.svc.close()
        self.clock.stop()
        self.env.stop()
        self.temp.cleanup()
    def chat(self,text,request_id=None,session=None,**kw):
        session=session or self.session
        return self.svc.chat(session['session_id'],session['access_token'],ChatInput(text=text,request_id=request_id or rid(),**kw))
    def proposal(self,session=None):
        response=self.chat('帮我预约内科明天下午',session=session)
        self.assertTrue(response['requires_confirmation'])
        return response['pending']
    def approve(self,p,session=None,request_id=None,decision='approve'):
        session=session or self.session
        return self.svc.confirm(session['session_id'],session['access_token'],DecisionInput(
            request_id=request_id or rid(),proposal_id=p['proposal_id'],confirmation_token=p['confirmation_token'],decision=decision))
    def count(self):
        with open_db(self.business) as conn:
            return conn.execute('SELECT COUNT(*) FROM appointment').fetchone()[0]
    def toolbox(self):
        return Toolbox(db,self.svc.store,self.svc.knowledge,self.sid,rid(),self.svc.store.load(self.sid))
    def assert_code(self,code,fn):
        with self.assertRaises(AgentError) as ctx:
            fn()
        self.assertEqual(ctx.exception.code,code)

class AgentBackendTests(Fixture):
    def test_departments_are_real_database_results(self):
        response=self.chat('查询科室')
        self.assertIn('内科：一楼',response['reply'])
        self.assertEqual(response['trace'][0]['tool'],'get_departments')
    def test_no_key_is_explicit_rules_demo(self):
        self.assertEqual(self.chat('查询科室')['mode'],'rules_demo')
        self.assertFalse(self.svc.status()['llm_configured'])
    def test_date_and_period_filter(self):
        r=self.chat('查询内科明天下午号源')
        self.assertIn('2030-01-08 下午',r['reply'])
        self.assertNotIn('2030-01-09',r['reply'])
        self.assertNotIn('上午',r['reply'])
        self.assertFalse(r['requires_confirmation'])
    def test_booking_only_prepares(self):
        self.proposal()
        self.assertEqual(self.count(),0)
    def test_raw_chat_confirm_has_no_write_authority(self):
        self.proposal()
        result=self.chat('确认模拟预约')
        self.assertTrue(result['requires_confirmation'])
        self.assertEqual(self.count(),0)
    def test_explicit_approval_commits(self):
        result=self.approve(self.proposal())
        self.assertTrue(result['operation_result']['ok'])
        self.assertEqual(self.count(),1)
    def test_duplicate_same_http_request_is_cached(self):
        p=self.proposal(); key=rid()
        first=self.approve(p,request_id=key)
        second=self.approve(p,request_id=key)
        self.assertEqual(first,second)
        self.assertEqual(self.count(),1)
    def test_repeated_proposal_new_request_does_not_duplicate(self):
        p=self.proposal()
        first=self.approve(p)
        second=self.approve(p)
        self.assertEqual(first['operation_result'],second['operation_result'])
        self.assertEqual(self.count(),1)
    def test_wrong_session_secret_is_rejected(self):
        other=self.svc.create_session()
        self.assert_code('unauthorized',lambda:self.svc.state(self.sid,other['access_token']))
    def test_cross_session_proposal_is_rejected(self):
        p=self.proposal(); other=self.svc.create_session()
        self.assert_code('proposal_not_found',lambda:self.approve(p,session=other))
        self.assertEqual(self.count(),0)
    def test_forged_confirmation_token_is_rejected(self):
        p=self.proposal(); p['confirmation_token']='x'*43
        self.assert_code('invalid_confirmation',lambda:self.approve(p))
    def test_expired_proposal_cannot_commit(self):
        p=self.proposal()
        with self.svc.store.connect() as c:
            c.execute('UPDATE agent_proposals SET expires=0 WHERE id=?',(p['proposal_id'],))
        self.assert_code('approval_expired',lambda:self.approve(p))
        self.assertEqual(self.count(),0)
    def test_completed_result_replay_survives_proposal_expiry(self):
        p=self.proposal(); self.approve(p)
        with self.svc.store.connect() as c:
            c.execute('UPDATE agent_proposals SET expires=0 WHERE id=?',(p['proposal_id'],))
        self.assertTrue(self.approve(p)['operation_result']['ok'])
        self.assertEqual(self.count(),1)
    def test_reject_has_no_business_write(self):
        r=self.approve(self.proposal(),decision='reject')
        self.assertTrue(r['operation_result']['cancelled'])
        self.assertEqual(self.count(),0)
    def test_rejected_proposal_cannot_be_approved(self):
        p=self.proposal(); self.approve(p,decision='reject')
        self.assert_code('already_rejected',lambda:self.approve(p))
    def test_committed_booking_is_not_falsely_cancelled(self):
        p=self.proposal(); self.approve(p)
        self.assert_code('already_committed',lambda:self.approve(p,decision='reject'))
    def test_commit_is_not_an_exposed_tool(self):
        names=[s['function']['name'] for s in tool_schemas()]
        self.assertNotIn('commit',names)
        self.assertNotIn('create_appointment',names)
        self.assertEqual(self.toolbox().execute('commit',{})['error'],'unknown_tool')
    def test_unobserved_schedule_id_cannot_be_prepared(self):
        result=self.toolbox().execute('prepare_appointment',{'schedule_id':'internal:2030-01-08:pm'})
        self.assertEqual(result['error'],'unobserved_slot')
    def test_extra_tool_arguments_rejected(self):
        for name,args in [('get_departments',{'sql':'DROP TABLE appointment'}),
                          ('prepare_appointment',{'schedule_id':'x','approved':True}),
                          ('get_health_records',{'user_id':'other'})]:
            with self.subTest(name=name):
                self.assertEqual(self.toolbox().execute(name,args)['error'],'invalid_arguments')
    def test_confirmation_cannot_override_schedule(self):
        p=self.proposal()
        with self.assertRaises(ValidationError):
            DecisionInput(request_id=rid(),proposal_id=p['proposal_id'],confirmation_token=p['confirmation_token'],
                          decision='approve',schedule_id='tampered')
    def test_database_disabled_never_claims_success(self):
        with patch.dict(os.environ,{'DIGITALHELPER_DB_ENABLED':'false'}):
            r=self.chat('帮我预约内科明天下午')
        self.assertFalse(r['requires_confirmation'])
        self.assertIn('暂不可用',r['reply'])
        self.assertEqual(self.count(),0)
    def test_capacity_recheck_prevents_overselling(self):
        with open_db(self.business) as c:
            c.execute("UPDATE schedule SET capacity=1,base_booked=0 WHERE schedule_id='internal:2030-01-08:pm'")
        p1=self.proposal(); other=self.svc.create_session(); p2=self.proposal(other)
        self.assertTrue(self.approve(p1)['operation_result']['ok'])
        r=self.approve(p2,session=other)
        self.assertFalse(r['operation_result']['ok'])
        self.assertEqual(self.count(),1)
    def test_same_session_confirmation_concurrency(self):
        p=self.proposal()
        def submit(_):
            try: return self.approve(p)['operation_result']['ok']
            except AgentError as exc: return exc.code
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(submit,range(4)))
        self.assertIn(True,results)
        self.assertTrue(all(x is True or x=='session_busy' for x in results))
        self.assertEqual(self.count(),1)
    def test_pending_state_survives_service_restart(self):
        p=self.proposal(); self.svc.close()
        self.svc=AgentService(self.settings,gateway=db,client=LLMClient(config={}))
        restored=self.svc.state(self.sid,self.secret)
        self.assertEqual(restored['pending']['proposal_id'],p['proposal_id'])
        self.approve(p)
        self.assertEqual(self.count(),1)
    def test_lost_response_after_database_commit_reconciles(self):
        p=self.proposal(); original=db.Repository.book
        def commit_then_disconnect(repo,*args,**kwargs):
            original(repo,*args,**kwargs)
            raise OSError('simulated connection loss after commit')
        with patch.object(db.Repository,'book',commit_then_disconnect):
            self.assert_code('commit_unknown',lambda:self.approve(p))
        self.assertEqual(self.count(),1)
        self.assert_code('commit_unknown',lambda:self.approve(p,decision='reject'))
        self.approve(p)
        self.assertEqual(self.count(),1)
    def test_unknown_commit_is_not_presented_as_unsubmitted(self):
        p=self.proposal(); original=db.Repository.book
        def lost(repo,*args,**kw):
            original(repo,*args,**kw)
            raise OSError('lost response')
        with patch.object(db.Repository,'book',lost):
            self.assert_code('commit_unknown',lambda:self.approve(p))
        result=self.chat('查看当前任务')
        self.assertIn('结果待核实',result['reply'])
        self.assertNotIn('尚未占用',result['reply'])
        self.assertNotIn('取消本次操作',result['quick_replies'])
    def test_old_prepare_request_does_not_redisplay_committed_proposal(self):
        key=rid(); first=self.chat('帮我预约内科明天下午',request_id=key)
        self.approve(first['pending'])
        replay=self.chat('帮我预约内科明天下午',request_id=key)
        self.assertFalse(replay['requires_confirmation'])
        self.assertIn('已经提交',replay['reply'])
        self.assertEqual(self.count(),1)
    def test_old_prepare_request_does_not_redisplay_expired_proposal(self):
        key=rid(); first=self.chat('帮我预约内科明天下午',request_id=key)
        with self.svc.store.connect() as c:
            c.execute('UPDATE agent_proposals SET expires=0 WHERE id=?',(first['pending']['proposal_id'],))
        replay=self.chat('帮我预约内科明天下午',request_id=key)
        self.assertFalse(replay['requires_confirmation'])
        self.assertIn('过期',replay['reply'])
    def test_reusing_request_id_for_changed_text_is_rejected(self):
        key=rid(); self.chat('查询科室',request_id=key)
        self.assert_code('request_id_conflict',lambda:self.chat('我的预约',request_id=key))
    def test_request_id_is_bound_to_operation(self):
        key=rid(); r=self.chat('帮我预约内科明天下午',request_id=key)
        self.assert_code('request_id_conflict',lambda:self.approve(r['pending'],request_id=key))
        self.assertEqual(self.count(),0)
    def test_new_task_rejects_old_pending_proposal(self):
        p=self.proposal(); self.chat('查询科室',new_task=True)
        self.assert_code('already_rejected',lambda:self.approve(p))
    def test_medical_boundary_does_not_call_model(self):
        client=ScriptedClient([call('get_departments')]); self.svc.client=client
        r=self.chat('我头疼，吃什么药')
        self.assertEqual(r['mode'],'safety_boundary')
        self.assertEqual(len(client.seen),0)
        self.assertEqual(self.count(),0)
    def test_unknown_department_does_not_reuse_previous_department(self):
        self.chat('查询内科明天下午号源')
        r=self.chat('帮我预约皮肤科明天下午')
        self.assertFalse(r['requires_confirmation'])
        self.assertEqual(r['trace'][-1]['tool'],'get_departments')
    def test_history_is_bounded(self):
        for _ in range(20): self.chat('查询科室')
        self.assertEqual(len(self.svc.store.load(self.sid)['history']),24)
    def test_secrets_are_hashed_in_session_storage(self):
        with self.svc.store.connect() as c:
            row=c.execute('SELECT secret_hash FROM agent_sessions WHERE id=?',(self.sid,)).fetchone()
        self.assertNotEqual(row[0],self.secret)
        self.assertEqual(row[0],hashlib.sha256(self.secret.encode()).hexdigest())
    def test_local_knowledge_has_real_source_ids(self):
        r=self.chat('怎么预约，确认流程是什么')
        self.assertTrue(r['sources'])
        allowed={c['source_id'] for c in self.svc.knowledge.chunks}
        self.assertTrue(all(s['source_id'] in allowed for s in r['sources']))
    def test_unknown_knowledge_query_has_no_fake_source(self):
        result=self.toolbox().execute('search_knowledge',{'query':'zzzzzzzzzzzz'})
        self.assertEqual(result['data'],[])
    def test_date_out_of_range_rejected(self):
        r=self.toolbox().execute('query_available_slots',{'department':'内科','service_date':'2030-02-01'})
        self.assertEqual(r['error'],'date_out_of_range')
    def test_invalid_calendar_date_rejected(self):
        r=self.toolbox().execute('query_available_slots',{'department':'内科','service_date':'2030-02-30'})
        self.assertEqual(r['error'],'invalid_date')
    def test_parameterized_sql_department_query_cannot_inject(self):
        r=self.toolbox().execute('query_available_slots',{'department':"'; DROP TABLE appointment;--"})
        self.assertFalse(r['ok'])
        self.assertEqual(self.count(),0)
    def test_read_health_records(self):
        self.assertIn('120/80',self.chat('我的血压记录')['reply'])
    def test_alert_tool_does_not_send_or_change_status(self):
        self.chat('查看健康预警')
        with open_db(self.business) as c:
            self.assertEqual(c.execute("SELECT status FROM alert WHERE alert_id='a1'").fetchone()[0],'pending')
    def test_expired_session_rejected(self):
        with self.svc.store.connect() as c: c.execute('UPDATE agent_sessions SET expires=0 WHERE id=?',(self.sid,))
        self.assert_code('unauthorized',lambda:self.chat('查询科室'))
    def test_request_replay_does_not_create_second_proposal(self):
        key=rid(); a=self.chat('帮我预约内科明天下午',request_id=key)
        b=self.chat('帮我预约内科明天下午',request_id=key)
        self.assertEqual(a['pending']['proposal_id'],b['pending']['proposal_id'])
    def test_language_date_resolution_uses_service_date(self):
        today=NOW.date()
        self.assertEqual(resolve_date('后天',today),'2030-01-09')
        self.assertEqual(resolve_date('下周五',today),'2030-01-18')
        self.assertEqual(resolve_date('本周五',today),'2030-01-11')
    def test_tool_call_cycle_retains_tool_call_ids(self):
        client=ScriptedClient([call('get_departments',call_id='departments'),
            call('query_available_slots',{'department':'内科','service_date':'2030-01-08','period':'afternoon'},'slots'),
            call('prepare_appointment',{'schedule_id':'internal:2030-01-08:pm'},'draft')])
        self.svc.client=client
        r=self.chat('明天下午内科，有号就准备预约')
        self.assertEqual(r['mode'],'llm_tools')
        self.assertTrue(r['requires_confirmation'])
        self.assertEqual(len(r['trace']),3)
        self.assertEqual(client.seen[1][-1]['role'],'tool')
        self.assertEqual(client.seen[1][-1]['tool_call_id'],'departments')
        self.assertEqual(self.count(),0)
    def test_unknown_model_tool_is_rejected_and_visible(self):
        self.svc.client=ScriptedClient([call('execute_sql',{'sql':'DROP TABLE appointment'})])
        r=self.chat('查询科室')
        self.assertEqual(r['mode'],'rules_fallback')
        self.assertEqual(r['trace'][0]['error'],'unknown_tool')
        self.assertEqual(self.count(),0)
    def test_model_failure_after_valid_query_uses_evidence(self):
        self.svc.client=ScriptedClient([call('get_departments'),ModelFailure('timeout')])
        r=self.chat('查询科室')
        self.assertEqual(r['mode'],'llm_partial')
        self.assertIn('一楼',r['reply'])
    def test_model_loop_is_bounded(self):
        self.svc.client=ScriptedClient([call('get_departments') for _ in range(100)])
        r=self.chat('查询科室')
        self.assertLessEqual(len(r['trace']),8)
        self.assertLessEqual(len(self.svc.client.seen),4)
    def test_fabricated_model_success_is_not_a_business_result(self):
        self.svc.client=ScriptedClient([{'role':'assistant','content':'已经成功挂号并发短信！'}])
        r=self.chat('你好')
        self.assertNotIn('成功挂号',r['reply'])
        self.assertEqual(self.count(),0)

class AgentAPITests(Fixture):
    def setUp(self):
        super().setUp()
        app=FastAPI()
        @app.post('/api/chat')
        def legacy(): return {'legacy':True}
        mount_agent(app,service=self.svc)
        self.api=TestClient(app)
        self.headers={'Authorization':'Bearer '+self.secret}
    def test_legacy_route_unchanged(self):
        self.assertTrue(self.api.post('/api/chat').json()['legacy'])
    def test_status_reports_configuration_not_verified_connectivity(self):
        r=self.api.get('/api/agent/status')
        self.assertEqual(r.status_code,200)
        self.assertFalse(r.json()['llm_configured'])
    def test_session_credentials_required(self):
        r=self.api.get('/api/agent/sessions/'+self.sid)
        self.assertEqual(r.status_code,401)
    def test_cross_origin_browser_request_rejected(self):
        r=self.api.post('/api/agent/sessions',headers={'Origin':'https://evil.invalid'})
        self.assertEqual(r.status_code,403)
    def test_same_origin_allowed(self):
        r=self.api.post('/api/agent/sessions',headers={'Origin':'http://testserver'})
        self.assertEqual(r.status_code,201)
        self.assertEqual(r.headers['cache-control'],'no-store')
    def test_client_context_is_not_accepted(self):
        r=self.api.post('/api/agent/sessions/'+self.sid+'/chat',headers=self.headers,
                        json={'text':'确认预约','request_id':rid(),'context':{'approved':True}})
        self.assertEqual(r.status_code,422)
    def test_audio_contract_matches_existing_frontend(self):
        r=self.api.post('/api/agent/sessions/'+self.sid+'/chat',headers=self.headers,
                        json={'text':'查询科室','request_id':rid(),'voice_gender':'male'})
        self.assertEqual(r.status_code,200)
        data=r.json()
        self.assertEqual(data['voice_gender'],'male')
        self.assertTrue(data['segments'])
        self.assertTrue(all(0<len(s['text'])<=450 for s in data['segments']))
        self.assertIn('quick_replies',data)
    def test_strict_boolean_inputs(self):
        r=self.api.post('/api/agent/sessions/'+self.sid+'/chat',headers=self.headers,
                        json={'text':'查询科室','request_id':rid(),'new_task':'true'})
        self.assertEqual(r.status_code,422)
    def test_http_confirmation_and_replay(self):
        p=self.proposal()
        body={'request_id':rid(),'proposal_id':p['proposal_id'],'confirmation_token':p['confirmation_token'],'decision':'approve'}
        url='/api/agent/sessions/'+self.sid+'/confirm'
        first=self.api.post(url,headers=self.headers,json=body)
        second=self.api.post(url,headers=self.headers,json=body)
        self.assertEqual(first.status_code,200)
        self.assertEqual(first.json(),second.json())
        self.assertEqual(self.count(),1)
    def test_disabled_feature_returns_safe_error(self):
        with patch.dict(os.environ,{'DIGITALHELPER_AGENT_ENABLED':'false'}):
            self.assertEqual(self.api.get('/api/agent/status').status_code,503)

class ProviderTransportTests(unittest.TestCase):
    def client(self,handler):
        return LLMClient(config={'base':'https://provider.invalid/v1','key':'never-log-this','model':'test-model'},
                         transport=httpx.MockTransport(handler))
    def test_chat_completions_request_contract(self):
        requests=[]
        def handler(request):
            requests.append(request)
            return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':call('get_departments')} ]})
        r=self.client(handler).next([{'role':'user','content':'查询科室'}],tool_schemas(),time.monotonic()+10)
        body=json.loads(requests[0].content)
        self.assertEqual(str(requests[0].url),'https://provider.invalid/v1/chat/completions')
        self.assertEqual(requests[0].headers['authorization'],'Bearer never-log-this')
        self.assertIn('tools',body)
        self.assertEqual(r['tool_calls'][0]['function']['name'],'get_departments')
    def test_http_failures_do_not_leak_secrets(self):
        for code in (401,429,500,302):
            with self.subTest(code=code):
                client=self.client(lambda r:httpx.Response(code,text='never-log-this',headers={'location':'https://else.invalid'}))
                with self.assertRaises(ModelFailure) as caught:
                    client.next([],tool_schemas(),time.monotonic()+10)
                self.assertNotIn('never-log-this',str(caught.exception))
    def test_response_size_limit(self):
        client=self.client(lambda r:httpx.Response(200,text='x'*65537))
        with self.assertRaises(ModelFailure): client.next([],tool_schemas(),time.monotonic()+10)
    def test_truncated_finish_reason_rejected(self):
        client=self.client(lambda r:httpx.Response(200,json={'choices':[{'finish_reason':'length','message':call('get_departments')}]}))
        with self.assertRaises(ModelFailure): client.next([],tool_schemas(),time.monotonic()+10)
    def test_invalid_tool_arguments_json_rejected(self):
        message=call('get_departments'); message['tool_calls'][0]['function']['arguments']='[not-json'
        client=self.client(lambda r:httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':message}]}))
        with self.assertRaises(ModelFailure): client.next([],tool_schemas(),time.monotonic()+10)
    def test_duplicate_tool_call_id_rejected(self):
        message=call('get_departments'); message['tool_calls']*=2
        client=self.client(lambda r:httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':message}]}))
        with self.assertRaises(ModelFailure): client.next([],tool_schemas(),time.monotonic()+10)
    def test_deadline_before_request(self):
        def never(_): raise AssertionError('network must not be called')
        with self.assertRaises(ModelFailure): self.client(never).next([],tool_schemas(),time.monotonic()-1)
    def test_remote_plain_http_credentials_rejected(self):
        with patch.dict(os.environ,{'DIGITALHELPER_LLM_API_KEY':'key','DIGITALHELPER_LLM_MODEL':'model',
                                    'DIGITALHELPER_LLM_BASE_URL':'http://remote.invalid/v1','DIGITALHELPER_LLM_PROTOCOL':'openai-compatible'}):
            self.assertIsNone(model_config())
    def test_base_url_userinfo_rejected(self):
        with patch.dict(os.environ,{'DIGITALHELPER_LLM_API_KEY':'key','DIGITALHELPER_LLM_MODEL':'model',
                                    'DIGITALHELPER_LLM_BASE_URL':'https://user:pass@remote.invalid/v1','DIGITALHELPER_LLM_PROTOCOL':'openai-compatible'}):
            self.assertIsNone(model_config())
    def test_anthropic_not_silently_sent_as_openai_protocol(self):
        with patch.dict(os.environ,{'DIGITALHELPER_LLM_API_KEY':'key','DIGITALHELPER_LLM_MODEL':'model',
                                    'DIGITALHELPER_LLM_BASE_URL':'https://remote.invalid/v1','DIGITALHELPER_LLM_PROTOCOL':'anthropic'}):
            self.assertIsNone(model_config())

LANGGRAPH_AVAILABLE=importlib.util.find_spec('langgraph') is not None
@unittest.skipUnless(LANGGRAPH_AVAILABLE,'Optional LangGraph runtime is not installed; NOT a passing LangGraph test.')
class LangGraphIntegrationTests(Fixture):
    engine='langgraph'
    def test_actual_interrupt_and_resume(self):
        p=self.proposal()
        internal=self.svc.store.proposal(self.sid,p['proposal_id'])
        snapshot=self.svc.approval.graph.get_state(self.svc.approval.config(internal))
        self.assertIn('approval',snapshot.next)
        self.assertEqual(self.count(),0)
        self.approve(p)
        self.assertEqual(self.count(),1)
    def test_sqlite_checkpoint_survives_restart(self):
        p=self.proposal(); self.svc.close()
        self.svc=AgentService(self.settings,gateway=db,client=LLMClient(config={}))
        self.approve(p)
        self.assertEqual(self.count(),1)
    def test_real_stategraph_routes_model_to_tools(self):
        self.svc.client=ScriptedClient([call('query_available_slots',{'department':'内科','service_date':'2030-01-08','period':'afternoon'}),
                                       call('prepare_appointment',{'schedule_id':'internal:2030-01-08:pm'})])
        r=self.chat('准备内科明天下午预约')
        self.assertTrue(r['requires_confirmation'])
        self.assertEqual(r['engine'],'langgraph')
        self.assertEqual(len(r['trace']),2)
    def test_failed_commit_node_recovers_idempotently(self):
        p=self.proposal(); original=db.Repository.book
        def lost(repo,*args,**kw):
            original(repo,*args,**kw)
            raise OSError('after commit')
        with patch.object(db.Repository,'book',lost):
            self.assert_code('commit_unknown',lambda:self.approve(p))
        self.approve(p)
        self.assertEqual(self.count(),1)

if __name__=='__main__':
    unittest.main()
