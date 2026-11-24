#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模拟 LLM 网关（OpenAI Chat Completions + Anthropic Messages 双协议），供端到端测试。

- GET  <base>/models                校验 Key（Authorization 含 bad-key 时 401）
- POST <base>/chat/completions      OpenAI 兼容 SSE（data-only 帧 + [DONE]）
- POST <base>/anthropic/v1/messages Anthropic 兼容 SSE（event+data 帧）
按最后一条用户消息内容选择脚本：
    含「晨跑」→ 文本 + plan-json 提案；含「慢速」→ 慢流（测停止）；
    含「错误」→ 首次失败、重试成功；含「思考」→ 输出思考内容；其他 → Markdown 富文本。
环境变量 NO_CORS=1 时不下发 CORS 头（用于验证浏览器直连失败后的本机代理回退）。
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ERROR_ONCE = {"errored": False}
NO_CORS = os.environ.get("NO_CORS") == "1"

MODELS = ["deepseek-chat", "deepseek-reasoner", "deepseek-flash", "deepseek-v4-pro"]

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

THINK_TEXT = "用户想要安排建议。先看现有计划进度：项目冲刺处于关键阶段，应优先；晨跑是习惯项，放在早上；阅读可弹性安排。"


def script_reply(last_user):
    """返回 (thinking_text 或 None, reply_text, title)"""
    thinking = THINK_TEXT if ("思考" in last_user) else None
    if "晨跑" in last_user:
        text = ("好的，给你一份循序渐进的 30 天晨跑安排：\n\n"
                "```plan-json\n" + json.dumps(PLAN_JSON, ensure_ascii=False, indent=1) + "\n```"
                "\n\n点下方按钮即可一键创建，之后可以随时让我调整。")
        return thinking, text, "晨跑计划安排"
    if "慢速" in last_user:
        return thinking, "这是一段很慢的回复，用来测试停止生成。" * 8, "慢速回复"
    return thinking, MD_REPLY, "今日安排建议"


