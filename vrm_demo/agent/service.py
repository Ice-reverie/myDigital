"""Application boundary: authorization, confirmation, persistence and evidence."""
import hmac
import time
from .config import Settings
from .graph import ApprovalFlow, run_model_turn, select_engine
from .knowledge import KnowledgeIndex
from .llm import LLMClient
from .policy import medical_request, native_turn, selected_index
from .store import Store, AgentError, digest, encode
from .tools import Toolbox

NOTICE = "仅操作虚构演示数据，不连接医院，不提供诊断，不发送通知。"

# RUNTIME_DIAGNOSTICS_V1_1. Enum-only report: no prompts, arguments, IDs, keys,
# model text/reasoning, tool results, database paths or raw upstream errors.
def model_diagnostics(turn):
    from .llm import MODEL_FAILURE_CODES
    from .tools import SPECS
    model_errors = MODEL_FAILURE_CODES | {
        "no_tool_call_before_evidence", "turn_budget_exceeded", "round_limit", "call_limit",
    }
    tool_errors = {
        "unknown_tool", "invalid_arguments", "database_unavailable", "invalid_date",
        "date_out_of_range", "department_required", "unobserved_slot", "slot_unavailable",
        "execution_stopped", "session_busy", "session_expired", "unauthorized",
    }
    events = []
    for source in turn.get("model_events", [])[:8]:
        event = {"round":source.get("round", 0),
                 "outcome":source.get("outcome") if source.get("outcome") in
                           {"error", "limit", "tool_calls", "normal_end"} else "unknown"}
        for key in ("elapsed_ms", "tool_count", "http_status"):
            value=source.get(key)
            if type(value) in (int, float):
                event[key]=value
        if source.get("error"):
            event["error"] = source["error"] if source["error"] in model_errors else "unknown_model_error"
        events.append(event)
    tools=[]
    for source in turn.get("trace", [])[:16]:
        event={"tool":source.get("tool") if source.get("tool") in SPECS else "unknown_tool",
               "ok":source.get("ok") is True}
        if source.get("error"):
            event["error"]=source["error"] if source["error"] in tool_errors else "other_tool_error"
        tools.append(event)
    errors=[e["error"] for e in events if e.get("error")]
    tool_failures=[t["error"] for t in tools if t.get("error")]
    any_success=any(e.get("ok") for e in turn.get("evidence", []))
    recovered = any_success and turn["evidence"][-1].get("ok") and not turn.get("degraded")
    reason=("completed" if recovered else errors[-1] if errors else tool_failures[-1] if tool_failures else
            "tool_loop_limit" if turn.get("degraded") else
            "completed" if any_success else "no_successful_tool_result")
    return {"version":"1.1.0", "reason":reason, "model_events":events,
            "model_tools":tools, "model_rounds":turn.get("rounds",0),
            "successful_model_tools":sum(t["ok"] for t in tools)}

