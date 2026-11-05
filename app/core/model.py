"""纯逻辑层：排序、进度、预计完成时间、热力图分档、配色、板块月份汇总。

不读写磁盘、不碰界面，单元测试直接调用这里的函数。
"""
from __future__ import annotations

import datetime as dt
import math
from collections import OrderedDict

from .dates import (add_days, fmt_md, fmt_minutes, fmt_range, local_date, parse_dt,
                    parse_iso_date, weekday_text, week_label)
from .parser import Group, Task

PRIO = {"P0": 0, "P1": 1, "P2": 2}
_HEAT_LEVELS = ((0, ""), (2, "lv1"), (5, "lv2"), (10**9, "lv3"))

EXAM_SUBJECT_ORDER = (
    (0, "数学", ("数学", "数一", "数二", "数三", "math")),
    (1, "专业课", ("408", "专业课", "专业基础", "computer", "cs408")),
    (2, "英语", ("英语", "英一", "英二", "英文", "english", "eng2")),
    (3, "政治", ("政治", "思政", "politics")),
)
RANK_EXAM_BASE = 0
RANK_OTHER_BASE = 10
RANK_FITNESS = 900


def prio_rank(task: Task) -> int:
    return PRIO.get(task.priority, 2)


def slot_rank(task: Task) -> int:
    s = str(task.slot or "")
    if "早" in s or "上午" in s:
        return 0
    if "中" in s or "午" in s:
        return 1
    if "下午" in s:
        return 2
    if "晚" in s:
        return 3
    return 9


def stats(tasks) -> dict:
    total = len(tasks)
    done = sum(1 for t in tasks if t.done)
    minutes = sum(t.minutes or 0 for t in tasks)
    return {
        "total": total,
        "done": done,
        "remaining": total - done,
        "minutes": minutes,
        "minutesText": fmt_minutes(minutes),
        "pct": round(done * 100 / total) if total else 0,
    }


def sort_by_priority(tasks) -> list[Task]:
    return sorted(tasks, key=lambda t: (prio_rank(t), t.date_obj, t.id))


def sort_for_display(tasks) -> list[Task]:
    """未完成在前、已完成沉底；同组内 P0→P1→P2，同级按日期与 id。"""
    return sorted(tasks, key=lambda t: (1 if t.done else 0, prio_rank(t), t.date_obj, t.id))


def sort_calendar(tasks) -> list[Task]:
    """月历格内排序：已完成沉底；未完成按 P0→P1→P2，再按时间段。"""
    return sorted(tasks, key=lambda t: (1 if t.done else 0, prio_rank(t), slot_rank(t), t.id))


def all_done(tasks) -> bool:
    return bool(tasks) and all(t.done for t in tasks)


def tasks_in_range(tasks, start: dt.date, end: dt.date) -> list[Task]:
    return [t for t in tasks if start <= t.date_obj <= end]


def week_tasks(group: Group, groups, start: dt.date, end: dt.date) -> list[Task]:
    """本周本组任务 + 其他组的健身任务（按 文件+id 去重）。"""
    out: list[Task] = []
    seen: set[str] = set()

    def push(t: Task) -> None:
        key = f"{t.group_path}::{t.id}"
        if key in seen:
            return
        seen.add(key)
        out.append(t)

    for t in tasks_in_range(group.tasks, start, end):
        push(t)
    for g in groups:
        for t in tasks_in_range(g.tasks, start, end):
            if t.kind == "fitness":
                push(t)
    return out


def group_by_day(tasks) -> list[dict]:
    ordered = sorted(tasks, key=lambda t: t.date_obj)
    buckets: OrderedDict[str, dict] = OrderedDict()
    for t in ordered:
        buckets.setdefault(t.date, {"date": t.date, "dateObj": t.date_obj, "tasks": []})["tasks"].append(t)
    for bucket in buckets.values():
        bucket["tasks"] = sort_for_display(bucket["tasks"])
    return list(buckets.values())


def heat_level(count: int) -> str:
    """四档：0 → 空，1–2 → lv1，3–5 → lv2，6+ → lv3。"""
    for bound, cls in _HEAT_LEVELS:
        if count <= bound:
            return cls
    return "lv3"


