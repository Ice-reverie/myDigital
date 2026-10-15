"""Opt-in FastAPI routes. Work is synchronous so FastAPI uses its thread pool."""
import re
import threading
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request, Response
from .config import truth
from .schemas import ChatInput, DecisionInput
from .service import AgentService
from .store import AgentError


def mount_agent(app, *, gateway=None, voice_resolver=None, sentence_splitter=None, service=None):
    router=APIRouter(prefix="/api/agent",tags=["Agent demo"])
    instance=service
    init_lock=threading.Lock()

    def get_service():
        nonlocal instance
        if not truth("DIGITALHELPER_AGENT_ENABLED","true"):
            raise AgentError("agent_disabled","Agent演示功能未开启。",503)
        with init_lock:
            if instance is None:
                instance=AgentService(gateway=gateway)
        return instance

    def boundary(request):
        origin=request.headers.get("origin")
        if request.headers.get("sec-fetch-site")=="cross-site" or (
            origin and (urlsplit(origin).netloc != request.headers.get("host") or
                        urlsplit(origin).scheme != request.url.scheme)):
            raise AgentError("cross_origin_denied","Agent接口只接受同源浏览器请求。",403)

    def secret(request):
        authorization=request.headers.get("authorization","")
        if not authorization.startswith("Bearer "):
            raise AgentError("unauthorized","缺少会话凭据。",401)
        return authorization[7:]

    def invoke(request,response,function):
        response.headers["Cache-Control"]="no-store"
        try:
            boundary(request)
            return function(get_service())
        except AgentError as exc:
            raise HTTPException(exc.status,detail={"code":exc.code,"message":exc.message},
                                headers={"Cache-Control":"no-store"}) from None
        except Exception:
            # Do not leak provider, credential, SQL or local-path details.
            raise HTTPException(503,detail={"code":"agent_unavailable","message":"Agent暂不可用；确认请求请原样重试核实结果。"},
                                headers={"Cache-Control":"no-store"}) from None

    def with_speech(result,body):
        result=dict(result)
        result["voice_gender"]=voice_resolver(body.avatar_id,body.voice_gender) if voice_resolver else (
            "female" if body.voice_gender=="auto" else body.voice_gender)
        parts=sentence_splitter(result["reply"]) if sentence_splitter else re.split(r"(?<=[。！？\n])",result["reply"])
        # Existing /api/tts accepts at most 500 characters. Preserve every chunk.
        result["segments"]=[{"text":part[i:i+450]} for part in parts if part.strip() for i in range(0,len(part),450)]
        return result

    @router.get("/status")
    def status(request:Request,response:Response):
        return invoke(request,response,lambda s:s.status())

    @router.post("/sessions",status_code=201)
    def create_session(request:Request,response:Response):
        return invoke(request,response,lambda s:s.create_session())

    @router.get("/sessions/{session_id}")
    def read_session(session_id:str,request:Request,response:Response):
        return invoke(request,response,lambda s:s.state(session_id,secret(request)))

    @router.post("/sessions/{session_id}/chat")
    def chat(session_id:str,body:ChatInput,request:Request,response:Response):
        return invoke(request,response,lambda s:with_speech(s.chat(session_id,secret(request),body),body))

    @router.post("/sessions/{session_id}/confirm")
    def confirm(session_id:str,body:DecisionInput,request:Request,response:Response):
        return invoke(request,response,lambda s:with_speech(s.confirm(session_id,secret(request),body),body))

    app.include_router(router)

    @app.on_event("shutdown")
    def close_agent():
        if instance is not None:
            instance.close()

    return router
