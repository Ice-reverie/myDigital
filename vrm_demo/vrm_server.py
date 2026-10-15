import asyncio
import base64
import io
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Dict, List, Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

if __package__:
    from . import tts_gateway, database_gateway, database_dialogue
    from .model_gateway import reply_with_model, configuration as model_configuration
else:
    import tts_gateway
    import database_gateway
    import database_dialogue
    from model_gateway import reply_with_model, configuration as model_configuration

try:
    import edge_tts
except ImportError:  # Browser speech synthesis remains available as a fallback.
    edge_tts = None

try:
    from pypinyin import lazy_pinyin
except ImportError:
    lazy_pinyin = None

try:
    import av
except ImportError:
    av = None


app = FastAPI(title="安心健康助手")

mimetypes.add_type("text/javascript", ".js")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
DEFAULT_AVATAR = "schoolBoy"
AVATAR_LABELS = {
    "doctorBoy": "医生（男）",
    "schoolBoy": "校服男生",
    "schoolGirl": "校服女生",
    "studentGirl": "学生女生",
    "Lumine_companion": "Lumine（适配版）",
}


@app.get("/api/avatar")
async def default_avatar():
    path = avatar_files().get(DEFAULT_AVATAR)
    if path is None:
        raise HTTPException(status_code=404, detail="Default avatar not found")
    return FileResponse(path, media_type="model/gltf-binary")


CHARACTERS_DIR = Path(BASE_DIR).parent / "models" / "characters"


def avatar_files():
    """Discover direct VRM children without exposing directories or linked files."""
    try:
        files = [p for p in CHARACTERS_DIR.iterdir()
                 if p.suffix.lower() == ".vrm" and p.stem and not p.is_symlink()
                 and p.is_file() and p.resolve().parent == CHARACTERS_DIR.resolve()]
    except FileNotFoundError:
        return {}
    return {p.stem: p for p in sorted(files, key=lambda p: (
        p.stem != DEFAULT_AVATAR, p.stem.casefold(), p.name))}


@app.get("/api/avatars")
async def avatar_catalog():
    return [{"id": name, "label": AVATAR_LABELS.get(name, name) + ("（默认）" if name == DEFAULT_AVATAR else ""),
             "voice_gender": tts_gateway.voice_gender(name),
             "profile": "lumine" if name in {"Lumine_companion", "Lumine"} else "standard"}
            for name in avatar_files()]


@app.get("/api/avatars/{name}")
async def named_avatar(name: str):
    path = avatar_files().get(name)
    if path is None:
        raise HTTPException(status_code=404, detail="Unknown avatar")
    return FileResponse(path, media_type="model/gltf-binary")


@app.get("/api/animations/idle")
async def default_idle():
    path = os.path.join(BASE_DIR, "..", "models", "animations", "Idle_Doctor.vrma")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Default idle animation not found")
    return FileResponse(path, media_type="model/gltf-binary")


@app.get("/api/animations/idle/legacy")
async def legacy_idle():
    """Compatibility fallback when the new idle cannot be loaded."""
    path = os.path.join(BASE_DIR, "..", "models", "animations", "Lumine_idle.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Legacy idle animation not found")
    return FileResponse(path, media_type="application/json")


SCENE_ACTIONS = frozenset({"greet", "explain", "alert", "booking", "confirm", "thanks", "wink"})


def animation_variants(name):
    if name not in SCENE_ACTIONS:
        raise HTTPException(status_code=404, detail="Unknown animation")
    directory = os.path.join(BASE_DIR, "..", "models", "animations")
    variants = []
    for filename in os.listdir(directory):
        match = re.fullmatch(re.escape(name) + r"_([1-9][0-9]*)\.vrma", filename)
        if match and os.path.isfile(os.path.join(directory, filename)):
            variants.append((int(match[1]), filename[:-5]))
    return [variant for _, variant in sorted(variants)]


def variant_path(name, variant, suffix):
    if variant not in animation_variants(name):
        raise HTTPException(status_code=404, detail="Unknown animation variant")
    path = os.path.join(BASE_DIR, "..", "models", "animations", variant + suffix)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Animation file not found")
    return path


