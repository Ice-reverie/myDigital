"""Shared tool nodes, optional real LangGraph routing and durable HITL graph.

Native mode is explicit: it is not a mocked LangGraph and makes no Checkpoint
claim. In LangGraph mode the approval node actually interrupts and resumes from
a SqliteSaver checkpoint, including after process restart.
"""
import json
import time
from typing import TypedDict
from .llm import SYSTEM, ModelFailure
from .store import AgentError
from .tools import Toolbox, tool_schemas

class TurnState(TypedDict):
    messages: list
    calls: list
    evidence: list
    trace: list
    rounds: int
    total_calls: int
    stop: bool
    degraded: bool
    model_events: list

class ApprovalState(TypedDict):
    session_id: str
    proposal_id: str
    decision: str
    outcome: dict


def select_engine(requested):
    if requested == "native":
        return "native"
    try:
        from langgraph.graph import StateGraph  # noqa: F401
        from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: F401
    except ImportError:
        if requested == "langgraph":
            raise AgentError("missing_langgraph", "请先安装 requirements-agent.txt；或显式选择 native 演示引擎。",503)
        return "native"
    return "langgraph"


def run_model_turn(client, toolbox, text, history, budget, max_rounds, engine):
    deadline = time.monotonic()+budget
    initial: TurnState = {
        "messages":[{"role":"system","content":SYSTEM+"\n北京时间日期："+toolbox.db.now().date().isoformat()}]
                   + [{"role":h["role"],"content":h["content"][:1000]} for h in history[-12:]]
                   + [{"role":"user","content":text}],
        "calls":[],"evidence":[],"trace":[],"rounds":0,"total_calls":0,"stop":False,"degraded":False,"model_events":[],
    }

    # RUNTIME_DIAGNOSTICS_V1_1: per-turn events, no client-global mutable state.
    def model_node(state):
        event = {"round":state["rounds"]+1}
        if state["rounds"]>=max_rounds or state["total_calls"]>=8 or time.monotonic()>deadline:
            reason = ("turn_budget_exceeded" if time.monotonic()>deadline else
                      "round_limit" if state["rounds"]>=max_rounds else "call_limit")
            event.update(outcome="limit", error=reason)
            return {"stop":True,"degraded":True,"calls":[],"model_events":state["model_events"]+[event]}
        started = time.monotonic()
        try:
            message = client.next(state["messages"],tool_schemas(),deadline)
        except ModelFailure as exc:
            event.update(outcome="error", error=exc.code,
                         elapsed_ms=round((time.monotonic()-started)*1000,2))
            if exc.http_status is not None:
                event["http_status"] = exc.http_status
            return {"stop":True,"degraded":True,"calls":[],"model_events":state["model_events"]+[event]}
        calls = message.get("tool_calls",[])
        event.update(outcome="tool_calls" if calls else "normal_end", tool_count=len(calls),
                     elapsed_ms=round((time.monotonic()-started)*1000,2))
        if not calls and not state["evidence"]:
            event["error"] = "no_tool_call_before_evidence"
        return {"messages":state["messages"]+[message],"calls":calls,"rounds":state["rounds"]+1,
                "stop":not bool(calls),"model_events":state["model_events"]+[event]}

    def tools_node(state):
        messages,evidence,trace = list(state["messages"]),list(state["evidence"]),list(state["trace"])
        total = state["total_calls"]
        for call in state["calls"]:
            name = call["function"]["name"]
            start = time.monotonic()
            if total>=8 or time.monotonic()>deadline or toolbox.proposal is not None:
                result = {"ok":False,"error":"execution_stopped","message":"已达到执行边界，未继续调用工具。"}
            else:
                result = toolbox.execute(name,json.loads(call["function"]["arguments"]))
                evidence.append(result)
                total += 1
            trace.append({"origin":"llm","tool":name,"ok":result["ok"],"error":result.get("error"),
                          "elapsed_ms":round((time.monotonic()-start)*1000,2)})
            messages.append({"role":"tool","tool_call_id":call["id"],"content":json.dumps(result,ensure_ascii=False)})
        return {"messages":messages,"evidence":evidence,"trace":trace,"total_calls":total,
                "stop":toolbox.proposal is not None or total>=8,
                "degraded":state["degraded"] or (total>=8 and toolbox.proposal is None) or time.monotonic()>deadline}

    if engine == "langgraph":
        from langgraph.graph import StateGraph, START, END
        builder = StateGraph(TurnState)
        builder.add_node("model",model_node)
        builder.add_node("tools",tools_node)
        builder.add_edge(START,"model")
        builder.add_conditional_edges("model",lambda s: END if s["stop"] else "tools")
        builder.add_conditional_edges("tools",lambda s: END if s["stop"] else "model")
        return builder.compile().invoke(initial,{"recursion_limit":2*max_rounds+4})
    state = initial
    while not state["stop"]:
        state.update(model_node(state))
        if state["stop"]:
            break
        state.update(tools_node(state))
    return state

