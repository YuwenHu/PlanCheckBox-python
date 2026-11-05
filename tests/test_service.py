import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.service import AppService  # noqa: E402
from tests import support  # noqa: E402

T1 = "2026-11-05T09:10:00+08:00"
T2 = "2026-11-05T10:20:00+08:00"
T3 = "2026-11-05T11:30:00+08:00"


class ServiceCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._old_env = os.environ.get("PLANCHECKBOX_DATA_DIR")
        os.environ["PLANCHECKBOX_DATA_DIR"] = str(self.tmp / "appdata")
        (self.tmp / "appdata").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("PLANCHECKBOX_DATA_DIR", None)
        else:
            os.environ["PLANCHECKBOX_DATA_DIR"] = self._old_env
        self._tmp.cleanup()

    def make_file(self, name, tasks, **kwargs):
        path = self.tmp / name
        support.write_json(path, support.plan_json(tasks, **kwargs))
        return path


class Page1Test(ServiceCase):
    def test_sorted_by_task_count_and_name_fallback(self):
        big = self.make_file("math2_checkbox_use.json",
                             [support.task(f"m{i}", f"M{i}", "2026-11-02") for i in range(6)],
                             group_name="")
        small = self.make_file("eng2_checkbox_use.json",
                               [support.task(f"e{i}", f"E{i}", "2026-11-02") for i in range(2)],
                               group_name="英二")
        svc = AppService()
        svc.add_paths([str(small), str(big)])
        view = svc.build_view()
        names = [f["displayName"] for f in view["page1"]["files"]]
        self.assertEqual(names, ["math2", "英二"])
        self.assertEqual(view["title"], "选择任务 · 任务进度追踪")

    def test_invalid_files_listed_with_error(self):
        bad = self.tmp / "broken.json"
        bad.write_text("{not json", encoding="utf-8")
        good = self.make_file("g_checkbox_use.json", [support.task("a", "A", "2026-11-02")], group_name="数学")
        svc = AppService()
        result = svc.add_paths([str(good), str(bad), str(self.tmp / "missing.json")])
        self.assertIn("1 个可用", result["message"])
        view = svc.build_view()
        rows = view["page1"]["files"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[-1]["error"])
        self.assertIn("JSON", rows[-1]["sub"])

    def test_remove_and_clear(self):
        path = self.make_file("g_checkbox_use.json", [support.task("a", "A", "2026-11-02")])
        svc = AppService()
        svc.add_paths([str(path)])
        svc.dispatch("remove_file", {"path": str(path)})
        self.assertEqual(svc.build_view()["page"], 1)
        self.assertEqual(len(svc.files), 0)
        svc.add_paths([str(path)])
        svc.dispatch("clear_files")
        self.assertEqual(len(svc.files), 0)


class NavigationTest(ServiceCase):
    def setUp(self):
        super().setUp()
        self.path = self.make_file("math2_checkbox_use.json",
                                   [support.task("t1", "行列式", "2026-11-02"),
                                    support.task("t2", "矩阵", "2026-12-01")],
                                   group_name="数二")
        self.svc = AppService()
        self.svc.add_paths([str(self.path)])

    def test_crumbs_current_flags(self):
        self.svc.dispatch("to_overview")
        v = self.svc.build_view()
        self.assertEqual([c["current"] for c in v["crumbs"]], [False, True])

        self.svc.dispatch("open_group", {"path": str(self.path)})
        v = self.svc.build_view()
        self.assertEqual([c["label"] for c in v["crumbs"]], ["选择题库", "总览", "数二"])
        self.assertEqual([c["current"] for c in v["crumbs"]], [False, False, True])

        month = v["cards"][0]["id"]
        self.svc.dispatch("open_month", {"month": month})
        v = self.svc.build_view()
        self.assertEqual(v["page"], 4)
        self.assertEqual(v["crumbs"][-1]["current"], True)

    def test_back_walks_up(self):
        self.svc.dispatch("to_overview")
        self.svc.dispatch("open_group", {"path": str(self.path)})
        self.svc.dispatch("open_month", {"month": "2026-11"})
        self.assertEqual(self.svc.build_view()["page"], 4)
        self.svc.dispatch("back")
        self.assertEqual(self.svc.build_view()["page"], 3)
        self.svc.dispatch("back")
        self.assertEqual(self.svc.build_view()["page"], 2)
        self.svc.dispatch("back")
        self.assertEqual(self.svc.build_view()["page"], 1)

    def test_week_toggle_updates_expanded(self):
        self.svc.dispatch("to_overview")
        self.svc.dispatch("open_group", {"path": str(self.path)})
        self.svc.dispatch("open_month", {"month": "2026-11"})
        v = self.svc.build_view()
        key = v["weeks"][0]["key"]
        self.assertFalse(v["weeks"][0]["open"])
        self.svc.dispatch("toggle_week", {"week": key})
        v = self.svc.build_view()
        self.assertTrue(v["weeks"][0]["open"])
        self.assertTrue(v["weeks"][0]["days"])
        self.svc.dispatch("toggle_week", {"week": key})
        self.assertFalse(self.svc.build_view()["weeks"][0]["open"])

    def test_ov_month_shift(self):
        self.svc.dispatch("to_overview")
        v = self.svc.build_view()
        current = v["calendar"]["monthId"]
        self.svc.dispatch("ov_month_next")
        self.assertEqual(self.svc.build_view()["calendar"]["monthId"] != current, True)
        self.svc.dispatch("ov_month_today")
        self.assertEqual(self.svc.build_view()["calendar"]["monthId"], current)