def chunk_text(text, chunk=7):
    return [text[i:i + chunk] for i in range(0, len(text), chunk)]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _cors(self):
        if NO_CORS:
            return
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers",
                         "x-api-key, content-type, accept, authorization, anthropic-beta")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/models"):
            auth = self.headers.get("Authorization", "")
            if "bad-key" in auth:
                return self._send_json({"error": {"message": "Authentication Fails, Your api key is invalid"}}, 401)
            return self._send_json({"object": "list",
                                    "data": [{"id": m, "object": "model", "owned_by": "mock"} for m in MODELS]})
        self.send_response(404)
        self._cors()
        self.end_headers()

    def _auth_fail(self):
        key = self.headers.get("x-api-key", "") or self.headers.get("Authorization", "")
        return "bad-key" in key

    def _read_last_user(self, req):
        for m in reversed(req.get("messages", [])):
            role = m.get("role")
            if role == "user":
                c = m.get("content")
                if isinstance(c, str):
                    return c
                if isinstance(c, list):
                    return " ".join(x.get("text", "") for x in c if isinstance(x, dict))
        return ""

    def do_POST(self):
        p = self.path
        is_anthropic = "anthropic" in p and p.endswith("/messages")
        is_openai = p.endswith("/chat/completions")
        if not (is_anthropic or is_openai):
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length).decode("utf-8"))
        if self._auth_fail():
            return self._send_json({"error": {"message": "Authentication Fails"}}, 401)
        last_user = self._read_last_user(req)
        thinking, reply, title = script_reply(last_user)
        if "错误" in last_user and not ERROR_ONCE["errored"]:
            ERROR_ONCE["errored"] = True
            return self._send_json({"error": {"message": "mock upstream timeout", "type": "server_error"}}, 400)

        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        w = self.wfile
        try:
            w.write(b": keep-alive\n\n")
            w.flush()
            if is_openai:
                self._stream_openai(w, req, thinking, reply, title)
            else:
                self._stream_anthropic(w, req, thinking, reply, title)
        except (BrokenPipeError, ConnectionResetError):
            pass

    @staticmethod
    def _w(wfile, text):
        wfile.write(text.encode("utf-8"))
        wfile.flush()

    def _stream_openai(self, w, req, thinking, reply, title):
        base = {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "model": req.get("model", "mock")}

        def emit(delta, finish=None):
            body = dict(base)
            body["choices"] = [{"index": 0, "delta": delta, "finish_reason": finish}]
            self._w(w, "data: %s\n\n" % json.dumps(body, ensure_ascii=False))

        emit({"role": "assistant"})
        for piece in chunk_text(thinking or "", 9):
            emit({"reasoning_content": piece})
            time.sleep(0.01)
        if reply.startswith("好的，") and "plan-json" in reply:
            head = "好的，给你一份循序渐进的 30 天晨跑安排：\n\n"
            for piece in chunk_text(head):
                emit({"content": piece})
                time.sleep(0.012)
            fence = "```plan-json\n" + json.dumps(PLAN_JSON, ensure_ascii=False, indent=1) + "\n```"
            for piece in chunk_text(fence, 24):
                emit({"content": piece})
                time.sleep(0.012)
            tail = "\n\n点下方按钮即可一键创建，之后可以随时让我调整。"
            slow = "慢速" in title
            for piece in chunk_text(tail, 18 if not slow else 4):
                emit({"content": piece})
                time.sleep(0.18 if slow else 0.012)
        else:
            step = 4 if "慢速" in title else 7
            for piece in chunk_text(reply, step):
                emit({"content": piece})
                time.sleep(0.18 if step == 4 else 0.012)
        emit({}, finish="stop")
        self._w(w, "data: [DONE]\n\n")

    def _stream_anthropic(self, w, req, thinking, reply, title):
        def sse(event, data):
            self._w(w, "event: %s\ndata: %s\n\n" % (event, json.dumps(data, ensure_ascii=False)))

        sse("message_start", {"type": "message_start",
                              "message": {"id": "mock-msg-1", "model": req.get("model", "mock"),
                                          "usage": {"input_tokens": 100, "output_tokens": 0}}})
        sse("ping", {"type": "ping"})
        idx = 0
        if thinking:
            sse("content_block_start", {"type": "content_block_start", "index": idx,
                                        "content_block": {"type": "thinking", "thinking": ""}})
            for piece in chunk_text(thinking, 9):
                sse("content_block_delta", {"type": "content_block_delta", "index": idx,
                                            "delta": {"type": "thinking_delta", "thinking": piece}})
                time.sleep(0.01)
            sse("content_block_stop", {"type": "content_block_stop", "index": idx})
            idx += 1

        def text_block(text, chunk, delay):
            nonlocal idx
            sse("content_block_start", {"type": "content_block_start", "index": idx,
                                        "content_block": {"type": "text", "text": ""}})
            for piece in chunk_text(text, chunk):
                sse("content_block_delta", {"type": "content_block_delta", "index": idx,
                                            "delta": {"type": "text_delta", "text": piece}})
                time.sleep(delay)
            sse("content_block_stop", {"type": "content_block_stop", "index": idx})
            idx += 1

        if "plan-json" in reply:
            head = "好的，给你一份循序渐进的 30 天晨跑安排：\n\n"
            text_block(head, 7, 0.012)
            fence = "```plan-json\n" + json.dumps(PLAN_JSON, ensure_ascii=False, indent=1) + "\n```"
            text_block(fence, 24, 0.012)
            text_block("\n\n点下方按钮即可一键创建，之后可以随时让我调整。", 18, 0.012)
        elif "慢速" in title:
            text_block(reply, 4, 0.18)
        else:
            text_block(reply, 7, 0.012)

        sse("message_delta", {"type": "message_delta",
                              "delta": {"stop_reason": "end_turn", "stop_sequence": None, "title": title},
                              "usage": {"output_tokens": 200}})
        sse("message_stop", {"type": "message_stop"})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8797
    print("mock llm on %d (NO_CORS=%s)" % (port, NO_CORS))
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
