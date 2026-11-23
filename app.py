#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PlanCheckBox-python —— 丢入任务文件，或在界面上直接创建计划。

零第三方依赖，Python 3.8+ 直接启动：

    python3 app.py            # 默认 http://127.0.0.1:8765，自动打开浏览器
    python3 app.py --port 9000 --no-browser

数据以 JSON 文件形式保存在 ./data/ 目录，一个计划一个文件，可随时备份/迁移。
"""

import argparse
import json
import os
import re
import sys
import threading
import uuid
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")
CHAT_DIR = os.path.join(DATA_DIR, "chat")

COLORS = ["pine", "amber", "coral", "blue", "mint", "magenta", "lavender", "teal"]
EMOJIS = ["🎯", "🏃", "📚", "", "✍️", "🧠", "🎨", "", "🗣️", "💻", "", "🍳"]

_lock = threading.Lock()


# ---------------------------------------------------------------- 工具函数

def today_str():
    return date.today().isoformat()


def new_id(prefix):
    return "%s-%s" % (prefix, uuid.uuid4().hex[:10])


def valid_date(s):
    if not isinstance(s, str):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def clean_str(v, limit=200):
    if not isinstance(v, str):
        return ""
    return v.strip()[:limit]


def atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------- 数据层

def normalize_task(t, default_date=None):
    """把任意来源的任务规整为统一结构。"""
    tid = clean_str(t.get("id"), 60) or new_id("t")
    title = clean_str(t.get("title") or t.get("name"), 200)
    if not title:
        return None
    d = t.get("date") or default_date
    if not valid_date(d):
        d = default_date if valid_date(default_date or "") else today_str()
    note_parts = []
    if t.get("note"):
        note_parts.append(clean_str(t["note"], 300))
    extras = []
    if t.get("slot"):
        extras.append(clean_str(t["slot"], 20))
    if t.get("minutes"):
        try:
            extras.append("%d 分钟" % int(t["minutes"]))
        except (TypeError, ValueError):
            pass
    if t.get("priority"):
        extras.append(clean_str(t["priority"], 10))
    if extras:
        note_parts.append(" · ".join(extras))
    return {
        "id": tid,
        "title": title,
        "date": d,
        "done": bool(t.get("done", False)),
        "doneAt": t.get("doneAt") or "",
        "note": " · ".join(p for p in note_parts if p),
    }


def normalize_plan(p, order=0):
    name = clean_str(p.get("name") or p.get("title"), 80)
    if not name:
        return None
    start = p.get("startDate") or p.get("start") or today_str()
    end = p.get("endDate") or p.get("end") or start
    if not valid_date(start):
        start = today_str()
    if not valid_date(end):
        end = start
    if end < start:
        start, end = end, start
    tasks = []
    seen = set()
    for t in p.get("tasks", []) or []:
        nt = normalize_task(t, default_date=start)
        if nt and nt["id"] not in seen:
            seen.add(nt["id"])
            tasks.append(nt)
    tasks.sort(key=lambda x: (x["date"], x["title"]))
    color = p.get("color")
    if color not in COLORS:
        color = COLORS[order % len(COLORS)]
    emoji = clean_str(p.get("emoji"), 16) or "🎯"
    return {
        "id": clean_str(p.get("id"), 60) or new_id("p"),
        "name": name,
        "emoji": emoji,
        "color": color,
        "description": clean_str(p.get("description"), 500),
        "startDate": start,
        "endDate": end,
        "createdAt": p.get("createdAt") or datetime.now().isoformat(timespec="seconds"),
        "order": int(p.get("order", order)),
        "tasks": tasks,
    }


def parse_import(payload):
    """兼容三种格式：原生格式 / 原版 PlanCheckBox checkbox_use / 简易任务数组。"""
    plans = []
    if isinstance(payload, list):
        if payload and isinstance(payload[0], dict) and ("tasks" in payload[0] or "name" in payload[0]):
            for i, p in enumerate(payload):
                np = normalize_plan(p, i)
                if np:
                    plans.append((np, "原生格式"))
        else:
            tasks = [normalize_task(t) for t in payload if isinstance(t, dict)]
            tasks = [t for t in tasks if t]
            if tasks:
                dates = [t["date"] for t in tasks]
                plans.append((normalize_plan({
                    "name": "导入的计划",
                    "startDate": min(dates),
                    "endDate": max(dates),
                    "tasks": tasks,
                }), "简易列表"))
    elif isinstance(payload, dict):
        if "months" in payload:  # 原版 PlanCheckBox checkbox_use.json
            meta = payload.get("meta", {}) or {}
            tasks = []
            for month in payload.get("months", []) or []:
                for week in month.get("weeks", []) or []:
                    for day in week.get("days", []) or []:
                        for t in day.get("tasks", []) or []:
                            nt = normalize_task(t, default_date=day.get("date"))
                            if nt:
                                tasks.append(nt)
            if tasks:
                dates = [t["date"] for t in tasks]
                start = meta.get("planStart") if valid_date(meta.get("planStart", "")) else min(dates)
                end = meta.get("examDate") if valid_date(meta.get("examDate", "")) else max(dates)
                name = clean_str(meta.get("groupName") or meta.get("subject"), 80) or "导入的计划"
                plans.append((normalize_plan({
                    "name": name,
                    "description": clean_str(meta.get("subject"), 500),
                    "startDate": start,
                    "endDate": end,
                    "tasks": tasks,
                }), "原版 PlanCheckBox"))
        elif "plans" in payload and isinstance(payload["plans"], list):
            for i, p in enumerate(payload["plans"]):
                np = normalize_plan(p, i)
                if np:
                    plans.append((np, "原生格式"))
        else:
            np = normalize_plan(payload)
            if np:
                plans.append((np, "原生格式"))
    return plans


def load_plans():
    plans = []
    if os.path.isdir(DATA_DIR):
        for fn in os.listdir(DATA_DIR):
            if fn.endswith(".json") and not fn.startswith("_"):
                try:
                    with open(os.path.join(DATA_DIR, fn), encoding="utf-8") as f:
                        p = json.load(f)
                    np = normalize_plan(p, p.get("order", 0))
                    if np:
                        plans.append(np)
                except (json.JSONDecodeError, OSError):
                    continue
    plans.sort(key=lambda p: (p.get("order", 0), p.get("createdAt", "")))
    return plans


def save_plan(plan):
    os.makedirs(DATA_DIR, exist_ok=True)
    atomic_write(os.path.join(DATA_DIR, plan["id"] + ".json"), plan)


def delete_plan_file(pid):
    path = os.path.join(DATA_DIR, pid + ".json")
    if os.path.exists(path):
        os.remove(path)


def find_plan(plans, pid):
    for p in plans:
        if p["id"] == pid:
            return p
    return None


# ---------------------------------------------------------------- 聊天会话存储
# 会话消息存在本机 data/chat/；API Key 只保存在浏览器 localStorage，不经过本服务。

def clean_message(m):
    if not isinstance(m, dict):
        return None
    role = m.get("role")
    if role not in ("user", "assistant"):
        return None
    text = m.get("text")
    if not isinstance(text, str):
        return None
    return {
        "id": clean_str(m.get("id"), 60) or new_id("m"),
        "role": role,
        "text": text[:32000],
        "thinking": clean_str(m.get("thinking"), 32000) if isinstance(m.get("thinking"), str) else "",
        "status": m.get("status") if m.get("status") in ("done", "stopped", "error") else "done",
        "error": clean_str(m.get("error"), 500),
        "createdAt": clean_str(m.get("createdAt"), 40) or datetime.now().isoformat(timespec="seconds"),
    }


def load_chat_sessions():
    sessions = []
    if os.path.isdir(CHAT_DIR):
        for fn in os.listdir(CHAT_DIR):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(CHAT_DIR, fn), encoding="utf-8") as f:
                    s = json.load(f)
                if isinstance(s, dict) and s.get("id"):
                    sessions.append(s)
            except (json.JSONDecodeError, OSError):
                continue
    sessions.sort(key=lambda s: s.get("updatedAt", ""), reverse=True)
    return sessions


def save_chat_session(s):
    os.makedirs(CHAT_DIR, exist_ok=True)
    atomic_write(os.path.join(CHAT_DIR, s["id"] + ".json"), s)


# ---------------------------------------------------------------- 首次启动示例数据

def seed_if_empty():
    if load_plans():
        return
    today = date.today()

    def d(offset):
        return (today + timedelta(days=offset)).isoformat()

    run_tasks = []
    cur = today - timedelta(days=12)
    while cur <= today + timedelta(days=17):
        if cur.weekday() in (0, 2, 4, 6):
            done = cur < today and (cur.toordinal() % 10) < 7
            run_tasks.append({
                "title": "晨跑 3 公里", "date": cur.isoformat(), "done": done,
                "note": "跑前热身 5 分钟",
            })
            if cur.weekday() == 6:
                run_tasks.append({"title": "跑后拉伸 15 分钟", "date": cur.isoformat(), "done": done})
        cur += timedelta(days=1)

    books = ["《认知觉醒》", "《置身事内》", "《纳瓦尔宝典》"]
    read_tasks = []
    cur = today - timedelta(days=10)
    i = 0
    while cur <= today + timedelta(days=24):
        if cur.weekday() in (1, 3):
            read_tasks.append({
                "title": "阅读 %s 30 页" % books[i % 3], "date": cur.isoformat(),
                "done": cur < today and i % 5 != 4,
            })
            i += 1
        elif cur.weekday() == 5:
            read_tasks.append({"title": "写本周读书笔记", "date": cur.isoformat(), "done": cur < today})
        cur += timedelta(days=1)

    sprint = ["梳理需求清单", "画核心流程原型", "搭建项目骨架", "实现数据层",
              "实现界面交互", "联调与自测", "修复体验问题", "准备验收演示"]
    sprint_tasks = []
    cur = today - timedelta(days=3)
    i = 0
    while cur <= today + timedelta(days=10) and i < len(sprint):
        if cur.weekday() < 5:
            sprint_tasks.append({
                "title": sprint[i], "date": cur.isoformat(),
                "done": cur < today - timedelta(days=1),
                "note": "项目冲刺 · 第 %d 步" % (i + 1),
            })
            i += 1
        cur += timedelta(days=1)

    seeds = [
        normalize_plan({"name": "晨跑习惯", "emoji": "🏃", "color": "mint",
                        "description": "每周四天晨跑，先把习惯立住。",
                        "startDate": d(-12), "endDate": d(17), "tasks": run_tasks}, 0),
        normalize_plan({"name": "深度阅读", "emoji": "📚", "color": "blue",
                        "description": "三本书轮读，周六输出笔记。",
                        "startDate": d(-10), "endDate": d(24), "tasks": read_tasks}, 1),
        normalize_plan({"name": "项目冲刺", "emoji": "🎯", "color": "amber",
                        "description": "两周交付一个可用版本。",
                        "startDate": d(-3), "endDate": d(10), "tasks": sprint_tasks}, 2),
    ]
    for p in seeds:
        save_plan(p)


# ---------------------------------------------------------------- HTTP 服务

class Handler(BaseHTTPRequestHandler):
    server_version = "PlanCheckBox/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), fmt % args))

    # ---- 响应工具
    def send_json(self, obj, code=200, extra_headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_err(self, msg, code=400):
        self.send_json({"error": msg}, code)

    def read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > 20 * 1024 * 1024:
                return None
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return None

    # ---- 静态文件
    def serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        path = unquote(path.split("?")[0])
        if ".." in path:
            return self.send_err("forbidden", 403)
        full = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            return self.send_err("not found", 404)
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".json": "application/json; charset=utf-8",
        }.get(os.path.splitext(full)[1], "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ---- 路由
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            with _lock:
                plans = load_plans()
            return self.send_json({"plans": plans, "today": today_str(),
                                   "colors": COLORS, "emojis": EMOJIS})
        if path == "/api/chat/sessions":
            with _lock:
                sessions = load_chat_sessions()
            return self.send_json({"sessions": sessions})
        if path == "/api/export":
            with _lock:
                plans = load_plans()
            return self.send_json({"plans": plans}, extra_headers={
                "Content-Disposition": 'attachment; filename="plancheckbox-export.json"'})
        m = re.match(r"^/api/export/([\w-]+)$", path)
        if m:
            with _lock:
                p = find_plan(load_plans(), m.group(1))
            if not p:
                return self.send_err("计划不存在", 404)
            fname = re.sub(r"[^\w\u4e00-\u9fff-]", "_", p["name"]) or "plan"
            return self.send_json(p, extra_headers={
                "Content-Disposition": 'attachment; filename="%s.json"' % fname})
        if path.startswith("/api/"):
            return self.send_err("not found", 404)
        return self.serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self.read_body()
        if body is None:
            return self.send_err("请求体不是合法 JSON")
        with _lock:
            plans = load_plans()
            if path == "/api/plans":
                np = normalize_plan(body, len(plans))
                if not np:
                    return self.send_err("计划名称不能为空")
                if find_plan(plans, np["id"]):  # 恢复（撤销删除）时 id 冲突则换新 id
                    np["id"] = new_id("p")
                save_plan(np)
                return self.send_json(np, 201)
            if path == "/api/import":
                wrapped = isinstance(body, dict) and "payload" in body
                payload = body["payload"] if wrapped else body
                dry = wrapped and bool(body.get("dryRun"))
                parsed = parse_import(payload)
                if not parsed:
                    return self.send_err("无法识别文件格式：支持原生格式、原版 checkbox_use.json 或任务数组")
                if dry:
                    return self.send_json({"imported": [{"plan": np, "source": src} for np, src in parsed]})
                created = []
                for np, src in parsed:
                    np["order"] = len(plans) + len(created)
                    save_plan(np)
                    created.append({"plan": np, "source": src})
                return self.send_json({"imported": created}, 201)
            if path == "/api/reorder":
                ids = body.get("ids", [])
                by_id = {p["id"]: p for p in plans}
                for i, pid in enumerate(ids):
                    if pid in by_id:
                        by_id[pid]["order"] = i
                        save_plan(by_id[pid])
                return self.send_json({"ok": True})
            m = re.match(r"^/api/plans/([\w-]+)/tasks$", path)
            if m:
                p = find_plan(plans, m.group(1))
                if not p:
                    return self.send_err("计划不存在", 404)
                nt = normalize_task(body, default_date=today_str())
                if not nt:
                    return self.send_err("任务标题不能为空")
                p["tasks"].append(nt)
                p["tasks"].sort(key=lambda x: (x["date"], x["title"]))
                save_plan(p)
                return self.send_json(nt, 201)
        return self.send_err("not found", 404)

    def do_PUT(self):
        path = urlparse(self.path).path
        body = self.read_body()
        if body is None:
            return self.send_err("请求体不是合法 JSON")
        with _lock:
            m = re.match(r"^/api/chat/sessions/([\w-]+)$", path)
            if m:
                sid = m.group(1)
                messages = [clean_message(x) for x in (body.get("messages") or [])[:400]]
                messages = [x for x in messages if x]
                session = {
                    "id": sid,
                    "title": clean_str(body.get("title"), 80) or "新对话",
                    "createdAt": clean_str(body.get("createdAt"), 40) or datetime.now().isoformat(timespec="seconds"),
                    "updatedAt": datetime.now().isoformat(timespec="seconds"),
                    "messages": messages,
                }
                save_chat_session(session)
                return self.send_json(session)
            plans = load_plans()
            m = re.match(r"^/api/plans/([\w-]+)$", path)
            if m:
                p = find_plan(plans, m.group(1))
                if not p:
                    return self.send_err("计划不存在", 404)
                body["id"] = p["id"]
                body.setdefault("order", p["order"])
                body.setdefault("createdAt", p["createdAt"])
                np = normalize_plan(body, p["order"])
                if not np:
                    return self.send_err("计划名称不能为空")
                save_plan(np)
                return self.send_json(np)
            m = re.match(r"^/api/plans/([\w-]+)/tasks/([\w-]+)$", path)
            if m:
                p = find_plan(plans, m.group(1))
                if not p:
                    return self.send_err("计划不存在", 404)
                for i, t in enumerate(p["tasks"]):
                    if t["id"] == m.group(2):
                        body["id"] = t["id"]
                        nt = normalize_task(body, default_date=t["date"])
                        if not nt:
                            return self.send_err("任务标题不能为空")
                        p["tasks"][i] = nt
                        p["tasks"].sort(key=lambda x: (x["date"], x["title"]))
                        save_plan(p)
                        return self.send_json(nt)
                return self.send_err("任务不存在", 404)
        return self.send_err("not found", 404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        with _lock:
            m = re.match(r"^/api/chat/sessions/([\w-]+)$", path)
            if m:
                fp = os.path.join(CHAT_DIR, m.group(1) + ".json")
                if os.path.exists(fp):
                    os.remove(fp)
                return self.send_json({"ok": True})
            plans = load_plans()
            m = re.match(r"^/api/plans/([\w-]+)$", path)
            if m:
                p = find_plan(plans, m.group(1))
                if not p:
                    return self.send_err("计划不存在", 404)
                delete_plan_file(p["id"])
                return self.send_json({"deleted": p})
            m = re.match(r"^/api/plans/([\w-]+)/tasks/([\w-]+)$", path)
            if m:
                p = find_plan(plans, m.group(1))
                if not p:
                    return self.send_err("计划不存在", 404)
                for i, t in enumerate(p["tasks"]):
                    if t["id"] == m.group(2):
                        p["tasks"].pop(i)
                        save_plan(p)
                        return self.send_json({"deleted": t, "planId": p["id"]})
                return self.send_err("任务不存在", 404)
        return self.send_err("not found", 404)


def main():
    parser = argparse.ArgumentParser(description="PlanCheckBox-python 本地服务")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true", help="启动时不自动打开浏览器")
    args = parser.parse_args()

    seed_if_empty()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = "http://%s:%d" % (args.host, args.port)
    print("PlanCheckBox 已启动：%s" % url)
    print("数据目录：%s" % DATA_DIR)
    print("按 Ctrl+C 停止。")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
