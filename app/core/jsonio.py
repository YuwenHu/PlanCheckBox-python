"""JSON 读写保真层。

写回时只改目标任务的 done / doneAt / history（以及原文件已有 progress 段中的同名记录），
其余键、键序、缩进、换行、结尾换行都保持原样；未知字段原样保留。
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .parser import clean_history


@dataclass(frozen=True)
class Format:
    indent: str = "  "
    crlf: bool = False
    trailing: bool = True

    def as_dict(self) -> dict:
        return {"indent": self.indent, "crlf": self.crlf, "trailing": self.trailing}

    @staticmethod
    def from_dict(value) -> "Format":
        if not isinstance(value, dict):
            return Format()
        return Format(
            indent=value.get("indent") if isinstance(value.get("indent"), str) and value.get("indent") else "  ",
            crlf=bool(value.get("crlf")),
            trailing=bool(value.get("trailing", True)),
        )


def detect_format(text: str) -> Format:
    """探测缩进、换行与结尾换行，写回时尽量还原。"""
    crlf = "\r\n" in text
    indent = "  "
    for line in text.splitlines():
        stripped = line.lstrip(" \t")
        if stripped and stripped != line and (stripped.startswith('"') or stripped.startswith("{")):
            indent = line[: len(line) - len(stripped)]
            break
    trailing = text.endswith("\n") or text.endswith("\r\n")
    return Format(indent=indent or "  ", crlf=crlf, trailing=trailing)


def serialize(raw, fmt: Format | None = None) -> str:
    fmt = fmt or Format()
    out = json.dumps(raw, ensure_ascii=False, indent=fmt.indent)
    if fmt.crlf:
        out = out.replace("\n", "\r\n")
    if fmt.trailing:
        out += "\r\n" if fmt.crlf else "\n"
    return out


def digest(text: str) -> str:
    """FNV-1a 32 位摘要，只用于检测外部改动。"""
    h = 0x811C9DC5
    for ch in text:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return f"{h:08x}"


def read_text(path: str | Path) -> str:
    """按字节读取再解码，避免 universal newline 把 CRLF 归一化掉。"""
    return Path(path).read_bytes().decode("utf-8-sig")


def write_text_atomic(path: str | Path, text: str) -> None:
    target = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=".pcb-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def apply_task(raw: dict, task_id: str, done: bool, done_at: str | None, history) -> bool:
    """只改 id 匹配的任务；返回是否命中。"""
    found = False
    history = clean_history(history)
    for month in raw.get("months") or []:
        if not isinstance(month, dict):
            continue
        for week in month.get("weeks") or []:
            if not isinstance(week, dict):
                continue
            for day in week.get("days") or []:
                if not isinstance(day, dict):
                    continue
                for task in day.get("tasks") or []:
                    if not isinstance(task, dict) or task.get("id") is None:
                        continue
                    if str(task.get("id")) != str(task_id):
                        continue
                    task["done"] = bool(done)
                    task["doneAt"] = done_at or None
                    if history:
                        task["history"] = history
                    elif "history" in task:
                        del task["history"]
                    found = True
    return found


def apply_progress_section(raw: dict, file_name: str, task_ids, records: dict) -> None:
    """若原文件自带 progress 段，同步更新其中已存在的记录（不改动其它键）。"""
    progress = raw.get("progress")
    if not isinstance(progress, dict):
        return
    for task_id in task_ids:
        rec = records.get(task_id)
        if not rec:
            continue
        for key in (str(task_id), f"{file_name}::{task_id}"):
            entry = progress.get(key)
            if not isinstance(entry, dict):
                continue
            entry["done"] = bool(rec.get("done"))
            if "doneAt" in entry:
                entry["doneAt"] = rec.get("done_at")
            hist = clean_history(rec.get("history"))
            if hist:
                entry["history"] = hist
            elif "history" in entry:
                entry["history"] = []