class AgentService:
    def __init__(self, settings=None, gateway=None, client=None):
        self.settings=settings or Settings.from_env()
        if gateway is None:
            from .. import database_gateway
            gateway=database_gateway
        self.db=gateway
        self.engine=select_engine(self.settings.engine)
        self.store=Store(self.settings.state_path,self.settings.session_ttl,self.settings.approval_ttl)
        self.knowledge=KnowledgeIndex(self.settings.knowledge_path)
        self.client=client if client is not None else LLMClient()
        self.approval=ApprovalFlow(self.engine,self.store,self.db,self.knowledge,self.settings.checkpoint_path)

    def status(self):
        return {"enabled":True,"engine":self.engine,"llm_configured":self.client.configured,
                "llm_protocol":"openai-compatible tool_calls", "database_enabled":self.db.enabled(),
                "knowledge_chunks":len(self.knowledge.chunks),"notice":NOTICE,
                "mode":"llm_tools" if self.client.configured else "rules_demo", "diagnostics_version":"1.1.0"}

    def create_session(self):
        return self.store.create_session() | {"notice":NOTICE}

    def state(self,sid,secret):
        self.store.authenticate(sid,secret)
        state=self.store.load(sid)
        proposal=self.store.pending(sid)
        # Do not redisplay an expired confirmation card as though still valid.
        last=state.get("last_response")
        if last and last.get("requires_confirmation") and proposal is None:
            last=None
        return {"session_id":sid,"pending":self.public_proposal(proposal),
                "last_response":last,"history":state["history"][-12:],"notice":NOTICE}

    @staticmethod
    def public_proposal(proposal):
        if not proposal:
            return None
        return {"proposal_id":proposal["id"],"confirmation_token":proposal["token"],
                "expires_at":proposal["expires"],"status":proposal["status"],"selection":proposal["payload"]}

    def response(self,sid,reply,*,action="explain",quick=None,proposal=None,trace=None,sources=None,mode="rules_demo"):
        return {"session_id":sid,"reply":reply,"action":action,"quick_replies":quick or [],
                "context":{"flow":"agent","step":"confirmation"} if proposal else {},
                "requires_confirmation":proposal is not None,"pending":self.public_proposal(proposal),
                "trace":trace or [],"sources":sources or [],"engine":self.engine,"mode":mode,"notice":NOTICE}

    def proposal_response(self,sid,p,trace=None,mode="rules_demo"):
        item=p["payload"]
        if p["status"]=="committing":
            return self.response(sid,
                f"{item['department']}，{item['service_date']} {item['slot_name']}的提交结果待核实。"
                "请重试原确认请求以核实同一预约，不要新建或取消。",
                action="booking",quick=["确认模拟预约"],proposal=p,trace=trace,mode=mode)
        return self.response(sid,
            f"请确认模拟预约：{item['department']}，{item['service_date']} {item['slot_name']}。"
            "此时尚未占用名额。确认后只写入演示数据库，不会真实挂号。",
            action="booking",quick=["确认模拟预约","取消本次操作"],proposal=p,trace=trace,mode=mode)

    def from_evidence(self,sid,turn,mode):
        facts=turn["evidence"]
        trace=turn["trace"]
        if not facts:
            return self.response(sid,"可以查询演示科室、号源、预约记录及服务说明。请说出科室和日期。",
                                 quick=["查询科室","查询内科明天下午号源","我的预约"],trace=trace,mode=mode)
        fact=facts[-1]
        if not fact["ok"]:
            return self.response(sid,fact["message"],quick=["查询科室"],trace=trace,mode=mode)
        tool,data=fact["tool"],fact["data"]
        if tool=="query_available_slots":
            slots=data["slots"]
            if not slots:
                return self.response(sid,"在所选条件下没有可用的演示号源。没有生成或提交预约。请换日期或时段。",trace=trace,mode=mode)
            lines=[f"{i+1}. {s['department']}，{s['service_date']} {s['slot_name']}，余号{s['remaining']}。" for i,s in enumerate(slots)]
            return self.response(sid,"查到以下虚构演示号源：\n"+"\n".join(lines)+"\n请选择时段，选择后仍需确认。",
                                 action="booking",quick=[f"选择时段{i+1}" for i in range(len(slots))],trace=trace,mode=mode)
        if tool=="get_departments":
            text="；".join(f"{d['dept_name']}：{d['location']}" for d in data)
            return self.response(sid,"演示科室信息："+text if text else "暂无演示科室数据。",
                                 quick=[d["dept_name"] for d in data[:8]],trace=trace,mode=mode)
        if tool=="get_appointments":
            text="；".join(f"{d['dept_name']} {str(d['service_date'])[:10]} {d['slot_name']}（序号{d['queue_no']}）" for d in data)
            return self.response(sid,"虚构用户的模拟预约记录："+text if text else "暂无演示预约记录。",trace=trace,mode=mode)
        if tool=="get_health_records":
            text="；".join(f"{str(d['recorded_at'])[:10]}：{d['content']}" for d in data)
            return self.response(sid,("虚构演示记录："+text+"。不用于诊断。") if text else "暂无对应演示记录。",trace=trace,mode=mode)
        if tool=="get_health_alerts":
            text="；".join(f"{d['alert_content']}（状态：{d['status']}）" for d in data)
            return self.response(sid,("虚构演示预警："+text+"。本功能只查询，不发送提醒。") if text else "暂无演示预警。",trace=trace,mode=mode)
        if tool=="search_knowledge":
            sources=[{"source_id":d["source_id"],"title":d["title"]} for d in data]
            text="\n".join(d["text"] for d in data[:2])
            return self.response(sid,"项目服务资料：\n"+text if text else "本地服务文档没有找到依据；不编造回答。",
                                 trace=trace,sources=sources,mode=mode)
        return self.response(sid,"查询已完成。",trace=trace,mode=mode)

    @staticmethod
    def add_history(state,text,reply):
        state["history"]=(state.get("history",[])+[{"role":"user","content":text[:500]},
                           {"role":"assistant","content":reply[:1500]}])[-24:]

    def chat(self,sid,secret,request):
        self.store.authenticate(sid,secret)
        fingerprint=digest(encode({"operation":"chat",**request.model_dump()}))
        start=time.monotonic()
        with self.store.lease(sid):
            cached=self.store.cached(sid,request.request_id,fingerprint)
            if cached is not None:
                if cached.get("requires_confirmation"):
                    p=self.store.proposal(sid,cached["pending"]["proposal_id"])
                    if p["status"]=="pending" and p["expires"]<time.time():
                        self.store.set_proposal_status(p["id"],"expired")
                        p["status"]="expired"
                    if p["status"]=="committing":
                        return self.proposal_response(sid,p,mode="recovered_result") | {"request_id":request.request_id}
                    if p["status"] not in {"pending","committing"}:
                        if p["status"]=="approved":
                            reply="此前这条模拟预约已经提交，演示序号为"+str(p["result"]["queue_no"])+"。无需再次新建预约。"
                        elif p["status"]=="failed":
                            reply=p["result"]["message"]
                        else:
                            reply="此前的待确认预约已取消或过期，请重新查询。"
                        return self.response(sid,reply,mode="recovered_result") | {"request_id":request.request_id}
                return cached
            state=self.store.load(sid)
            pending=self.store.pending(sid)
            diagnostics = None
            mode="llm_tools" if self.client.configured else "rules_demo"
            if pending and request.new_task:
                if pending["status"]=="committing":
                    raise AgentError("commit_in_progress","请先核实正在提交的预约结果。",409)
                self.approval.resolve(pending,"reject")
                pending=None
            if request.new_task:
                state["preferences"],state["eligible_slots"]={},{}
            if pending:
                # Merely saying 'confirm' to the chat API has no write authority.
                response=self.proposal_response(sid,pending,mode=mode)
            elif request.text.strip() in {"取消本次操作","取消预约"}:
                state["preferences"],state["eligible_slots"]={},{}
                response=self.response(sid,"已停止本次未提交的操作。不会撤销已提交的模拟预约。",mode=mode)
            elif medical_request(request.text):
                response=self.response(sid,"这里是虚构医院服务演示，不判断病情、不提供诊断或用药建议。可以为您查询科室和演示号源。",
                                       quick=["查询科室"],mode="safety_boundary")
            else:
                toolbox=Toolbox(self.db,self.store,self.knowledge,sid,request.request_id,state)
                if self.client.configured and selected_index(request.text) is None:
                    turn=run_model_turn(self.client,toolbox,request.text,state["history"],
                                        self.settings.model_budget,self.settings.max_rounds,self.engine)
                    diagnostics = model_diagnostics(turn)
                    if not any(e.get("ok") for e in turn["evidence"]):
                        fallback=native_turn(toolbox,request.text)
                        fallback["trace"]=turn["trace"]+[dict(item,origin="rules") for item in fallback["trace"]]
                        turn=fallback
                        mode="rules_fallback"
                    elif turn["degraded"] or not turn["evidence"][-1].get("ok"):
                        mode="llm_partial"
                else:
                    turn=native_turn(toolbox,request.text)
                    if self.client.configured:
                        mode="explicit_selection"
                if toolbox.proposal is not None:
                    self.approval.start(toolbox.proposal)
                    response=self.proposal_response(sid,toolbox.proposal,turn["trace"],mode)
                else:
                    response=self.from_evidence(sid,turn,mode)
            if diagnostics is not None:
                response["diagnostics"] = diagnostics
                # Only the allow-listed summary is logged. No response/proposal objects.
                print("[AgentRuntime] " + encode({"mode":mode, **diagnostics}), flush=True)
            response["request_id"]=request.request_id
            response["elapsed_ms"]=round((time.monotonic()-start)*1000,2)
            self.add_history(state,request.text,response["reply"])
            self.store.complete(sid,request.request_id,fingerprint,response,state)
            return response

    def confirm(self,sid,secret,request):
        self.store.authenticate(sid,secret)
        fingerprint=digest(encode({"operation":"confirm",**request.model_dump()}))
        with self.store.lease(sid):
            cached=self.store.cached(sid,request.request_id,fingerprint)
            if cached is not None:
                return cached
            p=self.store.proposal(sid,request.proposal_id)
            if not hmac.compare_digest(p["token"],request.confirmation_token):
                raise AgentError("invalid_confirmation","确认令牌与当前待确认预约不匹配。",403)
            status=p["status"]
            if status=="approved":
                if request.decision!="approve":
                    raise AgentError("already_committed","预约已经提交；本接口不能撤销已提交记录。",409)
                outcome=p["result"]
            elif status=="rejected":
                if request.decision!="reject":
                    raise AgentError("already_rejected","该待确认预约已取消，请重新选择。",409)
                outcome={"ok":True,"cancelled":True,"fictional":True}
            elif status=="failed":
                outcome=p["result"]
            elif status=="expired" or status=="pending" and p["expires"]<time.time():
                self.store.set_proposal_status(p["id"],"expired")
                raise AgentError("approval_expired","确认已过期，请重新查询并选择时段。",409)
            else:
                if status=="committing" and request.decision!="approve":
                    raise AgentError("commit_unknown","提交结果待核实，不能把它当作未提交而取消；请重试原确认。",409)
                if request.decision=="approve":
                    self.store.set_proposal_status(p["id"],"committing")
                    p=self.store.proposal(sid,p["id"])
                outcome=self.approval.resolve(p,request.decision)
            state=self.store.load(sid)
            state["eligible_slots"]={}
            if outcome.get("cancelled"):
                reply="已取消本次待确认预约，没有提交这条模拟预约。"
            elif outcome["ok"]:
                d=outcome["selection"]
                reply=(f"已完成模拟预约：{d['department']}，{d['service_date']} {d['slot_name']}，演示序号{outcome['queue_no']}。"
                       "只写入了虚构演示数据库，不会产生真实挂号记录。")
            else:
                reply=outcome["message"]
            response=self.response(sid,reply,action="confirm",mode="confirmed_action")
            response["request_id"]=request.request_id
            response["operation_result"]=outcome
            self.add_history(state,"确认模拟预约" if request.decision=="approve" else "取消本次操作",reply)
            self.store.complete(sid,request.request_id,fingerprint,response,state)
            return response

    def close(self):
        self.approval.close()
