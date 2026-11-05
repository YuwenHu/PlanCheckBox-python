"""PlanCheckBox · Python 桌面版入口。

- 有界面时：pywebview 承载 ui/index.html，键盘/勾选通过 JS-Python 桥接直接读写本地 JSON。
- 无 pywebview 或缺少 WebView2 时：打印可读的原因，不弹崩溃窗口。
- `--version` / `--help` / `--selftest` 可在无显示环境下验证程序完整性。
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

APP_NAME = "PlanCheckBox"
VERSION = "1.0.0"


def resource_dir() -> Path:
    """PyInstaller onefile 会把资源解压到 sys._MEIPASS；源码态用仓库根目录。"""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent.parent
    return root


def asset_path(name: str) -> Path:
    return resource_dir() / "assets" / name


def ui_path() -> Path:
    return resource_dir() / "ui" / "index.html"


def webview2_available() -> bool:
    """Win10/11 通常自带 WebView2 Runtime；这里只做只读检测，不安装任何东西。"""
    if os.name != "nt":
        return True
    try:
        import winreg
    except ImportError:
        return True
    keys = (
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    )
    for root, path in keys:
        try:
            with winreg.OpenKey(root, path) as key:
                version, _ = winreg.QueryValueEx(key, "pv")
                if str(version).strip() and str(version) != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def show_message(text: str, title: str = APP_NAME) -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
            return
        except Exception:
            pass
    print(text, file=sys.stderr)


def selftest() -> int:
    """非交互自检：导入全部模块、解析内置示例、构建四页视图（用临时目录，不碰用户数据）。"""
    import tempfile

    from app.core import store

    resolved = store.data_dir()
    os.environ["PLANCHECKBOX_DATA_DIR"] = tempfile.mkdtemp(prefix="pcb-selftest-")
    from app.core.service import AppService

    sample = resource_dir() / "sample_data" / "math2_checkbox_use.json"
    service = AppService()
    if sample.exists():
        service.add_paths([str(sample)])
    view = service.build_view()
    print(f"{APP_NAME} {VERSION} selftest ok · page={view['page']} · groups={len(service.groups)}"
          f" · data_dir={resolved}")
    return 0


def diag_probe(window) -> None:
    """打包后自检：等前端渲染完，读回 DOM 关键指标再关窗（供 --diag 使用）。"""
    import time

    from app.core import store

    print(f"data_dir = {store.data_dir()!s}", flush=True)
    time.sleep(6)
    checks = {
        "api": "String(!!(window.pywebview && window.pywebview.api))",
        "rows": "document.querySelectorAll('.file-row').length",
        "app_len": "(document.getElementById('app')||{innerHTML:''}).innerHTML.length",
        "title": "document.title",
        "toast": "(document.getElementById('toast')||{textContent:''}).textContent",
    }
    for name, expr in checks.items():
        try:
            print(f"{name} = {window.evaluate_js(expr)!r}", flush=True)
        except Exception as exc:
            print(f"{name} ERROR {exc}", flush=True)
    window.destroy()


def run_gui(diag: bool = False) -> int:
    try:
        import webview
    except ImportError:
        show_message("缺少 pywebview，无法启动界面。\n\n请在项目目录执行：\n"
                     "python -m pip install -r requirements.txt")
        return 2

    if not ui_path().exists():
        show_message(f"找不到界面文件：\n{ui_path()}")
        return 3

    if not webview2_available():
        show_message("未检测到 Microsoft Edge WebView2 Runtime。\n\n"
                     "Windows 10/11 通常已自带；若缺失，请到 Microsoft 官网安装 "
                     "「WebView2 Runtime」（Evergreen Bootstrapper），安装后重新打开本程序。\n\n"
                     "本程序不会自动联网下载或安装任何组件。")
        return 4

    from app.bridge import Api
    from app.core import store
    from app.core.service import AppService

    service = AppService()
    api = Api(service)
    window = webview.create_window(
        "任务进度追踪",
        ui_path().as_uri(),
        js_api=api,
        width=1240,
        height=880,
        min_size=(1000, 680),
        text_select=True,
    )
    api.window = window
    icon = asset_path("icon.ico")
    kwargs = {"private_mode": False, "storage_path": str(store.standard_dir() / "webview")}
    if icon.exists():
        kwargs["icon"] = str(icon)
    try:
        if diag:
            webview.start(diag_probe, (window,), **kwargs)
        else:
            webview.start(**kwargs)
    except TypeError:
        kwargs.pop("icon", None)
        if diag:
            webview.start(diag_probe, (window,), **kwargs)
        else:
            webview.start(**kwargs)
    except Exception as exc:  # WebView2 初始化失败等
        show_message(f"界面启动失败：{exc}\n\n若系统缺少 WebView2 Runtime，请先安装后重试。")
        return 5
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="任务进度追踪 · Python 桌面版")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    parser.add_argument("--selftest", action="store_true", help="无界面自检（导入 + 解析示例 + 构建视图）")
    parser.add_argument("--diag", action="store_true", help="启动界面并读回 DOM 指标后自动退出（打包后自检）")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    try:
        return run_gui(diag=args.diag)
    except Exception:
        show_message("程序异常：\n" + traceback.format_exc(limit=4))
        return 6


if __name__ == "__main__":
    sys.exit(main())
