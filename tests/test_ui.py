#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PlanCheckBox 端到端界面测试。

使用系统 Chrome + Playwright，在隔离的临时目录里启动服务并验证：
创建计划（三种录入方式）/ 勾选持久化 / 三视图 / 快速添加 / 编辑 /
删除撤销 / 搜索 / 导入 / 移动端布局。

运行：python3 tests/test_ui.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, timedelta

from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8799
URL = "http://127.0.0.1:%d" % PORT
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
        print("FAIL  %s  ->  %s" % (name, e))


def main():
    os.makedirs(SHOTS, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="pcb-test-")
    shutil.copy(os.path.join(BASE, "app.py"), tmp)
    shutil.copytree(os.path.join(BASE, "static"), os.path.join(tmp, "static"))
    env = dict(os.environ, TZ="Asia/Shanghai")
    server = subprocess.Popen(
        [sys.executable, "app.py", "--port", str(PORT), "--no-browser"],
        cwd=tmp, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(URL + "/api/state", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("服务启动失败")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=CHROME, headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: console_errors.append(str(e)))

            today = date.today()
            today_s = today.isoformat()
            tomorrow_s = (today + timedelta(days=1)).isoformat()

            def load():
                page.goto(URL, wait_until="networkidle")
                page.wait_for_selector(".plan-card")

            def state():
                with urllib.request.urlopen(URL + "/api/state") as r:
                    return json.load(r)

            load()
            step("首屏：3 个示例计划 + 日视图渲染", lambda: (
                page.wait_for_selector(".day-big"),
                assert_eq(len(page.query_selector_all(".plan-card")), 3)))

            def toggle_persist():
                row = page.query_selector(".task-row:not(.done)")
                assert row, "今天应有未完成任务"
                row.query_selector(".t-check").click()
                page.wait_for_timeout(400)
                load()
                assert page.query_selector(".task-row.done"), "勾选状态应在刷新后保留"
            step("勾选完成 → 刷新后持久化", toggle_persist)

            step("周视图：7 列渲染", lambda: (
                page.click('[data-view="week"]'),
                page.wait_for_selector(".week-col"),
                assert_eq(len(page.query_selector_all(".week-col")), 7)))
            page.wait_for_timeout(750)
            page.screenshot(path=os.path.join(SHOTS, "桌面_周视图.png"), full_page=True)

            step("月视图：日历格子渲染", lambda: (
                page.click('[data-view="month"]'),
                page.wait_for_selector(".m-cell"),
                check(len(page.query_selector_all(".m-cell")) >= 28, "日历格子数不足")))
            page.wait_for_timeout(750)
            page.screenshot(path=os.path.join(SHOTS, "桌面_月视图.png"), full_page=True)

            step("视图偏好持久化（刷新后仍是月视图）", lambda: (
                load(),
                page.wait_for_selector(".month-grid")))

            page.click('[data-view="day"]')
            page.wait_for_selector(".day-big")
            page.wait_for_timeout(750)
            page.screenshot(path=os.path.join(SHOTS, "桌面_日视图.png"), full_page=True)

            def create_plan():
                page.click("#newPlanBtn")
                page.wait_for_selector("#planModal:not(.hidden)")
                page.fill("#pmName", "界面创建测试计划")
                page.click('.color-dot[data-color="coral"]')
                page.click('.emoji-btn[data-emoji="🎨"]')
                # 逐条添加
                page.fill(".pm-row .row-title", "任务A")
                page.click("#pmAddRow")
                rows = page.query_selector_all(".pm-row .row-title")
                rows[-1].fill("任务B")
                # 批量粘贴
                page.click('.pm-tabs button[data-tab="paste"]')
                page.fill("#pmPaste", "%s 任务C\n任务D" % tomorrow_s)
                page.click("#pmPasteAdd")
                page.wait_for_timeout(200)
                # 每周重复
                page.click('.pm-tabs button[data-tab="repeat"]')
                page.fill("#pmRepeatTitle", "每日站会")
                page.click("#pmRepeatAdd")
                page.wait_for_timeout(200)
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "桌面_新建计划弹窗.png"))
                page.click("#pmSubmit")
                page.wait_for_selector("#planModal", state="hidden")
                page.wait_for_timeout(400)
                names = [c.inner_text() for c in page.query_selector_all(".pc-name")]
                assert any("界面创建测试计划" in n for n in names), "新计划应出现在侧栏"
                p = next(x for x in state()["plans"] if x["name"] == "界面创建测试计划")
                assert len(p["tasks"]) >= 6, "三种方式的任务都应入库，实际 %d" % len(p["tasks"])
                assert p["color"] == "coral" and p["emoji"] == "🎨"
            step("界面创建计划：逐条 + 批量粘贴 + 每周重复", create_plan)

            def quick_add():
                page.fill("#dayQuickInput", "快速任务")
                p = next(x for x in state()["plans"] if x["name"] == "界面创建测试计划")
                page.select_option("#dayQuickPlan", p["id"])
                page.click("#dayQuickAdd")
                page.wait_for_timeout(400)
                assert page.query_selector(".task-row .t-title:has-text('快速任务')"), "快速任务应出现在日视图"
            step("日视图快速添加任务", quick_add)

            def edit_task():
                row = page.locator(".task-row", has_text="快速任务").first
                row.hover()
                row.locator("[data-edit]").click()
                page.wait_for_selector("#taskModal:not(.hidden)")
                page.fill("#tmTitle", "快速任务·已编辑")
                page.click("#tmSave")
                page.wait_for_selector("#taskModal", state="hidden")
                page.wait_for_timeout(300)
                assert page.query_selector(".task-row .t-title:has-text('快速任务·已编辑')")
            step("编辑任务标题", edit_task)

            def delete_undo():
                row = page.locator(".task-row", has_text="快速任务·已编辑").first
                row.hover()
                row.locator("[data-del]").click()
                page.wait_for_selector(".toast-undo")
                assert not page.query_selector(".task-row .t-title:has-text('快速任务·已编辑')")
                page.click(".toast-undo")
                page.wait_for_timeout(400)
                assert page.query_selector(".task-row .t-title:has-text('快速任务·已编辑')"), "撤销后任务应恢复"
            step("删除任务 → 撤销恢复", delete_undo)

            def search():
                page.fill("#searchInput", "站会")
                page.wait_for_timeout(300)
                marks = page.query_selector_all(".task-row mark")
                assert marks, "搜索结果应高亮"
                page.click("#searchClear")
                page.wait_for_timeout(200)
            step("搜索任务并高亮", search)

            def drawer_delete_undo():
                card = page.locator(".plan-card", has_text="界面创建测试计划").first
                card.click()
                page.wait_for_selector(".drawer.open")
                page.wait_for_timeout(350)
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "桌面_计划详情抽屉.png"))
                assert page.query_selector(".drawer-stats"), "抽屉应显示统计"
                page.click("#drawerDelete")
                page.click("#drawerDelete")
                page.wait_for_selector(".toast-undo")
                page.wait_for_timeout(300)
                names = [c.inner_text() for c in page.query_selector_all(".pc-name")]
                assert not any("界面创建测试计划" in n for n in names)
                page.click(".toast-undo")
                page.wait_for_timeout(400)
                names = [c.inner_text() for c in page.query_selector_all(".pc-name")]
                assert any("界面创建测试计划" in n for n in names), "撤销后计划应恢复"
            step("计划抽屉 → 删除计划 → 撤销恢复", drawer_delete_undo)

            def import_file():
                sample = os.path.join(BASE, "samples", "原版格式示例_健身.json")
                page.set_input_files("#fileInput", sample)
                page.wait_for_selector("#importModal:not(.hidden)")
                assert page.query_selector(".ii-badge:has-text('原版 PlanCheckBox')"), "应识别为原版格式"
                page.wait_for_timeout(750)
                page.screenshot(path=os.path.join(SHOTS, "桌面_导入预览.png"))
                page.click("#importConfirm")
                page.wait_for_selector("#importModal", state="hidden")
                page.wait_for_timeout(500)
                names = [c.inner_text() for c in page.query_selector_all(".pc-name")]
                assert any("健身" in n for n in names), "导入的计划应出现在侧栏"
            step("导入原版 checkbox_use.json（预览 → 确认）", import_file)

            def mobile():
                mctx = browser.new_context(viewport={"width": 390, "height": 844})
                mp = mctx.new_page()
                mp.goto(URL, wait_until="networkidle")
                mp.wait_for_selector(".plan-card, .day-big")
                overflow = mp.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                assert overflow <= 1, "移动端不应横向溢出，实际 %dpx" % overflow
                mp.click("#sidebarToggle")
                mp.wait_for_timeout(400)
                assert mp.evaluate("document.body.classList.contains('sidebar-open')")
                mp.wait_for_timeout(750)
                mp.screenshot(path=os.path.join(SHOTS, "移动端_侧栏.png"))
                mp.click("#sidebarScrim", position={"x": 350, "y": 400})
                mp.wait_for_timeout(450)
                mp.click('[data-view="week"]')
                mp.wait_for_selector(".week-col")
                mp.wait_for_timeout(750)
                mp.screenshot(path=os.path.join(SHOTS, "移动端_周视图.png"))
                mp.click("#newPlanBtn")
                mp.wait_for_selector("#planModal:not(.hidden)")
                mp.wait_for_timeout(750)
                mp.screenshot(path=os.path.join(SHOTS, "移动端_新建计划.png"))
                mctx.close()
            step("移动端：无横向溢出 + 侧栏抽屉 + 弹窗", mobile)

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
        server.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


def assert_eq(a, b):
    assert a == b, "期望 %r，实际 %r" % (b, a)


def check(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "条件不成立")


if __name__ == "__main__":
    main()
