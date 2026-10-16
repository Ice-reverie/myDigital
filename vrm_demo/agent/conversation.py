"""Three-path dialogue graph: conversation / service evidence / business.

The routing node uses a documented deterministic policy, NOT an extra LLM call.
Ordinary chat and knowledge answers never receive business tools or DB history.
Only the business callback can reach the original, gated business orchestrator.
"""
from __future__ import annotations
import json
import re
import time
from typing import TypedDict
from .conversation_policy import (VERSION, CHAT_SYSTEM, KNOWLEDGE_SYSTEM, ReplyRejected,
                                  check_text, choose_route, validate_grounded)
from .conversation_text import TextClient
from .knowledge_generation import KnowledgeClient, COMPACT_SYSTEM, MAX_OUTPUT_TOKENS, PROFILE, evidence_for_prompt
from .knowledge import tokens
from .llm import ModelFailure


class ConversationState(TypedDict, total=False):
    route: str
    route_reason: str
    path: list[str]
    chunks: list[dict]
    response: dict


class ConversationFlow:
    """Per-request StateGraph with invocation-local closures; no shared dialogue state."""
    @staticmethod
    def run(engine: str, route, chat, retrieve, answer, business, capability):
        initial: ConversationState = {"path": []}
        functions = {"route_input": route, "chat_reply": chat, "retrieve_service": retrieve,
                     "grounded_reply": answer, "business_workflow": business,
                     "capability_reply": capability}
        destinations = {"chat": "chat_reply", "knowledge": "retrieve_service",
                        "business": "business_workflow", "capability": "capability_reply"}
        if engine == "langgraph":
            from langgraph.graph import StateGraph, START, END
            builder = StateGraph(ConversationState)
            for name, function in functions.items():
                builder.add_node(name, function)
            builder.add_edge(START, "route_input")
            builder.add_conditional_edges("route_input", lambda s: s["route"], destinations)
            builder.add_edge("retrieve_service", "grounded_reply")
            for name in ("chat_reply", "grounded_reply", "business_workflow", "capability_reply"):
                builder.add_edge(name, END)
            # Conversation histories are persisted by the application, not this
            # transient graph. ApprovalFlow keeps its own durable checkpointer.
            return builder.compile().invoke(initial, {"recursion_limit": 8})
        state = dict(initial)
        state.update(route(state))
        name = destinations[state["route"]]
        state.update(functions[name](state))
        if name == "retrieve_service":
            state.update(answer(state))
        return state


def public_text_diagnostics(route, reason, events=None, *, chunks=0):
    return {"version": VERSION, "route": route, "reason": reason,
            "model_events": events or [], "model_tools": [],
            "model_rounds": sum(e.get("outcome") == "normal_end" for e in (events or [])),
            "successful_model_tools": 0, "retrieved_chunks": chunks}


def remember_route(state: dict, text: str, response: dict):
    route = response.get("route")
    if route not in {"chat", "knowledge", "business"}:
        return
    histories = state.setdefault("conversation_histories", {})
    histories[route] = (histories.get(route, []) + [
        {"role": "user", "content": text[:500]},
        {"role": "assistant", "content": response["reply"][:1500]},
    ])[-12:]
    state["conversation_last_route"] = route
    if route == "knowledge" and response.get("knowledge_query"):
        state["conversation_knowledge_query"] = response["knowledge_query"][:200]


def history_for(state: dict, route: str) -> list[dict]:
    # No migration of legacy mixed histories into free chat: this intentionally
    # prevents health/appointment data from being replayed to the chat model.
    return [{"role": h["role"], "content": h["content"][:1000]}
            for h in state.get("conversation_histories", {}).get(route, [])[-10:]
            if h.get("role") in {"user", "assistant"} and isinstance(h.get("content"), str)]


def retrieve_chunks(knowledge, query: str) -> list[dict]:
    found = knowledge.search(query[:200], limit=3)
    # Remove hits supported ONLY by generic words shared by nearly all queries.
    generic = set(tokens("这个项目系统请问什么怎么如何可以一下说明服务需要还有"))
    q = set(tokens(query)) - generic
    return [c for c in found if q & set(tokens(c["text"]))][:3]


def excerpt_response(service, sid, chunks, *, mode, reason, events=None):
    sources = [{"source_id": c["source_id"], "title": c["title"], "quote": c["text"][:350]} for c in chunks[:2]]
    reply = ("已找到相关服务资料，但这次未生成完整的模型回答。请展开“查看本轮资料依据”查看原文，"
             "或稍后重新提问。这不是已完成业务操作的通知。")
    result = service.response(sid, reply, sources=sources, mode=mode)
    result["diagnostics"] = public_text_diagnostics("knowledge", reason, events, chunks=len(chunks))
    return result