class ToggleTest(ServiceCase):
    def setUp(self):
        super().setUp()
        self.path = self.make_file("math2_checkbox_use.json",
                                   [support.task("t1", "行列式", "2026-11-02", extra_field={"keep": 1}),
                                    support.task("t2", "矩阵", "2026-11-03")],
                                   group_name="数二", day_extra={"note": "保留字段"})
        self.svc = AppService()
        self.svc.add_paths([str(self.path)])
        self.svc.dispatch("to_overview")
        self.svc.dispatch("open_group", {"path": str(self.path)})

    def read_raw(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def find(self, raw, task_id):
        for m in raw["months"]:
            for w in m["weeks"]:
                for d in w["days"]:
                    for t in d["tasks"]:
                        if t["id"] == task_id:
                            return t
        raise AssertionError(task_id)

    def test_check_writes_only_target_and_keeps_format(self):
        with mock.patch("app.core.service.now_local_iso", return_value=T1):
            result = self.svc.dispatch("toggle_task", {"path": str(self.path), "id": "t1", "checked": True})
        self.assertTrue(result["ok"])
        raw = self.read_raw()
        t1 = self.find(raw, "t1")
        t2 = self.find(raw, "t2")
        self.assertTrue(t1["done"])
        self.assertEqual(t1["doneAt"], T1)
        self.assertEqual(t1["history"], [{"action": "done", "at": T1}])
        self.assertEqual(t2["done"], False)
        self.assertIn("keep", t1["extra_field"])
        day = raw["months"][0]["weeks"][0]["days"][0]
        self.assertEqual(list(day.keys()), ["date", "type", "tasks", "note"])
        text = self.path.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("}\n"))
        self.assertNotIn("\r\n", text)

    def test_uncheck_keeps_latest_done_at(self):
        with mock.patch("app.core.service.now_local_iso", return_value=T1):
            self.svc.dispatch("toggle_task", {"path": str(self.path), "id": "t1", "checked": True})
        with mock.patch("app.core.service.now_local_iso", return_value=T2):
            self.svc.dispatch("toggle_task", {"path": str(self.path), "id": "t1", "checked": False})
        t1 = self.find(self.read_raw(), "t1")
        self.assertEqual(t1["done"], False)
        self.assertEqual(t1["doneAt"], T1)
        self.assertEqual([h["action"] for h in t1["history"]], ["done", "undone"])

    def test_recheck_uses_latest_time(self):
        with mock.patch("app.core.service.now_local_iso", return_value=T1):
            self.svc.dispatch("toggle_task", {"path": str(self.path), "id": "t1", "checked": True})
        with mock.patch("app.core.service.now_local_iso", return_value=T2):
            self.svc.dispatch("toggle_task", {"path": str(self.path), "id": "t1", "checked": False})
        with mock.patch("app.core.service.now_local_iso", return_value=T3):
            self.svc.dispatch("toggle_task", {"path": str(self.path), "id": "t1", "checked": True})
        t1 = self.find(self.read_raw(), "t1")
        self.assertTrue(t1["done"])
        self.assertEqual(t1["doneAt"], T3)
        self.assertEqual([h["at"] for h in t1["history"]], [T1, T2, T3])

    def test_in_memory_state_refreshes(self):
        with mock.patch("app.core.service.now_local_iso", return_value=T1):
            self.svc.dispatch("toggle_task", {"path": str(self.path), "id": "t1", "checked": True})
        view = self.svc.build_view()
        self.assertEqual(view["stat"]["stats"]["done"], 1)
        card = next(c for c in view["cards"] if c["id"] == "2026-11")
        self.assertEqual(card["done"], 1)
        self.assertTrue(any(t["was"].startswith("已完成") for t in card["tasks"]))

    def test_external_plan_edit_is_merged(self):
        raw = self.read_raw()
        raw["months"][0]["weeks"][0]["days"][0]["tasks"].append({
            "id": "t3", "title": "新增题", "priority": "P0", "kind": "study", "topic": "高数",
            "minutes": 25, "slot": "晚上", "done": False, "doneAt": None, "history": [],
        })
        support.write_json(self.path, raw)
        with mock.patch("app.core.service.now_local_iso", return_value=T1):
            result = self.svc.dispatch("toggle_task", {"path": str(self.path), "id": "t1", "checked": True})
        self.assertTrue(result["ok"])
        self.assertIn("外部改动", result["message"])
        raw = self.read_raw()
        ids = [t["id"] for m in raw["months"] for w in m["weeks"] for d in w["days"] for t in d["tasks"]]
        self.assertIn("t3", ids)
        self.assertEqual(self.find(raw, "t3")["done"], False)
        self.assertTrue(self.find(raw, "t1")["done"])

    def test_unknown_task_is_rejected(self):
        result = self.svc.dispatch("toggle_task", {"path": str(self.path), "id": "nope", "checked": True})
        self.assertFalse(result["ok"])
        self.assertEqual(self.find(self.read_raw(), "t1")["done"], False)

    def test_crlf_and_four_space_preserved(self):
        obj = json.loads(self.path.read_text(encoding="utf-8"))
        support.write_json(self.path, obj, indent=4, crlf=True)
        self.svc = AppService()
        self.svc.add_paths([str(self.path)])
        with mock.patch("app.core.service.now_local_iso", return_value=T1):
            self.svc.dispatch("toggle_task", {"path": str(self.path), "id": "t1", "checked": True})
        text = self.path.read_bytes().decode("utf-8")
        self.assertIn("\r\n", text)
        self.assertIn('\r\n    "meta"', text)


