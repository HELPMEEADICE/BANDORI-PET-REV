import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import chat_attachment_manager
import database_manager
from compact_ai_window import CompactAIWindow
from database_manager import DatabaseManager


class DatabaseMemorySafetyTests(unittest.TestCase):
    def test_relationship_zero_values_are_not_replaced_by_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(str(Path(temp_dir) / "data.db"))
            try:
                state = db.upsert_relationship_state(
                    "character",
                    "user",
                    affection=0,
                    trust=0,
                    mood_intensity=0,
                )
            finally:
                db.close()

        self.assertEqual(0, state["affection"])
        self.assertEqual(0, state["trust"])
        self.assertEqual(0, state["mood_intensity"])

    def test_memory_upsert_returns_the_existing_memory_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(str(Path(temp_dir) / "data.db"))
            try:
                first_id = db.add_character_memory(
                    "character", "user", "note", "first"
                )
                second_id = db.add_character_memory(
                    "character", "user", "note", "second"
                )
                repeated_id = db.add_character_memory(
                    "character", "user", "preference", "first", 90
                )
            finally:
                db.close()

        self.assertNotEqual(first_id, second_id)
        self.assertEqual(first_id, repeated_id)

    def test_stale_compact_memory_result_is_not_written_to_new_character(self):
        worker = object()
        harness = SimpleNamespace(
            _memory_generation=2,
            _db=object(),
            _forget_memory_worker=Mock(),
            _apply_relationship_analysis=Mock(),
        )
        fallback = {
            "affection_delta": 0,
            "trust_delta": 0,
            "familiarity_delta": 1,
            "mood": "calm",
            "mood_intensity": 20,
            "reason": "fallback",
        }

        with patch("compact_ai_window.store_extracted_memories") as store:
            CompactAIWindow._on_memory_extraction_finished(
                harness,
                worker,
                "old-character",
                "user",
                '{}',
                1,
                fallback,
                1,
            )

        harness._forget_memory_worker.assert_called_once_with(worker)
        harness._apply_relationship_analysis.assert_not_called()
        store.assert_not_called()

    def test_attachment_directory_uses_application_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            with patch.object(
                chat_attachment_manager,
                "app_data_dir",
                return_value=data_dir,
            ):
                self.assertEqual(
                    data_dir / "chat_attachments",
                    chat_attachment_manager.chat_attachment_dir(),
                )

    def test_posix_database_lock_file_is_persistent(self):
        with patch.object(database_manager.os, "name", "posix"):
            self.assertFalse(database_manager._remove_database_lock_on_close())

    def test_windows_database_lock_file_can_be_cleaned_up(self):
        with patch.object(database_manager.os, "name", "nt"):
            self.assertTrue(database_manager._remove_database_lock_on_close())

    def test_character_aliases_are_loaded_from_the_asset_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asset_dir = root / "assets"
            data_dir = root / "data"
            asset_dir.mkdir()
            data_dir.mkdir()
            (asset_dir / "outfit.json").write_text(
                json.dumps({
                    "characters": {
                        "character": {"display": "Display Name"},
                    },
                }),
                encoding="utf-8",
            )
            DatabaseManager._character_display_aliases.cache_clear()
            with (
                patch.object(database_manager, "LEGACY_BASE_DIR", asset_dir),
                patch.object(database_manager, "BASE_DIR", data_dir),
            ):
                aliases = DatabaseManager._character_display_aliases("character")
            DatabaseManager._character_display_aliases.cache_clear()

        self.assertEqual({"character", "Display Name"}, aliases)


if __name__ == "__main__":
    unittest.main()
