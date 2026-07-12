import os
import tempfile
import time
import unittest
from pathlib import Path

from config_manager import ConfigManager, _config_file_lock, cleanup_stale_config_temp_files
from database_manager import DatabaseManager


class ConfigTempCleanupTest(unittest.TestCase):
    def test_cleanup_removes_only_old_matching_temp_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.json"
            old_tmp = root / "config.json.old.tmp"
            fresh_tmp = root / "config.json.fresh.tmp"
            non_matching = root / "config.json.old.bak"
            lock_file = root / "config.json.lock"

            for path in (config_path, old_tmp, fresh_tmp, non_matching, lock_file):
                path.write_text("{}", encoding="utf-8")

            old_time = time.time() - 48 * 60 * 60
            os.utime(old_tmp, (old_time, old_time))

            removed = cleanup_stale_config_temp_files(config_path, max_age_seconds=24 * 60 * 60)

            self.assertEqual(1, removed)
            self.assertFalse(old_tmp.exists())
            self.assertTrue(fresh_tmp.exists())
            self.assertTrue(non_matching.exists())
            self.assertTrue(lock_file.exists())
            self.assertTrue(config_path.exists())

    def test_config_file_lock_marker_persists_after_release(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            with _config_file_lock(config_path):
                self.assertTrue(Path(str(config_path) + ".lock").exists())

            self.assertTrue(Path(str(config_path) + ".lock").exists())

    def test_config_file_lock_marker_persists_when_protected_operation_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            lock_path = Path(str(config_path) + ".lock")

            with self.assertRaisesRegex(OSError, "write failed"):
                with _config_file_lock(config_path):
                    self.assertTrue(lock_path.exists())
                    raise OSError("write failed")

            self.assertTrue(lock_path.exists())

    def test_flush_save_does_not_remove_other_process_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            runtime_tmp = Path(temp_dir) / "config.json.x14ibzhp.tmp"
            lock_file = Path(temp_dir) / "config.json.lock"
            runtime_tmp.write_text("{}", encoding="utf-8")
            lock_file.write_text("", encoding="utf-8")

            config = ConfigManager(config_path)
            config.flush_save()

            self.assertTrue(runtime_tmp.exists())
            self.assertTrue(lock_file.exists())

    def test_database_lock_is_removed_after_close(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "data.db"

            db = DatabaseManager(str(db_path))
            db.close()

            lock_exists = Path(str(db_path) + ".lock").exists()
            if os.name == "nt":
                self.assertFalse(lock_exists)
            else:
                self.assertTrue(lock_exists)


if __name__ == "__main__":
    unittest.main()
