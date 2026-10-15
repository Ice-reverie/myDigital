import asyncio, time, io, tempfile, os, wave, json, subprocess
import edge_tts, av

BASE = os.path.dirname(os.path.abspath(__file__))
exe = None
for root, _d, files in os.walk(os.path.join(BASE, "tools")):
    if "rhubarb.exe" in files and os.path.isdir(os.path.join(root, "res")):
        exe = os.path.join(root, "rhubarb.exe"); break

async def tts(text):
    t0 = time.time()
    c = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural", rate="+15%")
    buf = io.BytesIO()
    async for ch in c.stream():
        if ch["type"] == "audio": buf.write(ch["data"])
    mp3 = buf.getvalue()
    print(f"  TTS '{text[:10]}' = {time.time()-t0:.2f}s  mp3={len(mp3)}", flush=True)
    return mp3

def analyze(mp3):
    t0 = time.time()
    with tempfile.TemporaryDirectory() as d:
        wp = os.path.join(d, "s.wav")
        container = av.open(io.BytesIO(mp3))
        rs = av.AudioResampler(format='s16', layout='mono', rate=16000)
        pcm = bytearray()
        for frame in container.decode(container.streams.audio[0]):
            for f in rs.resample(frame): pcm.extend(f.to_ndarray().tobytes())
        container.close()
        with wave.open(wp, 'wb') as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000); wf.writeframes(bytes(pcm))
        r = subprocess.run([exe, "-r", "phonetic", "-f", "json", "--consoleLevel", "fatal", wp], capture_output=True, text=True, timeout=10)
        cues = json.loads(r.stdout).get("mouthCues", []) if r.stdout else []
    print(f"  Rhubarb = {time.time()-t0:.2f}s  cues={len(cues)}", flush=True)

async def main():
    texts = ["您好，我是安心健康助手。", "您可以直接说出需求，我能演示健康查询、预警确认和服务预约。"]
    t0 = time.time()
    await asyncio.gather(*(tts(t) for t in texts))
    print(f"parallel TTS total = {time.time()-t0:.2f}s", flush=True)
    mp3 = await tts(texts[0])
    analyze(mp3)

asyncio.run(main())