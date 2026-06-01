import logging
import re

from action_bus import publish_lip_sync


_ACTION_TAG_RE = re.compile(r"\[(?:DONE|[A-Za-z0-9_.\-]+)\]")


def strip_tts_action_tags(text: str) -> str:
    return _ACTION_TAG_RE.sub("", str(text or "")).strip()


def clean_tts_payload(text: str, strip_search_sources: bool = False) -> str:
    text = str(text or "")
    if strip_search_sources:
        text = re.sub(r"\{\s*\"(?:web_search_sources|search_sources|sources)\"\s*:\s*\[.*", "", text, flags=re.DOTALL)
    return strip_tts_action_tags(text).strip()


class SingleShotTTSCallbacksMixin:
    def _on_tts_audio_ready(self, sequence: int, generation: int, audio: bytes, media_type: str):
        del sequence
        if generation != self._tts_generation or self.sender() is not self._tts_worker:
            return
        if self._tts_worker is not None and self._tts_player is not None:
            self._tts_player.prepare_lip_sync_text(
                getattr(self._tts_worker, "prepared_text", ""),
                getattr(self._tts_worker, "prepared_language", ""),
            )
            self._tts_player.enqueue(audio, media_type)

    def _on_tts_error(self, error_msg: str):
        logging.getLogger(type(self).__module__).warning("TTS error: %s", error_msg)

    def _on_tts_worker_finished(self):
        if self.sender() is self._tts_worker:
            self._tts_worker = None

    def _on_tts_mouth_pose_changed(self, level: float, form: float):
        if self._tts_playing_character:
            publish_lip_sync(self._tts_playing_character, level, form)

    def _on_tts_playback_finished(self):
        if self._tts_playing_character:
            publish_lip_sync(self._tts_playing_character, 0.0)
        self._tts_playing_character = ""
