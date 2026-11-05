"""数据目录解析与配置持久化（不依赖 GUI、不写真实用户目录）。"""
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


if __name__ == "__main__":
    unittest.main()
