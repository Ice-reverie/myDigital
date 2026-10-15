from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import os
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from vrm_demo import database_dialogue as dialogue
from vrm_demo import database_gateway as db
from vrm_demo import vrm_server as server


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name) / "runtime.sqlite3"
        self.environment = patch.dict(os.environ, {
            "DIGITALHELPER_DB_ENABLED": "true", "DIGITALHELPER_DB_BACKEND": "sqlite",
            "DIGITALHELPER_SQLITE_PATH": str(self.runtime),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_checked_in_seed_has_varied_fictional_data(self):
        with sqlite3.connect(f"file:{db.SEED_PATH.as_posix()}?mode=ro", uri=True) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM department").fetchone()[0], 4)
            self.assertGreaterEqual(connection.execute("SELECT COUNT(*) FROM schedule_pattern").fetchone()[0], 80)
            self.assertGreaterEqual(connection.execute("SELECT COUNT(*) FROM schedule").fetchone()[0], 168)
            self.assertGreaterEqual(connection.execute("SELECT COUNT(*) FROM health_record").fetchone()[0], 20)
            self.assertGreaterEqual(connection.execute("SELECT COUNT(*) FROM alert").fetchone()[0], 8)
            self.assertGreater(connection.execute("SELECT COUNT(*) FROM schedule WHERE status='closed'").fetchone()[0], 0)
            self.assertGreater(connection.execute("SELECT COUNT(*) FROM schedule WHERE status='open' AND base_booked=capacity").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT display_name FROM user_base").fetchone()[0], "虚构演示用户")

    def test_runtime_copy_and_rolling_future_dates(self):
        with patch.object(db, "now", return_value=datetime(2028, 1, 2, tzinfo=db.CHINA_TIME)):
            with db.repository() as store:
                rows = store.all("SELECT DISTINCT service_date FROM schedule WHERE service_date >= ?", ("2028-01-02",))
        self.assertEqual(len(rows), 14)
        self.assertEqual(str(rows[-1]["service_date"]), "2028-01-15")
        self.assertTrue(self.runtime.is_file())
        with sqlite3.connect(db.SEED_PATH) as seed:
            self.assertEqual(seed.execute("SELECT COUNT(*) FROM schedule WHERE service_date >= '2028-01-02'").fetchone()[0], 0)

    def test_booking_uses_available_slots_and_is_idempotent(self):
        start = dialogue.respond("预约门诊")
        self.assertEqual(start["context"]["step"], "department")
        options = dialogue.respond("内科", start["context"])
        self.assertEqual(options["context"]["step"], "time")
        chosen = dialogue.respond(options["quick_replies"][0], options["context"])
        self.assertEqual(chosen["context"]["step"], "final_confirm")
        schedule_id = chosen["context"]["schedule_id"]
        with db.repository() as store:
            before = next(slot for slot in store.slots("internal") if slot["schedule_id"] == schedule_id)
        first = dialogue.respond("确认预约", chosen["context"])
        again = dialogue.respond("确认预约", chosen["context"])
        self.assertEqual(first["reply"], again["reply"])
        self.assertIn(f"前方有{dialogue.total_booked(before)}位", first["reply"])
        self.assertIn("不是现场叫号", first["reply"])
        with db.repository() as store:
            after = next(slot for slot in store.slots("internal") if slot["schedule_id"] == schedule_id)
            self.assertEqual(after["new_booked"], before["new_booked"] + 1)
            self.assertEqual(len(store.all("SELECT appointment_id FROM appointment WHERE booking_token = ?",
                                           (chosen["context"]["booking_token"],))), 1)
        self.assertIn("虚构演示用户最近的预约", dialogue.respond("我的预约")["reply"])

    def test_cancel_and_full_slot_do_not_write(self):
        start = dialogue.respond("预约门诊")
        self.assertEqual(dialogue.respond("取消预约", start["context"])["context"], {})
        with db.repository() as store:
            full = next(slot for slot in store.slots("internal")
                        if slot["status"] == "open" and dialogue.remaining(slot) == 0)
            before = store.one("SELECT COUNT(*) AS total FROM appointment WHERE schedule_id = ?",
                               (full["schedule_id"],))["total"]
            with self.assertRaises(db.SlotUnavailable):
                store.book(full["schedule_id"], "f" * 32)
            after = store.one("SELECT COUNT(*) AS total FROM appointment WHERE schedule_id = ?",
                              (full["schedule_id"],))["total"]
            self.assertEqual(before, after)

    def test_two_bookings_compete_for_last_place(self):
        with db.repository() as store:
            slot = next(item for item in store.slots("internal") if dialogue.remaining(item) > 0)
            store.execute("UPDATE schedule SET capacity = base_booked + ? WHERE schedule_id = ?",
                          (slot["new_booked"] + 1, slot["schedule_id"]))
            store.connection.commit()

        def attempt(token):
            try:
                with db.repository() as store:
                    return store.book(slot["schedule_id"], token)["queue_no"]
            except db.SlotUnavailable:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ("1" * 32, "2" * 32)))
        self.assertEqual(sum(value is not None for value in results), 1)
        with db.repository() as store:
            self.assertEqual(store.one("SELECT COUNT(*) AS total FROM appointment WHERE schedule_id = ?",
                                       (slot["schedule_id"],))["total"], 1)

    def test_records_and_alert_updates_are_from_database(self):
        record = dialogue.respond("我的血压记录")
        self.assertIn("虚构演示记录", record["reply"])
        self.assertIn("不能用于诊断", record["reply"])
        alert = dialogue.respond("查看健康预警")
        alert_id = alert["context"]["alert_id"]
        self.assertIn("虚构演示预警", alert["reply"])
        handled = dialogue.respond("我已确认", alert["context"])
        self.assertIn("已标记为确认", handled["reply"])
        with db.repository() as store:
            self.assertEqual(store.one("SELECT status FROM alert WHERE alert_id = ?", (alert_id,))["status"],
                             "confirmed")
        following = dialogue.respond("查看健康预警")
        self.assertNotEqual(following["context"]["alert_id"], alert_id)

    def test_service_and_department_facts_are_queried(self):
        location = dialogue.respond("内科在哪里")
        self.assertIn("门诊楼二层 A 区", location["reply"])
        available = dialogue.respond("内科什么时候有时间")
        self.assertEqual(available["context"]["step"], "time")
        self.assertTrue(any("余" in option for option in available["quick_replies"]))
        self.assertIn("演示服务信息", dialogue.respond("有哪些服务")["reply"])

    def test_missing_facts_do_not_become_invented_answers(self):
        with db.repository() as store:
            store.execute("DELETE FROM health_record WHERE content LIKE ?", ("%血压%",))
            store.execute("UPDATE schedule SET status = 'closed' WHERE dept_id = ?", ("rehab",))
            store.connection.commit()
        self.assertIn("暂无对应", dialogue.respond("我的血压记录")["reply"])
        self.assertIn("暂无可约", dialogue.respond("康复科什么时候有时间")["reply"])

    def test_cancel_still_works_if_database_goes_offline(self):
        context = {"flow": "appointment", "step": "time", "dept_id": "internal"}
        with patch.object(db, "repository", side_effect=RuntimeError("offline")):
            cancelled = dialogue.respond("取消预约", context)
        self.assertEqual(cancelled["context"], {})
        self.assertIn("已取消", cancelled["reply"])


class ChatIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_mode_does_not_open_database(self):
        with patch.dict(os.environ, {"DIGITALHELPER_DB_ENABLED": "false"}), \
             patch.object(db, "repository", side_effect=AssertionError("database was opened")), \
             patch.object(server, "reply_with_model", new=AsyncMock(side_effect=lambda text, context, fallback: fallback)):
            response = await server.chat(server.ChatRequest(text="预约门诊", include_audio=False))
        self.assertIn("本地流程演示", response["reply"])
        self.assertEqual(response["context"]["step"], "department")

    async def test_database_failure_never_claims_booking_success(self):
        context = {"flow": "appointment", "step": "final_confirm", "dept_id": "internal",
                   "schedule_id": "missing", "booking_token": "a" * 32}
        with patch.dict(os.environ, {"DIGITALHELPER_DB_ENABLED": "true"}), \
             patch.object(dialogue, "respond", side_effect=RuntimeError("secret connection URL")):
            response = await server.chat(server.ChatRequest(text="确认预约", context=context, include_audio=False))
        self.assertIn("没有写入预约", response["reply"])
        self.assertEqual(response["context"], context)
        self.assertNotIn("secret", str(response))

    async def test_http_chat_and_health_use_sqlite_when_enabled(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "DIGITALHELPER_DB_ENABLED": "true", "DIGITALHELPER_DB_BACKEND": "sqlite",
                "DIGITALHELPER_SQLITE_PATH": str(Path(directory) / "runtime.sqlite3")}):
            transport = httpx.ASGITransport(app=server.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/chat", json={"text": "预约门诊", "include_audio": False})
                health = await client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertIn("近期可约信息", response.json()["reply"])
        self.assertEqual(response.json()["context"]["step"], "department")
        self.assertTrue(health.json()["db_available"])
        self.assertNotIn("runtime.sqlite3", str(health.json()))


class MySQLInterfaceTests(unittest.TestCase):
    def test_parameterized_queries_and_explicit_transactions(self):
        calls = []

        class Cursor:
            rowcount = 1

            def execute(self, sql, params):
                calls.append((sql, params))

            def fetchone(self):
                sql = calls[-1][0]
                if "booking_token" in sql and "SELECT" in sql:
                    return None
                if "FROM schedule s" in sql:
                    return {"schedule_id": "s1", "service_date": date.today(), "status": "open",
                            "capacity": 4, "base_booked": 1, "slot_name": "上午 09:00",
                            "start_time": "09:00", "dept_id": "internal", "dept_name": "内科"}
                if "COUNT(*)" in sql:
                    return {"total": 1}
                return None

            def close(self):
                pass

        class Connection:
            def cursor(self, dictionary=False):
                self.dictionary = dictionary
                return Cursor()

            def start_transaction(self):
                calls.append(("BEGIN", ()))

            def commit(self):
                calls.append(("COMMIT", ()))

            def rollback(self):
                calls.append(("ROLLBACK", ()))

        store = db.Repository(Connection(), "mysql")
        booking = store.book("s1", "a" * 32, today=date.today())
        self.assertEqual(booking["queue_no"], 3)
        self.assertIn(("BEGIN", ()), calls)
        self.assertIn(("COMMIT", ()), calls)
        self.assertTrue(any("FOR UPDATE" in sql for sql, _ in calls))
        self.assertTrue(any("%s" in sql and params == ("s1",) for sql, params in calls))
        self.assertFalse(any("ROLLBACK" == sql for sql, _ in calls))

    def test_optional_connector_receives_only_configured_parameters(self):
        captured = {}

        class Connection:
            def close(self):
                pass

        def connect(**kwargs):
            captured.update(kwargs)
            return Connection()

        connector = types.ModuleType("mysql.connector")
        connector.connect = connect
        mysql = types.ModuleType("mysql")
        mysql.connector = connector
        with patch.dict(os.environ, {"DIGITALHELPER_DB_ENABLED": "true", "DIGITALHELPER_DB_BACKEND": "mysql",
                                  "DIGITALHELPER_MYSQL_DATABASE": "demo", "DIGITALHELPER_MYSQL_USER": "tester",
                                  "DIGITALHELPER_MYSQL_PASSWORD": "test-only"}), \
             patch.dict("sys.modules", {"mysql": mysql, "mysql.connector": connector}):
            with db.repository() as store:
                self.assertEqual(store.dialect, "mysql")
        self.assertEqual(captured["database"], "demo")
        self.assertEqual(captured["password"], "test-only")
        self.assertTrue(captured["autocommit"])
