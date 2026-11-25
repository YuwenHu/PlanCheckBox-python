"""数据目录解析与配置持久化（不依赖 GUI、不写真实用户目录）。"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core import store


class DataDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _patch_root(self):
        return mock.patch.object(store, "app_root", lambda: self.root)

    def test_portable_data_dir_wins(self):
        """① exe 同级 data\\ 优先，且高于 docs\\。"""
        (self.root / "data").mkdir()
        (self.root / "docs").mkdir()
        self.assertEqual(store.default_data_dir(self.root), self.root / "data")

    def test_docs_fallback(self):
        """② 没有 data 时用同级 docs\\（兼容既有结构）。"""
        (self.root / "docs").mkdir()
        self.assertEqual(store.default_data_dir(self.root), self.root / "docs")

    def test_standard_fallback(self):
        """③ 都没有时退回平台标准目录，且不含写死盘符。"""
        fallback = store.default_data_dir(self.root)
        self.assertEqual(fallback, store.standard_dir())
        self.assertNotEqual(fallback.anchor, "F:\\")

    def test_set_data_dir_persists_to_config(self):
        target = self.root / "chosen"
        with self._patch_root():
            resolved = store.set_data_dir(target)
            self.assertEqual(resolved, target.resolve())
            self.assertEqual(store.data_dir(), target.resolve())
            self.assertTrue((self.root / store.CONFIG_NAME).exists())

    def test_env_override_beats_config(self):
        target = self.root / "chosen"
        override = self.root / "envdir"
        with self._patch_root():
            store.set_data_dir(target)
            with mock.patch.dict(os.environ, {"PLANCHECKBOX_DATA_DIR": str(override)}):
                self.assertEqual(store.data_dir(), override)

    def test_session_file_lives_in_data_dir(self):
        target = self.root / "chosen"
        with self._patch_root():
            store.set_data_dir(target)
            store.save_session({"page": 1})
            self.assertTrue((target / "session.json").exists())
            self.assertEqual(store.load_session(), {"page": 1})

    def test_broken_config_dir_falls_back_with_readable_notice(self):
        """配置里的目录失效（被删/换盘/无权限）时不崩、不丢数据，并给出提示。"""
        blocker = self.root / "blocker"
        blocker.write_text("x", encoding="utf-8")
        broken = blocker / "no-such-sub"  # 父级是文件，必然创建失败
        with self._patch_root(), mock.patch.object(store, "standard_dir",
                                                   lambda: self.root / "std"):
            store.save_config({"dataDir": str(broken)})
            resolved = store.data_dir()
            self.assertEqual(resolved, self.root / "std")
            issue = store.pop_issue()
            self.assertIn("不可用", issue)
            self.assertIn("「数据目录」", issue)
            # 配置文件本身不能被覆盖掉，用户的选择还在
            self.assertEqual(store.load_config()["dataDir"], str(broken))

    def test_env_override_unavailable_warns_and_falls_back(self):
        blocker = self.root / "blocker2"
        blocker.write_text("x", encoding="utf-8")
        with self._patch_root(), mock.patch.object(store, "standard_dir",
                                                   lambda: self.root / "std2"):
            with mock.patch.dict(os.environ,
                                 {"PLANCHECKBOX_DATA_DIR": str(blocker / "sub")}):
                self.assertEqual(store.data_dir(), self.root / "std2")
                self.assertIn("PLANCHECKBOX_DATA_DIR", store.pop_issue())

    def test_all_candidates_unavailable_raises_readable_error(self):
        with self._patch_root(), mock.patch.object(store, "_usable", lambda path: False):
            with self.assertRaises(store.DataDirUnavailable) as ctx:
                store.data_dir()
            self.assertIn("找不到可写的数据目录", str(ctx.exception))

    def test_set_data_dir_reports_config_write_failure(self):
        with self._patch_root(), mock.patch.object(store, "save_config",
                                                   lambda payload: False):
            with self.assertRaises(OSError) as ctx:
                store.set_data_dir(self.root / "chosen2")
            self.assertIn("配置文件写入失败", str(ctx.exception))

    def test_config_with_bom_is_readable(self):
        """记事本另存的 UTF-8 BOM 配置也要能读出来。"""
        chosen = self.root / "chosen3"
        chosen.mkdir()
        payload = json.dumps({"dataDir": str(chosen)}).encode("utf-8")
        (self.root / "config.json").write_bytes(b"\xef\xbb\xbf" + payload)
        with self._patch_root():
            self.assertEqual(store.data_dir(), chosen)


if __name__ == "__main__":
    unittest.main()
