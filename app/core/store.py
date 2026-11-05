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


def config_path() -> Path:
    root = app_root()
    if _writable(root):
        return root / CONFIG_NAME
    return standard_dir() / CONFIG_NAME


def load_config() -> dict:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(payload: dict) -> None:
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def default_data_dir(root: Path | None = None) -> Path:
    """便携探测：优先 exe 同级 data\\，其次 docs\\，最后平台标准目录。"""
    root = root or app_root()
    for name in ("data", "docs"):
        candidate = root / name
        if candidate.is_dir():
            return candidate
    return standard_dir()


def data_dir() -> Path:
    override = os.environ.get("PLANCHECKBOX_DATA_DIR")
    if override:
        path = Path(override).expanduser()
    else:
        chosen = load_config().get("dataDir")
        path = Path(str(chosen)).expanduser() if chosen else default_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_data_dir(target) -> Path:
    """记住用户选择的数据目录（写入配置文件）。"""
    path = Path(str(target)).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    config = load_config()
    config["dataDir"] = str(path)
    save_config(config)
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