class ApprovalFlow:
    def __init__(self, engine, store, gateway, knowledge, checkpoint_path):
        self.engine,self.store,self.db,self.knowledge = engine,store,gateway,knowledge
        self.connection = None
        self.graph = None
        if engine != "langgraph":
            return
        import sqlite3
        from langgraph.graph import StateGraph, START, END
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.types import interrupt
        checkpoint_path.parent.mkdir(parents=True,exist_ok=True)
        self.connection = sqlite3.connect(checkpoint_path,check_same_thread=False,timeout=3)
        self.connection.execute("PRAGMA journal_mode=WAL")
        saver = SqliteSaver(self.connection)

        def approval(state):
            proposal = self.store.proposal(state["session_id"],state["proposal_id"])
            # No writes before interrupt: this node is re-executed on resume.
            decision = interrupt({"kind":"appointment_approval","proposal_id":proposal["id"],
                                  "selection":proposal["payload"],"fictional":True})
            if not isinstance(decision,dict) or decision.get("decision") not in {"approve","reject"}:
                raise AgentError("invalid_resume","无效确认指令。")
            return {"decision":decision["decision"]}

        def commit(state):
            p = self.store.proposal(state["session_id"],state["proposal_id"])
            if p["status"] not in {"committing","approved"}:
                raise AgentError("not_authorized","该预约未通过确认接口审批。",403)
            tools = Toolbox(self.db,self.store,self.knowledge,p["session_id"],p["request_id"],{})
            return {"outcome":p["result"] if p["status"]=="approved" else tools.commit(p)}

        def reject(state):
            self.store.set_proposal_status(state["proposal_id"],"rejected")
            return {"outcome":{"ok":True,"cancelled":True,"fictional":True}}

        builder = StateGraph(ApprovalState)
        builder.add_node("approval",approval)
        builder.add_node("commit",commit)
        builder.add_node("reject",reject)
        builder.add_edge(START,"approval")
        builder.add_conditional_edges("approval",lambda s:"commit" if s["decision"]=="approve" else "reject")
        builder.add_edge("commit",END)
        builder.add_edge("reject",END)
        self.graph = builder.compile(checkpointer=saver)

    @staticmethod
    def config(proposal):
        return {"configurable":{"thread_id":proposal["session_id"]+":"+proposal["id"]}}

    def start(self, proposal):
        if self.graph is None:
            return
        config = self.config(proposal)
        snapshot = self.graph.get_state(config)
        if not snapshot.values:
            self.graph.invoke({"session_id":proposal["session_id"],"proposal_id":proposal["id"]},config)

    def resolve(self, proposal, decision):
        if self.graph is None:
            if decision=="reject":
                self.store.set_proposal_status(proposal["id"],"rejected")
                return {"ok":True,"cancelled":True,"fictional":True}
            tools = Toolbox(self.db,self.store,self.knowledge,proposal["session_id"],proposal["request_id"],{})
            return tools.commit(proposal)
        from langgraph.types import Command
        self.start(proposal)
        config = self.config(proposal)
        snapshot = self.graph.get_state(config)
        if snapshot.next:
            # A failed commit resumes the commit node without re-requesting
            # approval. Its fixed booking token reconciles a lost DB response.
            value = Command(resume={"decision":decision}) if "approval" in snapshot.next else None
            return self.graph.invoke(value,config)["outcome"]
        return snapshot.values["outcome"]

    def close(self):
        if self.connection is not None:
            self.connection.close()
