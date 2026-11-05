import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import parser  # noqa: E402
from app.core.dates import parse_iso_date  # noqa: E402
from tests import support  # noqa: E402


class DisplayNameTest(unittest.TestCase):
    def test_group_name_wins(self):
        data = support.plan_json([support.task("t1", "标题", "2026-11-02")], group_name="数二")
        result = parser.build(data, "math2_checkbox_use.json", "学校文件")
        self.assertTrue(result.ok)
        self.assertEqual(result.group.display_name, "数二")

    def test_fallback_to_file_name(self):
        data = support.plan_json([support.task("t1", "标题", "2026-11-02")], group_name="")
        result = parser.build(data, "math2_checkbox_use.json", "x")
        self.assertEqual(result.group.display_name, "math2")

    def test_fallback_without_marker(self):
        self.assertEqual(parser.display_name_from_file_name("journal.json"), "journal")
        self.assertEqual(parser.display_name_from_file_name(r"C:\a\eng2_checkbox_use.json"), "eng2")


class ToleranceTest(unittest.TestCase):
    def test_unknown_day_and_task_fields_ignored(self):
        tasks = [support.task("t1", "行列式", "2026-11-02", extra_field={"deep": [1, 2]}, note="备注")]
        data = support.plan_json(tasks, day_extra={"note": "day note"})
        result = parser.build(data, "x_checkbox_use.json")
        self.assertTrue(result.ok)
        self.assertEqual(result.group.tasks[0].title, "行列式")
        self.assertEqual(len(result.group.warnings), 0)
        # 未知字段保留在 raw 里（写回时不能丢），但不进入模型
        self.assertIn("extra_field", result.group.raw["months"][0]["weeks"][0]["days"][0]["tasks"][0])

    def test_bad_date_is_warned_not_fatal(self):
        tasks = [support.task("t1", "OK", "2026-11-02"), support.task("t2", "OK2", "2026-11-03")]
        data = support.plan_json(tasks)
        data["months"][0]["weeks"][0]["days"][0]["date"] = "2026/11/02"
        result = parser.build(data, "x_checkbox_use.json")
        self.assertTrue(result.ok)
        self.assertTrue(any("非法日期" in w for w in result.group.warnings))
        self.assertEqual(len(result.group.tasks), 1)

    def test_strict_date_format(self):
        self.assertIsNone(parse_iso_date("2026-1-1"))
        self.assertIsNone(parse_iso_date("2026-13-01"))
        self.assertIsNone(parse_iso_date("2026-11-02T10:00"))
        self.assertIsNotNone(parse_iso_date("2026-11-02"))

    def test_history_cleanup(self):
        self.assertEqual(
            parser.clean_history([{"action": "done", "at": "2026-11-05T10:00:00+08:00"},
                                 {"action": "undone", "at": "2026-11-05T11:00:00+08:00"},
                                 {"action": "nope", "at": "2026-11-05T11:00:00+08:00"},
                                 "bad"]),
            [{"action": "done", "at": "2026-11-05T10:00:00+08:00"},
             {"action": "undone", "at": "2026-11-05T11:00:00+08:00"}])


class ErrorTest(unittest.TestCase):
    def test_missing_meta(self):
        data = {"months": [{"id": "2026-11", "label": "2026年11月", "weeks": []}]}
        result = parser.build(data, "x.json")
        self.assertFalse(result.ok)
        self.assertIn("meta", result.error)

    def test_empty_months(self):
        data = {"meta": {"groupName": "数学"}, "months": []}
        result = parser.build(data, "x.json")
        self.assertFalse(result.ok)
        self.assertIn("months 为空", result.error)

    def test_task_without_title(self):
        data = support.plan_json([support.task("t1", "", "2026-11-02")])
        result = parser.build(data, "x.json")
        self.assertFalse(result.ok)
        self.assertIn("没有解析到任何任务", result.error)

    def test_root_not_object(self):
        self.assertFalse(parser.build([], "x.json").ok)

    def test_missing_months_key(self):
        self.assertFalse(parser.build({"meta": {"groupName": "数学"}}, "x.json").ok)


class RealDataTest(unittest.TestCase):
    def test_all_five_groups_parse(self):
        groups = []
        for name in support.SAMPLE_KEYS:
            data = json.loads(support.sample_text(name))
            result = parser.build(data, f"{name}_checkbox_use.json")
            self.assertTrue(result.ok, name)
            groups.append(result.group)
        names = [g.display_name for g in groups]
        self.assertEqual(names, ["数二", "英二", "政治", "408", "健身"])
        studies = [g for g in groups if g.meta["kind"] == "study"]
        fitness = [g for g in groups if g.meta["kind"] == "fitness"]
        self.assertEqual(len(studies), 4)
        self.assertEqual(len(fitness), 1)
        for g in groups:
            self.assertTrue(g.tasks)
            for t in g.tasks:
                self.assertIn(t.kind, ("study", "fitness"))


if __name__ == "__main__":
    unittest.main()
