"""应用自身的本地状态：数据目录解析、配置文件、会话记录。

数据目录优先级（不写死任何盘符）：
1. 环境变量 ``PLANCHECKBOX_DATA_DIR``
2. 配置文件里的 ``dataDir``（界面「数据目录」按钮选择后写入）
3. exe 同级 ``data\\``（便携优先：整包拷走即可带走数据）
4. exe 同级 ``docs\\``（兼容既有结构）
5. ``%LOCALAPPDATA%\\PlanCheckBox``

配置文件 ``config.json`` 优先放 exe 同级（目录可写时，随包携带）；否则放
``%LOCALAPPDATA%\\PlanCheckBox``。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

APP_DIR_NAME = "PlanCheckBox"
CONFIG_NAME = "config.json"

# 最近一次解析出的问题（给界面提示用；读取后清空，避免反复弹）
_issue: str | None = None


class DataDirUnavailable(RuntimeError):
    """所有候选目录都不可写时抛出，调用方需给出可读提示。"""


def pop_issue() -> str | None:
    """取出并清空「数据目录降级」提示。"""
    global _issue
    value, _issue = _issue, None
    return value


def _note(text: str) -> None:
    global _issue
    _issue = text


def app_root() -> Path:
    """exe 所在目录（打包态）或仓库根目录（源码态）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def standard_dir() -> Path:
    """平台标准目录：Windows 用 LOCALAPPDATA，其他平台退回用户主目录。"""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home()
    return root / APP_DIR_NAME


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=str(path), prefix=".probe-", delete=True):
            return True
    except OSError:
        return False


def _usable(path: Path) -> bool:
    """目录能否用来存数据（建得出来、写得进去）。"""
    probe = path / f".write-probe-{os.getpid()}"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
        return True
    except OSError:
        return False
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass


def config_path() -> Path:
    root = app_root()
    if _writable(root):
        return root / CONFIG_NAME
    return standard_dir() / CONFIG_NAME


def load_config() -> dict:
    """读取配置；兼容记事本另存产生的 UTF-8 BOM。"""
    try:
        data = json.loads(config_path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(payload: dict) -> bool:
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


def default_data_dir(root: Path | None = None) -> Path:
    """便携探测：优先 exe 同级 data\\，其次 docs\\，最后平台标准目录。"""
    root = root or app_root()
    for name in ("data", "docs"):
        candidate = root / name
        if candidate.is_dir():
            return candidate
    return standard_dir()


def data_dir() -> Path:
    """按优先级解析可用数据目录；任何一层不可用都降级到下一个候选并留下提示。"""
    override = os.environ.get("PLANCHECKBOX_DATA_DIR")
    if override:
        path = Path(override).expanduser()
        if _usable(path):
            return path
        _note(f"环境变量 PLANCHECKBOX_DATA_DIR 指向的目录不可用：{path}。\n"
              "程序已临时改用其他目录，原目录内容未被修改。")

    chosen = load_config().get("dataDir")
    if chosen:
        path = Path(str(chosen)).expanduser()
        if _usable(path):
            return path
        _note(f"上次设置的数据目录不可用：{path}\n"
              "可能被删除、换了盘符或没有写入权限。程序已临时改用其他目录，原文件没有被修改；"
              "请点顶栏「数据目录」重新选择。")

    root = app_root()
    candidates = []
    # 便携候选只看「已经存在」的目录，绝不主动创建，否则永远轮不到系统默认目录
    for portable in (root / "data", root / "docs"):
        if portable.is_dir():
            candidates.append((portable, None))
    candidates += [
        (standard_dir(), None),
        (root / f"{APP_DIR_NAME}-data",
         f"系统默认目录不可写（{standard_dir()}），已临时改用 exe 同级的 {APP_DIR_NAME}-data。\n"
         "建议点顶栏「数据目录」选择一个固定位置。"),
        (Path.home() / APP_DIR_NAME,
         f"系统默认目录不可写（{standard_dir()}），已临时改用用户主目录下的 {APP_DIR_NAME}。\n"
         "建议点顶栏「数据目录」选择一个固定位置。"),
        (Path(tempfile.gettempdir()) / APP_DIR_NAME,
         "警告：只能使用临时目录存放数据，关机或清理临时文件后可能丢失。\n"
         "请点顶栏「数据目录」选择固定位置。"),
    ]
    for path, message in candidates:
        if _usable(path):
            if message:
                _note(message)
            return path

    raise DataDirUnavailable(
        "找不到可写的数据目录。\n\n"
        f"已尝试：{'、'.join(str(p) for p, _ in candidates)}\n\n"
        "请检查磁盘是否已满或被安全策略锁定，或手动创建一个可写文件夹后重试。")


def set_data_dir(target) -> Path:
    """记住用户选择的数据目录（写入配置文件，并确认真的写进去了）。"""
    path = Path(str(target)).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    config = load_config()
    config["dataDir"] = str(path)
    if not save_config(config):
        raise OSError(f"配置文件写入失败：{config_path()}\n目录本身可用，但重启后会忘记这个选择。")
    global _issue
    _issue = None
    return path


def session_path() -> Path:
    return data_dir() / "session.json"


def load_session() -> dict:
    path = session_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_session(payload: dict) -> None:
    path = session_path()
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def clear_session() -> None:
    try:
        session_path().unlink(missing_ok=True)
    except OSError:
        pass