def completion_by_day(groups) -> dict[str, int]:
    """按 doneAt 的本地日期计数；跨组按 task id 去重。"""
    seen: set[str] = set()
    counts: dict[str, int] = {}
    for g in groups:
        for t in g.tasks:
            if t.id in seen:
                continue
            seen.add(t.id)
            if not t.done:
                continue
            day = local_date(t.done_at) or t.date_obj
            key = day.isoformat()
            counts[key] = counts.get(key, 0) + 1
    return counts


def unique_task_stats(groups) -> dict:
    seen: set[str] = set()
    total = done = 0
    for g in groups:
        for t in g.tasks:
            if t.id in seen:
                continue
            seen.add(t.id)
            total += 1
            done += 1 if t.done else 0
    return {"total": total, "done": done}


def month_entries(group: Group) -> list:
    seen: set[str] = set()
    out = []
    for m in group.months:
        if m.id not in seen:
            seen.add(m.id)
            out.append(m)
    return sorted(out, key=lambda m: m.id)


def month_range(month) -> tuple[dt.date, dt.date] | None:
    parsed = parse_iso_date(f"{month.id}-01")
    if parsed is not None:
        nxt = dt.date(parsed.year + (parsed.month == 12), (parsed.month % 12) + 1, 1)
        return parsed, nxt - dt.timedelta(days=1)
    if not month.weeks:
        return None
    return min(w.start_obj for w in month.weeks), max(w.end_obj for w in month.weeks)


def tasks_in_month(group: Group, month) -> list[Task]:
    if month is None:
        return []
    return [t for t in group.tasks if t.month_id == month.id]


def fitness_in_month(groups, month) -> list[Task]:
    if month is None:
        return []
    out: list[Task] = []
    seen: set[str] = set()
    rng = month_range(month)
    for g in groups:
        owned = any(m.id == month.id for m in g.months)
        if owned:
            picked = [t for t in g.tasks if t.kind == "fitness" and t.month_id == month.id]
        elif rng:
            picked = [t for t in tasks_in_range(g.tasks, *rng) if t.kind == "fitness"]
        else:
            picked = []
        for t in picked:
            key = f"{t.group_path}::{t.id}"
            if key in seen:
                continue
            seen.add(key)
            out.append(t)
    return out


