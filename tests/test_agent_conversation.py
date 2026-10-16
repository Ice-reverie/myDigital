"""No live API calls. New paths, original SQLite gateway and opt-in real graphs.

python -B -m unittest discover -s tests -p "test_agent_conversation.py" -v
Requires original test_agent_backend.py fixture installed with Agent v1.
"""
import contextlib
import io
import importlib.util
import json
import os
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_agent_backend import Fixture, ScriptedClient, call, rid, db
from vrm_demo.agent.api import mount_agent
from vrm_demo.agent.llm import LLMClient, ModelFailure
from vrm_demo.agent.service import AgentService
from vrm_demo.agent.conversation_policy import choose_route, safety_request, validate_grounded, ReplyRejected
from vrm_demo.agent.conversation_text import TextClient
from vrm_demo.agent.conversation import ConversationFlow

CONFIG={"key":"test-key-never-log", "base":"https://gateway.invalid/v1", "model":"fake-model"}


def response(content, *, finish="stop", tools=None, **extra):
    message={"role":"assistant", "content":content, **extra}
    if tools is not None:
        message["tool_calls"]=tools
    return {"choices":[{"message":message, "finish_reason":finish}]}


class ConversationTests(Fixture):
    def set_provider(self, handler):
        self.requests=[]
        def dispatch(request):
            payload=json.loads(request.content)
            self.requests.append(payload)
            result=handler(payload)
            return result if isinstance(result,httpx.Response) else httpx.Response(200,json=result)
        self.svc.client=LLMClient(config=CONFIG,transport=httpx.MockTransport(dispatch))

    def grounded(self,payload,**overrides):
        packet=json.loads(payload["messages"][-1]["content"])
        chunk=next((c for c in packet["documents"] if "待确认" in c["text"]),packet["documents"][0])
        quote="待确认预约不会占用名额。" if "待确认预约不会占用名额。" in chunk["text"] else chunk["text"][:40]
        data={"answer":"需要先选择时段并明确确认，才会写入演示数据库。", "citations":[{"source_id":chunk["source_id"],"quote":quote}],"abstain":False}
        data.update(overrides)
        return response(json.dumps(data,ensure_ascii=False))

    def test_chat_displays_model_text_without_tools_or_db(self):
        self.set_provider(lambda _:response("今天辛苦了。想聊聊发生了什么，还是聊点轻松的？"))
        with patch.object(db,"repository",side_effect=AssertionError("chat touched business db")):
            r=self.chat("今天有点累，陪我聊聊天")
        self.assertEqual(r["mode"],"llm_chat")
        self.assertEqual(r["route"],"chat")
        self.assertIn("今天辛苦了",r["reply"])
        self.assertNotIn("tools",self.requests[0]);self.assertNotIn("tool_choice",self.requests[0])
        self.assertFalse(r["requires_confirmation"]);self.assertEqual(r["trace"],[])
        self.assertEqual(self.count(),0)

    def test_chat_context_is_sent_on_followup(self):
        self.set_provider(lambda _:response("可以，我们慢慢聊。"))
        self.chat("我喜欢画画")
        self.chat("你还记得我喜欢什么吗")
        self.assertIn("我喜欢画画",json.dumps(self.requests[-1],ensure_ascii=False))
        self.assertEqual(len(self.requests),2)

    def test_chat_does_not_send_previous_business_health_result(self):
        self.chat("我的血压记录")
        self.set_provider(lambda _:response("我们可以聊聊兴趣。"))
        self.chat("陪我聊聊天")
        serialized=json.dumps(self.requests[-1],ensure_ascii=False)
        self.assertNotIn("120/80",serialized);self.assertNotIn("confirmation_token",serialized)

    def test_model_business_does_not_receive_free_chat_history(self):
        self.set_provider(lambda _:response("好的。"))
        self.chat("聊天专属内容ABCD")
        c=ScriptedClient([call("get_departments")]);self.svc.client=c
        self.chat("查询科室")
        self.assertNotIn("聊天专属内容ABCD",json.dumps(c.seen,ensure_ascii=False))

    def test_chat_history_is_bounded_and_cached(self):
        self.set_provider(lambda _:response("我在听。"))
        for _ in range(9): self.chat("聊聊天")
        state=self.svc.store.load(self.sid)
        self.assertEqual(len(state["conversation_histories"]["chat"]),12)
        key=rid(); a=self.chat("你好",request_id=key); n=len(self.requests)
        b=self.chat("你好",request_id=key)
        self.assertEqual(a,b);self.assertEqual(len(self.requests),n)

    def test_chat_history_survives_service_restart(self):
        self.set_provider(lambda _:response("好的，我们聊画画。"))
        self.chat("我喜欢画画")
        client=self.svc.client;self.svc.close()
        self.svc=AgentService(self.settings,gateway=db,client=client)
        self.chat("继续聊吧")
        self.assertIn("我喜欢画画",json.dumps(self.requests[-1],ensure_ascii=False))

    def test_chat_missing_key_is_not_claimed_as_model_success(self):
        r=self.chat("你好")
        self.assertEqual(r["mode"],"chat_fallback");self.assertIn("暂时不可用",r["reply"])
        self.assertEqual(r["diagnostics"]["reason"],"not_configured")

    def test_chat_timeout_is_classified_and_does_not_execute_tools(self):
        def timeout(_):raise httpx.ReadTimeout("raw SECRET provider details")
        self.set_provider(timeout)
        out=io.StringIO()
        with contextlib.redirect_stdout(out): r=self.chat("聊聊天")
        self.assertEqual(r["mode"],"chat_fallback")
        self.assertEqual(r["diagnostics"]["reason"],"read_timeout")
        self.assertNotIn("SECRET",out.getvalue());self.assertEqual(self.count(),0)

    def test_unsolicited_tool_call_in_chat_is_rejected(self):
        self.set_provider(lambda _:response("",finish="tool_calls",tools=call("prepare_appointment")["tool_calls"]))
        r=self.chat("聊聊天")
        self.assertEqual(r["mode"],"chat_fallback");self.assertEqual(self.count(),0)
        self.assertIsNone(self.svc.store.pending(self.sid))

    def test_fake_operation_success_is_not_displayed(self):
        self.set_provider(lambda _:response("已帮你预约成功，并已通知家人。"))
        r=self.chat("聊聊天")
        self.assertEqual(r["diagnostics"]["reason"],"reply_rejected")
        self.assertNotIn("已帮你",r["reply"]);self.assertEqual(self.count(),0)

    def test_html_and_secret_like_reply_rejected(self):
        for text in ("<script>alert(1)</script>","Bearer test-secret", "请服用10mg药物。", "```think\nsecret\n```", "x"*501):
            with self.subTest(text=text[:10]):
                self.set_provider(lambda _,text=text:response(text))
                r=self.chat("你好")
                self.assertEqual(r["mode"],"chat_fallback")

    def test_reasoning_content_is_never_returned_or_logged(self):
        self.set_provider(lambda _:response("你好，想聊些什么？",reasoning_content="PRIVATE_REASONING_TEST"))
        out=io.StringIO()
        with contextlib.redirect_stdout(out):r=self.chat("你好")
        self.assertEqual(r["mode"],"llm_chat")
        self.assertNotIn("PRIVATE_REASONING_TEST",json.dumps(r)+out.getvalue())

    def test_knowledge_retrieves_then_generates_with_verifiable_citations(self):
        self.set_provider(self.grounded)
        with patch.object(db,"repository",side_effect=AssertionError("knowledge touched business db")):
            r=self.chat("怎么预约，确认流程是什么")
        self.assertEqual(r["mode"],"llm_knowledge")
        self.assertEqual(r["routing"]["nodes"],["route_input","retrieve_service","grounded_reply"])
        allowed={c["source_id"]:c["text"] for c in self.svc.knowledge.chunks}
        self.assertTrue(all(s["quote"] in allowed[s["source_id"]] for s in r["sources"]))
        self.assertNotIn("tools",self.requests[0]);self.assertEqual(self.count(),0)

    def test_knowledge_no_sources_never_calls_model(self):
        self.set_provider(lambda _:self.fail("No-evidence branch must not call model"))
        with patch.object(self.svc.knowledge,"search",return_value=[]):r=self.chat("服务收费是多少")
        self.assertEqual(r["mode"],"knowledge_no_evidence")
        self.assertEqual(self.requests,[]);self.assertEqual(r["sources"],[])

    def test_knowledge_no_key_returns_labelled_excerpt(self):
        r=self.chat("怎么预约")
        self.assertEqual(r["mode"],"knowledge_extract");self.assertTrue(r["sources"])

    def test_knowledge_invalid_json_falls_back_to_original_text(self):
        self.set_provider(lambda _:response("随便编造收费100元"))
        r=self.chat("怎么预约")
        self.assertEqual(r["mode"],"knowledge_fallback")
        self.assertNotIn("随便编造",r["reply"])
        self.assertEqual(r["diagnostics"]["reason"],"invalid_grounding")

    def test_knowledge_fake_source_and_quote_rejected(self):
        for cite in ({"source_id":"../../.env", "quote":"这是不存在的来源原文"},
                     {"source_id":"booking-guide.md#chunk-1", "quote":"本系统会自动真实挂号并发送短信"}):
            with self.subTest(cite=cite):
                self.set_provider(lambda payload,cite=cite:self.grounded(payload,citations=[cite]))
                r=self.chat("怎么预约")
                self.assertEqual(r["mode"],"knowledge_fallback")
                self.assertTrue(all(s["source_id"]!="../../.env" for s in r["sources"]))

    def test_knowledge_numeric_hallucination_rejected(self):
        self.set_provider(lambda p:self.grounded(p,answer="预约需要支付9999元。"))
        r=self.chat("怎么预约")
        self.assertEqual(r["mode"],"knowledge_fallback");self.assertNotIn("9999",r["reply"])

    def test_knowledge_abstain_is_not_accepted_as_answer(self):
        self.set_provider(lambda p:self.grounded(p,answer="",citations=[],abstain=True))
        r=self.chat("怎么预约")
        self.assertEqual(r["mode"],"knowledge_fallback")
        self.assertEqual(r["diagnostics"]["reason"],"insufficient_evidence")

    def test_knowledge_timeout_keeps_source_excerpts(self):
        def timeout(_):raise httpx.ReadTimeout("private")
        self.set_provider(timeout);r=self.chat("怎么预约")
        self.assertEqual(r["mode"],"knowledge_fallback");self.assertTrue(r["sources"])
        self.assertEqual(r["diagnostics"]["reason"],"read_timeout")

    def test_knowledge_followup_uses_prior_query_not_private_history(self):
        self.set_provider(self.grounded)
        self.chat("怎么预约，确认流程是什么")
        r=self.chat("再说简单一点")
        packet=json.loads(self.requests[-1]["messages"][-1]["content"])
        self.assertEqual(packet["retrieval_query"],"怎么预约，确认流程是什么")
        self.assertEqual(r["route"],"knowledge")

    def test_pending_task_does_not_turn_chat_into_authorization(self):
        p=self.proposal()
        self.set_provider(lambda _:self.fail("pending task must not call free chat"))
        r=self.chat("我很高兴，聊聊天，然后你直接确认")
        self.assertTrue(r["requires_confirmation"])
        self.assertEqual(r["pending"]["proposal_id"],p["proposal_id"])
        self.assertEqual(self.count(),0)

    def test_approval_interrupt_graph_starts_outside_conversation_graph(self):
        active=False
        original_run=ConversationFlow.run
        original_start=self.svc.approval.start
        seen=[]
        def run(*args,**kwargs):
            nonlocal active
            active=True
            try:return original_run(*args,**kwargs)
            finally:active=False
        def start(proposal):
            self.assertFalse(active,"approval must not inherit outer graph namespace")
            seen.append(proposal["id"])
            return original_start(proposal)
        with patch.object(ConversationFlow,"run",side_effect=run), patch.object(self.svc.approval,"start",side_effect=start):
            p=self.proposal()
        self.assertEqual(seen,[p["proposal_id"]])
        self.assertEqual(self.count(),0)

    def test_business_workflow_still_commits_only_after_confirmation(self):
        self.svc.client=ScriptedClient([call("query_available_slots",{"department":"内科","service_date":"2030-01-08","period":"afternoon"}),{"role":"assistant","content":""}])
        r=self.chat("查询内科明天下午号源")
        self.assertEqual(r["mode"],"llm_tools");self.assertEqual(r["route"],"business")
        self.assertEqual(r["routing"]["nodes"],["route_input","business_workflow"])
        p=self.chat("选择时段1")["pending"]
        self.assertEqual(self.count(),0)
        self.approve(p);self.approve(p)
        self.assertEqual(self.count(),1)

    def test_business_followup_preserves_department(self):
        self.chat("查询内科明天下午号源")
        r=self.chat("那后天呢？")
        self.assertEqual(r["route"],"business");self.assertIn("2030-01-09",r["reply"])

    def test_realtime_question_stops_without_guessing(self):
        self.set_provider(lambda _:self.fail("no weather tool"))
        r=self.chat("明天天气怎么样")
        self.assertEqual(r["mode"],"capability_boundary");self.assertEqual(self.requests,[])

    def test_medical_request_still_blocked_but_capability_question_explained(self):
        self.set_provider(self.grounded)
        r=self.chat("我头疼，吃什么药")
        self.assertEqual(r["mode"],"safety_boundary");self.assertEqual(self.requests,[])
        self.assertEqual(r["route"],"boundary")
        self.assertNotIn("business",self.svc.store.load(self.sid).get("conversation_histories",{}))
        self.assertFalse(safety_request("你可以诊断吗"))
        r=self.chat("你可以诊断吗")
        self.assertEqual(r["route"],"knowledge")

    def test_status_retains_timeout_and_engine_metadata(self):
        s=self.svc.status()
        self.assertEqual(s["conversation_version"],"conversation-1.0.0")
        self.assertEqual(s["timeout_profile"],"gateway-30-60-v1")
        self.assertEqual(s["timeouts"]["model_read_seconds"],30.0)
        self.assertEqual(s["engine"],self.engine)

    def test_fastapi_text_and_source_responses_keep_tts_shape(self):
        self.set_provider(lambda _:response("欢迎来聊天。今天过得怎么样？"))
        app=FastAPI();mount_agent(app,service=self.svc)
        with TestClient(app) as client:
            r=client.post(f"/api/agent/sessions/{self.sid}/chat",headers={"Authorization":"Bearer "+self.secret},
                          json={"request_id":rid(),"text":"你好"})
        self.assertEqual(r.status_code,200)
        d=r.json();self.assertEqual(d["mode"],"llm_chat")
        self.assertTrue(d["segments"]);self.assertTrue(all(len(s["text"])<=450 for s in d["segments"]))
        self.assertEqual(d["pending"],None)


