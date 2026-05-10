import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from qq_valhalla.exporter import export_run_files, format_archive_time, prune_export_files, write_error_marker
from qq_valhalla.storage import ArchiveStore


class ExporterTests(unittest.TestCase):
    def test_export_run_files(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = ArchiveStore(root / "test.sqlite3")
            try:
                run_id = store.create_run("snapshot", {"group_ids": ["100"]})
                store.upsert_groups([{"gc": 100, "gn": "测试群"}])
                store.save_member_page(run_id=run_id, group_id="100", members=[{"uin": 123, "nick": "成员"}])
                store.finish_run(run_id, "ok", metadata={"group_ids": ["100"]})
                store.conn.execute(
                    "UPDATE archive_runs SET started_at=?, finished_at=? WHERE id=?",
                    ("2026-05-10T09:29:58+00:00", "2026-05-10T09:30:00+00:00", run_id),
                )
                store.conn.commit()

                exported = export_run_files(store, root / "archive", run_id)
                payload = json.loads(exported["structured_json"].read_text(encoding="utf-8"))
                dashboard = exported["dashboard"].read_text(encoding="utf-8")

                self.assertTrue(exported["dashboard"].exists())
                self.assertEqual(payload["run"]["finished_at"], "2026-05-10T09:30:00+00:00")
                self.assertEqual(payload["latest_archive_time"], "2026-05-10T17:30:00+08:00")
                self.assertIn("2026-05-10T17:30:00+08:00", dashboard)
                self.assertEqual(payload["groups"][0]["group_id"], "100")
                self.assertEqual(payload["groups"][0]["members"][0]["uin"], "123")
            finally:
                store.close()

    def test_format_archive_time_uses_utc_plus_eight(self):
        self.assertEqual(format_archive_time("2026-05-10T00:00:00+00:00"), "2026-05-10T08:00:00+08:00")
        self.assertEqual(format_archive_time("2026-05-10T00:00:00Z"), "2026-05-10T08:00:00+08:00")
        self.assertEqual(format_archive_time("2026-05-10T00:00:00"), "2026-05-10T08:00:00+08:00")
        self.assertEqual(format_archive_time(""), "")
        self.assertEqual(format_archive_time("invalid"), "invalid")

    def test_prune_export_files_keeps_latest_five_runs(self):
        with TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "archive" / "2026-05-10"
            archive.mkdir(parents=True)
            for run_id in range(1, 8):
                (archive / f"run_{run_id}.jsonl").write_text("{}", encoding="utf-8")
                (archive / f"run_{run_id}.structured.json").write_text("{}", encoding="utf-8")

            prune_export_files(Path(temp_dir) / "archive", keep=5)

            remaining = sorted(path.name for path in archive.glob("run_*.*"))
            self.assertNotIn("run_1.jsonl", remaining)
            self.assertNotIn("run_2.structured.json", remaining)
            self.assertIn("run_7.jsonl", remaining)
            self.assertEqual(len({name.split(".")[0] for name in remaining}), 5)

    def test_write_error_marker(self):
        with TemporaryDirectory() as temp_dir:
            marker = write_error_marker(
                Path(temp_dir) / "archive",
                run_id=9,
                error="cookie 失效",
                metadata={"a": 1},
                raw_responses=[],
            )
            payload = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["error"], "cookie 失效")