class CalendarAndStatsTest(ServiceCase):
    def test_month_calendar_42_cells_and_done_sinks(self):
        path = self.make_file("math2_checkbox_use.json", [
            support.task("a", "早做", "2026-11-02", priority="P2", done=True, done_at="2026-11-02T20:00:00+08:00"),
            support.task("b", "晚做", "2026-11-02", priority="P0"),
        ], group_name="数二")
        svc = AppService()
        svc.add_paths([str(path)])
        svc.dispatch("to_overview")
        svc.dispatch("open_group", {"path": str(path)})
        cal = svc.build_view()["calendar"]
        self.assertEqual(len(cal["cells"]), 42)
        cell = next(c for c in cal["cells"] if c.get("date") == "2026-11-02")
        self.assertEqual([t["title"] for t in cell["tasks"]], ["晚做", "早做"])
        self.assertEqual(cell["minutesText"], "1 小时")

    def test_complete_month_sinks_to_bottom(self):
        path = self.make_file("math2_checkbox_use.json", [
            support.task("a", "A", "2026-11-02", done=True, done_at="2026-11-02T09:00:00+08:00"),
            support.task("b", "B", "2026-12-01"),
        ], group_name="数二")
        svc = AppService()
        svc.add_paths([str(path)])
        svc.dispatch("open_group", {"path": str(path)})
        cards = svc.build_view()["cards"]
        self.assertEqual([c["label"] for c in cards], ["2026年12月", "2026年11月"])
        self.assertTrue(cards[-1]["complete"])
        self.assertFalse(cards[0]["complete"])

    def test_heatmap_years_and_levels(self):
        path = self.make_file("math2_checkbox_use.json", [
            support.task("a", "A", "2026-11-02", done=True, done_at="2026-11-02T09:00:00+08:00"),
            support.task("b", "B", "2026-11-03", done=True, done_at="2026-11-03T09:00:00+08:00"),
            support.task("c", "C", "2025-12-31", done=True, done_at="2025-12-31T09:00:00+08:00"),
        ], group_name="数二")
        svc = AppService()
        svc.add_paths([str(path)])
        svc.dispatch("to_overview")
        heat = svc.build_view()["heat"]
        self.assertEqual(heat["years"], [2025, 2026])
        cell = next(c for c in heat["cells"] if c.get("key") == "2026-11-02")
        self.assertEqual(cell["level"], "lv1")
        self.assertIn("完成 1 项", cell["title"])

    def test_page4_two_bars_for_study_one_for_fitness(self):
        study = self.make_file("math2_checkbox_use.json", [
            support.task("s1", "数学", "2026-11-02"),
        ], group_name="数二")
        fit = self.make_file("fitness_checkbox_use.json", [
            support.task("f1", "跑步", "2026-11-03", kind="fitness"),
            support.task("f2", "力量", "2026-11-05", kind="fitness"),
        ], group_name="健身", subject="健身", kind="fitness")
        svc = AppService()
        svc.add_paths([str(study), str(fit)])
        svc.dispatch("to_overview")
        svc.dispatch("open_group", {"path": str(study)})
        svc.dispatch("open_month", {"month": "2026-11"})
        v = svc.build_view()
        self.assertEqual([b["label"] for b in v["bars"]], ["学习", "健身"])
        self.assertEqual(v["bars"][0]["stats"]["total"], 1)
        self.assertEqual(v["bars"][1]["stats"]["total"], 2)

        svc.dispatch("open_group", {"path": str(fit)})
        svc.dispatch("open_month", {"month": "2026-11"})
        v = svc.build_view()
        self.assertEqual([b["label"] for b in v["bars"]], ["健身"])

    def test_week_title_and_days(self):
        path = self.make_file("math2_checkbox_use.json", [
            support.task("a", "A", "2026-11-02"),
            support.task("b", "B", "2026-11-08"),
        ], group_name="数二")
        svc = AppService()
        svc.add_paths([str(path)])
        svc.dispatch("open_group", {"path": str(path)})
        svc.dispatch("open_month", {"month": "2026-11"})
        v = svc.build_view()
        self.assertEqual(v["weeks"][0]["title"], "第一周，11月2日 ~ 11月8日")
        svc.dispatch("toggle_week", {"week": v["weeks"][0]["key"]})
        v = svc.build_view()
        self.assertEqual(len(v["weeks"][0]["days"]), 2)