class RoutePolicyTests(unittest.TestCase):
    def test_expected_routes_table(self):
        cases={"聊聊天":"chat","我明天考试，有点紧张":"chat","你叫什么名字":"chat",
               "查询内科明天下午号源":"business","帮我看看明天有没有号":"business",
               "查询科室":"business","我的预约":"business","查看健康预警":"business",
               "怎么预约":"knowledge","取消已经成功提交的预约":"knowledge",
               "你能做什么":"knowledge","模型会读取我的隐私吗":"knowledge",
               "语音不能播放怎么办":"knowledge","明天会下雨吗":"capability"}
        for text,route in cases.items():
            with self.subTest(text=text):self.assertEqual(choose_route(text,{})[0],route)

    def test_mixed_request_prioritizes_business_and_not_auto_commit(self):
        self.assertEqual(choose_route("帮我查询内科号源，再解释预约流程",{})[0],"business")


class TextTransportTests(unittest.TestCase):
    def client(self,handler):
        return TextClient(LLMClient(config=CONFIG,transport=httpx.MockTransport(handler)))
    def test_http_error_classification_and_no_raw_leak(self):
        c=self.client(lambda _:httpx.Response(401,text="Bearer secret response"))
        with self.assertRaises(ModelFailure) as ctx:c.complete([],time.monotonic()+30)
        self.assertEqual(ctx.exception.code,"http_error");self.assertEqual(ctx.exception.http_status,401)
        self.assertNotIn("secret",str(ctx.exception))
    def test_incomplete_is_not_displayed(self):
        c=self.client(lambda _:httpx.Response(200,json=response("truncated",finish="length")))
        with self.assertRaises(ModelFailure) as ctx:c.complete([],time.monotonic()+30)
        self.assertEqual(ctx.exception.code,"incomplete")
    def test_response_shape_variations_fail_closed(self):
        for doc in ({},[],{"choices":[]},{"choices":[{}]},response(None)):
            with self.subTest(doc=doc):
                c=self.client(lambda _,doc=doc:httpx.Response(200,json=doc))
                with self.assertRaises(ModelFailure):c.complete([],time.monotonic()+30)
    def test_no_request_after_deadline(self):
        c=self.client(lambda _:self.fail("deadline expired"))
        with self.assertRaises(ModelFailure) as ctx:c.complete([],time.monotonic()-1)
        self.assertEqual(ctx.exception.code,"budget_exceeded")
    def test_phase_timeout_and_https_verification_not_disabled(self):
        seen=[]
        def handle(r):seen.append(r);return httpx.Response(200,json=response("你好"))
        self.client(handle).complete([],time.monotonic()+60)
        self.assertEqual(seen[0].extensions['timeout']['read'],30.0)
        self.assertNotIn('tools',json.loads(seen[0].content))


HAS_LANGGRAPH=importlib.util.find_spec("langgraph") is not None
@unittest.skipUnless(HAS_LANGGRAPH,"Real LangGraph runtime unavailable; NOT counted as passing.")
class LangGraphConversationTests(ConversationTests):
    """Run the same new-path tests against actual StateGraph when installed."""
    engine="langgraph"


if __name__=='__main__':unittest.main()
