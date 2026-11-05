"""JSON 结构解析：把原始对象变成组模型。

只读白名单字段（meta.groupName / months[].weeks[].days[].tasks[] 的已知键），
未知字段一律容忍并忽略；真正的结构错误（缺 meta、months 为空、任务缺标题等）仍然报错。
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field

from .dates import iso_date, month_label, parse_iso_date, parse_dt

PRIORITIES = ("P0", "P1", "P2")
KINDS = ("study", "fitness")


@dataclass
class Task:
    id: str
    title: str
    topic: str
    kind: str
    priority: str
    minutes: int
    slot: str
    done: bool
    done_at: str | None
    history: list[dict]
    date: str
    date_obj: dt.date
    month_id: str
    week_id: str
    group_path: str
    group_name: str


@dataclass
class Day:
    date: str
    date_obj: dt.date
    type: str
    tasks: list[Task] = field(default_factory=list)


@dataclass
class Week:
    id: str
    index: int
    label: str
    start: str
    end: str
    start_obj: dt.date
    end_obj: dt.date
    days: list[Day] = field(default_factory=list)


@dataclass
class Month:
    id: str
    label: str
    weeks: list[Week] = field(default_factory=list)


@dataclass
class Group:
    path: str
    file_name: str
    display_name: str
    raw: dict
    meta: dict
    months: list[Month]
    tasks: list[Task]
    warnings: list[str]

    @property
    def info(self) -> dict:
        return self.meta


@dataclass
class ParseResult:
    ok: bool
    group: Group | None = None
    error: str = ""


def _is_obj(v) -> bool:
    return isinstance(v, dict)


def _arr(v) -> list:
    return v if isinstance(v, list) else []


def _text(v, fallback: str = "") -> str:
    if isinstance(v, str) and v.strip():
        return v.strip()
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    return fallback


def clean_history(value) -> list[dict]:
    """只保留合法的 {action: done|undone, at}，未知字段丢弃。"""
    out: list[dict] = []
    if not isinstance(value, list):
        return out
    for item in value:
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        action = action.strip().lower() if isinstance(action, str) else ""
        if action not in ("done", "undone"):
            continue
        at = item.get("at")
        at = at.strip() if isinstance(at, str) else ""
        if not at or parse_dt(at) is None:
            continue
        out.append({"action": action, "at": at})
    return out


def display_name_from_file_name(file_name: str) -> str:
    """meta.groupName 缺失时的回退：math2_checkbox_use.json → math2。"""
    base = str(file_name or "").replace("\\", "/").split("/")[-1]
    idx = base.find("_checkbox_use")
    base = base[:idx] if idx >= 0 else os.path.splitext(base)[0]
    return base.strip() or "未命名"


def _normalize_kind(value, fallback: str) -> str:
    v = value.strip().lower() if isinstance(value, str) else ""
    return v if v in KINDS else fallback


def _normalize_priority(value) -> str:
    v = value.strip().upper() if isinstance(value, str) else ""
    return v if v in PRIORITIES else "P2"


def build(raw, file_name: str, display_name: str = "", path: str = "") -> ParseResult:
    if not _is_obj(raw):
        return ParseResult(False, error="文件内容的根节点不是 JSON 对象")
    meta_raw = raw.get("meta")
    if not _is_obj(meta_raw):
        return ParseResult(False, error="缺少 meta 字段，无法识别科目信息")

    raw_name = meta_raw.get("groupName")
    raw_name = raw_name if isinstance(raw_name, str) else ""
    group_name = raw_name if raw_name.strip() else display_name_from_file_name(file_name)

    months_raw = raw.get("months")
    if not isinstance(months_raw, list):
        return ParseResult(False, error="缺少 months 数组")
    if not months_raw:
        return ParseResult(False, error="months 为空，没有可排期的月份")

    warnings: list[str] = []
    meta_kind = _normalize_kind(meta_raw.get("kind"), "study")
    meta_priority = ""
    priority_raw = meta_raw.get("priority")
    if isinstance(priority_raw, str) and priority_raw.strip().upper() in PRIORITIES:
        meta_priority = priority_raw.strip().upper()
    plan_start = parse_iso_date(meta_raw.get("planStart"))
    if plan_start is None:
        warnings.append("meta.planStart 缺失或格式不正确，预计完成时间会退回整体平均速率")

    months: list[Month] = []
    tasks: list[Task] = []
    seen_ids: set[str] = set()
    auto_seq = 0
    month_seq = 0

    for m_index, m in enumerate(months_raw):
        if not _is_obj(m):
            warnings.append(f"第 {m_index + 1} 个月份结构异常，已跳过")
            continue
        month_seq += 1
        weeks_raw = m.get("weeks")
        first_week = _arr(weeks_raw)[0] if isinstance(weeks_raw, list) and weeks_raw else None
        derived = ""
        if _is_obj(first_week) and isinstance(first_week.get("start"), str):
            derived = first_week["start"][:7]
        month_id = _text(m.get("id")) or derived or (iso_date(plan_start)[:7] if plan_start else f"m{month_seq}")
        label = _text(m.get("label")) or month_label(month_id) or f"第 {month_seq} 个月"
        if not _text(m.get("id")):
            warnings.append(f"月份 {label} 缺少 id，已按周期推算")
        if not isinstance(weeks_raw, list):
            warnings.append(f"月份 {label} 缺少 weeks 数组，已跳过")
            weeks_raw = []
        elif not weeks_raw:
            warnings.append(f"月份 {label} 的 weeks 为空")

        weeks: list[Week] = []
        for w_index, w in enumerate(weeks_raw):
            if not _is_obj(w):
                warnings.append(f"月份 {label} 第 {w_index + 1} 周结构异常，已跳过")
                continue
            start = parse_iso_date(w.get("start"))
            if start is None:
                warnings.append(f"月份 {label} 第 {w_index + 1} 周缺少合法的 start，已跳过")
                continue
            end_valid = parse_iso_date(w.get("end"))
            end = end_valid or start + dt.timedelta(days=6)
            if end_valid is None:
                warnings.append(f"周 {iso_date(start)} 的 end 缺失或非法，按 7 天补齐")
            if end < start:
                warnings.append(f"周 {iso_date(start)} 的 end 早于 start，已跳过")
                continue
            try:
                index = int(w.get("index"))
            except (TypeError, ValueError):
                index = w_index + 1
            if index <= 0:
                index = w_index + 1
            week = Week(
                id=_text(w.get("id")) or iso_date(start),
                index=index,
                label=_text(w.get("label")) or f"第{index}周",
                start=iso_date(start),
                end=iso_date(end),
                start_obj=start,
                end_obj=end,
            )
            weeks.append(week)

            days_raw = w.get("days")
            if not isinstance(days_raw, list):
                warnings.append(f"周 {week.label} 缺少 days 数组")
                days_raw = []
            for day in days_raw:
                if not _is_obj(day):
                    warnings.append(f"周 {week.label} 存在结构异常的日子，已跳过")
                    continue
                date_obj = parse_iso_date(day.get("date"))
                if date_obj is None:
                    warnings.append(f"周 {week.label} 存在非法日期，已跳过")
                    continue
                day_type = _text(day.get("type")).lower()
                day_tasks: list[Task] = []
                for t in _arr(day.get("tasks")):
                    if not _is_obj(t):
                        warnings.append(f"日期 {day.get('date')} 存在结构异常的任务，已跳过")
                        continue
                    title = _text(t.get("title"))
                    if not title:
                        warnings.append(f"日期 {day.get('date')} 有任务缺少 title，已跳过")
                        continue
                    task_id = _text(t.get("id"))
                    if not task_id:
                        auto_seq += 1
                        task_id = f"{file_name}#{day.get('date')}-{auto_seq}"
                        warnings.append(f"日期 {day.get('date')} 有任务缺少 id，已自动生成 {task_id}")
                    if task_id in seen_ids:
                        warnings.append(f"任务 id 重复：{task_id}（同组内会共用完成状态）")
                    seen_ids.add(task_id)
                    try:
                        minutes = round(float(t.get("minutes")) / 1.0)
                    except (TypeError, ValueError):
                        minutes = 0
                    if minutes <= 0:
                        minutes = 0
                        warnings.append(f"任务 {task_id} 的 minutes 无效，按 0 分钟处理")
                    task_kind = _normalize_kind(t.get("kind"), _normalize_kind(day_type, meta_kind))
                    task = Task(
                        id=task_id,
                        title=title,
                        topic=_text(t.get("topic"), "未分类"),
                        kind=task_kind,
                        priority=_normalize_priority(t.get("priority")),
                        minutes=minutes,
                        slot=_text(t.get("slot")),
                        done=bool(t.get("done")),
                        done_at=(t.get("doneAt").strip() if isinstance(t.get("doneAt"), str) and t.get("doneAt").strip() else None),
                        history=clean_history(t.get("history")),
                        date=str(day.get("date")),
                        date_obj=date_obj,
                        month_id=month_id,
                        week_id=week.id,
                        group_path=path,
                        group_name=group_name,
                    )
                    if not task.history and task.done_at:
                        task.history = [{"action": "done", "at": task.done_at}]
                    day_tasks.append(task)
                    tasks.append(task)
                week.days.append(Day(date=str(day.get("date")), date_obj=date_obj, type=day_type, tasks=day_tasks))
        months.append(Month(id=month_id, label=label, weeks=weeks))

    if not tasks:
        return ParseResult(False, error="没有解析到任何任务，请检查 days / tasks 字段是否完整")

    group = Group(
        path=path,
        file_name=file_name,
        display_name=group_name or display_name,
        raw=raw,
        meta={
            "groupName": group_name,
            "subject": _text(meta_raw.get("subject"), group_name),
            "kind": meta_kind,
            "priority": meta_priority,
            "examDate": _text(meta_raw.get("examDate")),
            "planStart": iso_date(plan_start) if plan_start else "",
            "generatedAt": _text(meta_raw.get("generatedAt")),
            "version": meta_raw.get("version"),
        },
        months=months,
        tasks=tasks,
        warnings=warnings,
    )
    return ParseResult(True, group=group)
