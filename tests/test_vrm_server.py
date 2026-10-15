import asyncio
from pathlib import Path
import threading
import unittest
from unittest.mock import AsyncMock, patch

from vrm_demo import vrm_server as server
from vrm_demo.vrm_server import build_reply, split_sentence


class DemoConversationTests(unittest.TestCase):
    def test_health_query_has_safety_boundary(self):
        result = build_reply("我最近总是头晕")
        self.assertEqual(result["action"], "explain")
        self.assertIn("不能替代医生诊断", result["reply"])
        self.assertIn("查看健康预警", result["quick_replies"])

    def test_alert_can_be_confirmed(self):
        alert = build_reply("查看健康预警")
        self.assertEqual(alert["context"].get("flow"), "alert")
        confirmed = build_reply("我已确认", alert["context"])
        self.assertEqual(confirmed["action"], "confirm")
        self.assertEqual(confirmed["context"], {})
        self.assertIn("已确认", confirmed["reply"])

    def test_negated_actions_do_not_complete_demo_flows(self):
        alert = build_reply("查看健康预警")["context"]
        for text in ("还没确认", "先不要确认", "我不想联系家人", "不要稍后提醒"):
            with self.subTest(text=text):
                result = build_reply(text, alert)
                self.assertEqual(result["context"], alert)
                self.assertIn("我已确认", result["quick_replies"])
        appointment = {"flow": "appointment", "step": "final_confirm",
                       "department": "内科", "time": "明天上午"}
        for text in ("先不要确认", "还没确认预约", "不要取消预约", "不重新选择"):
            with self.subTest(text=text):
                result = build_reply(text, appointment)
                self.assertEqual(result["context"], appointment)
                self.assertIn("确认预约", result["quick_replies"])

    def test_appointment_flow_requires_final_confirmation(self):
        start = build_reply("帮我预约门诊")
        department = build_reply("康复科", start["context"])
        appointment_time = build_reply("明天上午", department["context"])
        self.assertEqual(appointment_time["context"].get("step"), "final_confirm")
        self.assertIn("不会向医院真实提交预约", appointment_time["reply"])

        confirmed = build_reply("确认预约", appointment_time["context"])
        self.assertEqual(confirmed["context"], {})
        self.assertIn("模拟预约", confirmed["reply"])
        self.assertIn("康复科", confirmed["reply"])

    def test_reselect_appointment_returns_to_department(self):
        context = {
            "flow": "appointment",
            "step": "final_confirm",
            "department": "内科",
            "time": "明天上午",
        }
        result = build_reply("重新选择", context)
        self.assertEqual(result["context"].get("step"), "department")
        self.assertIn("体检中心", result["quick_replies"])

    def test_sentence_split_keeps_punctuation(self):
        self.assertEqual(split_sentence("您好！请坐下休息。"), ["您好！请坐下休息。"])

    def test_cancel_exits_every_appointment_step(self):
        for step in ["department", "time", "final_confirm"]:
            with self.subTest(step=step):
                result = build_reply("取消预约", {"flow": "appointment", "step": step})
                self.assertEqual(result["context"], {})
                self.assertIn("已取消", result["reply"])
                self.assertEqual(build_reply("你好", result["context"])["action"], "greet")

    def test_cancel_is_offered_at_department_and_time(self):
        start = build_reply("预约门诊")
        department = build_reply("内科", start["context"])
        for result in [start, department, build_reply("听不清", department["context"])]:
            self.assertIn("取消预约", result["quick_replies"])


class SpeechPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_chat_returns_before_speech_synthesis(self):
        async def use_rules(text, context, fallback):
            return fallback

        with patch.object(server, "tts_to_mp3", new=AsyncMock()) as synthesize, \
             patch.object(server, "reply_with_model", side_effect=use_rules):
            result = await server.chat(server.ChatRequest(text="预约门诊", include_audio=False))
        synthesize.assert_not_awaited()
        self.assertEqual(result["action"], "booking")
        self.assertEqual("".join(part["text"] for part in result["segments"]), result["reply"])
        self.assertNotIn("audio", result["segments"][0])

    async def test_legacy_chat_has_total_speech_budget(self):
        async def stalled(*args):
            await asyncio.Event().wait()

        with patch.object(server, "speech_segments", side_effect=stalled), \
             patch.object(server, "LEGACY_AUDIO_BUDGET_SECONDS", .01):
            result = await server.chat(server.ChatRequest(text="你好"))
        self.assertFalse(result["tts_available"])
        self.assertEqual(result["segments"][0]["audio"], "")

    async def test_next_synthesis_overlaps_previous_analysis(self):
        analyzing = asyncio.Event()
        release = asyncio.Event()
        started = []

        async def synthesize(text, gender):
            started.append(text)
            if text == "second":
                await analyzing.wait()
                release.set()
            return b"audio"

        async def analyze(*args):
            analyzing.set()
            await release.wait()
            return []

        with patch.object(server, "split_sentence", return_value=["first", "second"]), \
             patch.object(server, "tts_to_mp3", side_effect=synthesize), \
             patch.object(server, "run_in_threadpool", side_effect=analyze):
            await asyncio.wait_for(server.speech_segments("ignored", "female"), 1)
        self.assertEqual(started, ["first", "second"])

    async def test_synthesis_runs_sequentially_and_returns_sentence_order(self):
        started = []
        all_started = asyncio.Event()

        async def synthesize(text, gender):
            started.append(text)
            if len(started) == 2:
                all_started.set()
            await asyncio.sleep(0)
            return text.encode()

        with patch.object(server, "split_sentence", return_value=["first", "second"]), \
             patch.object(server, "tts_to_mp3", side_effect=synthesize), \
             patch.object(server, "analyze_audio", return_value=[]):
            result = await server.chat(server.ChatRequest(text="hello"))
        self.assertTrue(all_started.is_set())
        self.assertEqual([s["text"] for s in result["segments"]], ["first", "second"])
        self.assertTrue(result["tts_available"])

    async def test_timeout_keeps_text_and_reports_no_online_audio(self):
        async def stalled(text, gender):
            await asyncio.Event().wait()

        with patch.object(server, "tts_to_mp3", side_effect=stalled), \
             patch.object(server, "TTS_TIMEOUT_SECONDS", 0.01):
            result = await server.chat(server.ChatRequest(text="hello"))
        self.assertFalse(result["tts_available"])
        self.assertTrue(result["segments"])
        self.assertTrue(all(s["text"] and not s["audio"] for s in result["segments"]))

    async def test_lipsync_worker_does_not_block_event_loop(self):
        entered = threading.Event()
        release = threading.Event()

        def analyze(audio):
            entered.set()
            if not release.wait(2):
                raise AssertionError("The event loop was blocked")
            return []

        with patch.object(server, "split_sentence", return_value=["first"]), \
             patch.object(server, "tts_to_mp3", new=AsyncMock(return_value=b"audio")), \
             patch.object(server, "analyze_audio", side_effect=analyze):
            task = asyncio.create_task(server.chat(server.ChatRequest(text="hello")))
            try:
                async def wait_for_worker():
                    while not entered.is_set():
                        await asyncio.sleep(0.005)
                await asyncio.wait_for(wait_for_worker(), 1)
                self.assertFalse(task.done())
                self.assertEqual((await server.health())["status"], "ok")
            finally:
                release.set()
                await task

    async def test_analysis_failure_keeps_audio_for_energy_fallback(self):
        with patch.object(server, "tts_to_mp3", new=AsyncMock(return_value=b"audio")), \
             patch.object(server, "analyze_audio", side_effect=RuntimeError("failed")):
            result = await server.chat(server.ChatRequest(text="hello"))
        self.assertTrue(all(s["audio"] and s["visemeTimeline"] == [] for s in result["segments"]))

    def test_worker_cleans_temp_file_on_failure(self):
        paths = []

        def fail_decode(audio, wav_path):
            paths.append(Path(wav_path))
            paths[-1].write_bytes(b"partial")
            raise RuntimeError("decode failed")

        with patch.object(server, "av", object()), \
             patch.object(server.os.path, "isfile", return_value=True), \
             patch.object(server, "mp3_to_wav", side_effect=fail_decode):
            with self.assertRaises(RuntimeError):
                server.analyze_audio(b"audio")
        self.assertFalse(paths[0].parent.exists())


if __name__ == "__main__":
    unittest.main()


class SceneActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_named_assets_and_whitelist(self):
        from fastapi import HTTPException
        for name in server.SCENE_ACTIONS:
            response = await server.scene_animation(name)
            self.assertTrue(Path(response.path).is_file())
        for name in ['idle', '../characters/Lumine', 'missing', 'greet.vrma']:
            with self.assertRaises(HTTPException):
                await server.scene_animation(name)
        with patch.object(server.os.path, 'isfile', return_value=False):
            with self.assertRaises(HTTPException):
                await server.scene_animation('greet')

    async def test_seven_scenes_and_business_priority(self):
        for message, action in [('你好','greet'), ('健康查询','explain'), ('查看健康预警','alert'),
                                ('预约门诊','booking'), ('谢谢','thanks'), ('你真可爱','wink'), ('WINK','wink')]:
            self.assertEqual(build_reply(message)['action'], action)
        for context in [{'flow':'alert','step':'confirm'}, {'flow':'appointment','step':'department'}]:
            result = build_reply('你真棒，眨个眼', context)
            self.assertNotEqual(result['action'], 'wink')
            self.assertEqual(result['context'], context)
        start = build_reply('预约门诊')
        department = build_reply('内科',start['context'])
        time = build_reply('明天上午',department['context'])
        self.assertEqual([start['action'],department['action'],time['action']], ['booking']*3)
        self.assertEqual(build_reply('确认预约',time['context'])['action'],'confirm')
        self.assertEqual(build_reply('取消预约',department['context'])['action'],'confirm')
