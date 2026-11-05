import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import jsonio  # noqa: E402
from tests import support  # noqa: E402


class RoundTripTest(unittest.TestCase):
    def test_sample_files_byte_identical(self):
        """5 个契约文件：解析后重新序列化必须与原文字节一致（键序/缩进/换行/结尾）。"""
        for name in support.SAMPLE_KEYS:
            raw = support.sample_text(name)
            fmt = jsonio.detect_format(raw)
            self.assertEqual(jsonio.serialize(json.loads(raw), fmt), raw, name)

    @unittest.skipUnless(support.REAL_DIR.exists(), "只读契约目录不存在")
    def test_real_contract_files_byte_identical(self):
        for name in support.SAMPLE_KEYS:
            path = support.REAL_DIR / f"{name}_checkbox_use.json"
            raw = path.read_text(encoding="utf-8-sig")
            self.assertEqual(jsonio.serialize(json.loads(raw), jsonio.detect_format(raw)), raw, name)


class FormatTest(unittest.TestCase):
    def test_detect_four_space_crlf(self):
        text = '{\r\n    "a": 1\r\n}\r\n'
        fmt = jsonio.detect_format(text)
        self.assertEqual(fmt.indent, "    ")
        self.assertTrue(fmt.crlf)
        self.assertTrue(fmt.trailing)
        self.assertEqual(jsonio.serialize({"a": 1}, fmt), text)

    def test_detect_no_trailing_newline(self):
        text = '{\n  "a": 1\n}'
        fmt = jsonio.detect_format(text)
        self.assertFalse(fmt.trailing)
        self.assertEqual(jsonio.serialize({"a": 1}, fmt), text)

    def test_digest_changes_with_content(self):
        self.assertNotEqual(jsonio.digest("a"), jsonio.digest("b"))
        self.assertEqual(jsonio.digest("中文"), jsonio.digest("中文"))


class ApplyTaskTest(unittest.TestCase):
    def setUp(self):
        self.raw = support.plan_json([
            support.task("t1", "行列式", "2026-11-02"),
            support.task("t2", "矩阵", "2026-11-03"),
        ], day_extra={"note": "未知字段应保留"}, meta_extra={"custom": {"k": 1}})
        self.original = json.dumps(self.raw, ensure_ascii=False, indent=2)

    def test_only_target_task_changes(self):
        before = json.loads(self.original)
        self.assertTrue(jsonio.apply_task(self.raw, "t1", True, "2026-11-05T10:00:00+08:00",
                                          [{"action": "done", "at": "2026-11-05T10:00:00+08:00"}]))
        t1 = self.raw["months"][0]["weeks"][0]["days"][0]["tasks"][0]
        t2 = self.raw["months"][0]["weeks"][0]["days"][1]["tasks"][0]
        self.assertTrue(t1["done"])
        self.assertEqual(t1["history"], [{"action": "done", "at": "2026-11-05T10:00:00+08:00"}])
        self.assertEqual(t2, before["months"][0]["weeks"][0]["days"][1]["tasks"][0])
        self.assertEqual(t1["title"], before["months"][0]["weeks"][0]["days"][0]["tasks"][0]["title"])

    def test_key_order_and_unknown_fields_kept(self):
        self.assertTrue(jsonio.apply_task(self.raw, "t2", False, None, []))
        text = json.dumps(self.raw, ensure_ascii=False, indent=2)
        self.assertIn('"note": "未知字段应保留"', text)
        self.assertIn('"custom"', text)
        day = self.raw["months"][0]["weeks"][0]["days"][0]
        self.assertEqual(list(day.keys()), ["date", "type", "tasks", "note"])
        self.assertEqual(list(day["tasks"][0].keys()),
                         ["id", "title", "priority", "kind", "topic", "minutes", "slot",
                          "done", "doneAt", "history"])

    def test_history_is_cleaned(self):
        self.assertTrue(jsonio.apply_task(self.raw, "t1", True, "2026-11-05T10:00:00+08:00",
                                          [{"action": "done", "at": "2026-11-05T10:00:00+08:00"},
                                           {"action": "bogus", "at": "x"},
                                           {"action": "done", "at": "not-a-time"}]))
        t1 = self.raw["months"][0]["weeks"][0]["days"][0]["tasks"][0]
        self.assertEqual(len(t1["history"]), 1)

    def test_missing_task_returns_false(self):
        self.assertFalse(jsonio.apply_task(self.raw, "nope", True, "2026-11-05T10:00:00+08:00", []))


class WriteFileTest(unittest.TestCase):
    def test_atomic_write_preserves_crlf_indent(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.json"
            text = '{\r\n    "a": 1\r\n}\r\n'
            path.write_text(text, encoding="utf-8", newline="")
            jsonio.write_text_atomic(path, text)
            self.assertEqual(path.read_bytes().decode("utf-8"), text)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["a.json"])


if __name__ == "__main__":
    unittest.main()