class ExportImportTest(ServiceCase):
    def test_export_then_import(self):
        path = self.make_file("math2_checkbox_use.json", [
            support.task("a", "A", "2026-11-02", done=True, done_at=T1,
                         history=[{"action": "done", "at": T1}]),
            support.task("b", "B", "2026-11-03"),
        ], group_name="数二")
        svc = AppService()
        svc.add_paths([str(path)])
        bundle = json.loads(svc.build_export())
        self.assertEqual(bundle["type"], "kyn-progress-export")
        self.assertTrue(bundle["progress"])

        export_path = self.tmp / "bundle.json"
        export_path.write_text(svc.build_export(), encoding="utf-8")
        svc2 = AppService()
        svc2.add_paths([str(path)])
        # 先把磁盘上的完成状态清掉
        raw = json.loads(path.read_text(encoding="utf-8"))
        for m in raw["months"]:
            for w in m["weeks"]:
                for d in w["days"]:
                    for t in d["tasks"]:
                        t["done"] = False
                        t["doneAt"] = None
                        t["history"] = []
        support.write_json(path, raw)
        svc3 = AppService()
        svc3.add_paths([str(path)])
        result = svc3.import_progress(str(export_path))
        self.assertTrue(result["ok"])
        self.assertIn("2 条记录", result["message"])
        task = next(t for t in svc3.groups[0].tasks if t.id == "a")
        self.assertTrue(task.done)
        self.assertEqual(task.done_at, T1)


class SessionTest(ServiceCase):
    def test_session_restores_files(self):
        path = self.make_file("math2_checkbox_use.json", [support.task("a", "A", "2026-11-02")], group_name="数二")
        svc = AppService()
        svc.add_paths([str(path)])
        svc.dispatch("to_overview")
        svc.dispatch("open_group", {"path": str(path)})
        restored = AppService()
        self.assertEqual(len(restored.files), 1)
        self.assertEqual(restored.build_view()["page"], 3)
        self.assertEqual(restored.build_view()["groupName"], "数二")


if __name__ == "__main__":
    unittest.main()
