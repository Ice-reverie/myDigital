"""Validated business tools. A model can propose, but cannot commit a booking."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pydantic import ValidationError
from .schemas import EmptyArgs, SlotArgs, RecordArgs, KnowledgeArgs, PrepareArgs
from .store import AgentError

@dataclass(frozen=True)
class ToolSpec:
    description: str
    arguments: type

SPECS = {
    "get_departments": ToolSpec("查询演示科室、位置及服务范围。", EmptyArgs),
    "query_available_slots": ToolSpec("查询指定科室未来14天的真实演示数据库余号。日期使用北京时间ISO日期；上午/下午可过滤。", SlotArgs),
    "get_appointments": ToolSpec("查询固定虚构演示用户的模拟预约。", EmptyArgs),
    "get_health_records": ToolSpec("只读查询虚构演示记录，不做诊断或建议用药。", RecordArgs),
    "get_health_alerts": ToolSpec("只读查询演示预警，不发送通知。", EmptyArgs),
    "search_knowledge": ToolSpec("检索本项目审核的服务说明文档，返回引用来源；不含医疗诊断知识。", KnowledgeArgs),
    "prepare_appointment": ToolSpec("仅为已经查询到的 schedule_id 生成待确认预约，绝不提交。必须等待用户确认。", PrepareArgs),
}

def tool_schemas():
    return [{"type":"function", "function":{"name":name, "description":s.description,
             "parameters":s.arguments.model_json_schema()}} for name,s in SPECS.items()]

def safe_json(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))

def iso_day(value):
    return value.isoformat()[:10] if hasattr(value, "isoformat") else str(value)[:10]

def time_hour(value):
    if isinstance(value, timedelta):
        return int(value.total_seconds()//3600)
    return int(str(value).split(":",1)[0])

class Toolbox:
    def __init__(self, gateway, store, knowledge, sid, rid, state):
        self.db, self.store, self.knowledge = gateway, store, knowledge
        self.sid, self.rid, self.state = sid,rid,state
        self.proposal = None

    def execute(self, name, arguments):
        if name not in SPECS:
            return {"ok":False,"error":"unknown_tool","message":"工具不在允许列表。"}
        try:
            args = SPECS[name].arguments.model_validate(arguments)
        except (ValidationError, TypeError, ValueError):
            return {"ok":False,"error":"invalid_arguments","message":"工具参数不符合服务端结构约束。"}
        try:
            data = getattr(self, name)(**args.model_dump())
            return {"ok":True,"tool":name,"fictional":True,"data":safe_json(data)}
        except AgentError as exc:
            return {"ok":False,"error":exc.code,"message":exc.message}
        except Exception:
            # SQL/driver/HTTP exceptions can contain credentials and are NOT logged.
            return {"ok":False,"error":"database_unavailable","message":"演示数据暂不可用，没有提交预约。"}

    def get_departments(self):
        with self.db.repository() as repo:
            return repo.departments()

    def query_available_slots(self, department, service_date=None, period="any"):
        today = self.db.now().date()
        if service_date is not None:
            try:
                day = date.fromisoformat(service_date)
            except ValueError:
                raise AgentError("invalid_date","日期无效，请提供有效日期。")
            if not today <= day < today+timedelta(days=14):
                raise AgentError("date_out_of_range","仅支持未来14天内的演示号源。")
        with self.db.repository() as repo:
            departments = repo.departments()
            dept = next((d for d in departments if department in {d["dept_id"],d["dept_name"]}),None)
            if dept is None:
                raise AgentError("department_required","请选择确切的演示科室名称。")
            slots = repo.slots(dept["dept_id"])
        available = []
        for row in slots:
            remaining = int(row["capacity"])-int(row["base_booked"])-int(row["new_booked"])
            day = iso_day(row["service_date"])
            hour = time_hour(row["start_time"])
            if row["status"] != "open" or remaining <= 0:
                continue
            if service_date and day != service_date:
                continue
            if period == "morning" and hour >= 12 or period == "afternoon" and hour < 12:
                continue
            # Never offer a same-day session whose start hour is already past.
            if day == today.isoformat() and hour <= self.db.now().hour:
                continue
            item = {"schedule_id":row["schedule_id"],"department":dept["dept_name"],
                    "service_date":day,"slot_name":str(row["slot_name"]),"remaining":remaining}
            available.append(item)
        visible = available[:8]
        # Only returned, server-observed IDs can be proposed. A new search
        # invalidates the previous choice list (no client-supplied context).
        self.state["eligible_slots"] = {s["schedule_id"]:s for s in visible}
        self.state["preferences"] = {"department":dept["dept_name"],"service_date":service_date,"period":period}
        self.store.save(self.sid, self.state)
        return {"slots":visible,"total_available":len(available),"department":dept["dept_name"],
                "service_date":service_date,"period":period}

    def get_appointments(self):
        with self.db.repository() as repo:
            return repo.appointments()

    def get_health_records(self, keyword=None):
        with self.db.repository() as repo:
            return repo.records(keyword)

    def get_health_alerts(self):
        with self.db.repository() as repo:
            return repo.alerts()

    def search_knowledge(self, query):
        return self.knowledge.search(query)

    def prepare_appointment(self, schedule_id):
        observed = self.state.get("eligible_slots",{}).get(schedule_id)
        if not observed:
            raise AgentError("unobserved_slot","必须先查询并选择服务端返回的时段，不能自行构造号源ID。")
        with self.db.repository() as repo:
            slot = repo.slot(schedule_id)
            if slot is None:
                raise AgentError("slot_unavailable","号源已失效，请重新查询。")
            actual = next((s for s in repo.slots(slot["dept_id"]) if s["schedule_id"]==schedule_id),None)
            if (actual is None or actual["status"]!="open" or
                int(actual["base_booked"])+int(actual["new_booked"]) >= int(actual["capacity"])):
                raise AgentError("slot_unavailable","时段已满或已关闭，请重新查询。")
        payload = {**observed, "service_date":iso_day(slot["service_date"]),
                   "slot_name":str(slot["slot_name"]),"department":str(slot["dept_name"])}
        self.proposal = self.store.create_proposal(self.sid, self.rid, payload)
        return {"requires_confirmation":True,"proposal_id":self.proposal["id"],"selection":payload}

    def commit(self, proposal):
        """Not in SPECS: reachable only after the HTTP confirmation gate."""
        pid, payload = proposal["id"], proposal["payload"]
        try:
            with self.db.repository() as repo:
                slot = repo.slot(payload["schedule_id"])
                # On retry after a lost response, let Repository.book return its
                # already-committed row even when the slot date has since passed.
                existing = repo.one("SELECT schedule_id FROM appointment WHERE booking_token=? AND user_id=? AND status='confirmed'",
                                    (pid,self.db.DEMO_USER_ID))
                if existing is None and (slot is None or (iso_day(slot["service_date"]) == self.db.now().date().isoformat()
                                                           and time_hour(slot["start_time"]) <= self.db.now().hour)):
                    raise self.db.SlotUnavailable("expired")
                booking = repo.book(payload["schedule_id"], pid)
                if booking["schedule_id"] != payload["schedule_id"]:
                    raise AgentError("booking_binding_error","预约幂等令牌绑定异常，请检查演示数据库。",409)
            result = {"ok":True,"appointment_id":booking["appointment_id"],
                      "schedule_id":booking["schedule_id"],"queue_no":booking["queue_no"],
                      "selection":payload,"fictional":True}
            self.store.set_proposal_status(pid,"approved",result)
            return result
        except self.db.SlotUnavailable:
            result = {"ok":False,"error":"slot_unavailable","message":"所选时段已满、过期或关闭，没有新增预约。"}
            self.store.set_proposal_status(pid,"failed",result)
            return result
        except AgentError:
            raise
        except Exception:
            # An unknown commit result must NOT be called 'failed'. Keep the
            # immutable proposal + idempotency key and allow safe reconciliation.
            raise AgentError("commit_unknown","预约结果暂无法核实，请重试原确认请求；不会换一个令牌重复预约。",503)
