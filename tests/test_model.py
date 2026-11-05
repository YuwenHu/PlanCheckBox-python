import datetime as dt
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import model, parser  # noqa: E402
from app.core.dates import fmt_range, week_label  # noqa: E402
from tests import support  # noqa: E402

TODAY = dt.date(2026, 11, 5)


def make_group(tasks=None, **kwargs):
    tasks = tasks or [support.task("t1", "行列式", "2026-11-02")]
    result = parser.build(support.plan_json(tasks, **kwargs), "x_checkbox_use.json", path="C:/x.json")
    assert result.ok, result.error
    return result.group


class HeatTest(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual(model.heat_level(0), "")
        self.assertEqual(model.heat_level(1), "lv1")
        self.assertEqual(model.heat_level(2), "lv1")
        self.assertEqual(model.heat_level(3), "lv2")
        self.assertEqual(model.heat_level(5), "lv2")
        self.assertEqual(model.heat_level(6), "lv3")
        self.assertEqual(model.heat_level(99), "lv3")

    def test_counts_by_local_date_and_dedupes_id(self):
        g1 = make_group([
            support.task("a", "A", "2026-11-02", done=True, done_at="2026-11-05T09:00:00+08:00"),
            support.task("b", "B", "2026-11-03", done=True, done_at="2026-11-05T23:30:00+08:00"),
        ])
        g2 = make_group([
            support.task("a", "A2", "2026-11-02", done=True, done_at="2026-11-06T01:00:00+08:00"),
            support.task("c", "C", "2026-11-03"),
        ])
        counts = model.completion_by_day([g1, g2])
        self.assertEqual(counts.get("2026-11-05"), 2)
        self.assertIsNone(counts.get("2026-11-06"))
        self.assertEqual(sum(counts.values()), 2)

    def test_undated_falls_back_to_task_date(self):
        g = make_group([support.task("a", "A", "2026-11-02", done=True, done_at=None)])
        self.assertEqual(model.completion_by_day([g]), {"2026-11-02": 1})


class StatsTest(unittest.TestCase):
    def test_stats_and_pct(self):
        g = make_group([support.task(f"t{i}", f"T{i}", f"2026-11-{2 + i:02d}",
                                    minutes=30, done=(i < 2)) for i in range(3)])
        st = model.stats(g.tasks)
        self.assertEqual((st["total"], st["done"], st["remaining"]), (3, 2, 1))
        self.assertEqual(st["pct"], 67)
        self.assertEqual(st["minutes"], 90)
        self.assertEqual(st["minutesText"], "1 小时 30 分")

    def test_empty_stats(self):
        st = model.stats([])
        self.assertEqual((st["total"], st["done"], st["pct"]), (0, 0, 0))
        self.assertEqual(st["minutesText"], "未填时长")


class SortTest(unittest.TestCase):
    def setUp(self):
        self.group = make_group([
            support.task("p2done", "已完成P2", "2026-11-02", priority="P2", done=True),
            support.task("p1", "P1", "2026-11-03", priority="P1"),
            support.task("p0", "P0", "2026-11-04", priority="P0"),
            support.task("p2", "P2", "2026-11-05", priority="P2"),
        ])

    def test_display_sort_puts_done_last(self):
        ordered = [t.id for t in model.sort_for_display(self.group.tasks)]
        self.assertEqual(ordered, ["p0", "p1", "p2", "p2done"])

    def test_calendar_sort_priority_then_slot(self):
        ordered = [t.id for t in model.sort_calendar(self.group.tasks)]
        self.assertEqual(ordered[0], "p0")
        self.assertEqual(ordered[-1], "p2done")

    def test_all_done(self):
        done_group = make_group([support.task("a", "A", "2026-11-02", done=True),
                                 support.task("b", "B", "2026-11-03", done=True)])
        mixed_group = make_group([support.task("c", "C", "2026-11-02", done=True),
                                  support.task("d", "D", "2026-11-03")])
        self.assertTrue(model.all_done(done_group.tasks))
        self.assertFalse(model.all_done([]))
        self.assertFalse(model.all_done(mixed_group.tasks))


class PredictTest(unittest.TestCase):
    def test_completed(self):
        g = make_group([support.task("a", "A", "2026-11-02", done=True,
                                     done_at="2026-11-04T10:00:00+08:00")])
        p = model.predict(g.tasks, "2026-11-01", TODAY)
        self.assertTrue(p["ok"])
        self.assertTrue(p["completed"])
        self.assertEqual(p["label"], "已全部完成")

    def test_recent_weighted_rate(self):
        tasks = [support.task(f"d{i}", f"D{i}", f"2026-11-0{2 + i}", done=True,
                              done_at=f"2026-11-0{2 + i}T10:00:00+08:00") for i in range(3)]
        tasks += [support.task(f"r{i}", f"R{i}", f"2026-11-0{3 + i}") for i in range(7)]
        g = make_group(tasks)
        p = model.predict(g.tasks, "2026-11-01", TODAY)
        self.assertTrue(p["ok"])
        self.assertEqual(p["basis"], "近14天加权")
        self.assertGreater(p["rate"], 0)
        need = math.ceil(7 / p["rate"])
        self.assertEqual(p["needDays"], need)
        self.assertEqual(p["date"], (TODAY + dt.timedelta(days=need)).isoformat())

    def test_fallback_to_overall_average(self):
        tasks = [support.task(f"a{i}", f"A{i}", f"2026-11-0{1 + i}", done=True, done_at=None)
                 for i in range(2)]
        tasks += [support.task(f"b{i}", f"B{i}", f"2026-11-0{3 + i}") for i in range(3)]
        g = make_group(tasks)
        p = model.predict(g.tasks, "2026-10-25", TODAY)
        self.assertTrue(p["ok"])
        self.assertEqual(p["basis"], "整体平均")
        self.assertAlmostEqual(p["rate"], 2 / 12, places=3)

    def test_too_slow_shows_insufficient(self):
        g = make_group([support.task("a", "A", "2026-11-02", done=True, done_at="2026-09-01T10:00:00+08:00")]
                       + [support.task(f"b{i}", f"B{i}", f"2026-11-0{2 + i}") for i in range(2)],
                       plan_start="2026-01-01")
        p = model.predict(g.tasks, g.meta["planStart"], TODAY)
        self.assertFalse(p["ok"])
        self.assertEqual(p["label"], "数据不足")

    def test_empty_scope(self):
        self.assertFalse(model.predict([], "2026-11-01", TODAY)["ok"])


class FormattingTest(unittest.TestCase):
    def test_week_label_cn(self):
        self.assertEqual(week_label("第1周"), "第一周")
        self.assertEqual(week_label("第10周"), "第十周")
        self.assertEqual(week_label("第12周"), "第十二周")
        self.assertEqual(week_label("第21周"), "第二十一周")

    def test_fmt_range(self):
        self.assertEqual(fmt_range(dt.date(2026, 11, 2), dt.date(2026, 11, 8)), "11月2日 ~ 11月8日")
        self.assertEqual(fmt_range(dt.date(2026, 12, 28), dt.date(2027, 1, 3)),
                         "2026年12月28日 ~ 2027年1月3日")


class TopicAndColorTest(unittest.TestCase):
    def test_topic_summaries_compress(self):
        tasks = [support.task("a", "A", "2026-11-02", topic="极限"),
                 support.task("b", "B", "2026-12-03", topic="极限"),
                 support.task("c", "C", "2027-01-04", topic="极限"),
                 support.task("d", "D", "2026-11-05", topic="线代")]
        g = make_group(tasks)
        rows = model.topic_summaries(g)
        self.assertEqual([r["topic"] for r in rows], ["极限", "线代"])
        self.assertEqual(rows[0]["texts"], ["2026年11月–12月", "2027年1月"])
        self.assertEqual(rows[1]["texts"], ["11月"])

    def test_compress_months(self):
        self.assertEqual(model.compress_months([1, 2, 3, 7]), [(1, 3), (7, 7)])
        self.assertEqual(model.compress_months([11, 12, 1]), [(11, 12), (1, 1)])

    def test_group_color_deterministic(self):
        a = model.group_color("数二")
        b = model.group_color("数二")
        c = model.group_color("英二")
        self.assertEqual(a, b)
        self.assertNotEqual(a["hue"], c["hue"])

    def test_sort_groups_subjects_then_fitness(self):
        groups = [make_group([support.task("f", "跑", "2026-11-02", kind="fitness")],
                             group_name="健身", subject="健身", kind="fitness"),
                  make_group([support.task("p", "P", "2026-11-02")], group_name="政治", subject="政治"),
                  make_group([support.task("m", "M", "2026-11-02")], group_name="数二", subject="数学"),
                  make_group([support.task("e", "E", "2026-11-02")], group_name="英二", subject="英语")]
        names = [g.meta["groupName"] for g in model.sort_groups(groups)]
        self.assertEqual(names, ["数二", "英二", "政治", "健身"])


class DoneTextTest(unittest.TestCase):
    def test_done_and_last_done(self):
        t = make_group([support.task("a", "A", "2026-11-02", done=False,
                                     history=[{"action": "done", "at": "2026-11-03T09:00:00+08:00"},
                                              {"action": "undone", "at": "2026-11-04T10:00:00+08:00"},
                                              {"action": "done", "at": "2026-11-02T08:00:00+08:00"}])]).tasks[0]
        self.assertIn("11月3日 09:00", model.last_done_text(t, TODAY))
        self.assertEqual(model.done_text(t, TODAY), "")


if __name__ == "__main__":
    unittest.main()