def compress_months(months: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    start = prev = None
    for m in months:
        if start is None:
            start = prev = m
        elif m == prev + 1:
            prev = m
        else:
            out.append((start, prev))
            start = prev = m
    if start is not None:
        out.append((start, prev))
    return out


def topic_summaries(group: Group) -> list[dict]:
    """「板块 → 月份」：按 topic 聚合出现过的月份，保持首次出现顺序。"""
    order: list[str] = []
    months_by_topic: dict[str, dict[str, None]] = {}
    for t in group.tasks:
        topic = t.topic or "未分类"
        if topic not in months_by_topic:
            months_by_topic[topic] = {}
            order.append(topic)
        months_by_topic[topic][t.month_id] = None
    out = []
    for topic in order:
        ids = sorted(months_by_topic[topic].keys())
        years: dict[str, list[int]] = {}
        for mid in ids:
            years.setdefault(mid[:4], []).append(int(mid[5:7]))
        if len(years) == 1 and len(ids) <= 4:
            texts = [" ".join(f"{m}月" for m in years[ids[0][:4]])]
        else:
            texts = []
            for year, months in years.items():
                ranges = [f"{a}月" if a == b else f"{a}月–{b}月" for a, b in compress_months(months)]
                texts.append(f"{year}年" + "、".join(ranges))
        out.append({"topic": topic, "texts": texts})
    return out


def group_color(name: str) -> dict:
    """确定性哈希配色：同名永远同色。"""
    h = 0
    for ch in str(name or ""):
        h = (h * 31 + ord(ch)) % 1000000007
    hue = h % 360
    return {
        "hue": hue,
        "strong": f"hsl({hue}, 62%, 42%)",
        "soft": f"hsl({hue}, 80%, 96%)",
        "light": f"hsl({hue}, 70%, 90%)",
    }


def subject_rank(group: Group) -> int:
    meta = group.meta
    if meta.get("kind") == "fitness":
        return RANK_FITNESS
    hay = f"{meta.get('subject', '')} {meta.get('groupName', '')} {group.file_name}".lower()
    for rank, _label, keys in EXAM_SUBJECT_ORDER:
        if any(k.lower() in hay for k in keys):
            return RANK_EXAM_BASE + rank
    return RANK_OTHER_BASE + PRIO.get(meta.get("priority") or "", 3)


def sort_groups(groups) -> list[Group]:
    return sorted(
        groups,
        key=lambda g: (subject_rank(g), str(g.meta.get("groupName") or g.file_name).lower(), g.file_name),
    )


def last_done_at(task: Task) -> str | None:
    latest = None
    latest_ts = None
    for h in task.history or []:
        if h.get("action") != "done":
            continue
        parsed = parse_dt(h.get("at"))
        if parsed is None:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        if latest_ts is None or parsed > latest_ts:
            latest_ts, latest = parsed, h["at"]
    return latest or task.done_at or None


def done_text(task: Task, today: dt.date | None = None) -> str:
    from .dates import time_text

    if not task.done:
        return ""
    if not task.done_at:
        return "已勾选 · 无时间记录"
    t = time_text(task.done_at, today)
    return f"已完成 {t}" if t else "已完成"


def last_done_text(task: Task, today: dt.date | None = None) -> str:
    from .dates import time_text

    if task.done:
        return done_text(task, today)
    at = last_done_at(task)
    if not at:
        return ""
    t = time_text(at, today)
    return f"曾完成 {t}" if t else ""


def predict(tasks, plan_start: str | dt.date | None, today: dt.date | None = None) -> dict:
    """近期 14 天加权（近 7 天权重 2）；无近期记录退回 planStart 整体均值。"""
    today = today or dt.date.today()
    total = len(tasks)
    if total == 0:
        return {"ok": False, "label": "数据不足", "detail": "该范围暂无任务", "cls": "muted"}
    done_tasks = [t for t in tasks if t.done]
    remaining = total - len(done_tasks)
    if remaining == 0:
        return {"ok": True, "completed": True, "remaining": 0, "rate": 0,
                "label": "已全部完成", "detail": "该范围任务已全部完成", "cls": "predict"}

    recent = prev = 0
    for t in done_tasks:
        day = local_date(t.done_at)
        if day is None:
            continue
        diff = (today - day).days
        if 0 <= diff <= 6:
            recent += 1
        elif 7 <= diff <= 13:
            prev += 1
    rate = (2 * (recent / 7) + prev / 7) / 3
    basis = "近14天加权"
    detail = (f"近7天完成 {recent} 项，前7天 {prev} 项；加权速率 {rate:.2f} 项/天，剩余 {remaining} 项")

    if rate <= 0:
        start = plan_start if isinstance(plan_start, dt.date) else parse_iso_date(plan_start)
        start = start or today
        days = max(1, (today - start).days + 1)
        rate = len(done_tasks) / days
        basis = "整体平均"
        detail = (f"无近期完成时间可用，按整体平均：已完成 {len(done_tasks)} 项 / {days} 天 = "
                  f"{rate:.2f} 项/天，剩余 {remaining} 项")

    if rate <= 0 or rate < 0.02:
        return {"ok": False, "label": "数据不足", "basis": basis, "rate": rate,
                "detail": detail + "；速率过低，暂不给出预计日期", "cls": "muted"}
    need = math.ceil(remaining / rate)
    if need > 1825:
        return {"ok": False, "label": "数据不足", "basis": basis, "rate": rate,
                "detail": detail + "；据此推算超过 5 年", "cls": "muted"}
    date = add_days(today, need)
    return {
        "ok": True,
        "completed": False,
        "remaining": remaining,
        "rate": rate,
        "needDays": need,
        "date": date.isoformat(),
        "basis": basis,
        "label": f"预计 {fmt_md(date, today)}完成所有任务",
        "detail": detail + f"；预计还需 {need} 天（{basis}）",
        "cls": "predict",
    }


def week_title(week) -> str:
    return f"{week_label(week.label)}，{fmt_range(week.start_obj, week.end_obj)}"


__all__ = [
    "PRIO", "prio_rank", "slot_rank", "stats", "sort_by_priority", "sort_for_display",
    "sort_calendar", "all_done", "tasks_in_range", "week_tasks", "group_by_day",
    "heat_level", "completion_by_day", "unique_task_stats", "month_entries", "month_range",
    "tasks_in_month", "fitness_in_month", "compress_months", "topic_summaries",
    "group_color", "subject_rank", "sort_groups", "last_done_at", "done_text",
    "last_done_text", "predict", "week_title", "weekday_text",
]
