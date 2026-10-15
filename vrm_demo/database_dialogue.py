"""Rule-based answers grounded in the fictional demo database."""

from datetime import timedelta
import re
import uuid

try:
    from . import database_gateway as db
except ImportError:
    import database_gateway as db


APPOINTMENT_CANCEL = {"取消", "取消预约", "请取消预约", "退出", "退出预约", "不预约了", "不挂号了"}
BOOKING_CONFIRM = {"确认预约", "我确认预约", "确定预约", "确认挂号", "我确认挂号"}
RESELECT = {"重新选择", "重新选科室", "请重新选择"}
ALERT_CHOICES = {
    "确认": "confirmed", "已确认": "confirmed", "我已确认": "confirmed", "知道了": "confirmed", "我知道了": "confirmed",
    "联系家人": "family_requested", "请联系家人": "family_requested", "帮我联系家人": "family_requested",
    "稍后": "later", "稍后提醒": "later", "提醒我": "later", "稍后提醒我": "later",
}
DB_TERMS = ("预约", "挂号", "门诊", "科室", "号源", "余号", "排队", "前面几人", "前面多少人",
            "我的记录", "健康记录", "血压记录", "血糖记录", "最近血压", "上次血压", "我的血压",
            "最近血糖", "上次血糖", "我的血糖", "有时间", "有空", "可约", "还有号",
            "预警", "提醒", "服务", "体检",
            "康复科", "内科", "外科", "地点", "位置", "开放时间", "就诊时间", "在哪里", "数据库")
AVAILABILITY_TERMS = ("有时间", "有空", "什么时候", "哪天", "可约", "还有号", "有号", "余号", "号源")


def result(reply, action=None, quick_replies=None, context=None):
    return {"reply": reply, "action": action, "quick_replies": quick_replies or [], "context": context or {}}


def clean(text):
    return re.sub(r"[\s，。！？!?,.；;]+", "", text.strip())


