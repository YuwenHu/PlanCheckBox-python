"""pywebview 桥接层：前端只调用这里的少量方法，业务逻辑全在 app.core。"""
from __future__ import annotations

import time
from pathlib import Path

from .core.service import AppService


class Api:
    def __init__(self, service: AppService, window=None):
        self.service = service
        self.window = window

    # ---------------------------------------------------------------- 视图
    def get_view(self) -> dict:
        view = self.service.build_view()
        self._sync_title(view)
        return view

    def do_action(self, action: str, payload: dict | None = None) -> dict:
        result = self.service.dispatch(action, payload or {})
        view = self.service.build_view()
        self._sync_title(view)
        return {"result": result, "view": view}

    def _sync_title(self, view: dict) -> None:
        if self.window is None:
            return
        try:
            self.window.set_title(view.get("title") or "任务进度追踪")
        except Exception:
            pass

    # ---------------------------------------------------------------- 文件对话框
    def _dialog(self, kind: str, **kwargs):
        import webview

        if self.window is None:
            return None
        constant = getattr(webview, kind, None)
        if constant is None:
            enum = getattr(webview, "FileDialog", None)
            constant = getattr(enum, kind.replace("_DIALOG", ""), None) if enum else None
        return self.window.create_file_dialog(constant, **kwargs)

    def pick_files(self) -> dict:
        """原生多选对话框；返回已载入的文件视图。"""
        try:
            picked = self._dialog("OPEN_DIALOG", allow_multiple=True,
                                  file_types=("JSON 文件 (*.json)", "所有文件 (*.*)"))
        except Exception as exc:  # 用户取消或对话框不可用
            return {"result": {"ok": False, "message": f"无法打开文件选择框：{exc}"},
                    "view": self.service.build_view()}
        paths = [str(p) for p in (picked or [])]
        result = self.service.add_paths(paths) if paths else {"ok": False, "message": "未选择文件"}
        view = self.service.build_view()
        self._sync_title(view)
        return {"result": result, "view": view}

    def import_progress(self) -> dict:
        try:
            picked = self._dialog("OPEN_DIALOG", allow_multiple=False, file_types=("JSON 文件 (*.json)",))
        except Exception as exc:
            return {"result": {"ok": False, "message": f"无法打开文件选择框：{exc}"},
                    "view": self.service.build_view()}
        if not picked:
            return {"result": {"ok": False, "message": "未选择导入文件"},
                    "view": self.service.build_view()}
        path = picked[0] if isinstance(picked, (list, tuple)) else picked
        result = self.service.import_progress(str(path))
        view = self.service.build_view()
        return {"result": result, "view": view}

    def export_progress(self) -> dict:
        if not self.service.groups:
            return {"result": {"ok": False, "message": "还没有载入题库，无法导出", "kind": "error"},
                    "view": self.service.build_view()}
        stamp = time.strftime("%Y%m%d-%H%M")
        target = None
        try:
            picked = self._dialog("SAVE_DIALOG", save_filename=f"kyn_progress_{stamp}.json",
                                  file_types=("JSON 文件 (*.json)",))
            if picked:
                target = picked[0] if isinstance(picked, (list, tuple)) else picked
        except Exception as exc:
            return {"result": {"ok": False, "message": f"无法打开保存对话框：{exc}", "kind": "error"},
                    "view": self.service.build_view()}
        if not target:
            return {"result": {"ok": False, "message": "已取消导出"}, "view": self.service.build_view()}
        target = str(target)
        if not target.lower().endswith(".json"):
            target += ".json"
        try:
            Path(target).write_text(self.service.build_export(), encoding="utf-8")
        except OSError as exc:
            return {"result": {"ok": False, "message": f"导出失败：{exc.strerror or exc}", "kind": "error"},
                    "view": self.service.build_view()}
        return {"result": {"ok": True, "message": f"已导出 {len(self.service.groups)} 个组的完成记录"},
                "view": self.service.build_view()}

    def set_data_dir(self) -> dict:
        """原生选目录对话框：把「数据目录」记到配置文件，重启后仍生效。"""
        from .core import store

        try:
            picked = self._dialog("FOLDER_DIALOG")
        except Exception as exc:
            return {"result": {"ok": False, "message": f"无法打开目录选择框：{exc}", "kind": "error"},
                    "view": self.service.build_view()}
        target = picked[0] if isinstance(picked, (list, tuple)) else picked
        if not target:
            return {"result": {"ok": False, "message": "未选择数据目录"},
                    "view": self.service.build_view()}
        try:
            resolved = store.set_data_dir(target)
        except OSError as exc:
            return {"result": {"ok": False, "message": f"无法使用该目录：{exc.strerror or exc}", "kind": "error"},
                    "view": self.service.build_view()}
        return {"result": {"ok": True, "message": f"数据目录已设置为 {resolved}"},
                "view": self.service.build_view()}

    def quit(self) -> dict:
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
        return {"ok": True}