def run_conversation(service, sid: str, request, state: dict, business):
    deadline = time.monotonic() + service.settings.model_budget
    text = request.text
    # Optional test injection. Production uses exactly the existing tool
    # client's resolved endpoint/key/HTTP-allowlist configuration.
    client = getattr(service, "text_client", None) or TextClient(service.client)
    route_name, route_reason = choose_route(text, state)
    query = text[:200]
    if route_reason == "service_capability":
        query = "服务范围 诊断 治疗 处方"
    elif route_reason == "cancellation_scope":
        query = "取消 已提交 模拟预约 规则"
    elif route_name == "knowledge" and re.search(r"你能做什么|有什么功能|有哪些服务|能帮我什么", text):
        query = "普通聊天 服务咨询 业务办理 功能"
    if route_reason == "knowledge_followup":
        query = state.get("conversation_knowledge_query", query)

    def route_node(s):
        return {"route": route_name, "route_reason": route_reason, "path": ["route_input"]}

    def completion(messages, *, max_tokens=800, request_client=None):
        selected = request_client or client
        start = time.monotonic()
        try:
            raw = selected.complete(messages, deadline, max_tokens=max_tokens)
        except ModelFailure as exc:
            event = {"round": 1, "outcome": "error", "error": exc.code,
                     "elapsed_ms": round((time.monotonic()-start)*1000, 2)}
            if exc.http_status is not None:
                event["http_status"] = exc.http_status
            event.update(getattr(selected, "diagnostics", {}))
            return None, event, exc.code
        return raw, {"round": 1, "outcome": "normal_end", "tool_count": 0,
                     "elapsed_ms": round((time.monotonic()-start)*1000, 2),
                     **getattr(selected, "diagnostics", {})}, None

    def chat_node(s):
        reason = "not_configured"
        events = []
        reply = None
        if client.configured:
            raw, event, reason = completion([{"role": "system", "content": CHAT_SYSTEM}]
                                            + history_for(state, "chat")
                                            + [{"role": "user", "content": text}])
            events = [event]
            if raw is not None:
                try:
                    reply = check_text(raw, limit=500)
                except ReplyRejected as exc:
                    reason = exc.code
        mode = "llm_chat" if reply is not None else "chat_fallback"
        if reply is None:
            reply = ("当前大模型聊天暂时不可用，没有生成聊天回复。可以稍后再试；"
                     "演示科室、号源查询仍可继续使用。")
        result = service.response(sid, reply, mode=mode, action="explain")
        result["diagnostics"] = public_text_diagnostics("chat", reason or "completed", events)
        return {"response": result, "path": s["path"] + ["chat_reply"]}

    def retrieve_node(s):
        chunks = retrieve_chunks(service.knowledge, query)
        return {"chunks": chunks, "path": s["path"] + ["retrieve_service"]}

    def answer_node(s):
        chunks = s["chunks"]
        result = None
        if not chunks:
            result = service.response(sid, "当前本地服务资料没有找到这个问题的依据，不能据此给出确定答案。"
                                      "这里不连接真实医院；可继续询问模拟预约流程或数据使用说明。",
                                      mode="knowledge_no_evidence")
            result["diagnostics"] = public_text_diagnostics("knowledge", "no_evidence")
        elif not client.configured:
            result = excerpt_response(service, sid, chunks, mode="knowledge_extract", reason="not_configured")
        else:
            documents = evidence_for_prompt(chunks)
            generation_client = getattr(service, "knowledge_client", None) or KnowledgeClient(service.client)
            packet = {"question": text, "retrieval_query": query, "documents": documents}
            raw, event, reason = completion([{"role": "system", "content": COMPACT_SYSTEM},
                                            {"role": "user", "content": json.dumps(packet, ensure_ascii=False)}],
                                           max_tokens=MAX_OUTPUT_TOKENS, request_client=generation_client)
            event["evidence_chunks"] = len(documents)
            if raw is not None:
                try:
                    validated = validate_grounded(raw, documents)
                    if validated is None:
                        reason = "insufficient_evidence"
                    else:
                        answer, sources = validated
                        # Numbered sources are rendered from verified server data,
                        # never as model-controlled links, HTML or file paths.
                        reply = answer + "\n资料依据：" + " ".join(f"[{i+1}] {c['title']}" for i, c in enumerate(sources))
                        result = service.response(sid, reply, sources=sources, mode="llm_knowledge")
                        result["diagnostics"] = public_text_diagnostics("knowledge", "completed", [event], chunks=len(chunks))
                except ReplyRejected as exc:
                    reason = exc.code
            if result is None:
                result = excerpt_response(service, sid, chunks, mode="knowledge_fallback", reason=reason, events=[event])
        result["diagnostics"]["generation_profile"] = PROFILE
        result["knowledge_query"] = query
        result["trace"] = [{"origin": "retrieval", "tool": "search_knowledge", "ok": True,
                            "retrieved_chunks": len(chunks)}]
        return {"response": result, "path": s["path"] + ["grounded_reply"]}

    def business_node(s):
        return {"response": business(), "path": s["path"] + ["business_workflow"]}

    def capability_node(s):
        result = service.response(sid, "这个演示当前没有联网天气、新闻、航班或消息发送工具，不能提供实时查询或执行发送。"
                                  "我可以和您聊天，也可以查询项目服务说明、演示科室和号源。",
                                  mode="capability_boundary")
        result["diagnostics"] = public_text_diagnostics("capability", "external_tool_missing")
        return {"response": result, "path": s["path"] + ["capability_reply"]}

    output = ConversationFlow.run(service.engine, route_node, chat_node, retrieve_node,
                                  answer_node, business_node, capability_node)
    result = output["response"]
    result["route"] = output["route"]
    result["routing"] = {"policy": "guarded_rules_v1", "reason": output["route_reason"],
                         "engine": service.engine, "nodes": output["path"]}
    return result
