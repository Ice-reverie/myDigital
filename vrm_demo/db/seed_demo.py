"""Create the checked-in SQLite fixture using fictional data only.

Run from the repository root: python -m vrm_demo.db.seed_demo
The command refuses to overwrite an existing database.
"""

from datetime import timedelta
from pathlib import Path
import sqlite3
import sys

from vrm_demo.database_gateway import ROOT, fill_future_slots, now


DEPARTMENTS = [
    ("internal", "内科", "门诊楼二层 A 区", "一般内科咨询与常见症状就诊演示", "周一至周六 09:00–17:00", 1, 1),
    ("surgery", "外科", "门诊楼二层 B 区", "外科门诊咨询演示", "周一至周六 09:00–17:00", 2, 1),
    ("rehab", "康复科", "康复楼一层", "康复评估与复诊演示", "周一至周六 09:00–17:00", 3, 1),
    ("checkup", "体检中心", "综合楼三层", "常规体检与报告咨询演示", "周一至周六 09:00–17:00", 4, 1),
]
SLOTS = [
    ("morning", "上午 09:00", "09:00", "11:00", 1),
    ("afternoon", "下午 14:00", "14:00", "16:00", 2),
    ("late", "下午 16:00", "16:00", "17:00", 3),
]


def create(path, today=None):
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite {path}")
    today = today or now().date()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript((Path(__file__).parent / "schema.sqlite.sql").read_text(encoding="utf-8"))
        connection.executemany("INSERT INTO department VALUES (?, ?, ?, ?, ?, ?, ?)", DEPARTMENTS)
        connection.executemany("INSERT INTO time_slot VALUES (?, ?, ?, ?, ?)", SLOTS)
        connection.execute("INSERT INTO user_base VALUES (?, ?, ?)", ("demo-001", "虚构演示用户", 1))
        connection.executemany("INSERT INTO service_info VALUES (?, ?, ?)", [
            ("booking", "预约服务", "可查询未来 14 天的演示号源、余号和同一时段的模拟预约顺序。不会向医院提交挂号。"),
            ("alerts", "健康提醒", "可以查看和确认虚构演示预警；联系家人仅记录演示选择，不会发送消息。"),
            ("records", "健康记录", "只展示虚构演示用户已有的记录，不提供诊断或治疗建议。"),
            ("hours", "服务时间", "各科室地点及开放时间以科室数据为准；本系统不连接真实医院。"),
        ])
        patterns = []
        for dept_index, department in enumerate(DEPARTMENTS):
            for weekday in range(7):
                for slot_index, slot in enumerate(SLOTS):
                    capacity = 5 + (dept_index * 3 + weekday + slot_index * 2) % 7
                    booked = (dept_index + weekday * 2 + slot_index * 3) % (capacity + 1)
                    closed = weekday == 6 or (weekday == 2 and dept_index == 2 and slot_index == 2)
                    if (weekday + dept_index + slot_index) % 9 == 0:
                        booked = capacity
                    patterns.append((department[0], weekday, slot[0], capacity, booked,
                                     "closed" if closed else "open"))
        connection.executemany("INSERT INTO schedule_pattern VALUES (?, ?, ?, ?, ?, ?)", patterns)
        fill_future_slots(connection, today)

        # Historical rows exercise 'my appointments' without counting against future slots.
        for index in range(12):
            day = today - timedelta(days=index + 1)
            dept_id = DEPARTMENTS[index % len(DEPARTMENTS)][0]
            slot_id = SLOTS[index % len(SLOTS)][0]
            schedule_id = f"history:{index + 1}"
            connection.execute("INSERT INTO schedule VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (schedule_id, dept_id, day.isoformat(), slot_id, 20, 2, "open"))
            connection.execute("INSERT INTO appointment VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (f"history-{index + 1}", f"history-token-{index + 1}",
                                "demo-001", schedule_id, 3, "confirmed",
                                f"{day.isoformat()}T08:00:00"))

        observations = ["日常血压测量记录", "日常血糖测量记录", "睡眠时长自述", "步行活动自述",
                        "体温测量记录", "饮水情况自述", "复诊时间备忘", "晨间脉搏测量记录"]
        for index in range(20):
            day = today - timedelta(days=index * 2 + 1)
            kind = "指标" if index % 3 != 2 else "自述"
            content = f"{observations[index % len(observations)]}（虚构样例 {index + 1}）"
            if index % 3 == 0:
                content += f"：{118 + index % 13}/{76 + index % 9} mmHg"
            connection.execute("INSERT INTO health_record VALUES (?, ?, ?, ?, ?)",
                               (f"record-{index + 1}", "demo-001", kind, content,
                                f"{day.isoformat()}T09:30:00"))

        alert_contents = [
            "演示提醒：请查看最近一次血压记录。", "演示提醒：体检报告可在服务台咨询。",
            "演示提醒：复诊日期即将到来。", "演示提醒：请核对预约时间。",
            "演示提醒：记录近期睡眠情况。", "演示提醒：确认康复科咨询时间。",
            "演示提醒：查看健康记录。", "演示提醒：留意下次体检时间。",
        ]
        statuses = ["pending", "pending", "pending", "confirmed", "later", "family_requested", "confirmed", "later"]
        for index, (content, status) in enumerate(zip(alert_contents, statuses)):
            day = today - timedelta(days=index)
            connection.execute("INSERT INTO alert VALUES (?, ?, ?, ?, ?, ?)",
                               (f"alert-{index + 1}", "demo-001", content, status,
                                f"{day.isoformat()}T10:00:00",
                                None if status == "pending" else f"{day.isoformat()}T11:00:00"))
        connection.commit()
    except Exception:
        connection.close()
        path.unlink(missing_ok=True)
        raise
    else:
        connection.close()


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "digitalhelper_demo.sqlite3"
    create(target)
    print(f"Created fictional demo database: {target}")
