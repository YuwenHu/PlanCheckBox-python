"""清扫 PyInstaller onefile 在 %TEMP% 留下的 ``_MEI*`` 解包目录。

onefile exe 每次启动都会把自身解压到 ``%TEMP%\\_MEIxxxxxx``，正常退出时 PyInstaller
会自行删除；但被强杀、断电或杀软拦截时会留下整份解压结果（几十到几百 MB 一份）。

本模块在启动时做一次保守清扫，判定顺序（任何一步不满足就跳过）：

1. 只处理名字严格匹配 ``_MEI<数字>`` 的目录，以及它们被上次清理改名后的
   ``_MEI<数字>.__orphan__*`` 形态；``%TEMP%`` 下其它任何文件/目录一律不碰。
2. 跳过当前进程自己的解包目录（``sys._MEIPASS``）。
3. 跳过最近 ``MIN_AGE_SECONDS`` 内还在变化的目录——刚启动的实例可能还没加载完 DLL。
4. 用 Windows 进程模块枚举确认没有任何进程从该目录加载模块（DLL）。
5. 改名探测：先改成 ``__orphan__`` 再删；改名失败说明目录仍被占用，直接跳过。
6. 每次最多删 ``MAX_DIRS`` 个 / ``MAX_BYTES`` 字节，避免一次误伤太多。

注意：本模块永远不删除正在被自己使用的目录，也永远不碰非 ``_MEI`` 前缀的内容。
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# 30 分钟内创建/更新过的目录一律跳过（启动中的实例保护）
MIN_AGE_SECONDS = 30 * 60
# 单次清扫上限，防止误伤
MAX_DIRS = 20
MAX_BYTES = 2 * 1024 ** 3  # 2 GB
# 改名后残留的标记；下次启动仍会被识别
ORPHAN_TAG = ".__orphan__"

# PyInstaller 的解包目录名是 ``_MEI`` + 十六进制串（如 _MEI157282 / _MEI0000b4cc2）
_NAME_RE = re.compile(r"^_MEI[0-9a-fA-F]{3,}$")
_ORPHAN_RE = re.compile(r"^_MEI[0-9a-fA-F]{3,}\.__orphan__[0-9]+_[0-9]+$")


@dataclass
class SweepResult:
    """一次清扫的结果，便于日志、自检和单元测试断言。"""

    removed: list[tuple[Path, int]] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    freed_bytes: int = 0

    def skip(self, path: Path, reason: str) -> None:
        self.skipped.append((path, reason))

    def summary(self) -> str:
        return (f"removed={len(self.removed)} skipped={len(self.skipped)} "
                f"failed={len(self.failed)} freed={self.freed_bytes / 1024 / 1024:.1f}MB")


def enabled() -> bool:
    """默认开启；设置 ``PLANCHECKBOX_NO_TEMP_CLEAN=1`` 可关闭。"""
    return os.environ.get("PLANCHECKBOX_NO_TEMP_CLEAN", "").strip() not in {"1", "true", "yes"}


def temp_root() -> Path:
    return Path(tempfile.gettempdir())


def own_dir() -> Path | None:
    """当前进程自己的 onefile 解包目录；源码态没有。"""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def is_candidate(name: str) -> bool:
    return bool(_NAME_RE.match(name) or _ORPHAN_RE.match(name))


def _dir_size(path: Path) -> int:
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


# --------------------------------------------------------------------------
# 占用检测：枚举所有进程已加载的模块路径，看是否落在候选目录内
# --------------------------------------------------------------------------
def _windows_module_paths() -> list[str]:
    """返回所有可查询进程的模块路径（失败/无权限的进程直接忽略）。"""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD)]
    psapi.EnumProcessModulesEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE),
                                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                          wintypes.DWORD]
    psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, wintypes.HMODULE,
                                          wintypes.LPWSTR, wintypes.DWORD]
    psapi.GetModuleFileNameExW.restype = wintypes.DWORD

    arr = (wintypes.DWORD * 8192)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed)):
        return []
    count = needed.value // ctypes.sizeof(wintypes.DWORD)

    paths: list[str] = []
    for index in range(count):
        pid = arr[index]
        if not pid:
            continue
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)  # QUERY_INFORMATION | VM_READ
        if not handle:
            continue
        try:
            mods = (wintypes.HMODULE * 1024)()
            got = wintypes.DWORD()
            if not psapi.EnumProcessModulesEx(handle, mods, ctypes.sizeof(mods),
                                              ctypes.byref(got), 0x03):  # LIST_MODULES_ALL
                continue
            buf = ctypes.create_unicode_buffer(32768)
            for i in range(got.value // ctypes.sizeof(wintypes.HMODULE)):
                if psapi.GetModuleFileNameExW(handle, mods[i], buf, 32768):
                    paths.append(buf.value)
        except OSError:
            continue
        finally:
            kernel32.CloseHandle(handle)
    return paths


def occupied_dirs(candidates: list[Path]) -> set[str]:
    """返回被任何进程当作模块目录使用的候选目录（规范化绝对路径）。"""
    if not candidates:
        return set()
    prefixes = {_norm(p).rstrip("\\") + "\\" for p in candidates}
    busy: set[str] = set()
    for module_path in _windows_module_paths():
        lowered = os.path.normcase(module_path)
        for prefix in prefixes:
            if lowered.startswith(prefix):
                busy.add(prefix)
                break
    return {p.rstrip("\\") for p in busy}


def _rename_to_orphan(path: Path) -> Path:
    target = path.with_name(f"{path.name}{ORPHAN_TAG}{os.getpid()}_{int(time.time())}")
    os.rename(path, target)
    return target


def _rmtree(path: Path) -> None:
    def onexc(func, failed, _exc):
        try:
            os.chmod(failed, stat.S_IWRITE)
            func(failed)
        except OSError:
            pass

    try:
        shutil.rmtree(path, onexc=onexc)
    except TypeError:  # Python < 3.12
        shutil.rmtree(path, onerror=onexc)


def sweep(tmp_root: Path | None = None, *, min_age: float = MIN_AGE_SECONDS,
          max_dirs: int = MAX_DIRS, max_bytes: int = MAX_BYTES,
          now: float | None = None, occupied=None) -> SweepResult:
    """扫描并删除孤儿 ``_MEI*`` 目录；``tmp_root`` / ``occupied`` 可注入，便于测试。"""
    result = SweepResult()
    root = Path(tmp_root) if tmp_root else temp_root()
    try:
        entries = list(os.scandir(root))
    except OSError:
        return result

    mine = _norm(own_dir()) if own_dir() else None
    clock = time.time() if now is None else now

    fresh: list[Path] = []
    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False) or not is_candidate(entry.name):
                continue
        except OSError:
            continue
        path = Path(entry.path)
        if mine and _norm(path) == mine:
            result.skip(path, "own")
            continue
        if ORPHAN_TAG not in entry.name:
            try:
                age = clock - entry.stat(follow_symlinks=False).st_mtime
            except OSError:
                result.skip(path, "stat-failed")
                continue
            if age < min_age:
                result.skip(path, "recent")
                continue
        fresh.append(path)

    probe = occupied if occupied is not None else occupied_dirs
    busy = {os.path.normcase(p) for p in probe(fresh)}

    removed_count = 0
    for path in fresh:
        if os.path.normcase(str(path)) in busy:
            result.skip(path, "in-use")
            continue
        if removed_count >= max_dirs:
            result.skip(path, "quota-dirs")
            continue
        size = _dir_size(path)
        if result.freed_bytes + size > max_bytes:
            result.skip(path, "quota-bytes")
            continue
        try:
            target = _rename_to_orphan(path)
        except OSError:
            result.skip(path, "locked")
            continue
        try:
            _rmtree(target)
        except OSError as exc:
            result.failed.append((target, str(exc)))
            continue
        if target.exists():
            result.failed.append((target, "部分文件未删除"))
            continue
        result.removed.append((path, size))
        result.freed_bytes += size
        removed_count += 1
    return result


def auto_sweep() -> SweepResult | None:
    """GUI 启动前的静默清扫；任何异常都不影响主流程。"""
    if not enabled():
        return None
    try:
        return sweep()
    except Exception:  # 清理是尽力而为，绝不阻塞启动
        return None