@app.get("/api/animations")
async def animation_catalog():
    return {name: [{"id": variant,
                    "secondary": os.path.isfile(os.path.join(BASE_DIR, "..", "models", "animations", variant + ".secondary.json"))}
                   for variant in animation_variants(name)] for name in sorted(SCENE_ACTIONS)}


@app.get("/api/animations/greet/secondary")
async def greet_secondary():
    path = os.path.join(BASE_DIR, "..", "models", "animations", "greet_1.secondary.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Secondary animation not found")
    return FileResponse(path, media_type="application/json")


@app.get("/api/animations/{name}/{variant}/secondary")
async def variant_secondary(name: str, variant: str):
    return FileResponse(variant_path(name, variant, ".secondary.json"), media_type="application/json")


@app.get("/api/animations/{name}/{variant}")
async def scene_animation_variant(name: str, variant: str):
    return FileResponse(variant_path(name, variant, ".vrma"), media_type="model/gltf-binary")


@app.get("/api/animations/{name}")
async def scene_animation(name: str):
    if name not in SCENE_ACTIONS:
        raise HTTPException(status_code=404, detail="Unknown animation")
    # Legacy clients keep a stable first variant; new clients select from the catalog.
    variants = animation_variants(name)
    if not variants:
        raise HTTPException(status_code=404, detail="Animation file not found")
    path = variant_path(name, variants[0], ".vrma")
    return FileResponse(path, media_type="model/gltf-binary")

TTS_VOICE = "zh-CN-XiaoxiaoNeural"
TTS_TIMEOUT_SECONDS = 15
LEGACY_AUDIO_BUDGET_SECONDS = 45
SEGMENT_CONCURRENCY = 3
DEPARTMENTS = ["内科", "外科", "康复科", "体检中心"]
APPOINTMENT_TIMES = ["明天上午", "明天下午", "后天上午"]

ACTION_RULES = [
    (["眨个眼", "眨一下", "眨眼", "wink", "你真可爱", "你真棒"], "wink"),
    (["预警", "异常", "提醒"], "alert"),
    (["确认", "知道了", "联系家人"], "confirm"),
    (["你好", "您好", "嗨", "在吗", "hello"], "greet"),
    (["预约", "挂号", "门诊"], "booking"),
    (["谢谢", "感谢", "辛苦"], "thanks"),
    (["健康", "不舒服", "症状", "头晕", "头疼", "血压", "血糖", "失眠"], "explain"),
]

VOWEL_TO_VISEME = {
    'a': 'aa', 'ai': 'aa', 'ao': 'aa', 'an': 'aa', 'ang': 'aa',
    'ia': 'aa', 'iao': 'aa', 'ian': 'aa', 'iang': 'aa',
    'ua': 'aa', 'uai': 'aa', 'uan': 'aa', 'uang': 'aa',
    'i': 'ih', 'in': 'ih', 'ing': 'ih',
    'u': 'ou', 'un': 'ou', 'uo': 'ou', 'ui': 'ou',
    'e': 'ee', 'ei': 'ee', 'en': 'ee', 'eng': 'ee', 'er': 'ee', 'ie': 'ee',
    'o': 'oh', 'ou': 'oh', 'ong': 'oh', 'iong': 'oh',
    'v': 'ou', 've': 'ou', 'vn': 'ou',
}

_VOWEL_KEYS = ['iang', 'iong', 'uang', 'ing', 'eng', 'ong', 'ian', 'uan', 'iao', 'uai',
               'ang', 'an', 'en', 'in', 'un', 'ai', 'ei', 'ao', 'ou', 'ie', 've', 'vn',
               'er', 'ua', 'uo', 'ui', 'a', 'o', 'e', 'i', 'u', 'v']


def pinyin_to_viseme(pinyin_str):
    if not pinyin_str or lazy_pinyin is None:
        return 'aa'
    p = re.sub(r'[1-4]', '', pinyin_str.lower().strip())
    for vowel in _VOWEL_KEYS:
        if p.endswith(vowel):
            return VOWEL_TO_VISEME.get(vowel, 'aa')
    return 'aa'


def text_to_visemes(text):
    if lazy_pinyin is None:
        return []
    return [pinyin_to_viseme(p) for p in lazy_pinyin(text)]


