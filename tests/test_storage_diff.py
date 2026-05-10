import unittest

from qq_valhalla.storage import ArchiveStore


class StorageDiffTests(unittest.TestCase):
    def test_member_events_lifecycle(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as temp_dir:
            store = ArchiveStore(Path(temp_dir) / "test.sqlite3")
            try:
                run1 = store.create_run("test")
                stats1 = store.save_member_page(run_id=run1, group_id="100", members=[{"uin": 1, "nick": "A"}])
                self.assertEqual(stats1.inserted, 1)
                self.assertEqual(stats1.changed, 0)
                self.assertEqual(store.mark_missing_members(run_id=run1, group_id="100", seen_uins={"1"}), 0)

                run2 = store.create_run("test")
                stats2 = store.save_member_page(run_id=run2, group_id="100", members=[{"uin": 1, "nick": "B"}])
                self.assertEqual(stats2.inserted, 0)
                self.assertEqual(stats2.changed, 1)

                run3 = store.create_run("test")
                self.assertEqual(store.mark_missing_members(run_id=run3, group_id="100", seen_uins=set()), 1)
            finally:
                store.close()
