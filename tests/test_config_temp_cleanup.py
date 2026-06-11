import os
import tempfile
import time
import unittest
from pathlib import Path

from config_manager import cleanup_stale_config_temp_files


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


if __name__ == "__main__":
    unittest.main()
