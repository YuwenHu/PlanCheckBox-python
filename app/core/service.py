"""应用服务层：文件载入、进度写回、页面视图数据（供 pywebview 桥接层直接返回给前端）。

所有界面文案都在这里算好，前端只负责拼 HTML，因此单元测试可以完全不依赖 GUI。
"""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import jsonio, model, store
from .dates import (add_days, fmt_minutes, fmt_range, local_date, month_label,
                    now_local_iso, parse_iso_date, weekday_text, week_label)
from .parser import Group, Task, build, clean_history, display_name_from_file_name

PAGE_NAMES = ("", "选择任务", "总览", "月度", "周度")


@dataclass
class FileEntry:
    path: str
    file_name: str
    display_name: str
    text: str = ""
    fmt: jsonio.Format = field(default_factory=jsonio.Format)
    digest: str = ""
    raw: dict | None = None
    group: Group | None = None
    error: str = ""


class AppService:
    def __init__(self, today: dt.date | None = None):
        self.today = today or dt.date.today()
        self.files: list[FileEntry] = []
        self.route = {"page": 1, "group_path": None, "month_id": None}
        self.expanded: dict[str, bool] = {}
        self.active_week = ""
        self.heat_year: int | None = None
        self.heat_tip = ""
        self.ov_month = ""
        self.day_detail = ""
        self.last_write = ""
        self._restore()

    # ------------------------------------------------------------------ 基础
    @property
    def groups(self) -> list[Group]:
        return [f.group for f in self.files if f.group is not None]

    def find_file(self, path: str) -> FileEntry | None:
        return next((f for f in self.files if f.path == path), None)

    def find_group(self, path: str | None) -> Group | None:
        entry = self.find_file(path) if path else None
        return entry.group if entry else None

    def _load_path(self, path: str) -> FileEntry:
        entry = FileEntry(path=path, file_name=os.path.basename(path),
                          display_name=display_name_from_file_name(os.path.basename(path)))
        try:
            text = jsonio.read_text(path)
        except OSError as exc:
            entry.error = f"文件读取失败：{exc.strerror or exc}"
            return entry
        entry.text = text
        entry.digest = jsonio.digest(text)
        entry.fmt = jsonio.detect_format(text)
        try:
            raw = json.loads(text)
        except ValueError:
            entry.error = "不是合法的 JSON（文件内容无法解析，可能已损坏或被截断）"
            return entry
        result = build(raw, entry.file_name, entry.display_name, path)
        if result.ok and result.group:
            entry.raw = raw
            entry.group = result.group
            entry.display_name = result.group.display_name
        else:
            entry.error = f"JSON 结构不完整：{result.error}"
        return entry

    # ------------------------------------------------------------------ 会话
    def _restore(self) -> None:
        saved = store.load_session()
        for path in saved.get("files") or []:
            if not isinstance(path, str) or not os.path.isfile(path):
                continue
            entry = self._load_path(path)
            if entry.group is not None:
                self.files.append(entry)
        route = saved.get("route") if isinstance(saved.get("route"), dict) else {}
        self.route = {
            "page": int(route.get("page") or 1) if str(route.get("page") or "1").isdigit() else 1,
            "group_path": route.get("group_path") if isinstance(route.get("group_path"), str) else None,
            "month_id": route.get("month_id") if isinstance(route.get("month_id"), str) else None,
        }
        for key in saved.get("expanded") or []:
            if isinstance(key, str):
                self.expanded[key] = True
        self.active_week = saved.get("active_week") if isinstance(saved.get("active_week"), str) else ""
        year = saved.get("heat_year")
        self.heat_year = year if isinstance(year, int) else None
        self.ov_month = saved.get("ov_month") if isinstance(saved.get("ov_month"), str) else ""

    def _persist(self) -> None:
        store.save_session({
            "version": 1,
            "files": [f.path for f in self.files],
            "route": self.route,
            "expanded": [k for k, v in self.expanded.items() if v],
            "active_week": self.active_week,
            "heat_year": self.heat_year,
            "ov_month": self.ov_month,
        })

    # ------------------------------------------------------------------ 动作
    def add_paths(self, paths) -> dict:
        added = 0
        bad = 0
        replaced = 0
        for path in paths or []:
            if not isinstance(path, str) or not os.path.isfile(path):
                bad += 1
                continue
            entry = self._load_path(path)
            existing = self.find_file(path)
            if existing is not None:
                self.files[self.files.index(existing)] = entry
                replaced += 1
            else:
                self.files.append(entry)
            if entry.group is not None:
                added += 1
            else:
                bad += 1
        self.route["page"] = 1
        self._persist()
        msg = f"已载入 {added} 个可用文件"
        if bad:
            msg += f"，{bad} 个无法解析"
        if replaced:
            msg += f"（{replaced} 个重复路径已更新）"
        return {"ok": True, "message": msg}

    def remove_file(self, path: str) -> dict:
        self.files = [f for f in self.files if f.path != path]
        self.expanded = {k: v for k, v in self.expanded.items() if not k.startswith(f"{path}#")}
        if not self.groups:
            self.route = {"page": 1, "group_path": None, "month_id": None}
            self.active_week = ""
            store.clear_session()
        else:
            if self.find_group(self.route.get("group_path")) is None:
                self.route = {"page": min(self.route.get("page") or 1, 2), "group_path": None, "month_id": None}
            self._persist()
        return {"ok": True, "message": "已移除该文件"}

    def clear_files(self) -> dict:
        self.files = []
        self.expanded = {}
        self.active_week = ""
        self.heat_tip = ""
        self.day_detail = ""
        self.route = {"page": 1, "group_path": None, "month_id": None}
        store.clear_session()
        return {"ok": True, "message": "已清空已选文件"}

    def to_overview(self) -> dict:
        if not self.groups:
            return {"ok": False, "message": "请先选择至少一个可用文件", "kind": "error"}
        self.route = {"page": 2, "group_path": None, "month_id": None}
        self._persist()
        return {"ok": True}

    def open_group(self, path: str) -> dict:
        g = self.find_group(path)
        if g is None:
            return {"ok": False, "message": "该组数据不可用", "kind": "error"}
        months = model.month_entries(g)
        self.route = {"page": 3, "group_path": path, "month_id": months[0].id if months else None}
        self.active_week = ""
        self.day_detail = ""
        self._persist()
        return {"ok": True}

    def select_month(self, month_id: str) -> dict:
        self.route["month_id"] = month_id
        self.active_week = ""
        self.day_detail = ""
        self._persist()
        return {"ok": True}

    def open_month(self, month_id: str) -> dict:
        g = self.find_group(self.route.get("group_path"))
        if g is None:
            return {"ok": False, "message": "该组数据不可用", "kind": "error"}
        months = model.month_entries(g)
        month = next((m for m in months if m.id == month_id), months[0] if months else None)
        if month is None:
            return {"ok": False, "message": "该月没有可展开的周", "kind": "error"}
        self.route = {"page": 4, "group_path": g.path, "month_id": month.id}
        self.active_week = f"{g.path}#{month.id}#{month.weeks[0].id}" if month.weeks else ""
        self.day_detail = ""
        self._persist()
        return {"ok": True}

    def toggle_week(self, key: str) -> dict:
        if not key:
            return {"ok": False}
        if self.expanded.get(key):
            self.expanded.pop(key, None)
        else:
            self.expanded[key] = True
            self.active_week = key
        self._persist()
        return {"ok": True}

    def heat_year_select(self, year) -> dict:
        try:
            self.heat_year = int(year)
        except (TypeError, ValueError):
            return {"ok": False}
        self.heat_tip = ""
        self._persist()
        return {"ok": True}

    def heat_day_select(self, date_key: str) -> dict:
        self.heat_tip = "" if self.heat_tip == date_key else date_key
        return {"ok": True}

    def ov_month_shift(self, delta: int) -> dict:
        base = self._ov_base()
        nxt = dt.date(base.year + (base.month + delta - 1) // 12, (base.month + delta - 1) % 12 + 1, 1)
        self.ov_month = f"{nxt.year}-{nxt.month:02d}"
        self.day_detail = ""
        self._persist()
        return {"ok": True}

    def ov_month_today(self) -> dict:
        self.ov_month = ""
        self.day_detail = ""
        self._persist()
        return {"ok": True}

    def open_day(self, date_key: str) -> dict:
        if parse_iso_date(date_key) is None:
            return {"ok": False}
        self.day_detail = date_key
        return {"ok": True}

    def close_day(self) -> dict:
        self.day_detail = ""
        return {"ok": True}

    def back(self) -> dict:
        page = self.route.get("page") or 1
        if page == 4:
            self.route["page"] = 3
        elif page == 3:
            self.route = {"page": 2, "group_path": None, "month_id": None}
        else:
            self.route = {"page": 1, "group_path": None, "month_id": None}
        self._persist()
        return {"ok": True}

    def crumb(self, page: int) -> dict:
        if page == 1:
            return self.reselect()
        if page == 2:
            return self.to_overview()
        if page == 3 and self.route.get("group_path"):
            self.route["page"] = 3
            self._persist()
            return {"ok": True}
        return {"ok": False}

    def reselect(self) -> dict:
        self.route = {"page": 1, "group_path": None, "month_id": None}
        self._persist()
        return {"ok": True}

    def toggle_task(self, path: str, task_id: str, checked: bool) -> dict:
        entry = self.find_file(path)
        if entry is None or entry.group is None:
            return {"ok": False, "message": "找不到该组数据，请重新选择文件", "kind": "error"}
        task = next((t for t in entry.group.tasks if t.id == task_id), None)
        if task is None:
            return {"ok": False, "message": "找不到该任务，计划可能已更新", "kind": "error"}

        now = now_local_iso()
        history = list(task.history) + [{"action": "done" if checked else "undone", "at": now}]
        history = clean_history(history)
        done_at = now if checked else (task.done_at or model.last_done_at(task))

        try:
            current_text = jsonio.read_text(path)
        except OSError as exc:
            return {"ok": False, "message": f"写回失败：{exc.strerror or exc}", "kind": "error"}
        try:
            fresh_raw = json.loads(current_text)
        except ValueError:
            return {"ok": False, "message": "写回失败：原文件已不是合法 JSON（可能被外部改动）", "kind": "error"}

        if not jsonio.apply_task(fresh_raw, task_id, checked, done_at, history):
            return {"ok": False, "message": "写回失败：目标任务在文件中已不存在（计划可能被重新生成）", "kind": "error"}

        fmt = jsonio.detect_format(current_text)
        text = jsonio.serialize(fresh_raw, fmt)
        try:
            jsonio.write_text_atomic(path, text)
        except OSError as exc:
            return {"ok": False, "message": f"写回失败：{exc.strerror or exc}", "kind": "error"}

        external = entry.digest and entry.digest != jsonio.digest(current_text)
        self.last_write = now
        refreshed = self._load_path(path)
        if refreshed.group is not None:
            idx = self.files.index(entry)
            self.files[idx] = refreshed
        else:
            entry.raw = fresh_raw
            entry.text = text
            entry.digest = jsonio.digest(text)
            entry.fmt = fmt
            task.done = checked
            task.done_at = done_at
            task.history = history

        clock = now[11:19]
        msg = f"已写回「{os.path.basename(path)}」 · {clock}"
        if external:
            msg += "（检测到外部改动，已按最新文件内容合并）"
        return {"ok": True, "message": msg}

    # ------------------------------------------------------------------ 导出/导入
    def build_export(self) -> str:
        groups = self.groups
        progress = {}
        for g in groups:
            for t in g.tasks:
                progress[f"{g.file_name}::{t.id}"] = {
                    "done": bool(t.done),
                    "doneAt": t.done_at,
                    "history": clean_history(t.history),
                }
        out_groups = []
        for g in groups:
            clone = json.loads(json.dumps(g.raw, ensure_ascii=False))
            by_id = {t.id: t for t in g.tasks}
            for month in clone.get("months") or []:
                for week in (month.get("weeks") or []):
                    for day in (week.get("days") or []):
                        for task in (day.get("tasks") or []):
                            if not isinstance(task, dict) or task.get("id") is None:
                                continue
                            m = by_id.get(str(task["id"]))
                            if m is None:
                                continue
                            task["done"] = bool(m.done)
                            task["doneAt"] = m.done_at
                            hist = clean_history(m.history)
                            if hist:
                                task["history"] = hist
                            elif "history" in task:
                                del task["history"]
            out_groups.append({"fileName": g.file_name, "groupName": g.meta.get("groupName"), "data": clone})
        bundle = {
            "type": "kyn-progress-export",
            "version": 1,
            "exportedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "note": "由「任务进度追踪」导出，可用「导入进度」恢复",
            "progress": progress,
            "groups": out_groups,
        }
        return json.dumps(bundle, ensure_ascii=False, indent=2)

    def import_progress(self, path: str) -> dict:
        try:
            data = json.loads(jsonio.read_text(path))
        except OSError as exc:
            return {"ok": False, "message": f"导入失败：{exc.strerror or exc}", "kind": "error"}
        except ValueError:
            return {"ok": False, "message": "导入失败：不是合法的 JSON 文件", "kind": "error"}
        if not isinstance(data, dict):
            return {"ok": False, "message": "导入失败：文件结构无法识别", "kind": "error"}

        record_map: dict[tuple[str, str], dict] = {}
        count = 0

        def take(file_name: str, task_id, done, done_at, history) -> None:
            nonlocal count
            if not file_name or task_id is None or str(task_id) == "":
                return
            record_map[(file_name, str(task_id))] = {
                "done": bool(done),
                "done_at": done_at if isinstance(done_at, str) and done_at else None,
                "history": clean_history(history),
            }
            count += 1

        def from_group_json(obj: dict, fname: str) -> None:
            for month in obj.get("months") or []:
                for week in (month.get("weeks") if isinstance(month, dict) else None) or []:
                    for day in (week.get("days") if isinstance(week, dict) else None) or []:
                        for task in (day.get("tasks") if isinstance(day, dict) else None) or []:
                            if isinstance(task, dict) and task.get("id") is not None:
                                take(fname, task.get("id"), task.get("done"), task.get("doneAt"), task.get("history"))

        if isinstance(data.get("groups"), list):
            for item in data["groups"]:
                if isinstance(item, dict) and isinstance(item.get("data"), dict):
                    from_group_json(item["data"], str(item.get("fileName") or ""))
        elif isinstance(data.get("meta"), dict) and isinstance(data.get("months"), list):
            from_group_json(data, os.path.basename(path))

        applied = 0
        for (file_name, task_id), rec in record_map.items():
            entry = next((f for f in self.files if f.file_name == file_name), None)
            if entry is None:
                continue
            task = next((t for t in entry.group.tasks if t.id == task_id), None) if entry.group else None
            if task is None:
                continue
            task.done = rec["done"]
            task.done_at = rec["done_at"]
            task.history = clean_history(rec["history"])
            if not task.history and task.done and task.done_at:
                task.history = [{"action": "done", "at": task.done_at}]
            applied += 1

        if not count:
            return {"ok": False, "message": "文件里没有可导入的完成记录", "kind": "error"}
        msg = f"已导入 {count} 条记录，应用到 {applied} 个任务（未写盘，重新勾选即写回）"
        return {"ok": True, "message": msg}

    # ------------------------------------------------------------------ 视图
    def _ov_base(self) -> dt.date:
        parsed = parse_iso_date(f"{self.ov_month}-01") if self.ov_month else None
        return parsed or dt.date(self.today.year, self.today.month, 1)

    def _selected_year(self) -> tuple[list[int], int]:
        years: set[int] = set()
        for g in self.groups:
            for t in g.tasks:
                years.add(t.date_obj.year)
                if t.done and t.done_at:
                    day = local_date(t.done_at)
                    if day:
                        years.add(day.year)
        year_list = sorted(years)
        if self.heat_year and (not year_list or self.heat_year in year_list):
            selected = self.heat_year
        elif self.today.year in year_list:
            selected = self.today.year
        else:
            selected = year_list[0] if year_list else self.today.year
        return year_list, selected

    def build_view(self) -> dict:
        self._sanitize()
        page = self.route["page"]
        view = {
            "page": page,
            "title": self._title(),
            "crumbs": self._crumbs(),
            "today": self.today.isoformat(),
            "lastWrite": self.last_write,
        }
        if page == 1:
            view["page1"] = self._page1()
        elif page == 2:
            view.update(self._page2())
        elif page == 3:
            view.update(self._page3())
        else:
            view.update(self._page4())
        return view

    def _sanitize(self) -> None:
        route = self.route
        if route.get("page") not in (1, 2, 3, 4):
            route["page"] = 1
        if route["page"] >= 2 and not self.groups:
            route = {"page": 1, "group_path": None, "month_id": None}
            self.route = route
        if route["page"] >= 3:
            g = self.find_group(route.get("group_path"))
            if g is None:
                self.route = {"page": 2, "group_path": None, "month_id": None}
                return
            months = model.month_entries(g)
            if not any(m.id == route.get("month_id") for m in months):
                route["month_id"] = months[0].id if months else None
            if route["page"] == 4 and not route.get("month_id"):
                route["page"] = 3

    def _title(self) -> str:
        g = self.find_group(self.route.get("group_path"))
        prefix = f"{g.meta['groupName']} · " if g else ""
        return f"{prefix}{PAGE_NAMES[self.route['page']]} · 任务进度追踪"

    def _crumbs(self) -> list[dict]:
        page = self.route["page"]
        crumbs = [{"label": "选择题库", "page": 1, "current": page == 1}]
        if page >= 2:
            crumbs.append({"label": "总览", "page": 2, "current": page == 2})
        g = self.find_group(self.route.get("group_path"))
        if page >= 3 and g is not None:
            crumbs.append({"label": g.meta["groupName"], "page": 3, "current": page == 3})
        month = self._current_month(g) if page == 4 else None
        if page == 4 and month is not None:
            crumbs.append({"label": month.label, "page": 4, "current": True})
        return crumbs

    def _current_group(self) -> Group | None:
        return self.find_group(self.route.get("group_path"))

    def _current_month(self, g: Group | None):
        if g is None:
            return None
        months = model.month_entries(g)
        for m in months:
            if m.id == self.route.get("month_id"):
                return m
        return months[0] if months else None

    # ---- 第 1 页
    def _page1(self) -> dict:
        valid = [f for f in self.files if f.group is not None]
        invalid = [f for f in self.files if f.group is None]
        valid.sort(key=lambda f: (-len(f.group.tasks), f.display_name.lower(), f.file_name))
        rows = []
        for f in valid + invalid:
            if f.group is not None:
                warns = f.group.warnings
                warn = f" · {len(warns)} 条数据提示（{warns[0]}{' 等' if len(warns) > 1 else ''}）" if warns else ""
                sub = (f"{len(f.group.tasks)} 项任务 · {len(model.month_entries(f.group))} 个月 · "
                       f"{f.group.meta['subject']}{warn}")
            else:
                sub = f.error
            rows.append({
                "path": f.path,
                "displayName": f.display_name,
                "sub": sub,
                "error": bool(f.error),
            })
        return {
            "files": rows,
            "total": len(self.files),
            "valid": len(valid),
            "writeStatus": ("自动写盘已开启：勾选后会直接写回该组原 JSON（只改 done / doneAt / history）"
                            if valid else "选择文件后自动开启写盘"),
        }

    # ---- 第 2 页
    def _page2(self) -> dict:
        total = sum(len(g.tasks) for g in self.groups)
        return {
            "head": {"groups": len(self.groups), "tasks": total},
            "heat": self._heat(),
            "calendar": self._overview_calendar(),
            "groups": self._group_rows(),
            "dayDetail": self._day_detail(),
        }

    def _heat(self) -> dict:
        counts = model.completion_by_day(self.groups)
        uniq = model.unique_task_stats(self.groups)
        year_list, selected = self._selected_year()
        if year_list:
            range_years = list(range(year_list[0], year_list[-1] + 1))
        else:
            range_years = [self.today.year]

        first = dt.date(selected, 1, 1)
        last = dt.date(selected, 12, 31)
        start = add_days(first, -((first.weekday()) % 7))
        end = add_days(last, 6 - (last.weekday() % 7))
        week_count = (end - start).days // 7 + 1

        months = []
        for mi in range(1, 13):
            m_first = dt.date(selected, mi, 1)
            m_last = dt.date(selected + (mi == 12), 1 if mi == 12 else mi + 1, 1) - dt.timedelta(days=1)
            st_week = (add_days(m_first, -(m_first.weekday() % 7)) - start).days // 7
            en_week = (add_days(m_last, -(m_last.weekday() % 7)) - start).days // 7
            span = max(1, en_week - st_week + 1)
            months.append({"label": f"{mi}月", "width": span * 15 - 3})

        cells = []
        for w in range(week_count):
            for di in range(7):
                day = add_days(start, w * 7 + di)
                if day.year != selected:
                    cells.append({"out": True})
                    continue
                key = day.isoformat()
                n = counts.get(key, 0)
                cells.append({
                    "key": key,
                    "count": n,
                    "level": model.heat_level(n),
                    "active": self.heat_tip == key,
                    "title": f"{day.month}月{day.day}日 · 完成 {n} 项",
                })
        year_done = sum(n for k, n in counts.items() if k[:4] == str(selected))
        total_done = sum(counts.values())
        tip = ""
        if self.heat_tip:
            day = parse_iso_date(self.heat_tip)
            if day:
                tip = f"{day.month}月{day.day}日 · 完成 {counts.get(self.heat_tip, 0)} 项"
        return {
            "years": range_years if len(range_years) > 1 else [],
            "selected": selected,
            "months": months,
            "cells": cells,
            "yearDone": year_done,
            "totalDone": total_done,
            "uniqTotal": uniq["total"],
            "uniqDone": uniq["done"],
            "uniqPct": round(uniq["done"] * 100 / uniq["total"]) if uniq["total"] else 0,
            "tipText": tip,
        }

    def _overview_calendar(self) -> dict | None:
        ordered = model.sort_groups(self.groups)
        if not ordered:
            return None
        base = self._ov_base()
        y, mo = base.year, base.month
        is_cur = (y, mo) == (self.today.year, self.today.month)
        lead = base.weekday()
        days_in_month = (dt.date(y + (mo == 12), 1 if mo == 12 else mo + 1, 1) - dt.timedelta(days=1)).day
        slots = ((lead + days_in_month + 6) // 7) * 7

        meta_by_file = {g.path: {"name": g.meta["groupName"], "color": model.group_color(g.meta["groupName"]),
                                 "rank": i} for i, g in enumerate(ordered)}
        by_date: dict[str, list[Task]] = {}
        for g in ordered:
            for t in g.tasks:
                if t.date_obj.year == y and t.date_obj.month == mo:
                    by_date.setdefault(t.date, []).append(t)
        month_tasks = [t for ts in by_date.values() for t in ts]
        count_by_file: dict[str, int] = {}
        for t in month_tasks:
            count_by_file[t.group_path] = count_by_file.get(t.group_path, 0) + 1
        mst = model.stats(month_tasks)

        cells = []
        for i in range(slots):
            day_num = i - lead + 1
            if day_num < 1 or day_num > days_in_month:
                cells.append({"empty": True})
                continue
            key = f"{y}-{mo:02d}-{day_num:02d}"
            tasks = sorted(by_date.get(key, []), key=lambda t: (
                meta_by_file.get(t.group_path, {}).get("rank", 999), model.prio_rank(t), t.id))
            chips = []
            seen: dict[str, dict] = {}
            for t in tasks:
                info = meta_by_file.get(t.group_path) or {
                    "name": t.group_name, "color": model.group_color(t.group_name)}
                entry = seen.setdefault(t.group_path, {"name": info["name"], "color": info["color"], "tasks": []})
                entry["tasks"].append(t)
            for item in list(seen.values())[:3]:
                st = model.stats(item["tasks"])
                chips.append({
                    "name": item["name"],
                    "strong": item["color"]["strong"],
                    "soft": item["color"]["soft"],
                    "done": st["done"],
                    "total": st["total"],
                    "isDone": bool(st["total"]) and st["done"] == st["total"],
                })
            more = max(0, len(seen) - len(chips))
            st = model.stats(tasks)
            cells.append({
                "date": key,
                "day": day_num,
                "count": len(tasks),
                "chips": chips,
                "more": more,
                "minutesText": fmt_minutes(st["minutes"]) if st["minutes"] else "",
            })

        legend = [{
            "name": g.meta["groupName"], "color": model.group_color(g.meta["groupName"])["strong"],
            "count": count_by_file.get(g.path, 0),
        } for g in ordered if count_by_file.get(g.path)]

        return {
            "title": f"{mo}月日历 · 全部科目",
            "note": f"本月 {mst['total']} 项 · 已完成 {mst['done']} 项" + (
                f" · {len(count_by_file)} 个科目" if count_by_file else ""),
            "isCurMonth": is_cur,
            "weekdays": ["一", "二", "三", "四", "五", "六", "日"],
            "cells": cells,
            "legend": legend,
            "monthId": f"{y}-{mo:02d}",
        }

    def _group_rows(self) -> list[dict]:
        rows = []
        for g in model.sort_groups(self.groups):
            color = model.group_color(g.meta["groupName"])
            rows.append({
                "path": g.path,
                "name": g.meta["groupName"],
                "subject": g.meta["subject"],
                "fit": g.meta["kind"] == "fitness",
                "kindLabel": "健身" if g.meta["kind"] == "fitness" else "学习",
                "mustKb": color["strong"],
                "soft": color["soft"],
                "topics": model.topic_summaries(g),
                "stats": model.stats(g.tasks),
                "prediction": model.predict(g.tasks, g.meta["planStart"], self.today),
            })
        return rows

    def _day_detail(self) -> dict | None:
        if self.route["page"] != 2 or not self.day_detail:
            return None
        day = parse_iso_date(self.day_detail)
        if day is None:
            return None
        ordered = model.sort_groups(self.groups)
        rank = {g.path: i for i, g in enumerate(ordered)}
        name_by = {g.path: g.meta["groupName"] for g in ordered}
        color_by = {g.path: model.group_color(g.meta["groupName"]) for g in ordered}
        tasks: list[Task] = []
        seen: set[str] = set()
        for g in ordered:
            for t in g.tasks:
                if t.date != self.day_detail:
                    continue
                key = f"{t.group_path}::{t.id}"
                if key in seen:
                    continue
                seen.add(key)
                tasks.append(t)
        tasks.sort(key=lambda t: (rank.get(t.group_path, 999), model.prio_rank(t), t.id))
        st = model.stats(tasks)
        rows = [{
            "name": name_by.get(t.group_path, t.group_name),
            "strong": color_by.get(t.group_path, model.group_color(t.group_name))["strong"],
            "soft": color_by.get(t.group_path, model.group_color(t.group_name))["soft"],
            "priority": t.priority,
            "title": t.title,
            "minutesText": fmt_minutes(t.minutes),
            "slot": t.slot,
            "was": model.done_text(t, self.today) if t.done else model.last_done_text(t, self.today),
            "done": t.done,
        } for t in tasks]
        subjects = len({t.group_path for t in tasks})
        return {
            "title": f"{day.month}月{day.day}日 {weekday_text(day)}",
            "sub": (f"共 {st['total']} 项 · 已完成 {st['done']} 项 · 总时长 "
                    f"{fmt_minutes(st['minutes']) if st['minutes'] else '0 分钟'}"
                    + (f" · {subjects} 个科目" if subjects else "")),
            "rows": rows,
        }

    # ---- 第 3 页
    def _page3(self) -> dict:
        g = self._current_group()
        if g is None:
            return {"empty": "该组数据已不可用，请返回总览重新选择。"}
        months = model.month_entries(g)
        month = self._current_month(g)
        is_fit = g.meta["kind"] == "fitness"
        month_tasks = model.tasks_in_month(g, month)
        own = [t for t in month_tasks if t.kind == g.meta["kind"]]
        own_stats = model.stats(own)
        color = model.group_color(g.meta["groupName"])

        open_months, done_months = [], []
        for m in months:
            (done_months if model.all_done(model.tasks_in_month(g, m)) else open_months).append(m)
        display_months = open_months + done_months

        cards = []
        for m in display_months:
            tasks = model.sort_for_display(model.tasks_in_month(g, m))
            st = model.stats(tasks)
            complete = model.all_done(tasks)
            cards.append({
                "id": m.id,
                "label": m.label,
                "complete": complete,
                "total": st["total"],
                "done": st["done"],
                "minutesText": fmt_minutes(st["minutes"]),
                "tasks": [{
                    "priority": t.priority,
                    "title": t.title,
                    "fit": t.kind == "fitness",
                    "dateText": f"{t.date_obj.month}月{t.date_obj.day}日",
                    "minutesText": fmt_minutes(t.minutes),
                    "was": model.done_text(t, self.today) if t.done else model.last_done_text(t, self.today),
                    "done": t.done,
                } for t in tasks],
            })

        return {
            "groupName": g.meta["groupName"],
            "groupPath": g.path,
            "isFit": is_fit,
            "chips": [{"id": m.id, "label": m.label, "active": bool(month and m.id == month.id)} for m in display_months],
            "stat": {
                "label": "健身" if is_fit else "学习",
                "stats": own_stats,
                "color": "#d9901f" if is_fit else color["strong"],
                "prediction": model.predict(own, g.meta["planStart"], self.today),
                "scope": f"统计范围：{month.label if month else '—'}（{'健身' if is_fit else '学习'} = 本组该月任务）",
            },
            "calendar": self._month_calendar(g, month),
            "cards": cards,
            "lead": f"顶部只显示本组类型（{'健身' if is_fit else '学习'}）的进度；下方按月列出任务，已完成任务沉到月内末尾。",
        }

    def _month_calendar(self, g: Group, month) -> dict | None:
        rng = model.month_range(month) if month else None
        if rng is None:
            return None
        rng_start, rng_end = rng
        y, mo = rng_start.year, rng_start.month
        base = dt.date(y, mo, 1)
        lead = base.weekday()
        days_in_month = (dt.date(y + (mo == 12), 1 if mo == 12 else mo + 1, 1) - dt.timedelta(days=1)).day
        cells: list[dict] = []
        by_date: dict[str, list[Task]] = {}
        for t in g.tasks:
            if rng_start <= t.date_obj <= rng_end:
                by_date.setdefault(t.date, []).append(t)
        for t in model.fitness_in_month(self.groups, month):
            if t.group_path == g.path:
                continue
            by_date.setdefault(t.date, []).append(t)
        for ts in by_date.values():
            ts[:] = model.sort_calendar(ts)
        for i in range(42):
            day_num = i - lead + 1
            if day_num < 1 or day_num > days_in_month:
                cells.append({"empty": True})
                continue
            key = f"{y}-{mo:02d}-{day_num:02d}"
            tasks = by_date.get(key, [])
            st = model.stats(tasks)
            cells.append({
                "date": key,
                "day": day_num,
                "count": len(tasks),
                "tasks": [{
                    "title": t.title,
                    "priority": t.priority,
                    "fit": t.kind == "fitness",
                    "done": t.done,
                } for t in tasks[:4]],
                "more": max(0, len(tasks) - 4),
                "minutesText": fmt_minutes(st["minutes"]) if st["minutes"] else "",
            })
        return {
            "title": f"{mo}月日历 · {g.meta['groupName']}",
            "note": "周一起始 · 已完成任务下沉并置灰",
            "weekdays": ["一", "二", "三", "四", "五", "六", "日"],
            "cells": cells,
            "groupPath": g.path,
        }

    # ---- 第 4 页
    def _page4(self) -> dict:
        g = self._current_group()
        if g is None:
            return {"empty": "该组数据已不可用，请返回总览重新选择。"}
        month = self._current_month(g)
        weeks = month.weeks if month else []
        is_fit = g.meta["kind"] == "fitness"
        color = model.group_color(g.meta["groupName"])
        active_key = self.active_week or (f"{g.path}#{month.id}#{weeks[0].id}" if month and weeks else "")
        active_week = next((w for w in weeks if f"{g.path}#{month.id}#{w.id}" == active_key), weeks[0] if weeks else None)

        cards = []
        for w in weeks:
            key = f"{g.path}#{month.id}#{w.id}"
            tasks = model.week_tasks(g, self.groups, w.start_obj, w.end_obj)
            st = model.stats(tasks)
            opened = bool(self.expanded.get(key))
            days = []
            if opened:
                for bucket in model.group_by_day(tasks):
                    dst = model.stats(bucket["tasks"])
                    days.append({
                        "head": f"{bucket['dateObj'].month}月{bucket['dateObj'].day}日 {weekday_text(bucket['dateObj'])}",
                        "sub": f"{dst['total']} 项 · 约 {fmt_minutes(dst['minutes'])}",
                        "tasks": [{
                            "path": t.group_path,
                            "id": t.id,
                            "title": t.title,
                            "priority": t.priority,
                            "minutesText": fmt_minutes(t.minutes),
                            "slot": t.slot,
                            "fit": t.kind == "fitness",
                            "done": t.done,
                            "timeText": model.last_done_text(t, self.today),
                        } for t in bucket["tasks"]],
                    })
            cards.append({
                "key": key,
                "title": model.week_title(w),
                "sub": f"{st['total']} 项 · 已完成 {st['done']} 项 · 约 {fmt_minutes(st['minutes'])}",
                "pct": st["pct"],
                "done": st["done"],
                "total": st["total"],
                "open": opened,
                "days": days,
            })

        bars = []
        if active_week is not None:
            own = [t for t in model.tasks_in_range(g.tasks, active_week.start_obj, active_week.end_obj)
                   if t.kind == g.meta["kind"]]
            if not is_fit:
                bars.append({
                    "label": "学习", "stats": model.stats(own), "color": color["strong"], "emptyWord": "学习任务",
                    "prediction": model.predict(own, g.meta["planStart"], self.today),
                })
                fit_tasks = [t for t in model.week_tasks(g, self.groups, active_week.start_obj, active_week.end_obj)
                             if t.kind == "fitness"]
                bars.append({
                    "label": "健身", "stats": model.stats(fit_tasks), "color": "#d9901f", "emptyWord": "健身任务",
                    "prediction": model.predict(fit_tasks, g.meta["planStart"], self.today),
                })
            else:
                bars.append({
                    "label": "健身", "stats": model.stats(own), "color": "#d9901f", "emptyWord": "健身任务",
                    "prediction": model.predict(own, g.meta["planStart"], self.today),
                })

        scope = (f"统计范围：{active_week.label}，{fmt_range(active_week.start_obj, active_week.end_obj)}"
                 if active_week else "统计范围：本周")
        return {
            "groupName": g.meta["groupName"],
            "groupPath": g.path,
            "monthLabel": month.label if month else "",
            "monthId": month.id if month else "",
            "bars": bars,
            "scope": scope + f"（{'健身' if is_fit else '学习'} = 本组该周任务）",
            "weeks": cards,
            "lead": "点击周卡片原地展开或收起；勾选即完成并记录当时时间戳，取消勾选会记录一次撤销，最近完成时间仍保留。",
        }

    def _all_tasks(self) -> list[Task]:
        return [t for g in self.groups for t in g.tasks]

    # ------------------------------------------------------------------ 分发
    def dispatch(self, action: str, payload: dict | None = None) -> dict:
        payload = payload or {}
        route_actions = {
            "to_overview": lambda: self.to_overview(),
            "open_group": lambda: self.open_group(str(payload.get("path") or "")),
            "select_month": lambda: self.select_month(str(payload.get("month") or "")),
            "open_month": lambda: self.open_month(str(payload.get("month") or "")),
            "toggle_week": lambda: self.toggle_week(str(payload.get("week") or "")),
            "heat_year": lambda: self.heat_year_select(payload.get("year")),
            "heat_day": lambda: self.heat_day_select(str(payload.get("date") or "")),
            "ov_month_prev": lambda: self.ov_month_shift(-1),
            "ov_month_next": lambda: self.ov_month_shift(1),
            "ov_month_today": self.ov_month_today,
            "open_day": lambda: self.open_day(str(payload.get("date") or "")),
            "close_day": self.close_day,
            "back": self.back,
            "crumb": lambda: self.crumb(int(payload.get("page") or 0)),
            "reselect": self.reselect,
            "remove_file": lambda: self.remove_file(str(payload.get("path") or "")),
            "clear_files": self.clear_files,
            "toggle_task": lambda: self.toggle_task(
                str(payload.get("path") or ""), str(payload.get("id") or ""), bool(payload.get("checked"))),
        }
        handler = route_actions.get(action)
        if handler is None:
            return {"ok": False, "message": f"未知操作：{action}", "kind": "error"}
        result = handler() or {"ok": True}
        result.setdefault("ok", True)
        return result


__all__ = ["AppService", "FileEntry", "PAGE_NAMES"]
