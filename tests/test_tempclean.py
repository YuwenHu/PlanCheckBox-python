"""_MEI* 孤儿目录清理的单元测试（全部在临时目录里跑，不碰真实 %TEMP%）。"""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from app.core import tempclean


class SweepTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make_dir(self, name, *, size=0, age=3600):
        path = self.root / name
        path.mkdir()
        if size:
            (path / "payload.bin").write_bytes(b"x" * size)
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    def test_removes_old_orphan_and_reports_size(self):
        target = self.make_dir("_MEI123456", size=2048)
        result = tempclean.sweep(self.root)
        self.assertFalse(target.exists())
        self.assertEqual(len(result.removed), 1)
        self.assertGreaterEqual(result.freed_bytes, 2048)

    def test_skips_own_extraction_dir(self):
        target = self.make_dir("_MEI777", size=16)
        with mock.patch.object(tempclean, "own_dir", lambda: target):
            result = tempclean.sweep(self.root)
        self.assertTrue(target.exists())
        self.assertEqual([reason for _, reason in result.skipped], ["own"])

    def test_skips_recent_dir(self):
        target = self.make_dir("_MEI888", age=5)
        result = tempclean.sweep(self.root)
        self.assertTrue(target.exists())
        self.assertEqual([reason for _, reason in result.skipped], ["recent"])

    def test_ignores_non_mei_entries(self):
        keep = [
            self.make_dir("_MEIzzz", age=3600),
            self.make_dir("_MEI", age=3600),
            self.make_dir("_MEI123.bak", age=3600),
            self.make_dir("other_dir", age=3600),
        ]
        marker = self.root / "_MEI999.txt"
        marker.write_text("keep", encoding="utf-8")
        result = tempclean.sweep(self.root)
        for path in keep:
            self.assertTrue(path.exists(), path)
        self.assertTrue(marker.exists())
        self.assertEqual(result.removed, [])

    def test_skips_dir_used_by_running_process(self):
        target = self.make_dir("_MEI555", size=32)
        result = tempclean.sweep(self.root, occupied=lambda paths: set(paths))
        self.assertTrue(target.exists())
        self.assertEqual([reason for _, reason in result.skipped], ["in-use"])

    def test_honours_dir_quota(self):
        targets = [self.make_dir(f"_MEI{1000 + i}", size=16) for i in range(4)]
        result = tempclean.sweep(self.root, max_dirs=2)
        self.assertEqual(len(result.removed), 2)
        self.assertEqual([r for _, r in result.skipped].count("quota-dirs"), 2)
        self.assertEqual(sum(1 for p in targets if p.exists()), 2)

    def test_honours_byte_quota(self):
        target = self.make_dir("_MEI4242", size=4096)
        result = tempclean.sweep(self.root, max_bytes=1024)
        self.assertTrue(target.exists())
        self.assertEqual([reason for _, reason in result.skipped], ["quota-bytes"])

    def test_locked_dir_is_skipped(self):
        target = self.make_dir("_MEI321", size=16)
        with mock.patch.object(tempclean.os, "rename", side_effect=OSError("locked")):
            result = tempclean.sweep(self.root)
        self.assertTrue(target.exists())
        self.assertEqual([reason for _, reason in result.skipped], ["locked"])

    def test_previous_orphan_tag_is_recovered(self):
        target = self.make_dir("_MEI222.__orphan__111_222", age=0)
        result = tempclean.sweep(self.root)
        self.assertFalse(target.exists())
        self.assertEqual(len(result.removed), 1)

    def test_candidate_names(self):
        self.assertTrue(tempclean.is_candidate("_MEI123"))
        self.assertTrue(tempclean.is_candidate("_MEI0000b4cc2"))
        self.assertTrue(tempclean.is_candidate("_MEI123.__orphan__1_2"))
        for name in ("_MEI", "_MEI12z", "_MEIX1", "pyi-123", "_MEI1.tmp"):
            self.assertFalse(tempclean.is_candidate(name), name)


if __name__ == "__main__":
    unittest.main()
