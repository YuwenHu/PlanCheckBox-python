import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import progress  # noqa: E402
from app.core.parser import build  # noqa: E402
from tests import support  # noqa: E402

T1 = "2026-11-05T09:10:00+08:00"
T2 = "2026-11-05T10:20:00+08:00"


def make_group(tasks, file_name="math2_checkbox_use.json", **kwargs):
    raw = support.bank_json(tasks, **kwargs)
    result = build(raw, file_name, "数二", f"/tmp/{file_name}")
    assert result.ok and result.group is not None, result.error
    return raw, result.group


def record(title, done=True, done_at=T1):
    return {"title": title, "done": done, "doneAt": done_at,
            "history": [{"action": "done", "at": done_at}] if done and done_at else []}


class FingerprintTest(unittest.TestCase):
    def test_progress_path_is_sibling(self):
        self.assertEqual(progress.progress_path(r"C:\x\math2_checkbox_use.json").name,
                         "math2_checkbox_use_progress.json")
        self.assertEqual(progress.progress_path("/a/b.json").parent.name, "a")

    def test_stable_across_formatting_and_equal_keys(self):
        raw, group = make_group([support.task("t1", "行列式", "2026-11-02")])
        first = progress.fingerprint(raw, group)
        clone = json.loads(json.dumps(raw, ensure_ascii=False, indent=4))
        self.assertEqual(progress.fingerprint(clone, group), first)
        self.assertEqual(set(first), {"hash", "taskCount", "generatedAt", "formatVersion"})
        self.assertEqual(first["taskCount"], 1)
        self.assertEqual(first["generatedAt"], "2026-11-04T16:00:00+08:00")
        self.assertEqual(first["formatVersion"], 1)
        self.assertEqual(len(first["hash"]), 64)

    def test_content_change_changes_hash(self):
        raw1, group1 = make_group([support.task("t1", "行列式", "2026-11-02")])
        raw2, group2 = make_group([support.task("t1", "行列式（改）", "2026-11-02")])
        self.assertNotEqual(progress.fingerprint(raw1, group1)["hash"],
                            progress.fingerprint(raw2, group2)["hash"])

    def test_same_source_ignores_file_note_only(self):
        raw, group = make_group([support.task("t1", "行列式", "2026-11-02")])
        fp = progress.fingerprint(raw, group)
        self.assertTrue(progress.same_source(fp, dict(fp, file="renamed.json")))
        self.assertFalse(progress.same_source(fp, dict(fp, taskCount=2)))
        self.assertFalse(progress.same_source(fp, None))


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.raw, self.group = make_group([
            support.task("t1", "行列式", "2026-11-02"),
            support.task("t2", "矩阵", "2026-11-03"),
        ])
        self.fp = progress.fingerprint(self.raw, self.group)

    def test_same_source_merges_directly(self):
        doc = progress.empty_doc(self.fp, "math2_checkbox_use.json")
        doc["tasks"]["t1"] = record("行列式")
        new_doc, report = progress.resolve(doc, self.group, self.fp)
        self.assertTrue(report.same_source)
        self.assertEqual(report.message, "")
        self.assertTrue(new_doc["tasks"]["t1"]["done"])
        progress.apply(self.group, new_doc)
        self.assertTrue(next(t for t in self.group.tasks if t.id == "t1").done)
        self.assertFalse(next(t for t in self.group.tasks if t.id == "t2").done)

    def test_cross_source_migrates_by_id(self):
        raw2, group2 = make_group([
            support.task("t1", "行列式", "2026-11-02"),
            support.task("t2", "矩阵", "2026-11-03"),
        ], meta_extra={"generatedAt": "2026-12-01T00:00:00+08:00"})
        fp2 = progress.fingerprint(raw2, group2)
        self.assertFalse(progress.same_source(self.fp, fp2))
        doc = progress.empty_doc(self.fp, "math2_checkbox_use.json")
        doc["tasks"]["t1"] = record("行列式")
        new_doc, report = progress.resolve(doc, group2, fp2)
        self.assertFalse(report.same_source)
        self.assertEqual(report.by_id, 1)
        self.assertEqual(report.by_title, 0)
        self.assertIn("题库已更新", report.message)
        self.assertIn("id 匹配 1 条", report.message)
        self.assertTrue(new_doc["tasks"]["t1"]["done"])

    def test_cross_source_migrates_by_title_when_ids_change(self):
        raw2, group2 = make_group([
            support.task("x1", "行列式", "2026-11-02"),
            support.task("x2", "矩阵", "2026-11-03"),
        ])
        fp2 = progress.fingerprint(raw2, group2)
        doc = progress.empty_doc(self.fp, "math2_checkbox_use.json")
        doc["tasks"]["t1"] = record("行列式")
        new_doc, report = progress.resolve(doc, group2, fp2)
        self.assertEqual(report.by_title, 1)
        self.assertEqual(report.kept_unmatched, 0)
        self.assertTrue(new_doc["tasks"]["x1"]["done"])
        self.assertEqual(new_doc["unmatched"], {})
        self.assertIn("标题匹配 1 条", report.message)

    def test_id_wins_when_old_record_has_no_title(self):
        raw2, group2 = make_group([support.task("t1", "换了个名字", "2026-11-02")])
        fp2 = progress.fingerprint(raw2, group2)
        doc = progress.empty_doc(self.fp, "math2_checkbox_use.json")
        doc["tasks"]["t1"] = {"done": True, "doneAt": T1, "history": []}
        new_doc, report = progress.resolve(doc, group2, fp2)
        self.assertEqual(report.by_id, 1)
        self.assertEqual(new_doc["tasks"]["t1"]["title"], "换了个名字")

    def test_retitled_id_falls_back_to_id(self):
        raw2, group2 = make_group([support.task("t1", "改名后的任务", "2026-11-02")])
        fp2 = progress.fingerprint(raw2, group2)
        doc = progress.empty_doc(self.fp, "math2_checkbox_use.json")
        doc["tasks"]["t1"] = record("行列式")
        new_doc, report = progress.resolve(doc, group2, fp2)
        self.assertEqual(report.id_retitled, 1)
        self.assertEqual(report.by_title, 0)
        self.assertIn("标题已变", report.message)
        self.assertTrue(new_doc["tasks"]["t1"]["done"])

    def test_unmatched_records_are_preserved(self):
        raw2, group2 = make_group([support.task("t2", "矩阵", "2026-11-03")])
        fp2 = progress.fingerprint(raw2, group2)
        doc = progress.empty_doc(self.fp, "math2_checkbox_use.json")
        doc["tasks"]["t1"] = record("已被删掉的任务")
        new_doc, report = progress.resolve(doc, group2, fp2)
        self.assertEqual(report.kept_unmatched, 1)
        self.assertNotIn("t1", new_doc["tasks"])
        kept = new_doc["unmatched"]["task:t1"]
        self.assertTrue(kept["done"])
        self.assertIn("旧 id：t1", kept["note"])
        self.assertIn("unmatched", report.message)

    def test_existing_unmatched_survives_next_migration(self):
        doc = progress.empty_doc(self.fp, "math2_checkbox_use.json")
        doc["unmatched"]["task:gone"] = {"title": "很久以前", "done": True,
                                         "doneAt": T1, "history": []}
        new_doc, _ = progress.resolve(doc, self.group, self.fp)
        self.assertIn("task:gone", new_doc["unmatched"])

    def test_apply_clears_tasks_without_record(self):
        self.group.tasks[0].done = True
        self.group.tasks[0].done_at = T1
        progress.apply(self.group, progress.empty_doc(self.fp, "x.json"))
        self.assertFalse(self.group.tasks[0].done)
        self.assertIsNone(self.group.tasks[0].done_at)


class FileIoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.bank = self.tmp / "math2_checkbox_use.json"
        self.bank.write_text("{}", encoding="utf-8")
        raw, group = make_group([support.task("t1", "行列式", "2026-11-02")])
        self.fp = progress.fingerprint(raw, group)

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_then_read_roundtrip(self):
        doc = progress.empty_doc(self.fp, self.bank.name)
        progress.set_record(doc, "t1", "行列式", True, T1, [{"action": "done", "at": T1}])
        doc["updatedAt"] = T2
        progress.write(str(self.bank), doc)
        path = progress.progress_path(self.bank)
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["format"], "plancheckbox-progress")
        self.assertEqual(data["updatedAt"], T2)
        self.assertEqual(data["source"]["hash"], self.fp["hash"])
        loaded = progress.read(path)
        self.assertTrue(loaded["tasks"]["t1"]["done"])
        self.assertEqual(loaded["tasks"]["t1"]["doneAt"], T1)

    def test_missing_file_returns_none(self):
        self.assertIsNone(progress.read(self.tmp / "nope_progress.json"))

    def test_corrupt_file_raises_instead_of_overwriting(self):
        path = progress.progress_path(self.bank)
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(progress.ProgressError):
            progress.read(path)
        self.assertEqual(path.read_text(encoding="utf-8"), "{not json")

    def test_foreign_json_raises(self):
        path = progress.progress_path(self.bank)
        path.write_text('{"hello": 1}', encoding="utf-8")
        with self.assertRaises(progress.ProgressError):
            progress.read(path)

    def test_set_record_drops_empty_state(self):
        doc = progress.empty_doc(self.fp, self.bank.name)
        progress.set_record(doc, "t1", "行列式", True, T1, [{"action": "done", "at": T1}])
        self.assertIn("t1", doc["tasks"])
        progress.set_record(doc, "t1", "行列式", False, None, [])
        self.assertNotIn("t1", doc["tasks"])


if __name__ == "__main__":
    unittest.main()