def _find_rhubarb():
    tools_dir = os.path.join(BASE_DIR, "tools")
    for root, _dirs, files in os.walk(tools_dir):
        if "rhubarb.exe" in files and os.path.isdir(os.path.join(root, "res")):
            return os.path.join(root, "rhubarb.exe")
    return os.path.join(tools_dir, "rhubarb.exe")


RHUBARB_PATH = _find_rhubarb()

RHUBARB_TO_VISEME = {
    'A': None, 'B': 'ih', 'C': 'ee', 'D': 'aa',
    'E': 'oh', 'F': 'ou', 'G': 'ih', 'H': 'aa', 'X': None,
}


def mp3_to_wav(mp3_bytes, wav_path):
    if av is None:
        raise RuntimeError("PyAV not available")
    resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
    pcm = bytearray()
    with av.open(io.BytesIO(mp3_bytes)) as container:
        for frame in container.decode(container.streams.audio[0]):
            for f in resampler.resample(frame):
                pcm.extend(f.to_ndarray().tobytes())
        for f in resampler.resample(None):
            pcm.extend(f.to_ndarray().tobytes())
    with wave.open(wav_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(bytes(pcm))


def rhubarb_analyze(wav_path):
    if not os.path.isfile(RHUBARB_PATH):
        return []
    try:
        result = subprocess.run(
            [RHUBARB_PATH, "-r", "phonetic", "-f", "json", "--consoleLevel", "fatal", wav_path],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return []
        return json.loads(result.stdout).get("mouthCues", [])
    except Exception as error:
        print("rhubarb error:", error)
        return []


def build_viseme_timeline(mouth_cues):
    return [
        {"start": c["start"], "end": c["end"], "viseme": RHUBARB_TO_VISEME.get(c["value"])}
        for c in mouth_cues
    ]


def analyze_audio(audio):
    """Run decoding and Rhubarb in a worker, with worker-owned temp files."""
    if av is None or not os.path.isfile(RHUBARB_PATH):
        return []
    # The worker owns cleanup even if the HTTP request is cancelled.
    with tempfile.TemporaryDirectory(prefix="vrm-lipsync-") as directory:
        wav_path = os.path.join(directory, "speech.wav")
        mp3_to_wav(audio, wav_path)
        return build_viseme_timeline(rhubarb_analyze(wav_path))


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    avatar_id: str | None = Field(default=None, max_length=255)
    voice_gender: Literal["auto", "male", "female"] = "auto"


class ChatRequest(TTSRequest):
    context: Dict[str, str] = Field(default_factory=dict)
    include_audio: bool = True


def match_action(text: str):
    for keywords, name in ACTION_RULES:
        if any(keyword in text for keyword in keywords):
            return name
    return None


def split_sentence(text: str, min_length: int = 6) -> List[str]:
    parts = re.split(r"([。！？!?；;\n])", text)
    sentences: List[str] = []
    current = ""
    for part in parts:
        if not part:
            continue
        current += part
        if re.search(r"[。！？!?；;\n]", part) and len(current) >= min_length:
            sentences.append(current.strip())
            current = ""
    if current.strip():
        sentences.append(current.strip())
    return [sentence for sentence in sentences if sentence]


def _result(reply, action=None, quick_replies=None, context=None):
    return {
        "reply": reply,
        "action": action,
        "quick_replies": quick_replies or [],
        "context": context or {},
    }


def build_reply(text: str, context: Dict[str, str] | None = None):
    """Return a deterministic demo response without calling an LLM or hospital system."""
    message = text.strip()
    choice = re.sub(r"[\s，。！？!?,.；;]+", "", message)
    state = dict(context or {})
    flow = state.get("flow")
    step = state.get("step")

    if flow == "appointment" and choice in {"取消", "取消预约", "请取消预约", "退出", "退出预约", "不预约了", "不挂号了"}:
        return _result("本次模拟预约已取消。您还可以继续咨询其他服务。", "confirm")

    if flow == "alert":
        if choice in {"确认", "已确认", "我已确认", "知道了", "我知道了"}:
            return _result(
                "好的，健康预警已在本次演示中标记为已确认。请留意身体变化，如有明显不适请及时就医。",
                "confirm",
            )
        if choice in {"联系家人", "请联系家人", "帮我联系家人"}:
            return _result(
                "好的，已模拟向家人发起联系提醒。演示系统不会真实发送消息。",
                "confirm",
            )
        if choice in {"稍后", "稍后提醒", "提醒我", "稍后提醒我"}:
            return _result(
                "好的，已模拟设置稍后提醒。演示系统不会真实创建通知。",
                "confirm",
            )
        return _result(
            "请先选择如何处理这条模拟健康预警。",
            "alert", ["我已确认", "联系家人", "稍后提醒"], state,
        )

    if flow == "appointment" and step == "department":
        department = next((item for item in DEPARTMENTS if item in message), "")
        if department:
            return _result(
                f"已选择{department}。您希望预约哪个时间？",
                "booking",
                APPOINTMENT_TIMES + ["取消预约"],
                {"flow": "appointment", "step": "time", "department": department},
            )
        return _result(
            "我还没有听清科室。请选择内科、外科、康复科或体检中心。",
            "booking",
            DEPARTMENTS + ["取消预约"],
            state,
        )

    if flow == "appointment" and step == "time":
        appointment_time = next((item for item in APPOINTMENT_TIMES if item in message), "")
        if appointment_time:
            department = state.get("department", "所选科室")
            return _result(
                f"请确认：{department}，{appointment_time}。这是流程演示，不会向医院真实提交预约。",
                "booking",
                ["确认预约", "重新选择", "取消预约"],
                {
                    "flow": "appointment",
                    "step": "final_confirm",
                    "department": department,
                    "time": appointment_time,
                },
            )
        return _result("请选择一个预约时间。", "booking", APPOINTMENT_TIMES + ["取消预约"], state)

    if flow == "appointment" and step == "final_confirm":
        if choice in {"重新选择", "重新选科室", "请重新选择"}:
            return _result(
                "好的，请重新选择科室。",
                "booking",
                DEPARTMENTS + ["取消预约"],
                {"flow": "appointment", "step": "department"},
            )
        if choice in {"确认预约", "我确认预约", "确定预约", "确认挂号", "我确认挂号"}:
            department = state.get("department", "所选科室")
            appointment_time = state.get("time", "所选时间")
            return _result(
                f"已完成模拟预约：{department}，{appointment_time}。演示系统未连接医院，不会产生真实挂号记录。",
                "confirm",
            )
        return _result(
            "请确认预约、重新选择，或取消预约。",
            "booking",
            ["确认预约", "重新选择", "取消预约"],
            state,
        )

    if any(word in message for word in ["预警", "异常提醒", "风险提醒"]):
        return _result(
            "发现一条模拟健康预警：今天上午的血压记录偏高。您可以确认已知晓、联系家人，或稍后提醒。",
            "alert",
            ["我已确认", "联系家人", "稍后提醒"],
            {"flow": "alert", "step": "confirm"},
        )

    if any(word in message for word in ["预约", "挂号", "门诊"]):
        return _result(
            "好的，我们先选择科室。这是本地流程演示，不会连接医院或真实挂号。",
            "booking",
            DEPARTMENTS + ["取消预约"],
            {"flow": "appointment", "step": "department"},
        )

    if any(word in message for word in ["健康", "不舒服", "症状", "头晕", "头疼", "血压", "血糖", "失眠"]):
        return _result(
            "我已记录您的描述。请先坐下休息并补充水分；如果症状持续、加重，或伴随胸痛、呼吸困难等情况，请尽快联系家人并及时就医。本演示不能替代医生诊断。",
            "explain",
            ["查看健康预警", "预约门诊"],
        )

    if any(word in message for word in ["服务", "咨询", "项目"]):
        return _result(
            "我可以演示健康查询、预警确认和服务预约。您想先体验哪一项？",
            "explain",
            ["健康查询", "查看健康预警", "预约门诊"],
        )

    if any(word in message.lower() for word in ["眨个眼", "眨一下", "眨眼", "wink", "你真可爱", "你真棒"]):
        return _result("收到，送您一个小小的眨眼。有我陪着，慢慢来。", "wink")

    if any(word in message.lower() for word in ["你好", "您好", "嗨", "在吗", "hello"]):
        return _result(
            "您好，我是安心健康助手。您可以直接说出需求，我能演示健康查询、预警确认和服务预约。",
            "greet",
            ["健康查询", "查看健康预警", "预约门诊"],
        )

    if any(word in message for word in ["谢谢", "感谢", "辛苦"]):
        return _result("不客气。祝您平安健康，有需要可以继续告诉我。", "thanks")

    return _result(
        "我可以帮助您演示健康查询、预警确认和服务预约。请直接说出您想办理的事情。",
        quick_replies=["健康查询", "查看健康预警", "预约门诊"],
    )


def llm_reply(text: str) -> str:
    """Compatibility wrapper: replies are rule-driven and do not use an LLM."""
    return build_reply(text)["reply"]


async def tts_to_mp3(text: str, gender: str = "female") -> bytes:
    return await tts_gateway.synthesize(text, gender, TTS_TIMEOUT_SECONDS)


@app.get("/")
async def index():
    return RedirectResponse(url="/static/VRMCharacter.html")


@app.get("/api/health")
async def health():
    return {"status": "ok", "tts_available": tts_gateway.edge_tts is not None or tts_gateway.configuration() is not None,
            **tts_gateway.status(),
            "llm_configured": model_configuration() is not None,
            **(await run_in_threadpool(database_gateway.status))}


@app.on_event("startup")
async def _warmup_tts():
    if edge_tts is not None:
        try:
            await asyncio.wait_for(tts_to_mp3("您好", tts_gateway.voice_gender(DEFAULT_AVATAR)), timeout=20)
            print("[warmup] edge_tts ready", flush=True)
        except Exception as error:
            print("[warmup] speech unavailable", flush=True)



async def speech_segments(text: str, gender: str):
    sentences = split_sentence(text)

    # Synthesize sequentially; overlap each Rhubarb analysis with the next TTS.
    segments = [None] * len(sentences)
    analyses = []
    analysis_slots = asyncio.Semaphore(SEGMENT_CONCURRENCY)
    for i, sentence in enumerate(sentences):
        audio = b""
        try:
            audio = await asyncio.wait_for(tts_to_mp3(sentence, gender), timeout=2*TTS_TIMEOUT_SECONDS)
        except Exception as error:
            print("Speech synthesis unavailable")
        audio_base64 = base64.b64encode(audio).decode("utf-8") if audio else ""
        seg = {
            "text": sentence,
            "audio": audio_base64,
            "visemes": text_to_visemes(sentence),
            "visemeTimeline": [],
        }
        segments[i] = seg
        if audio:
            async def _analyze(s=seg, a=audio):
                try:
                    async with analysis_slots:
                        s["visemeTimeline"] = await run_in_threadpool(analyze_audio, a)
                except Exception as error:
                    print("Lip synchronization unavailable")
            analyses.append(asyncio.create_task(_analyze()))
    if analyses:
        await asyncio.gather(*analyses)
    return {
        "voice_gender": gender,
        "segments": segments,
        "tts_available": any(segment["audio"] for segment in segments),
    }


@app.post("/api/tts")
async def tts(req: TTSRequest):
    gender = tts_gateway.voice_gender(req.avatar_id or DEFAULT_AVATAR, req.voice_gender)
    return await speech_segments(req.text, gender)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    result = None
    if database_gateway.enabled() and database_dialogue.needs_database(req.text, req.context):
        try:
            result = await run_in_threadpool(database_dialogue.respond, req.text, req.context)
        except Exception:
            # Do not log credentials, database URLs, or user content.
            print("Demo database unavailable; retaining safe dialogue state")
            result = database_dialogue.unavailable(req.text, req.context)
    if result is None:
        result = build_reply(req.text, req.context)
        result = await reply_with_model(req.text, req.context, result)
    gender = tts_gateway.voice_gender(req.avatar_id or DEFAULT_AVATAR, req.voice_gender)
    if not req.include_audio:
        return {**result, "voice_gender": gender,
                "segments": [{"text": sentence} for sentence in split_sentence(result["reply"])]}
    try:
        speech = await asyncio.wait_for(
            speech_segments(result["reply"], gender), LEGACY_AUDIO_BUDGET_SECONDS)
    except asyncio.TimeoutError:
        speech = {"voice_gender": gender, "tts_available": False,
                  "segments": [{"text": sentence, "audio": "", "visemes": [], "visemeTimeline": []}
                               for sentence in split_sentence(result["reply"])]}
    return {**result, **speech}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8890)
