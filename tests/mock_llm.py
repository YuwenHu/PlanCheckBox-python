#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模拟 DeepSeek 兼容 API（Anthropic Messages + SSE），供端到端测试使用。

- GET  /models                     校验 Key（bad-key 返回 401）
- POST /anthropic/v1/messages      按最后一条用户消息内容返回不同脚本：
    含「晨跑」→ 文本 + plan-json 提案；含「慢速」→ 慢流（测停止）；
    含「错误」→ 首次返回错误帧、重试成功；含「思考」→ thinking 块；
    其他 → Markdown 富文本回复。
"""
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ERROR_ONCE = {"errored": False}

PLAN_JSON = {
    "name": "30 天晨跑计划", "emoji": "🏃", "color": "mint",
    "description": "循序渐进，从走跑结合到连续 5 公里。",
    "startDate": "2026-11-23", "endDate": "2026-12-22",
    "tasks": [{"title": "走跑结合 20 分钟（第 %d 天）" % (i + 1), "date": "2026-11-%d" % (23 + i)}
              for i in range(0, 7)] +
             [{"title": "慢跑 3 公里（第 %d 天）" % (i + 8), "date": "2026-12-%02d" % (i + 1)}
              for i in range(0, 8)],
}

MD_REPLY = """今天的安排建议如下：

## 优先级排序

1. **项目冲刺**：先完成「实现界面交互」，这是今天的硬任务
2. **晨跑 3 公里**：早上完成，唤醒状态
3. 阅读可以放到晚间碎片时间

> 提示：上午专注攻坚，下午处理轻量任务。

示例代码块：

```python
def today_focus(tasks):
    return sorted(tasks, key=lambda t: t.priority)
```

| 时段 | 安排 |
| --- | --- |
| 上午 | 项目攻坚 |
| 晚上 | 阅读 30 页 |

有需要随时叫我调整。"""


def sse(wfile, event, data):
    wfile.write(("event: %s\ndata: %s\n\n" % (event, json.dumps(data, ensure_ascii=False))).encode("utf-8"))
    wfile.flush()


def stream_text(wfile, text, idx=0, chunk=7, delay=0.012):
    sse(wfile, "content_block_start", {"type": "content_block_start", "index": idx,
                                       "content_block": {"type": "text", "text": ""}})
    for i in range(0, len(text), chunk):
        sse(wfile, "content_block_delta", {"type": "content_block_delta", "index": idx,
                                           "delta": {"type": "text_delta", "text": text[i:i + chunk]}})
        time.sleep(delay)
    sse(wfile, "content_block_stop", {"type": "content_block_stop", "index": idx})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "x-api-key, content-type, accept, authorization, anthropic-beta")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/models":
            auth = self.headers.get("Authorization", "")
            if "bad-key" in auth:
                body = json.dumps({"error": {"message": "Authentication Fails, Your api key is invalid"}}).encode()
                self.send_response(401)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = json.dumps({"data": [{"id": "deepseek-flash"}, {"id": "deepseek-v4-pro"}]}).encode()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path != "/anthropic/v1/messages":
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length).decode("utf-8"))
        if self.headers.get("x-api-key") == "bad-key":
            body = json.dumps({"error": {"message": "Authentication Fails"}}).encode()
            self.send_response(401)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        last_user = ""
        for m in reversed(req.get("messages", [])):
            if m.get("role") == "user":
                last_user = m.get("content") if isinstance(m.get("content"), str) else ""
                break
        thinking_on = (req.get("thinking") or {}).get("type") == "enabled"

        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        w = self.wfile
        try:
            w.write(b": keep-alive\n\n")
            sse(w, "message_start", {"type": "message_start",
                                     "message": {"id": "mock-msg-1", "model": req.get("model", "deepseek-flash"),
                                                 "usage": {"input_tokens": 100, "output_tokens": 0}}})
            sse(w, "ping", {"type": "ping"})

            if "错误" in last_user and not ERROR_ONCE["errored"]:
                ERROR_ONCE["errored"] = True
                sse(w, "error", {"error": {"message": "mock upstream timeout", "type": "server_error"}})
                return

            idx = 0
            if thinking_on or "思考" in last_user:
                think = "用户想要安排建议。先看现有计划进度：项目冲刺处于关键阶段，应优先；晨跑是习惯项，放在早上；阅读可弹性安排。"
                sse(w, "content_block_start", {"type": "content_block_start", "index": idx,
                                               "content_block": {"type": "thinking", "thinking": ""}})
                for i in range(0, len(think), 9):
                    sse(w, "content_block_delta", {"type": "content_block_delta", "index": idx,
                                                   "delta": {"type": "thinking_delta", "thinking": think[i:i + 9]}})
                    time.sleep(0.01)
                sse(w, "content_block_delta", {"type": "content_block_delta", "index": idx,
                                               "delta": {"type": "signature_delta", "signature": "mock-msg-1"}})
                sse(w, "content_block_stop", {"type": "content_block_stop", "index": idx})
                idx += 1

            if "慢速" in last_user:
                stream_text(w, "这是一段很慢的回复，用来测试停止生成。" * 8, idx=idx, chunk=4, delay=0.18)
            elif "晨跑" in last_user:
                stream_text(w, "好的，给你一份循序渐进的 30 天晨跑安排：\n\n", idx=idx)
                idx += 1
                stream_text(w, "```plan-json\n" + json.dumps(PLAN_JSON, ensure_ascii=False, indent=1) + "\n```",
                            idx=idx, chunk=24)
                idx += 1
                stream_text(w, "\n\n点下方按钮即可一键创建，之后可以随时让我调整。", idx=idx)
            else:
                stream_text(w, MD_REPLY, idx=idx)

            title = "晨跑计划安排" if "晨跑" in last_user else "今日安排建议"
            sse(w, "message_delta", {"type": "message_delta",
                                     "delta": {"stop_reason": "end_turn", "stop_sequence": None, "title": title},
                                     "usage": {"output_tokens": 200}})
            sse(w, "message_stop", {"type": "message_stop"})
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8797
    print("mock llm on %d" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