def date_text(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def total_booked(slot):
    return slot["base_booked"] + slot["new_booked"]


def remaining(slot):
    return max(0, slot["capacity"] - total_booked(slot)) if slot["status"] == "open" else 0


def option(slot):
    return f"{date_text(slot['service_date'])} {slot['slot_name']}（余{remaining(slot)}位）"


def needs_database(text, context=None):
    if (context or {}).get("flow") in {"appointment", "alert"}:
        return True
    return any(term in text for term in DB_TERMS)


def unavailable(text, context=None):
    context = dict(context or {})
    if context.get("flow") == "appointment":
        step = context.get("step")
        buttons = ["确认预约", "重新选择", "取消预约"] if step == "final_confirm" else ["取消预约"]
        return result("演示数据库暂时无法查询，本次没有写入预约。请稍后重试或取消。", "booking", buttons, context)
    if context.get("flow") == "alert":
        return result("演示数据库暂时无法查询，本次没有更新预警状态。请稍后重试。", "alert",
                      ["我已确认", "联系家人", "稍后提醒"], context)
    return result("演示数据库暂时无法查询，暂不能提供号源或演示记录。请稍后再试。")


def _departments(store):
    return store.departments()


def _department_from_text(text, departments):
    return next((item for item in departments if item["dept_name"] in text or item["dept_id"] == text), None)


def _available_slots(store, dept_id):
    return [slot for slot in store.slots(dept_id) if remaining(slot) > 0]


def _slot_page(slots, offset):
    offset = max(0, min(offset, max(0, len(slots) - 1)))
    page = slots[offset:offset + 5]
    buttons = [option(slot) for slot in page]
    if offset + 5 < len(slots):
        buttons.append("更多时段")
    buttons += ["重新选择科室", "取消预约"]
    return page, buttons


def _offer_slots(store, department, prefix="", offset=0):
    slots = _available_slots(store, department["dept_id"])
    if not slots:
        return result(prefix + f"{department['dept_name']}未来 14 天暂无可约的演示号源。请选其他科室。",
                      "booking", [item["dept_name"] for item in _departments(store)] + ["取消预约"],
                      {"flow": "appointment", "step": "department"})
    page, buttons = _slot_page(slots, offset)
    details = "；".join(f"{option(slot)}，已约{total_booked(slot)}位" for slot in page[:3])
    reply = prefix + f"{department['dept_name']}可选：{details}。请选择具体日期时段；人数仅为模拟预约数据。"
    return result(reply, "booking", buttons,
                  {"flow": "appointment", "step": "time", "dept_id": department["dept_id"],
                   "offset": str(offset)})


def _choose_slot(text, slots):
    exact = [slot for slot in slots if option(slot) == text.strip()]
    if exact:
        return exact
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    target_day = match.group() if match else None
    if target_day is None:
        today = db.now().date()
        if "明天" in text:
            target_day = (today + timedelta(days=1)).isoformat()
        elif "后天" in text:
            target_day = (today + timedelta(days=2)).isoformat()
        elif "今天" in text:
            target_day = today.isoformat()
    candidates = [slot for slot in slots if target_day is None or date_text(slot["service_date"]) == target_day]
    if "上午" in text:
        candidates = [slot for slot in candidates if "上午" in slot["slot_name"]]
    elif "下午" in text:
        candidates = [slot for slot in candidates if "下午" in slot["slot_name"]]
    time = re.search(r"\b\d{1,2}:\d{2}\b", text)
    if time:
        candidates = [slot for slot in candidates if slot["start_time"] == time.group()]
    return candidates if target_day or time else []


def _begin_booking(store):
    departments = _departments(store)
    if not departments:
        return result("暂无可预约的演示科室数据。")
    summaries = []
    for department in departments:
        slots = _available_slots(store, department["dept_id"])
        summaries.append(f"{department['dept_name']}：{option(slots[0])}" if slots else
                         f"{department['dept_name']}：未来 14 天暂无余号")
    return result("这是虚构号源演示。近期可约信息：" + "；".join(summaries) + "。请先选择科室。",
                  "booking", [item["dept_name"] for item in departments] + ["取消预约"],
                  {"flow": "appointment", "step": "department"})


def _booking_step(store, text, context):
    choice = clean(text)
    if choice in APPOINTMENT_CANCEL:
        return result("本次模拟预约已取消，没有向医院提交挂号。", "confirm")
    step = context.get("step")
    departments = _departments(store)
    if step == "department":
        department = _department_from_text(text, departments)
        if department:
            return _offer_slots(store, department, prefix=f"已选择{department['dept_name']}。")
        return result("请选择一个演示科室。", "booking",
                      [item["dept_name"] for item in departments] + ["取消预约"], context)

    department = next((item for item in departments if item["dept_id"] == context.get("dept_id")), None)
    if department is None:
        return _begin_booking(store)
    if choice in RESELECT:
        return _begin_booking(store)
    if step == "time":
        slots = _available_slots(store, department["dept_id"])
        if choice == "更多时段":
            offset = int(context.get("offset", "0")) + 5
            return _offer_slots(store, department, offset=offset)
        matches = _choose_slot(text, slots)
        if len(matches) == 1:
            slot = matches[0]
            ahead = total_booked(slot)
            return result(
                f"请确认：{department['dept_name']}，{option(slot)}。当前同一时段已有{ahead}位模拟预约者；"
                "这不是医院现场候诊人数。确认后只会写入演示数据库。",
                "booking", ["确认预约", "重新选择", "取消预约"],
                {"flow": "appointment", "step": "final_confirm", "dept_id": department["dept_id"],
                 "schedule_id": slot["schedule_id"], "booking_token": uuid.uuid4().hex},
            )
        if len(matches) > 1:
            return result("这个日期有多个可选时段，请选具体时间。", "booking",
                          [option(item) for item in matches[:5]] + ["重新选择科室", "取消预约"], context)
        return _offer_slots(store, department, prefix="未找到所选时段，或该时段已满。")

    if step == "final_confirm":
        if choice not in BOOKING_CONFIRM:
            return result("请确认预约、重新选择或取消预约。", "booking",
                          ["确认预约", "重新选择", "取消预约"], context)
        schedule_id = context.get("schedule_id", "")
        token = context.get("booking_token", "")
        if not schedule_id or not re.fullmatch(r"[0-9a-f]{32}", token):
            return _offer_slots(store, department, prefix="预约信息已过期，请重新选择时段。")
        selected = store.slot(schedule_id)
        if selected is None or selected["dept_id"] != department["dept_id"]:
            return _offer_slots(store, department, prefix="预约信息已过期，请重新选择时段。")
        try:
            booking = store.book(schedule_id, token)
        except db.SlotUnavailable:
            return _offer_slots(store, department, prefix="所选时段已满或不再开放，请重新选择。")
        slot = store.slot(schedule_id)
        ahead = booking["queue_no"] - 1
        return result(
            f"已完成模拟预约：{department['dept_name']}，{date_text(slot['service_date'])} "
            f"{slot['slot_name']}。您的演示序号为{booking['queue_no']}，同一时段前方有{ahead}位模拟预约者。"
            "这不是现场叫号，也不会产生真实医院挂号记录。", "confirm",
        )
    return _begin_booking(store)


def _alert_step(store, text, context):
    status = ALERT_CHOICES.get(clean(text))
    if status is None:
        return result("请选择如何处理这条演示预警。", "alert",
                      ["我已确认", "联系家人", "稍后提醒"], context)
    saved = store.handle_alert(context.get("alert_id", ""), status)
    if saved is None:
        return result("这条演示预警已不存在，请重新查看提醒。", "alert", ["查看健康预警"])
    descriptions = {"confirmed": "已标记为确认", "family_requested": "已记录联系家人的演示选择",
                    "later": "已标记为稍后提醒"}
    return result(f"这条虚构演示预警{descriptions[saved]}。系统不会真实发送消息或创建通知。", "confirm")


def _show_alert(store):
    alerts = store.alerts()
    pending = next((item for item in alerts if item["status"] == "pending"), None)
    if pending is None:
        return result("暂无待处理的演示预警。" if alerts else "暂无演示预警数据。", "alert")
    return result(f"虚构演示预警（{date_text(pending['alert_time'])[:10]}）：{pending['alert_content']}"
                  "您可以确认、选择联系家人或稍后提醒。", "alert",
                  ["我已确认", "联系家人", "稍后提醒"],
                  {"flow": "alert", "step": "confirm", "alert_id": pending["alert_id"]})


def respond(text, context=None):
    context = dict(context or {})
    if not needs_database(text, context):
        return None
    if context.get("flow") == "appointment" and clean(text) in APPOINTMENT_CANCEL:
        return result("本次模拟预约已取消，没有向医院提交挂号。", "confirm")
    with db.repository() as store:
        if context.get("flow") == "appointment":
            return _booking_step(store, text, context)
        if context.get("flow") == "alert":
            return _alert_step(store, text, context)
        if "数据库" in text:
            return result("当前只使用虚构演示数据库查询科室、号源、演示记录和预警；不会访问真实医院或真实个人健康数据。", "explain")
        if "我的预约" in text or "预约记录" in text:
            bookings = store.appointments()
            if not bookings:
                return result("暂无演示预约记录。", "explain")
            lines = [f"{date_text(item['service_date'])} {item['dept_name']} {item['slot_name']}（序号{item['queue_no']}）"
                     for item in bookings[:3]]
            return result("虚构演示用户最近的预约：" + "；".join(lines) + "。", "explain")
        if any(word in text for word in ("健康记录", "血压记录", "血糖记录", "我的记录",
                                         "最近血压", "上次血压", "我的血压", "最近血糖", "上次血糖", "我的血糖")):
            keyword = "血压" if "血压" in text else "血糖" if "血糖" in text else None
            records = store.records(keyword)
            if not records:
                return result("暂无对应的虚构演示健康记录。", "explain")
            lines = [f"{date_text(item['recorded_at'])[:10]} {item['content']}" for item in records[:3]]
            return result("虚构演示记录：" + "；".join(lines) + "。这些记录不能用于诊断。", "explain")
        if any(word in text for word in ("预警", "提醒")):
            return _show_alert(store)
        departments = _departments(store)
        department = _department_from_text(text, departments)
        if department and any(word in text for word in AVAILABILITY_TERMS):
            return _offer_slots(store, department)
        if department and any(word in text for word in ("在哪里", "地点", "位置", "服务", "开放时间", "做什么")):
            return result(f"{department['dept_name']}位于{department['location']}；"
                          f"演示服务：{department['services']}；开放时间：{department['opening_hours']}。", "explain")
        if any(word in text for word in ("预约", "挂号", "号源", "余号", "排队", "前面几人", "前面多少人")) \
                or any(word in text for word in AVAILABILITY_TERMS):
            if department:
                return _offer_slots(store, department)
            return _begin_booking(store)
        if department:
            return result(f"{department['dept_name']}位于{department['location']}；"
                          f"演示服务：{department['services']}；开放时间：{department['opening_hours']}。", "explain")
        if any(word in text for word in ("科室", "在哪里", "地点", "位置", "开放时间", "就诊时间")) and departments:
            listing = "；".join(f"{item['dept_name']}（{item['location']}）" for item in departments)
            return result("可查询的演示科室：" + listing + "。", "explain",
                          ["预约门诊"])
        if "服务" in text or "体检" in text or "科室" in text:
            infos = store.service_info()
            if not infos:
                return result("暂无演示服务信息。", "explain")
            content = "；".join(f"{item['title']}：{item['content']}" for item in infos[:3])
            return result("演示服务信息：" + content, "explain",
                          ["预约门诊", "查看健康预警", "健康记录"])
    return None
