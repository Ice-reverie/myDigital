"""Server-owned speech providers; never expose upstream credentials/errors."""
import asyncio
import io
import logging
import os
from urllib.parse import parse_qs, urlencode, urlsplit

try:
    import httpx
except ImportError:
    httpx = None

try:
    import edge_tts
except ImportError:
    edge_tts = None
try:
    import av
except ImportError:
    av = None

logger = logging.getLogger(__name__)
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MALE_AVATARS = {"Harumasa", "doctorBoy", "schoolBoy", "Wriothesley", "Ratio", "Anaxa", "Ashveil", "Lohen"}


def voice_gender(avatar_id=None, override="auto"):
    if override in ("male", "female"):
        return override
    return "male" if avatar_id in MALE_AVATARS else "female"


def configuration():
    values = {name: os.getenv("DIGITALHELPER_TTS_" + name.upper(), "").strip()
              for name in ("protocol", "api_key", "base_url", "model", "voice_male", "voice_female")}
    values["base_url"] = values["base_url"].rstrip("/")
    try:
        url = urlsplit(values["base_url"])
        valid = url.hostname and not (url.username or url.password or url.query or url.fragment)
        valid = valid and (url.scheme == "https" or url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1"))
        if values["protocol"] == "openai-compatible" and httpx is not None and valid and all(values[k] for k in ("api_key", "model", "voice_male", "voice_female")):
            return values
    except ValueError:
        pass
    return None


def status():
    protocol = os.getenv("DIGITALHELPER_TTS_PROTOCOL", "edge").strip() or "edge"
    return {"tts_protocol": protocol if protocol in ("edge", "openai-compatible") else "unsupported",
            "tts_configured": configuration() is not None,
            "tts_edge_available": edge_tts is not None}


def valid_audio(data):
    if not data or len(data) > MAX_AUDIO_BYTES or av is None:
        return False
    try:
        with av.open(io.BytesIO(data)) as container:
            return next(container.decode(audio=0), None) is not None
    except Exception:
        return False


async def external_speech(config, text, gender):
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        async with client.stream("POST", config["base_url"] + "/audio/speech",
                                 headers={"Authorization": "Bearer " + config["api_key"]},
                                 json={"model": config["model"], "input": text,
                                       "voice": config["voice_" + gender], "response_format": "mp3"}) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_AUDIO_BYTES:
                    raise ValueError("Audio exceeds limit")
    audio = bytes(data)
    if not await asyncio.to_thread(valid_audio, audio):
        raise ValueError("Invalid audio")
    return audio


def _configure_edge_endpoint():
    """Bridge edge-tts 7.2.8 to Edge's migrated synthesis endpoint.

    Upstream fix: https://github.com/rany2/edge-tts/pull/491
    Only adapt the known legacy URL, leaving future upstream URLs untouched.
    The change is process-local; installed packages and voice-list URLs stay intact.
    """
    transport = edge_tts.communicate
    current = urlsplit(getattr(transport, "WSS_URL", ""))
    if (current.scheme, current.netloc, current.path) != (
            "wss", "speech.platform.bing.com", "/consumer/speech/synthesize/readaloud/edge/v1"):
        return
    query = parse_qs(current.query)
    if set(query) != {"TrustedClientToken"} or len(query["TrustedClientToken"]) != 1:
        return
    transport.WSS_URL = (
        "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1?"
        + urlencode({"Ocp-Apim-Subscription-Key": query["TrustedClientToken"][0]}))


def _failure_summary(error):
    """Never log exception text: it can contain tokens, URLs or user content."""
    status_code = getattr(error, "status", None)
    if status_code is None:
        status_code = getattr(getattr(error, "response", None), "status_code", None)
    suffix = f", HTTP {status_code}" if isinstance(status_code, int) else ""
    return type(error).__name__ + suffix


async def edge_speech(text, gender):
    if edge_tts is None:
        return b""
    _configure_edge_endpoint()
    default = "zh-CN-YunxiNeural" if gender == "male" else "zh-CN-XiaoxiaoNeural"
    voice = os.getenv("DIGITALHELPER_TTS_EDGE_VOICE_" + gender.upper(), "").strip() or default
    data = bytearray()
    async for chunk in edge_tts.Communicate(text, voice, rate="+15%").stream():
        if chunk["type"] == "audio":
            data.extend(chunk["data"])
            if len(data) > MAX_AUDIO_BYTES:
                raise ValueError("Audio exceeds limit")
    return bytes(data)


async def synthesize(text, gender, timeout=15):
    config = configuration()
    if config:
        try:
            return await asyncio.wait_for(external_speech(config, text, gender), timeout)
        except Exception as error:
            logger.warning("External speech unavailable (%s); falling back to Edge TTS", _failure_summary(error))
    try:
        return await asyncio.wait_for(edge_speech(text, gender), timeout)
    except Exception as error:
        logger.warning("Edge speech unavailable (%s); using browser fallback", _failure_summary(error))
        return b""
