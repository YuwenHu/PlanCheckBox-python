"""测试用的最小 JSON 构造器：按任务列表自动排出 月份 → 周 → 日 的契约结构。"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "sample_data"
REAL_DIR = Path(r"F:\trae\PlanCheckBox_beta\docs")

SAMPLE_KEYS = ("math2", "eng2", "politics", "cs408", "fitness")


def sample_path(name: str) -> Path:
    return SAMPLE_DIR / f"{name}_checkbox_use.json"


def sample_text(name: str) -> str:
    return sample_path(name).read_text(encoding="utf-8")


def _d(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def task(id, title, date, *, priority="P1", kind="study", minutes=30, done=False,
         done_at=None, history=None, topic="高数", slot="上午", **extra) -> dict:
    item = {
        "id": id,
        "title": title,
        "_date": date,
        "priority": priority,
        "kind": kind,
        "topic": topic,
        "minutes": minutes,
        "slot": slot,
        "done": done,
        "doneAt": done_at,
        "history": history or [],
    }
    item.update(extra)
    return item


def plan_json(tasks, *, group_name="数学", subject="数学", kind="study", plan_start="2026-11-01",
              meta_extra=None, day_extra=None, month_label=None) -> dict:
    """把扁平任务列表组装成完全符合既有契约的对象（键序与真实文件一致）。"""
    months: dict[str, dict] = {}
    week_counter = 0
    week_labels: dict[str, str] = {}
    for t in tasks:
        day = _d(t.get("_date") or t.get("date"))
        week_start = day - dt.timedelta(days=day.weekday())
        mkey = f"{day.year}-{day.month:02d}"
        month = months.setdefault(mkey, {
            "id": mkey,
            "label": month_label or f"{day.year}年{day.month}月",
            "weeks": {},
        })
        wkey = week_start.isoformat()
        if wkey not in week_labels:
            week_counter += 1
            week_labels[wkey] = f"第{week_counter}周"
        week = month["weeks"].setdefault(wkey, {
            "id": f"{mkey}-w{week_start.isocalendar()[1]:02d}",
            "index": week_counter,
            "label": week_labels[wkey],
            "start": wkey,
            "end": (week_start + dt.timedelta(days=6)).isoformat(),
            "days": {},
        })
        dkey = day.isoformat()
        week["days"].setdefault(dkey, {
            "date": dkey,
            "type": kind,
            "tasks": [],
        })
        clean = {k: v for k, v in t.items() if not k.startswith("_")}
        week["days"][dkey]["tasks"].append(clean)
    if day_extra:
        for m in months.values():
            for w in m["weeks"].values():
                for day in w["days"].values():
                    day.update(day_extra)
    meta = {
        "groupName": group_name,
        "subject": subject,
        "kind": kind,
        "priority": "P1",
        "examDate": "2027-12-19",
        "planStart": plan_start,
        "generatedAt": "2026-11-04T16:00:00+08:00",
        "version": 1,
    }
    if meta_extra:
        meta.update(meta_extra)
    out = {"meta": meta, "months": []}
    for mkey in sorted(months):
        m = months[mkey]
        ordered = []
        for wkey in sorted(m["weeks"]):
            w = m["weeks"][wkey]
            w["days"] = [w["days"][k] for k in sorted(w["days"])]
            ordered.append(w)
        m["weeks"] = ordered
        out["months"].append(m)
    return out


def write_json(path: Path, obj, *, indent=2, crlf=False) -> str:
    text = json.dumps(obj, ensure_ascii=False, indent=indent)
    if crlf:
        text = text.replace("\n", "\r\n")
    text += "\r\n" if crlf else "\n"
    path.write_text(text, encoding="utf-8", newline="")
    return text
