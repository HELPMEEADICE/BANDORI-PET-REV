import os
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import asr_manager
import tts_manager
from tts_manager import TTSPlayer


class AudioRuntimeSafetyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_tts_does_not_queue_audio_when_output_stream_cannot_start(self):
        player = TTSPlayer()
        soundfile = SimpleNamespace(read=Mock(return_value=(np.ones(20, dtype="float32"), 16000)))

        with (
            patch("tts_manager._soundfile", return_value=soundfile),
            patch("tts_manager._numpy", return_value=np),
            patch.object(player, "_ensure_stream", return_value=False),
        ):
            player.enqueue(b"audio", "wav")

        self.assertTrue(player._queue.empty())
        self.assertTrue(player.is_idle())

    def test_only_protocol_rejections_cache_streaming_incompatibility(self):
        self.assertTrue(tts_manager._streaming_failure_is_incompatible(400))
        self.assertTrue(tts_manager._streaming_failure_is_incompatible(415))
        self.assertFalse(tts_manager._streaming_failure_is_incompatible(500))
        self.assertFalse(tts_manager._streaming_failure_is_incompatible(None))

    def test_cancelled_install_command_does_not_start_process(self):
        cancelled = threading.Event()
        cancelled.set()

        with patch("asr_manager.subprocess.Popen") as popen:
            with self.assertRaises(asr_manager.ASRInstallCancelled):
                asr_manager._run_command(
                    ["python", "-m", "pip"],
                    asr_manager.ASR_LOCAL_SERVER_DIR,
                    cancel_event=cancelled,
                )

        popen.assert_not_called()

    def test_app_started_asr_server_receives_main_process_owner(self):
        process = Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as temp_dir:
            server_dir = Path(temp_dir)
            python = server_dir / "python"
            server = server_dir / "server.py"
            python.touch()
            server.touch()
            with (
                patch.object(asr_manager, "ASR_LOCAL_SERVER_DIR", server_dir),
                patch("asr_manager._local_asr_python", return_value=python),
                patch("asr_manager._is_local_asr_port_open", side_effect=[False, True]),
                patch("asr_manager.subprocess.Popen", return_value=process) as popen,
                patch.dict(os.environ, {"BANDORI_PET_MAIN_PID": "12345"}, clear=False),
            ):
                ready, _message = asr_manager._launch_local_asr_server_locked()

        self.assertTrue(ready)
        self.assertEqual("12345", popen.call_args.kwargs["env"]["ASR_OWNER_PID"])

    def test_existing_external_asr_server_is_never_started_or_owned(self):
        with (
            patch("asr_manager._is_local_asr_port_open", return_value=True),
            patch("asr_manager.subprocess.Popen") as popen,
        ):
            ready, _message = asr_manager._launch_local_asr_server_locked()

        self.assertTrue(ready)
        popen.assert_not_called()

    def test_generated_server_monitors_owner_process(self):
        self.assertIn("ASR_OWNER_PID", asr_manager._LOCAL_ASR_SERVER)
        self.assertIn("_monitor_owner", asr_manager._LOCAL_ASR_SERVER)

    def test_managed_local_asr_is_started_on_demand(self):
        with (
            patch("asr_manager._local_asr_python") as local_python,
            patch("asr_manager.ASR_LOCAL_SERVER_DIR") as server_dir,
            patch("asr_manager._launch_local_asr_server", return_value=(True, "ready")) as launch,
        ):
            local_python.return_value.exists.return_value = True
            (server_dir / "server.py").exists.return_value = True
            asr_manager._ensure_managed_local_asr_running(
                "http://127.0.0.1:8000/v1/audio/transcriptions"
            )

        launch.assert_called_once()

    def test_external_asr_url_is_not_started_or_owned(self):
        with patch("asr_manager._launch_local_asr_server") as launch:
            asr_manager._ensure_managed_local_asr_running(
                "https://speech.example.com/v1/audio/transcriptions"
            )

        launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
