#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 助手端到端测试：模拟 LLM 服务（OpenAI/Anthropic 双协议）+ 系统 Chrome。

覆盖：Key 设置与验证 / 流式回复与 Markdown / 计划提案一键创建 / 停止生成 /
重新生成 / 错误重试 / 深度思考 / 协议切换 / 模型列表拉取 / 带 /v1 的网关地址 /
无 CORS 网关的自动代理回退 / 多会话持久化 / 移动端。
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
APP_PORT, LLM_PORT, NC_PORT = 8798, 8797, 8792
URL = "http://127.0.0.1:%d" % APP_PORT
LLM = "http://127.0.0.1:%d" % LLM_PORT
NC_LLM = "http://127.0.0.1:%d" % NC_PORT
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


WAIT_DONE = (
    "() => { const m = document.querySelectorAll('.chat-msg.assistant');"
    " const last = m[m.length - 1];"
    " return last && (last.querySelector('.cm-actions') || last.querySelector('.cm-error')); }")


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
    nc_env = dict(env, NO_CORS="1")
    nc_llm = subprocess.Popen([sys.executable, os.path.join(BASE, "tests", "mock_llm.py"), str(NC_PORT)],
                              env=nc_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(URL + "/api/state", timeout=1)
                urllib.request.urlopen(LLM + "/models", timeout=1)
                urllib.request.urlopen(NC_LLM + "/models", timeout=1)
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

            def send(text):
                page.fill("#chatInput", text)
                page.click("#chatSendBtn")

            def wait_done():
                page.wait_for_function(WAIT_DONE, timeout=30000)

            def setup_key():
                page.click("#chatToggleBtn")
                page.wait_for_selector(".chat-panel.open")
                page.wait_for_selector("#chatSetupBtn")
                page.wait_for_timeout(750)
                page.click("#chatSetupBtn")
                page.wait_for_selector("#chatSettingsModal:not(.hidden)")
                page.fill("#csKey", "test-key-123")
                page.fill("#csOrigin", LLM)
                page.fill("#csModel", "deepseek-chat")
                page.click("#csVerify")
                page.wait_for_selector(".toast-msg:has-text('验证通过')")
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "聊天_API设置.png"))
                page.click("#csSave")
                page.wait_for_selector("#chatSettingsModal", state="hidden")
                page.wait_for_selector(".chat-welcome")
            step("打开面板 → 配置连接（OpenAI 协议）→ 验证通过", setup_key)

            def stream_md():
                send("我今天应该做什么？")
                page.wait_for_selector(".chat-msg.assistant .cm-cursor")
                wait_done()
                check(page.query_selector(".cm-bubble-md h2"), "Markdown 标题应渲染")
                check(page.query_selector(".cm-bubble-md ol li"), "有序列表应渲染")
                check(page.query_selector(".cm-code code"), "代码块应渲染")
                check(page.query_selector(".cm-bubble-md table"), "表格应渲染")
                check(page.query_selector(".cm-bubble-md blockquote"), "引用应渲染")
                check(page.inner_text("#chatTitle") != "新对话", "会话应自动获得标题")
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "聊天_流式回复.png"))
            step("OpenAI 协议流式回复 → Markdown 全要素渲染", stream_md)

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
            step("服务错误 → 友好提示 → 重试成功", error_retry)

            def thinking():
                page.click("#chatSettingsBtn")
                page.wait_for_selector("#chatSettingsModal:not(.hidden)")
                page.check("#csThinking")
                page.click("#csSave")
                page.wait_for_selector("#chatSettingsModal", state="hidden")
                send("深度思考一下今天的安排")
                page.wait_for_selector(".cm-thinking", timeout=15000)
                wait_done()
                th_txt = page.evaluate(
                    "()=>{const m=document.querySelectorAll('.chat-msg.assistant');"
                    "const l=m[m.length-1];const b=l.querySelector('.cm-thinking .th-body');"
                    "return b?b.textContent:'';}")
                check("优先" in th_txt, "思考内容应保存")
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "聊天_深度思考.png"))
            step("深度思考：reasoning 内容渲染与折叠", thinking)

            def protocols_and_models():
                # a. 拉取模型列表
                page.click("#chatSettingsBtn")
                page.wait_for_selector("#chatSettingsModal:not(.hidden)")
                page.uncheck("#csThinking")  # 关掉思考，恢复默认
                page.click("#csFetchModels")
                page.wait_for_function(
                    "()=>document.querySelectorAll('#csModelList option').length >= 4", timeout=15000)
                n = len(page.query_selector_all("#csModelList option"))
                check(n >= 4, "模型列表应返回多个模型，实际 %d" % n)
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "聊天_模型列表.png"))
                page.click("#csSave")
                page.wait_for_selector("#chatSettingsModal", state="hidden")
                # b. 切 Anthropic 协议（chat-demo 同款）
                page.click("#chatNewBtn")
                page.wait_for_selector(".chat-welcome")
                page.click("#chatSettingsBtn")
                page.wait_for_selector("#chatSettingsModal:not(.hidden)")
                page.select_option("#csProto", "anthropic")
                page.fill("#csModel", "deepseek-flash")
                page.click("#csVerify")
                page.wait_for_selector(".toast-msg:has-text('验证通过')")
                page.click("#csSave")
                page.wait_for_selector("#chatSettingsModal", state="hidden")
                send("Anthropic 协议可用性检查")
                wait_done()
                last = page.query_selector_all(".chat-msg.assistant")[-1]
                check(last.query_selector(".cm-actions"), "Anthropic 协议应正常流式返回")
                # c. 带 /v1 的网关风格地址 + OpenAI 协议
                page.click("#chatSettingsBtn")
                page.wait_for_selector("#chatSettingsModal:not(.hidden)")
                page.select_option("#csProto", "openai")
                page.fill("#csOrigin", LLM + "/v1")
                page.fill("#csModel", "deepseek-chat")
                page.click("#csVerify")
                page.wait_for_selector(".toast-msg:has-text('验证通过')")
                page.click("#csSave")
                page.wait_for_selector("#chatSettingsModal", state="hidden")
                page.click("#chatNewBtn")
                page.wait_for_selector(".chat-welcome")
                send("带 /v1 后缀的地址应自动识别")
                wait_done()
            step("模型列表拉取 / Anthropic 协议 / 带 /v1 网关地址", protocols_and_models)

            def proxy_fallback():
                page.click("#chatSettingsBtn")
                page.wait_for_selector("#chatSettingsModal:not(.hidden)")
                page.fill("#csOrigin", NC_LLM + "/v1")
                page.fill("#csModel", "deepseek-chat")
                page.select_option("#csTransport", "auto")
                page.click("#csSave")
                page.wait_for_selector("#chatSettingsModal", state="hidden")
                page.click("#chatNewBtn")
                page.wait_for_selector(".chat-welcome")
                send("不支持跨域的网关应自动走本机代理")
                page.wait_for_selector(".toast-msg:has-text('本机代理')", timeout=15000)
                wait_done()
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "聊天_代理回退.png"))
            step("无 CORS 网关 → 自动降级为经本机服务代理", proxy_fallback)

            def sessions():
                page.click("#chatSessionsBtn")
                page.wait_for_selector(".chat-session-list:not(.hidden)")
                items = page.query_selector_all(".cs-item")
                check(len(items) >= 3, "会话列表应至少有 3 个会话，实际 %d" % len(items))
                target = None
                for it in items:
                    if "我今天应该做什么" in it.inner_text():
                        target = it
                        break
                check(target, "应能找到含提案的原始会话")
                target.click()
                page.wait_for_timeout(400)
                check(page.query_selector(".plan-proposal"), "切回原会话应恢复提案卡片")
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "聊天_会话列表.png"))
                page.click("#chatNewBtn")
                page.wait_for_selector(".chat-welcome")
                send("新会话的消息")
                wait_done()
                page.reload(wait_until="networkidle")
                page.click("#chatToggleBtn")
                page.wait_for_selector(".chat-panel.open")
                page.wait_for_timeout(600)
                check("新会话的消息" in page.inner_text("#chatTitle"), "刷新后应恢复最近会话")
            step("多会话：新建 / 切换 / 刷新持久化", sessions)

            def rename_delete():
                page.click("#chatSessionsBtn")
                page.wait_for_selector(".chat-session-list:not(.hidden)")
                item = page.query_selector_all(".cs-item")[0]
                item.hover()
                item.query_selector("[data-rename]").click()
                inp = page.wait_for_selector(".cs-item-renaming input")
                inp.fill("renamed 会话")
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
                    "{key:'test-key-123', origin:'%s', model:'deepseek-chat', "
                    "thinking:false, protocol:'openai', transport:'auto'}))" % LLM)
                mp.goto(URL, wait_until="networkidle")
                mp.click("#chatToggleBtn")
                mp.wait_for_selector(".chat-panel.open")
                mp.wait_for_selector(".chat-msg, .chat-welcome")
                mp.fill("#chatInput", "我今天应该做什么？")
                mp.click("#chatSendBtn")
                mp.wait_for_function(WAIT_DONE, timeout=30000)
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
        # 预期内的控制台噪音：favicon、故意触发的 400（错误重试环节）、故意触发的 CORS 拦截（代理回退环节）
        expect_noise = ("favicon", "400 (bad request)", "access to fetch", "err_failed")
        real_errors = [e for e in console_errors
                       if not any(n in e.lower() for n in expect_noise)]
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
        nc_llm.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
