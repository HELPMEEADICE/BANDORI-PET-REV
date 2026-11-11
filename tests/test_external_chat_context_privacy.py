import ast
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from bandori_core.database_manager import DatabaseManager


@pytest.fixture
def database(tmp_path):
    db = DatabaseManager(str(tmp_path / "chat.db"))
    events = [
        ("qq", "shared", "private", "PRIVATE_SAME_ID_SECRET"),
        ("qq", "shared", "", "LEGACY_UNSCOPED_SECRET"),
        ("qq", "shared", "group", "CURRENT_GROUP_MESSAGE"),
        ("qq", "other-group", "group", "OTHER_GROUP_SECRET"),
        ("qq", "private-friend", "private", "PRIVATE_FRIEND_SECRET"),
        ("discord", "shared", "group", "OTHER_PLATFORM_SECRET"),
    ]
    for platform, thread_id, chat_type, text in events:
        db.add_external_chat_message({
            "platform": platform, "thread_id": thread_id, "chat_type": chat_type,
            "text": text, "sender_name": "sender",
        })
    try:
        yield db
    finally:
        db.close()


def test_group_context_excludes_other_threads_platforms_and_private_id_collisions(database):
    context = database.external_chat_context_text(platform="qq", thread_id="shared", chat_type="group")

    assert "CURRENT_GROUP_MESSAGE" in context
    assert "SECRET" not in context


def test_private_context_is_scoped_to_the_current_friend(database):
    context = database.external_chat_context_text(
        platform="qq", thread_id="private-friend", chat_type="private",
    )

    assert "PRIVATE_FRIEND_SECRET" in context
    for text in ("PRIVATE_SAME_ID_SECRET", "OTHER_GROUP_SECRET", "OTHER_PLATFORM_SECRET", "CURRENT_GROUP_MESSAGE"):
        assert text not in context


@pytest.mark.parametrize("scope", [
    {"platform": "qq"},
    {"platform": "qq", "thread_id": "shared"},
    {"platform": "", "thread_id": "shared", "chat_type": "group"},
    {"platform": "qq", "thread_id": "", "chat_type": "group"},
    {"platform": "qq", "thread_id": "shared", "chat_type": "invalid"},
    {"platform": "qq", "thread_id": "missing", "chat_type": "group"},
    {"platform": "qq", "thread_id": "shared", "chat_type": "private"},
])
def test_missing_or_incomplete_scope_never_returns_aggregate_context(database, scope):
    assert database.external_chat_context_text(**scope) == ""


def test_desktop_aggregate_context_remains_available(database):
    context = database.external_chat_context_text(limit_threads=12)

    assert "PRIVATE_FRIEND_SECRET" in context
    assert "OTHER_GROUP_SECRET" in context
    assert "OTHER_PLATFORM_SECRET" in context


@pytest.mark.parametrize("thread_id", ["shared", ""])
def test_napcat_auto_reply_passes_only_current_thread_context_to_llm(database, thread_id):
    # Exercise the actual nested startup callback without launching the desktop.
    source = Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                 and node.name in {"_napcat_generate_reply", "_napcat_chat_type"}]
    config = {"llm_api_url": "https://example.invalid", "llm_api_key": "fake", "llm_model_id": "model"}
    namespace = {
        "cfg": SimpleNamespace(get=config.get),
        "_napcat_reply_character": lambda: "kasumi",
        "chat_integration_ref": {"lock": threading.Lock()},
        "chat_integration_db": lambda: database,
        "app": None,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)

    class PromptCaptured(Exception):
        pass

    worker = Mock(side_effect=PromptCaptured)
    with (
        patch("bandori_llm.llm_manager.build_system_prompt", return_value="system"),
        patch("bandori_llm.llm_manager.NonStreamWorker", worker),
        pytest.raises(PromptCaptured),
    ):
        namespace["_napcat_generate_reply"]({
            "platform": "qq", "thread_id": thread_id, "chat_type": "group", "text": "hello",
        })

    prompt = worker.call_args.args[3][1]["content"]
    assert "SECRET" not in prompt
    assert ("CURRENT_GROUP_MESSAGE" in prompt) == bool(thread_id)
