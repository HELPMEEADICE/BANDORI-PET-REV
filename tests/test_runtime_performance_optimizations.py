from pathlib import Path
import os

from token_usage import (
    estimate_messages_tokens,
    estimate_text_tokens,
    estimate_untracked_history_usage,
    estimate_value_tokens,
)


def _legacy_untracked_usage(messages, *, input_overhead, history_limit):
    input_tokens = 0
    output_tokens = 0
    request_count = 0
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        trace = message.get("tool_trace") or {}
        if isinstance(trace.get("llm_usage"), dict):
            continue
        preceding = (
            messages[:index]
            if history_limit == 0
            else messages[max(0, index - max(1, history_limit)):index]
        )
        request_messages = [
            {"role": item.get("role", ""), "content": item.get("content", "")}
            for item in preceding
        ]
        input_tokens += input_overhead + estimate_messages_tokens(request_messages)
        output_tokens += estimate_value_tokens(message.get("content", ""))
        output_tokens += estimate_text_tokens(message.get("reasoning_content", ""))
        request_count += 1
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "estimated": request_count > 0,
        "request_count": request_count,
    }


def test_linear_token_usage_estimator_preserves_legacy_results():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "你好 world"},
        {"role": "assistant", "content": "first", "reasoning_content": "r1"},
        {"role": "user", "content": [{"type": "text", "text": "image"}]},
        {
            "role": "assistant",
            "content": "tracked",
            "tool_trace": {"llm_usage": {"input_tokens": 10}},
        },
        {"role": "assistant", "content": "last", "reasoning_content": "r2"},
    ]
    for history_limit in (0, 2, 5):
        expected = _legacy_untracked_usage(
            messages,
            input_overhead=17,
            history_limit=history_limit,
        )
        assert estimate_untracked_history_usage(
            messages,
            input_overhead=17,
            history_limit=history_limit,
        ) == expected


def test_pixel_renderer_keeps_only_one_uncompressed_sprite_backing_store():
    source = Path("pixel_pet_widget.py").read_text(encoding="utf-8")

    assert "self._sheet = QPixmap()" not in source
    assert "pixmap.toImage()" not in source
    assert "painter.drawImage(self.rect(), self._sheet_image, source)" in source


def test_pixel_sprite_memory_can_be_released_while_inactive():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from pixel_pet_widget import PixelPetWidget, load_pixel_frames

    app = QApplication.instance() or QApplication([])
    widget = PixelPetWidget()
    assert widget.load_sprite("pixels/arisa.webp", load_pixel_frames())
    assert not widget._sheet_image.isNull()
    assert widget._sheet_image.sizeInBytes() > 10 * 1024 * 1024

    widget.release_sprite()

    assert widget._sheet_image.isNull()
    assert widget._frames == {}
    assert not widget._anim_timer.isActive()
    assert not widget._wander_timer.isActive()
    widget.close()
    app.processEvents()
