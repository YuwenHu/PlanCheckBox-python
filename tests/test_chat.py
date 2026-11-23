#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 助手端到端测试：模拟 DeepSeek 兼容 API + 系统 Chrome。

覆盖：Key 设置与验证 / 流式回复与 Markdown / 计划提案一键创建 /
停止生成 / 重新生成 / 错误重试 / 深度思考 / 多会话持久化 / 移动端。
运行：python3 tests/test_chat.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_PORT, LLM_PORT = 8798, 8797
URL = "http://127.0.0.1:%d" % APP_PORT
LLM = "http://127.0.0.1:%d" % LLM_PORT
CHROME = "/usr/bin/google-chrome"
SHOTS = os.path.join(BASE, "tests", "screenshots")

results = []
console_errors = []


def step(name, fn):
    try:
        fn()
        results.append((name, True, ""))
        print("PASS  %s" % name)
    except Exception as e:
        results.append((name, False, str(e)))
        print("FAIL  %s  ->  %s" % (name, str(e)[:300]))


def check(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "条件不成立")


def main():
    os.makedirs(SHOTS, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="pcb-chat-test-")
    shutil.copy(os.path.join(BASE, "app.py"), tmp)
    shutil.copytree(os.path.join(BASE, "static"), os.path.join(tmp, "static"))
    env = dict(os.environ, TZ="Asia/Shanghai")
    app = subprocess.Popen([sys.executable, "app.py", "--port", str(APP_PORT), "--no-browser"],
                           cwd=tmp, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    llm = subprocess.Popen([sys.executable, os.path.join(BASE, "tests", "mock_llm.py"), str(LLM_PORT)],
                           env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(URL + "/api/state", timeout=1)
                urllib.request.urlopen(LLM + "/models", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("服务启动失败")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME, headless=True,
                                         args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: console_errors.append(str(e)))
            page.goto(URL, wait_until="networkidle")
            page.wait_for_selector(".plan-card")

            def setup_key():
                page.click("#chatToggleBtn")
                page.wait_for_selector(".chat-panel.open")
                page.wait_for_selector("#chatSetupBtn")
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "聊天_未配置Key.png"))
                page.click("#chatSetupBtn")
                page.wait_for_selector("#chatSettingsModal:not(.hidden)")
                page.fill("#csKey", "test-key-123")
                page.fill("#csOrigin", LLM)
                page.click("#csVerify")
                page.wait_for_selector(".toast-msg:has-text('验证通过')")
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "聊天_API设置.png"))
                page.click("#csSave")
                page.wait_for_selector("#chatSettingsModal", state="hidden")
                page.wait_for_selector(".chat-welcome")
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "聊天_欢迎页.png"))
            step("打开面板 → 配置 Key → 验证通过 → 欢迎页", setup_key)

            def send(text):
                page.fill("#chatInput", text)
                page.click("#chatSendBtn")

            def wait_done():
                page.wait_for_selector(".chat-msg.assistant .cm-actions", timeout=30000)

            def stream_md():
                send("我今天应该做什么？")
                page.wait_for_selector(".chat-msg.assistant .cm-cursor")  # 流式光标出现
                wait_done()
                check(page.query_selector(".cm-bubble-md h2"), "Markdown 标题应渲染")
                check(page.query_selector(".cm-bubble-md ol li"), "有序列表应渲染")
                check(page.query_selector(".cm-code code"), "代码块应渲染")
                check(page.query_selector(".cm-bubble-md table"), "表格应渲染")
                check(page.query_selector(".cm-bubble-md blockquote"), "引用应渲染")
                title = page.inner_text("#chatTitle")
                check(title != "新对话", "会话应自动获得标题，实际：%s" % title)
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "聊天_流式回复.png"))
            step("发送消息 → 流式回复 → Markdown 全要素渲染", stream_md)

            def proposal():
                send("帮我制定一个 30 天晨跑计划")
                page.wait_for_selector(".plan-proposal .pp-create", timeout=30000)
                wait_done()
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "聊天_计划提案.png"))
                check("30 天晨跑计划" in page.inner_text(".plan-proposal"), "提案卡片应显示计划名")
                page.click(".pp-create")
                page.wait_for_selector(".pp-created", timeout=10000)
                page.wait_for_timeout(500)
                names = [c.inner_text() for c in page.query_selector_all(".pc-name")]
                check(any("30 天晨跑计划" in n for n in names), "提案计划应出现在侧栏")
                with urllib.request.urlopen(URL + "/api/state") as r:
                    plans = json.load(r)["plans"]
                p = next(x for x in plans if x["name"] == "30 天晨跑计划")
                check(len(p["tasks"]) == 15, "提案任务应全部入库，实际 %d" % len(p["tasks"]))
            step("AI 计划提案 → 一键创建 → 入库", proposal)

            def stop_gen():
                send("慢速回复测试")
                page.wait_for_selector(".chat-msg.assistant .cm-cursor")
                page.wait_for_timeout(900)
                page.click("#chatStopBtn")
                page.wait_for_selector(".cm-note:has-text('已停止生成')", timeout=10000)
                check(page.query_selector("#chatSendBtn:not(.hidden)"), "停止后应恢复发送按钮")
            step("慢速流 → 停止生成 → 保留部分回复", stop_gen)

            def regen():
                msg = page.query_selector_all(".chat-msg.assistant")[-1]
                msg.hover()
                msg.query_selector("[data-regen]").click()
                wait_done()
            step("重新生成最后一条回复", regen)

            def error_retry():
                send("触发错误测试")
                page.wait_for_selector(".cm-error", timeout=15000)
                check("mock upstream timeout" in page.inner_text(".cm-error"), "应展示服务端错误信息")
                page.click(".cm-error [data-retry]")
                wait_done()
            step("流中错误帧 → 错误提示 → 重试成功", error_retry)

            def thinking():
                page.click("#chatSettingsBtn")
                page.wait_for_selector("#chatSettingsModal:not(.hidden)")
                page.check("#csThinking")
                page.click("#csSave")
                page.wait_for_selector("#chatSettingsModal", state="hidden")
                send("深度思考一下今天的安排")
                page.wait_for_selector(".cm-thinking", timeout=15000)
                wait_done()
                check("优先" in page.inner_text(".cm-thinking .th-body"), "思考内容应保存")
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "聊天_深度思考.png"))
            step("深度思考：thinking 块渲染与折叠", thinking)

            def sessions():
                first_title = page.inner_text("#chatTitle")
                page.click("#chatNewBtn")
                page.wait_for_selector(".chat-welcome")
                send("新会话的消息")
                wait_done()
                page.click("#chatSessionsBtn")
                page.wait_for_selector(".chat-session-list:not(.hidden)")
                items = page.query_selector_all(".cs-item")
                check(len(items) >= 2, "会话列表应至少有 2 个会话")
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "聊天_会话列表.png"))
                # 切回第一个会话
                target = None
                for it in items:
                    if first_title in it.inner_text():
                        target = it
                        break
                check(target, "应能找到之前的会话")
                target.click()
                page.wait_for_timeout(400)
                check(page.inner_text("#chatTitle") == first_title, "应切回原会话")
                check(page.query_selector(".plan-proposal"), "原会话的提案卡片应恢复")
                # 刷新后恢复最近更新的会话（服务端持久化）
                page.reload(wait_until="networkidle")
                page.click("#chatToggleBtn")
                page.wait_for_selector(".chat-panel.open")
                page.wait_for_timeout(600)
                check("新会话的消息" in page.inner_text("#chatTitle"), "刷新后应恢复最近会话")
                # 从列表切回第一个会话，历史应完整
                page.click("#chatSessionsBtn")
                page.wait_for_selector(".chat-session-list:not(.hidden)")
                target = None
                for it in page.query_selector_all(".cs-item"):
                    if first_title in it.inner_text():
                        target = it
                        break
                check(target, "刷新后应仍能找到之前的会话")
                target.click()
                page.wait_for_timeout(400)
                check(page.query_selector(".plan-proposal"), "刷新后历史提案卡片应完整")
            step("多会话：新建 / 切换 / 刷新持久化", sessions)

            def rename_delete():
                page.click("#chatSessionsBtn")
                page.wait_for_selector(".chat-session-list:not(.hidden)")
                item = page.query_selector_all(".cs-item")[0]
                item.hover()
                item.query_selector("[data-rename]").click()
                inp = page.wait_for_selector(".cs-item-renaming input")
                inp.fill(" renamed 会话")
                inp.press("Enter")
                page.wait_for_timeout(400)
                check(page.query_selector(".cs-item-title:has-text('renamed 会话')"), "重命名应生效")
                item = page.query_selector_all(".cs-item")[-1]
                item.hover()
                item.query_selector("[data-delsid]").click()
                page.wait_for_selector(".toast-undo")
                page.click(".toast-undo")
                page.wait_for_timeout(500)
            step("会话重命名 / 删除撤销", rename_delete)

            def mobile():
                mctx = browser.new_context(viewport={"width": 390, "height": 844})
                mp = mctx.new_page()
                mp.add_init_script(
                    "localStorage.setItem('plancheckbox-chat-settings', JSON.stringify("
                    "{key:'test-key-123', origin:'%s', model:'deepseek-flash', thinking:false}))" % LLM)
                mp.goto(URL, wait_until="networkidle")
                mp.click("#chatToggleBtn")
                mp.wait_for_selector(".chat-panel.open")
                mp.wait_for_selector(".chat-msg, .chat-welcome")
                mp.fill("#chatInput", "我今天应该做什么？")
                mp.click("#chatSendBtn")
                mp.wait_for_function(
                    "() => { const m = document.querySelectorAll('.chat-msg.assistant');"
                    " const last = m[m.length - 1];"
                    " return last && last.querySelector('.cm-actions'); }", timeout=30000)
                mp.wait_for_timeout(750)
                overflow = mp.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                check(overflow <= 1, "移动端不应横向溢出")
                mp.screenshot(path=os.path.join(SHOTS, "聊天_移动端.png"))
                mp.click("#chatCloseBtn")
                mp.wait_for_timeout(400)
                check(not mp.evaluate("document.getElementById('chatPanel').classList.contains('open')"))
                mctx.close()
            step("移动端：全屏面板 / 无溢出 / 关闭", mobile)

            browser.close()

        failed = [r for r in results if not r[1]]
        real_errors = [e for e in console_errors if "favicon" not in e.lower()]
        print("\n========== 结果 ==========")
        print("通过 %d / %d" % (len(results) - len(failed), len(results)))
        if real_errors:
            print("控制台错误：")
            for e in real_errors[:10]:
                print("  -", e[:200])
        print("截图目录：%s" % SHOTS)
        sys.exit(1 if failed or real_errors else 0)
    finally:
        app.terminate()
        llm.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
