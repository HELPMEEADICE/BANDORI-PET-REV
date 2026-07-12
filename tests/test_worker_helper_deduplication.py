from types import SimpleNamespace

from llm_manager import _auto_continue_limit, _prefetch_web_search_context
from tts_manager import _CancelableTTSWorker, TTSRequestWorker, TTSTranslationWorker


def test_stream_workers_share_auto_continue_and_prefetch_helpers():
    assert _auto_continue_limit({}) == 0
    assert _auto_continue_limit({"llm_auto_continue_enabled": True, "llm_auto_continue_max_turns": 99}) == 20
    assert _auto_continue_limit({"llm_auto_continue_enabled": True, "llm_auto_continue_max_turns": "bad"}) == 5
    assert _prefetch_web_search_context({"_latest_user_text": "latest news"}) == ""


def test_tts_workers_inherit_one_translation_decision():
    enabled = SimpleNamespace(_config={"tts_translate_to_selected_language": True})
    disabled = SimpleNamespace(_config={"tts_translate_to_selected_language": False})

    assert _CancelableTTSWorker._should_translate(enabled, "Japanese")
    assert not _CancelableTTSWorker._should_translate(enabled, "Chinese")
    assert not _CancelableTTSWorker._should_translate(disabled, "Japanese")
    assert "_should_translate" not in TTSTranslationWorker.__dict__
    assert "_should_translate" not in TTSRequestWorker.__dict__
