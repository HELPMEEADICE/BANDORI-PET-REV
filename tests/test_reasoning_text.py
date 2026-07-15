from llm_thinking import split_thinking_text
from vision_fallback import _strip_thinking_text


def test_closed_reasoning_tags_are_removed_from_visible_text():
    visible, reasoning = split_thinking_text(
        "<thinking>内部推理</thinking>该休息一下啦。"
    )

    assert visible == "该休息一下啦。"
    assert reasoning == "内部推理"


def test_reasoning_tag_variants_and_attributes_are_supported():
    visible, reasoning = split_thinking_text(
        '<ANALYSIS type="private">先判断场景</ANALYSIS>[smile]继续加油。',
        "接口独立推理",
    )

    assert visible == "[smile]继续加油。"
    assert reasoning == "接口独立推理\n\n先判断场景"


def test_unclosed_reasoning_tail_is_never_exposed_as_visible_text():
    visible, reasoning = split_thinking_text(
        "安全前缀<thinking>未闭合的内部推理\n可能还包含结论"
    )

    assert visible == "安全前缀"
    assert "未闭合的内部推理" in reasoning


def test_orphan_reasoning_close_tag_hides_preceding_internal_text():
    visible, reasoning = split_thinking_text(
        "内部推理内容</thinking>[smile]这是给用户的回答。"
    )

    assert visible == "[smile]这是给用户的回答。"
    assert reasoning == "内部推理内容"


def test_orphan_reasoning_close_tag_preserves_existing_reasoning():
    visible, reasoning = split_thinking_text(
        "补充内部推理</ANALYSIS>继续加油。",
        "接口独立推理",
    )

    assert visible == "继续加油。"
    assert reasoning == "接口独立推理\n\n补充内部推理"


def test_aux_vision_uses_the_same_reasoning_filter():
    assert _strip_thinking_text(
        "<thinking>识别截图细节</thinking>用户正在编辑代码。"
    ) == "用户正在编辑代码。"
