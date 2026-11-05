# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件、无控制台窗口，内置图标与前端资源。

用法（在仓库根目录）：
    pyinstaller build/PlanCheckBox.spec --noconfirm
产物：dist/PlanCheckBox.exe（再复制到仓库根目录，build.ps1 会自动做）。
"""
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
VERSION_FILE = ROOT / "app" / "version_info.txt"


def bundle(folder: str):
    base = ROOT / folder
    items = [(str(p), folder) for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    return items


a = Analysis(
    [str(ROOT / "launch.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=bundle("ui") + bundle("assets") + bundle("sample_data"),
    hiddenimports=[
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
        "clr_loader",
        "pythonnet",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "matplotlib", "numpy", "pandas"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PlanCheckBox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "icon.ico"),
    version=str(VERSION_FILE) if VERSION_FILE.exists() else None,
)
