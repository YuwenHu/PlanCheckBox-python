"""题库与进度分离：指纹、进度文件读写、跨题库迁移。

- 题库文件（``*_checkbox_use.json``）只读，只提供 meta 与任务树；
- 进度文件 ``<题库名>_progress.json`` 保存指纹与每条任务的 done / doneAt / history。

指纹用于表达血缘：内容哈希 + 任务总数 + 题库生成时间 + 题库格式版本。
同指纹直接合并；不同指纹按「taskId 优先、任务标题兜底」迁移，匹配不上的旧记录
保留在 ``unmatched`` 区域，绝不丢弃。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from . import jsonio
from .parser import Group, Task, clean_history

FORMAT_NAME = "plancheckbox-progress"
FORMAT_VERSION = 1
SUFFIX = "_progress.json"
SOURCE_KEYS = ("hash", "taskCount", "generatedAt", "formatVersion")
META_KEYS = ("groupName", "subject", "kind", "priority", "examDate", "planStart",
             "generatedAt", "version")


class ProgressError(RuntimeError):
    """进度文件存在但不可用（损坏、不是本程序格式、无法读取）。"""


@dataclass
class Migration:
    same_source: bool = False
    by_id: int = 0
    by_title: int = 0
    id_retitled: int = 0
    kept_unmatched: int = 0
    message: str = ""


# --------------------------------------------------------------------- 基础
def progress_path(bank_path) -> Path:
    """题库旁的进度文件：``math2_checkbox_use.json`` → ``math2_checkbox_use_progress.json``。"""
    p = Path(bank_path)
    return p.with_name(f"{p.stem}{SUFFIX}")


def _meta_of(raw) -> dict:
    meta = raw.get("meta") if isinstance(raw, dict) else None
    return meta if isinstance(meta, dict) else {}


def _canonical(raw, group: Group | None) -> str:
    """只取影响「这条计划是什么」的字段，忽略缩进/换行等排版差异。"""
    meta = _meta_of(raw)
    tasks = [[t.id, t.title, t.date, t.topic, t.kind, t.priority, int(t.minutes or 0), t.slot]
             for t in (group.tasks if group else [])]
    payload = {"meta": {k: meta.get(k) for k in META_KEYS}, "tasks": tasks}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(raw, group: Group | None) -> dict:
    meta = _meta_of(raw)
    version = meta.get("version")
    return {
        "hash": hashlib.sha256(_canonical(raw, group).encode("utf-8")).hexdigest(),
        "taskCount": len(group.tasks) if group else 0,
        "generatedAt": meta.get("generatedAt") if isinstance(meta.get("generatedAt"), str) else "",
        "formatVersion": version if isinstance(version, (int, str)) and not isinstance(version, bool) else None,
    }


def same_source(a, b) -> bool:
    """四个指纹字段全等才算同源（``file`` 只是人类可读的备注，不参与判同）。"""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    return all(a.get(k) == b.get(k) for k in SOURCE_KEYS)


def _record(raw) -> dict | None:
    """规范化一条状态记录；无法识别时返回 None。"""
    if not isinstance(raw, dict):
        return None
    done_at = raw.get("doneAt")
    done_at = done_at.strip() if isinstance(done_at, str) and done_at.strip() else None
    history = clean_history(raw.get("history"))
    done = bool(raw.get("done"))
    if not history and done and done_at:
        history = [{"action": "done", "at": done_at}]
    return {
        "title": raw.get("title") if isinstance(raw.get("title"), str) else "",
        "done": done,
        "doneAt": done_at,
        "history": history,
    }


def has_state(rec) -> bool:
    return bool(rec and (rec.get("done") or rec.get("doneAt") or rec.get("history")))


def empty_doc(fp: dict, file_name: str) -> dict:
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "source": dict({k: fp.get(k) for k in SOURCE_KEYS}, file=file_name),
        "updatedAt": "",
        "tasks": {},
        "unmatched": {},
    }


# --------------------------------------------------------------------- 读写
def read(path) -> dict | None:
    """读取进度文件；不存在返回 None，损坏则抛 :class:`ProgressError`（避免静默覆盖）。"""
    p = Path(path)
    if not p.exists():
        return None
    try:
        text = jsonio.read_text(p)
    except OSError as exc:
        raise ProgressError(f"进度文件读取失败：{exc.strerror or exc}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ProgressError("进度文件不是合法的 JSON，可能已损坏") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT_NAME:
        raise ProgressError("这不是本程序的进度文件（缺少 format 标记）")
    tasks: dict[str, dict] = {}
    raw_tasks = data.get("tasks")
    if isinstance(raw_tasks, dict):
        for key, value in raw_tasks.items():
            rec = _record(value)
            if rec is not None:
                tasks[str(key)] = rec
    unmatched: dict[str, dict] = {}
    raw_unmatched = data.get("unmatched")
    if isinstance(raw_unmatched, dict):
        for key, value in raw_unmatched.items():
            rec = _record(value)
            if rec is not None:
                unmatched[str(key)] = rec
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "source": dict(source),
        "updatedAt": data.get("updatedAt") if isinstance(data.get("updatedAt"), str) else "",
        "tasks": tasks,
        "unmatched": unmatched,
    }


def write(bank_path, doc: dict) -> None:
    """原子写入进度文件；键排序，保证同一状态生成同样的文本。"""
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "source": {k: source.get(k) for k in (*SOURCE_KEYS, "file")},
        "updatedAt": doc.get("updatedAt") or "",
        "tasks": {k: doc["tasks"][k] for k in sorted(doc.get("tasks") or {})},
        "unmatched": {k: doc["unmatched"][k] for k in sorted(doc.get("unmatched") or {})},
    }
    jsonio.write_text_atomic(progress_path(bank_path), jsonio.serialize(payload))


# --------------------------------------------------------------------- 迁移
def _norm_title(value) -> str:
    return " ".join(str(value or "").split())


def legacy_records(group: Group) -> dict:
    """老式单文件（done/doneAt/history 内嵌在题库里）的有效状态。"""
    out: dict[str, dict] = {}
    for task in group.tasks:
        rec = {
            "title": task.title,
            "done": bool(task.done),
            "doneAt": task.done_at,
            "history": clean_history(task.history),
        }
        if has_state(rec):
            out[task.id] = rec
    return out


def _message(report: Migration) -> str:
    if report.same_source:
        return ""
    detail = []
    if report.by_id:
        detail.append(f"id 匹配 {report.by_id} 条")
    if report.id_retitled:
        detail.append(f"id 匹配但标题已变 {report.id_retitled} 条")
    if report.by_title:
        detail.append(f"标题匹配 {report.by_title} 条")
    text = "检测到题库已更新，进度已迁移"
    if detail:
        text += "（" + "，".join(detail) + "）"
    if report.kept_unmatched:
        text += f"；{report.kept_unmatched} 条旧记录找不到对应任务，已保留在进度文件的 unmatched 区域"
    return text


def resolve(doc: dict, group: Group, fp: dict) -> tuple[dict, Migration]:
    """把旧进度记录对齐到当前题库，返回新的进度文档与迁移报告。"""
    report = Migration(same_source=same_source(doc.get("source"), fp))
    pool: dict[str, Task] = {t.id: t for t in group.tasks}
    by_title: dict[str, list[Task]] = {}
    for task in group.tasks:
        by_title.setdefault(_norm_title(task.title), []).append(task)

    old = doc.get("tasks") or {}
    matched: dict[str, dict] = {}
    claimed: set[str] = set()      # 已被占用的新任务 id
    consumed: set[str] = set()     # 已成功迁移的旧记录 id

    # 第一轮：id 命中且标题一致（旧记录没存标题时只认 id）
    for tid, rec in old.items():
        task = pool.get(tid)
        if task is None:
            continue
        stored = _norm_title(rec.get("title"))
        if stored and stored != _norm_title(task.title):
            continue
        matched[tid] = dict(rec, title=task.title)
        claimed.add(tid)
        consumed.add(tid)
        report.by_id += 1

    rest = [(tid, rec) for tid, rec in old.items() if tid not in consumed]

    # 第二轮：标题兜底（每个新任务只用一次）
    for tid, rec in rest:
        key = _norm_title(rec.get("title"))
        if not key:
            continue
        for task in by_title.get(key, []):
            if task.id in claimed:
                continue
            matched[task.id] = dict(rec, title=task.title)
            claimed.add(task.id)
            consumed.add(tid)
            report.by_title += 1
            break

    # 第三轮：id 命中但标题变了（同一任务被重命名）
    for tid, rec in rest:
        if tid in consumed or tid not in pool:
            continue
        matched[tid] = dict(rec, title=pool[tid].title)
        claimed.add(tid)
        consumed.add(tid)
        report.id_retitled += 1

    # 其余旧记录原样保留在 unmatched，供以后换回旧题库时再用
    unmatched: dict[str, dict] = dict(doc.get("unmatched") or {})
    for tid, rec in old.items():
        if tid in consumed:
            continue
        key = f"task:{tid}"
        if key in unmatched:
            key = f"task:{tid}:{rec.get('doneAt') or report.kept_unmatched + 1}"
        unmatched[key] = dict(rec, note=f"题库中找不到对应任务（旧 id：{tid}）")
        report.kept_unmatched += 1

    report.message = _message(report)
    new_doc = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "source": dict({k: fp.get(k) for k in SOURCE_KEYS},
                       file=(doc.get("source") or {}).get("file") or ""),
        "updatedAt": doc.get("updatedAt") or "",
        "tasks": matched,
        "unmatched": unmatched,
    }
    return new_doc, report


def apply(group: Group, doc: dict | None) -> None:
    """把进度文档写回内存里的任务（没有记录的按未完成处理）。"""
    tasks = (doc or {}).get("tasks") or {}
    for task in group.tasks:
        rec = tasks.get(task.id)
        if rec is None:
            task.done = False
            task.done_at = None
            task.history = []
            continue
        task.done = bool(rec.get("done"))
        task.done_at = rec.get("doneAt") or None
        task.history = clean_history(rec.get("history"))


def set_record(doc: dict, task_id: str, title: str, done: bool,
               done_at: str | None, history) -> None:
    rec = {
        "title": title,
        "done": bool(done),
        "doneAt": done_at or None,
        "history": clean_history(history),
    }
    bucket = doc.setdefault("tasks", {})
    if has_state(rec):
        bucket[task_id] = rec
    else:
        bucket.pop(task_id, None)


__all__ = [
    "FORMAT_NAME", "FORMAT_VERSION", "SUFFIX", "ProgressError", "Migration",
    "progress_path", "fingerprint", "same_source", "has_state", "empty_doc",
    "read", "write", "legacy_records", "resolve", "apply", "set_record",
]
