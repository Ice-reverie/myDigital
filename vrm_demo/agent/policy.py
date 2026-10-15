"""Transparent offline fallback; deliberately not described as LLM reasoning."""
from datetime import timedelta
import re
import time

MEDICAL = re.compile(r"诊断|确诊|治疗|处方|药物?剂量|吃什么药|用什么药|怎么用药|该吃药|头[疼痛晕]|胸[疼痛闷]|呼吸困难|发[烧热]|我.{0,6}不舒服")

def medical_request(text):
    return bool(MEDICAL.search(text))

def selected_index(text):
    match = re.fullmatch(r"选择时段\s*([1-8])",text.strip())
    return int(match[1])-1 if match else None

def resolve_date(text,today,previous=None):
    match = re.search(r"\d{4}-\d{2}-\d{2}",text)
    if match:
        return match[0]
    for token,days in (("后天",2),("明天",1),("今天",0)):
        if token in text:
            return (today+timedelta(days=days)).isoformat()
    match = re.search(r"(下周|本周|周|星期)([一二三四五六日天])",text)
    if match:
        weekday = "一二三四五六日".index(match[2].replace("天","日"))
        if match[1]=="下周":
            day = today+timedelta(days=7-today.weekday()+weekday)
        elif match[1]=="本周":
            day = today+timedelta(days=weekday-today.weekday())
        else:
            day = today+timedelta(days=(weekday-today.weekday())%7)
        return day.isoformat()
    if any(word in text for word in ("任意日期","不限日期","最近有号","最早")):
        return None
    return previous

def native_turn(toolbox,text):
    evidence,trace = [],[]
    def call(name,args=None):
        start=time.monotonic()
        result=toolbox.execute(name,args or {})
        evidence.append(result)
        trace.append({"tool":name,"ok":result["ok"],"error":result.get("error"),
                      "elapsed_ms":round((time.monotonic()-start)*1000,2)})
        return result
    index=selected_index(text)
    slots=list(toolbox.state.get("eligible_slots",{}).values())
    if index is not None:
        if index>=len(slots):
            evidence.append({"ok":False,"error":"no_selection","message":"选择已过期，请先重新查询号源。"})
        else:
            call("prepare_appointment",{"schedule_id":slots[index]["schedule_id"]})
    elif any(x in text for x in ("我的预约","预约记录")):
        call("get_appointments")
    elif any(x in text for x in ("健康记录","血压记录","血糖记录","我的血压","我的血糖")):
        call("get_health_records",{"keyword":"血压" if "血压" in text else "血糖" if "血糖" in text else None})
    elif any(x in text for x in ("预警","查看提醒")):
        call("get_health_alerts")
    elif any(x in text for x in ("如何","怎么预约","流程","是否真实","真实挂号","服务范围","语音","隐私","取消规则")):
        call("search_knowledge",{"query":text[:200]})
    else:
        departments=call("get_departments")
        if departments.get("ok"):
            names=[d["dept_name"] for d in departments["data"]]
            current=next((name for name in names if name in text),None)
            pref=toolbox.state.get("preferences",{})
            # A request mentioning an unknown department must not silently book
            # the department from the previous request.
            unknown_department = current is None and bool(re.search(r"[\u4e00-\u9fff]{1,6}科",text))
            department=current or (None if unknown_department else pref.get("department"))
            wants_slots=any(x in text for x in ("预约","挂号","号源","余号","有号","时间","上午","下午","明天","后天","最早","周","星期"))
            if department and (wants_slots or current and not any(x in text for x in ("位置","在哪","介绍","服务"))):
                service_date=resolve_date(text,toolbox.db.now().date(),pref.get("service_date"))
                period="afternoon" if "下午" in text else "morning" if "上午" in text else pref.get("period","any")
                if any(x in text for x in ("任意时间","不限时段")):
                    period="any"
                found=call("query_available_slots",{"department":department,"service_date":service_date,"period":period})
                if found.get("ok") and found["data"]["slots"]:
                    options=found["data"]["slots"]
                    if any(x in text for x in ("预约","挂号")) and (len(options)==1 or "最早" in text):
                        call("prepare_appointment",{"schedule_id":options[0]["schedule_id"]})
    return {"evidence":evidence,"trace":trace,"rounds":0,"degraded":False}
