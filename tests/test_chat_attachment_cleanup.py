import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chat_attachment_manager import cleanup_chat_attachments


class ChatAttachmentCleanupTest(unittest.TestCase):
    def test_missing_file_references_are_sanitized_without_new_deletions(self):
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("database_manager.sanitize_chat_attachment_references", return_value=2) as sanitize,
        ):
            result = cleanup_chat_attachments(directory=Path(temp_dir))

        sanitize.assert_called_once()
        self.assertEqual(0, result["deleted_files"])
        self.assertEqual(2, result["removed_references"])

    def test_database_sanitization_can_be_disabled(self):
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("database_manager.sanitize_chat_attachment_references") as sanitize,
        ):
            cleanup_chat_attachments(
                directory=Path(temp_dir),
                sanitize_database=False,
            )

        sanitize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
