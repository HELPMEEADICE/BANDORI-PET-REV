"""Export Python-owned compatibility contracts consumed by the Rust port."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "rust" / "compat"


def rendered_contracts() -> dict[Path, str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from config_manager import DEFAULTS
    from ipc_bus import is_control_ipc_line, is_reliable_ipc_line
    from llm_api_compat import (
        chat_completions_api_url,
        models_api_url,
        responses_api_url,
        supports_openai_responses_api,
    )
    from llm_manager import (
        CHARACTER_PROMPTS,
        COMMON_RULES,
        _CORE_TAGS,
        _MOC3_ACTION_TAGS,
        _build_key_to_name_mapping,
        build_system_prompt,
        parse_action_tags,
        strip_action_tags,
    )
    from local_tools import CHAT_COMPLETIONS_POKE_USER_TOOL, poke_user_system_hint
    from relationship_memory import (
        MEMORY_EXTRACTOR_SYSTEM_PROMPT,
        analyze_interaction,
        build_memory_extraction_messages,
        build_relationship_context,
        parse_memory_extraction_response,
        parse_memory_supersede_response,
        parse_relationship_analysis_response,
    )
    from model_manager import ModelManager
    from shared_memory_ipc import (
        _HEADER,
        _MAGIC,
        _SLOT_HEADER,
        _VERSION,
        coalesce_latest_peer_positions,
        encode_ipc_envelope,
        make_shared_memory_key,
    )

    database_contract = _database_contract()
    database_vectors = _database_behavior_contract()

    llm_endpoint_inputs = [
        "",
        "https://api.openai.com/v1",
        "https://api.openai.com/v1/chat/completions",
        "https://api.openai.com/v1/responses?tenant=1",
        "https://openrouter.ai/api/v1",
        "https://generativelanguage.googleapis.com/v1beta/models?key=test",
    ]
    llm_protocol_vectors = {
        "endpoints": [
            {
                "input": value,
                "chat_completions": chat_completions_api_url(value),
                "responses": responses_api_url(value),
                "models": models_api_url(value),
                "supports_responses": supports_openai_responses_api(value),
            }
            for value in llm_endpoint_inputs
        ]
    }

    prompt_cases = [
        {
            "name": "known_default",
            "character": "ran",
            "config": {},
        },
        {
            "name": "custom_system_and_user_pov",
            "character": "ran",
            "config": {
                "llm_custom_system_prompt_enabled": True,
                "llm_custom_system_prompt": "Always answer with concise warmth.",
                "user_name": "Alice",
                "pov_mode": "custom",
                "pov_custom_prompt": "The user is visiting the live house.",
            },
        },
        {
            "name": "moc3_and_outfit",
            "character": "ran",
            "config": {
                "character": "ran",
                "costume": "stage",
                "models": [
                    {
                        "character": "ran",
                        "costume": "stage",
                        "path": "models/ran/stage.model3.json",
                        "format": "moc3",
                    }
                ],
                "llm_live2d_outfit_recognition_enabled": True,
                "outfit_descriptions": {
                    "ran\\tstage": {
                        "character": "ran",
                        "costume": "stage",
                        "costume_name": "Stage outfit",
                        "description": "A black jacket with red accents.",
                    }
                },
            },
        },
        {
            "name": "unknown_active_persona",
            "character": "guest",
            "config": {
                "character_persona_presets": {
                    "guest": [
                        {
                            "id": "persona-1",
                            "title": "Guest persona",
                            "prompt": "You are an original guest guitarist.",
                        }
                    ]
                },
                "character_persona_active": {"guest": "persona-1"},
            },
        },
        {
            "name": "known_role_pov",
            "character": "ran",
            "config": {
                "pov_mode": "role",
                "pov_role_character": "moca",
            },
        },
    ]
    with (
        patch("llm_manager._build_event_context", return_value=""),
        patch("llm_manager._get_character_md_prompt", return_value=""),
    ):
        for case in prompt_cases:
            case["expected"] = build_system_prompt(
                case["character"], case["config"]
            )
    with patch("relationship_memory._tr", side_effect=_contract_translation):
        relationship_cases = _relationship_prompt_cases(
            build_relationship_context
        )
    chat_prompt_vectors = {
        "core_tags": _CORE_TAGS,
        "moc3_action_tags": _MOC3_ACTION_TAGS,
        "common_rules": COMMON_RULES,
        "character_prompts": CHARACTER_PROMPTS,
        "character_display_names": _build_key_to_name_mapping(),
        "cases": prompt_cases,
        "relationship_cases": relationship_cases,
        "action_cases": [
            {
                "input": source,
                "actions": parse_action_tags(source),
                "stripped": strip_action_tags(source),
            }
            for source in (
                "[smile]你好[smile][DONE]",
                "keep [not valid] [mtn_01.idle-2]",
                "[Smile][smile]mixed case",
                "partial [mtn_",
                "nested [bad[smile] tail",
            )
        ],
        "interaction_cases": [
            {
                "user_text": user_text,
                "actions": actions,
                "expected": analyze_interaction(user_text, actions=actions),
            }
            for user_text, actions in (
                ("谢谢你，最喜欢你了", []),
                ("今天好累，压力很大", []),
                ("讨厌你，对不起", []),
                ("", ["angry"]),
                ("普通的一天", ["smile"]),
            )
        ],
        "memory_extraction": _memory_extraction_contract(
            MEMORY_EXTRACTOR_SYSTEM_PROMPT,
            build_memory_extraction_messages,
            parse_relationship_analysis_response,
            parse_memory_extraction_response,
            parse_memory_supersede_response,
        ),
        "cross_chat_history": _cross_chat_history_contract(),
        "group_chat": _group_chat_contract(),
        "chat_tools": {
            "poke_user": CHAT_COMPLETIONS_POKE_USER_TOOL,
            "poke_user_system_hint": poke_user_system_hint(),
        },
    }

    key_cases = [
        ["bandori-main-123", "main-in"],
        ["会话 1", "main-out"],
        ["", "radial:cmd"],
    ]
    envelope_fields = {
        "sender_id": "pet-1",
        "line": 'SETTINGS\t{"语言":"中文"}\r\n',
        "exclude_peer_id": "pet-2",
        "message_id": "m-1",
        "reliable": True,
    }
    classification_lines = [
        "SHUTDOWN",
        "SETTINGS\t{}",
        "CHAT_EVENT\t{}",
        "PET_STATE\t{}",
        "OPEN_CHAT_NATIVE\t{}",
        "PEER_POS\t{}",
        "HEARTBEAT\tpet-1",
    ]
    coalesce_input = [
        'PEER_POS\t{"character":"Ran","x":1}',
        "CHAT_EVENT\t{}",
        'PEER_POS\t{"character":"Ran","x":2}',
    ]

    slot_count = 2
    slot_size = 32
    queue = bytearray(_HEADER.size + slot_count * (_SLOT_HEADER.size + slot_size))
    _HEADER.pack_into(queue, 0, _MAGIC, _VERSION, slot_count, slot_size, 0)
    for sequence, payload in enumerate((b"alpha", "中文".encode("utf-8"))):
        slot_index = sequence % slot_count
        offset = _HEADER.size + slot_index * (_SLOT_HEADER.size + slot_size)
        _SLOT_HEADER.pack_into(queue, offset, sequence, len(payload))
        start = offset + _SLOT_HEADER.size
        queue[start : start + len(payload)] = payload
        _HEADER.pack_into(queue, 0, _MAGIC, _VERSION, slot_count, slot_size, sequence + 1)

    ipc_vectors = {
        "keys": [
            {"parts": parts, "expected": make_shared_memory_key(*parts)}
            for parts in key_cases
        ],
        "envelope": {
            "fields": envelope_fields,
            "expected": encode_ipc_envelope(**envelope_fields),
        },
        "classification": [
            {
                "line": line,
                "control": is_control_ipc_line(line),
                "reliable": is_reliable_ipc_line(line),
            }
            for line in classification_lines
        ],
        "coalesce": {
            "input": coalesce_input,
            "expected": coalesce_latest_peer_positions(coalesce_input),
        },
        "queue_layout": {
            "slot_count": slot_count,
            "slot_size": slot_size,
            "messages": ["alpha", "中文"],
            "expected_hex": queue.hex(),
        },
    }

    model_cases = [
        {
            "name": "moc2",
            "manifest": "model.json",
            "data": {
                "model": "base.moc",
                "motions": {"idle": [], "tap": []},
                "expressions": [{"name": "smile"}, {"name": "angry"}],
            },
        },
        {
            "name": "moc3",
            "manifest": "test.model3.json",
            "data": {
                "Version": 3,
                "FileReferences": {
                    "Moc": "test.moc3",
                    "Motions": {"smile": [], "angry": []},
                    "Expressions": [{"Name": "smile"}, {"Name": "angry"}],
                },
            },
        },
    ]
    with tempfile.TemporaryDirectory() as temp_dir:
        manager = ModelManager(scan_models=False)
        for case in model_cases:
            path = Path(temp_dir) / case["manifest"]
            path.write_text(json.dumps(case["data"]), encoding="utf-8")
            manager._model_paths[("fixture", case["name"])] = str(path)
            case["expected_format"] = manager.get_model_format("fixture", case["name"])
            case["expected_motions"] = manager.get_motion_names("fixture", case["name"])
            case["expected_expressions"] = manager.get_expression_names(
                "fixture", case["name"]
            )

    return {
        OUTPUT_DIR / "config_defaults.json": json.dumps(
            DEFAULTS, ensure_ascii=False, indent=2
        )
        + "\n",
        OUTPUT_DIR / "ipc_vectors.json": json.dumps(
            ipc_vectors, ensure_ascii=False, indent=2
        )
        + "\n",
        OUTPUT_DIR / "model_vectors.json": json.dumps(
            {"cases": model_cases}, ensure_ascii=False, indent=2
        )
        + "\n",
        OUTPUT_DIR / "llm_protocol_vectors.json": json.dumps(
            llm_protocol_vectors, ensure_ascii=False, indent=2
        )
        + "\n",
        OUTPUT_DIR / "chat_prompt_vectors.json": json.dumps(
            chat_prompt_vectors, ensure_ascii=False, indent=2
        )
        + "\n",
        OUTPUT_DIR / "database_schema.json": json.dumps(
            database_contract, ensure_ascii=False, indent=2
        )
        + "\n",
        OUTPUT_DIR / "database_vectors.json": json.dumps(
            database_vectors, ensure_ascii=False, indent=2
        )
        + "\n",
    }


def _contract_translation(_key: str, default: str = "", **kwargs) -> str:
    return str(default).format(**kwargs)


def _memory_extraction_contract(
    system_prompt,
    build_messages,
    parse_relationship,
    parse_memories,
    parse_outdated,
) -> dict:
    message_inputs = [
        {
            "name": "empty_context",
            "user_text": "  今天只是随便聊聊。  ",
            "assistant_text": "",
            "existing_memories": [],
            "global_memories": [],
            "character_name": "",
        },
        {
            "name": "saved_context_and_long_reply",
            "user_text": "以后叫我 小K，之前那个称呼不用了。",
            "assistant_text": "明白了。\n" + "好" * 1210,
            "existing_memories": [
                {"content": " 和用户约好  周末一起看演唱会 "},
                {"content": "用户称角色为小兰"},
            ],
            "global_memories": [
                {"content": "希望被称呼为旧名字"},
                {"content": " 最喜欢的乐队是 MyGO "},
            ],
            "character_name": "美竹兰",
        },
    ]
    for case in message_inputs:
        case["expected"] = build_messages(
            case["user_text"],
            case["assistant_text"],
            case["existing_memories"],
            global_memories=case["global_memories"],
            character_name=case["character_name"],
        )

    response_sources = [
        (
            "wrapped_valid",
            "prefix ```json\n"
            '{"relationship":{"affection_delta":9,"trust_delta":-9,'
            '"familiarity_delta":2,"mood":"happy","mood_intensity":120,'
            '"reason":"  用户  分享了喜好。  "},"memories":['
            '{"scope":"global","kind":"preference","content":"  最喜欢  MyGO。  ","importance":999},'
            '{"scope":"char","kind":"relationship","content":"周末一起看直播","importance":65},'
            '{"scope":"char","kind":"relationship","content":"周末一起看直播","importance":1},'
            '{"scope":"unknown","kind":"mystery","content":"一条足够长的记录","importance":"bad"}],'
            '"outdated":["希望被称呼为 旧名字",{"content":"最喜欢的乐队是 MyGO"},"希望被称呼为旧名字"]}'
            " trailing",
        ),
        (
            "defaults_and_aliases",
            '{"relationship":{"affection_delta":"bad","mood":"unknown","reason":" 。 "},'
            '"memories":[{"kind":"profile","content":"  居住在 东京  "},'
            '{"content":"ab"},{"kind":"favorite","content":"收藏语句：永远不要放弃","importance":90}],'
            '"superseded":["  旧地址：大阪  ","旧 地址：大阪"]}',
        ),
        (
            "remove_alias_without_relationship",
            '{"memories":[],"remove":[{"content":"旧昵称是A"}],"relationship":null}',
        ),
        ("invalid", "not json at all"),
    ]
    response_cases = []
    for name, source in response_sources:
        response_cases.append(
            {
                "name": name,
                "source": source,
                "relationship": parse_relationship(source),
                "memories": parse_memories(source),
                "outdated": parse_outdated(source),
            }
        )
    return {
        "system_prompt": system_prompt,
        "message_cases": message_inputs,
        "response_cases": response_cases,
    }


def _cross_chat_history_contract() -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        from chat_window.chat_window import ChatWindow
    from database_manager import DatabaseManager

    class FixtureModelManager:
        characters = ["ran", "moca", "kasumi", "arisa"]
        names = {
            "ran": "美竹兰",
            "moca": "青叶摩卡",
            "kasumi": "户山香澄",
            "arisa": "市谷有咲",
        }

        def get_display_name(self, character: str) -> str:
            return self.names.get(character, character)

    class Harness:
        _normalize_group_characters = ChatWindow._normalize_group_characters
        _characters_for_group_key = ChatWindow._characters_for_group_key
        _compact_history_text = staticmethod(ChatWindow._compact_history_text)
        _split_group_history_message = ChatWindow._split_group_history_message
        _append_unified_history_item = ChatWindow._append_unified_history_item
        _history_time_label = staticmethod(ChatWindow._history_time_label)
        _history_user_label = ChatWindow._history_user_label

    with tempfile.TemporaryDirectory() as temp_dir:
        database = DatabaseManager(str(Path(temp_dir) / "data.db"))
        try:
            private = database.create_conversation("ran", user_key="alice")
            private_user = database.add_message(private, "user", "  私聊里  的消息  ")
            private_assistant = database.add_message(private, "assistant", "知道了")
            bob = database.create_conversation("ran", user_key="bob")
            database.add_message(bob, "user", "不应出现的用户")
            group_user = database.add_group_message(
                "__group__:moca|ran", "g1", "user", "群聊问题", user_key="alice"
            )
            group_assistant = database.add_group_message(
                "__group__:moca|ran",
                "g1",
                "assistant",
                "【青叶摩卡】\n群聊回答",
                user_key="alice",
            )
            database.add_group_message(
                "__group__:arisa|kasumi",
                "g2",
                "user",
                "不相关群聊",
                user_key="alice",
            )
            for table, message_id, created_at in (
                ("messages", private_user, "2026-07-14 08:01:02"),
                ("messages", private_assistant, "2026-07-14 08:02:03"),
                ("group_messages", group_user, "2026-07-15 09:03:04"),
                ("group_messages", group_assistant, "2026-07-15 09:04:05"),
            ):
                database._conn.execute(
                    f"UPDATE {table} SET created_at=? WHERE id=?",
                    (created_at, message_id),
                )
            database._conn.commit()
            harness = Harness()
            harness._db = database
            harness._model_manager = FixtureModelManager()
            harness._is_group_chat = False
            harness._chat_user_key = "alice"
            harness._user_name = "Alice"
            expected = ChatWindow._unified_history_context(
                harness, "ran", limit=18
            )
        finally:
            database.close()
    return {"expected": expected}


def _group_chat_contract() -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        from chat_window import chat_window as chat_module

    ChatWindow = chat_module.ChatWindow

    class FixtureModelManager:
        characters = ["ran", "moca", "kasumi"]
        names = {
            "ran": "美竹兰",
            "moca": "青叶摩卡",
            "kasumi": "户山香澄",
        }

        def get_display_name(self, character: str) -> str:
            return self.names.get(character, character)

    class Harness:
        _normalize_group_characters = ChatWindow._normalize_group_characters
        _conversation_key_for = ChatWindow._conversation_key_for
        _group_system_prompt = ChatWindow._group_system_prompt
        _parse_group_plan = ChatWindow._parse_group_plan
        _apply_group_plan_priority = ChatWindow._apply_group_plan_priority
        _sanitize_group_assistant_reply = ChatWindow._sanitize_group_assistant_reply
        _assistant_content = ChatWindow._assistant_content

    harness = Harness()
    harness._character = "ran"
    harness._group_characters = ["ran", "moca", "kasumi"]
    harness._is_group_chat = True
    harness._model_manager = FixtureModelManager()
    harness._cfg = {}

    key_cases = []
    for characters in (
        [],
        ["moca"],
        ["ran", "moca", "ran", ""],
        ["Kasumi", "arisa", "kasumi"],
    ):
        key_cases.append(
            {
                "characters": characters,
                "fallback": harness._character,
                "normalized": harness._normalize_group_characters(characters),
                "expected": harness._conversation_key_for(characters),
            }
        )

    with patch(
        "chat_window.chat_window.build_system_prompt", return_value="BASE"
    ):
        system_prompt = harness._group_system_prompt("ran", [])

    plan_sources = (
        '{"speakers":["ran","青叶摩卡","unknown","ran","kasumi","moca","ran"]}',
        'prefix {"speakers":["户山香澄"]} suffix',
        '{"speakers":"ran"}',
        'not json',
    )
    plan_cases = [
        {"source": source, "expected": harness._parse_group_plan(source)}
        for source in plan_sources
    ]
    priority_cases = []
    for queue, priority in (
        (["moca", "ran", "kasumi"], "ran"),
        (["ran"], "ran"),
        (["moca", "kasumi"], "unknown"),
    ):
        priority_cases.append(
            {
                "queue": queue,
                "priority": priority,
                "expected": harness._apply_group_plan_priority(queue, priority),
            }
        )
    assistant_cases = []
    for character, source in (
        ("ran", "你好"),
        ("ran", "【美竹兰】你好\n【青叶摩卡】代替发言\n【美竹兰】继续"),
        ("moca", "美竹兰：错误角色\n户山香澄：另一条"),
        ("moca", "[青叶摩卡] 自己的回答"),
    ):
        assistant_cases.append(
            {
                "character": character,
                "source": source,
                "expected": harness._assistant_content(character, source),
            }
        )
    return {
        "members": [
            {"key": key, "name": FixtureModelManager.names[key]}
            for key in harness._group_characters
        ],
        "key_cases": key_cases,
        "system_prompt": system_prompt,
        "plan_cases": plan_cases,
        "priority_cases": priority_cases,
        "assistant_cases": assistant_cases,
    }


def _relationship_prompt_cases(build_relationship_context) -> list[dict]:
    class FixtureDatabase:
        def __init__(self, state: dict, memories: dict[tuple[str, str], list[dict]]):
            self._state = state
            self._memories = memories

        def get_relationship_state(self, character: str, user_key: str) -> dict:
            return dict(self._state)

        def get_character_memories(
            self, character: str, user_key: str, limit: int = 8
        ) -> list[dict]:
            return [
                dict(memory)
                for memory in self._memories.get((character, user_key), [])[:limit]
            ]

    cases = [
        {
            "name": "default_relationship",
            "character": "ran",
            "user_key": "__default__",
            "display_name": "",
            "state": {
                "affection": 50,
                "trust": 50,
                "familiarity": 0,
                "mood": "calm",
                "mood_intensity": 20,
            },
            "memories": [],
            "global_memories": [],
        },
        {
            "name": "role_user_with_memories",
            "character": "ran",
            "user_key": "__role__:moca",
            "display_name": "",
            "state": {
                "affection": 87,
                "trust": 72,
                "familiarity": 61,
                "mood": "shy",
                "mood_intensity": 76,
            },
            "memories": [
                {"kind": "relationship", "content": "约好一起去看演出"},
                {"kind": "custom", "content": "共同口头禅是哦豁"},
            ],
            "global_memories": [
                {"kind": "preference", "content": "喜欢草莓蛋糕"},
            ],
        },
    ]
    for case in cases:
        memories = {
            (case["character"], case["user_key"]): case["memories"],
            ("__global__", case["user_key"]): case["global_memories"],
        }
        database = FixtureDatabase(case["state"], memories)
        case["expected"] = build_relationship_context(
            database,
            case["character"],
            case["user_key"],
            case["display_name"],
        )
    return cases


def _database_contract() -> dict:
    from database_manager import DatabaseManager

    with tempfile.TemporaryDirectory() as temp_dir:
        manager = DatabaseManager(str(Path(temp_dir) / "contract.db"))
        try:
            conn = manager._conn
            table_names = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name"
                ).fetchall()
            ]
            tables = {}
            for table in table_names:
                tables[table] = [
                    {
                        "name": row[1],
                        "type": row[2],
                        "not_null": bool(row[3]),
                        "default": row[4],
                        "primary_key": bool(row[5]),
                    }
                    for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                ]

            indexes = {}
            index_rows = conn.execute(
                "SELECT name, tbl_name FROM sqlite_master "
                "WHERE type='index' AND name NOT LIKE 'sqlite_autoindex_%' ORDER BY name"
            ).fetchall()
            for name, table in index_rows:
                info = conn.execute(f"PRAGMA index_list({table})").fetchall()
                unique = next(bool(row[2]) for row in info if row[1] == name)
                columns = [
                    row[2]
                    for row in conn.execute(f"PRAGMA index_info({name})").fetchall()
                ]
                indexes[name] = {
                    "table": table,
                    "unique": unique,
                    "columns": columns,
                }
        finally:
            manager.close()

    return {"tables": tables, "indexes": indexes}


def _database_behavior_contract() -> dict:
    from database_manager import DatabaseManager

    def without_times(value: dict) -> dict:
        return {
            key: item
            for key, item in value.items()
            if key not in {"created_at", "updated_at", "last_message_at"}
        }

    with tempfile.TemporaryDirectory() as temp_dir:
        manager = DatabaseManager(str(Path(temp_dir) / "vectors.db"))
        try:
            default_state = without_times(manager.get_relationship_state("Ran", ""))
            zero_state = without_times(
                manager.upsert_relationship_state(
                    "Ran", "", affection=0, trust=0, mood_intensity=0
                )
            )
            delta_state = without_times(
                manager.apply_relationship_delta(
                    "Moca",
                    "alice",
                    affection_delta=7,
                    trust_delta=-3,
                    familiarity_delta=2,
                    mood="happy",
                )
            )

            first_memory = manager.add_character_memory(
                "Ran", "", "note", "first", 50
            )
            second_memory = manager.add_character_memory(
                "Ran", "", "note", "second", 50
            )
            repeated_memory = manager.add_character_memory(
                "Ran", "", "preference", "first", 90
            )
            memories = [
                without_times(item)
                for item in manager.get_character_memories("Ran", "", 8)
            ]

            conversation = manager.create_conversation("Ran", "fixture", "")
            first_message = manager.add_message(conversation, "user", "hello")
            second_message = manager.add_message(
                conversation,
                "assistant",
                "tracked",
                tool_trace={
                    "llm_usage": {
                        "input_tokens": 100,
                        "output_tokens": 25,
                        "total_tokens": 125,
                    }
                },
            )
            third_message = manager.add_message(
                conversation, "assistant", "legacy"
            )
            page = [
                without_times(item)
                for item in manager.get_messages(conversation, limit=2)
            ]
            before = [
                without_times(item)
                for item in manager.get_messages(
                    conversation, limit=10, before_id=third_message
                )
            ]
            usage = manager.get_conversation_token_usage(conversation)

            group_user_message = manager.add_group_message(
                "__group__:Ran|Moca",
                "group-1",
                "user",
                "group hello",
                user_key="alice",
            )
            group_assistant_message = manager.add_group_message(
                "__group__:Ran|Moca",
                "group-1",
                "assistant",
                "【Ran】\ngroup reply",
                user_key="alice",
            )
            manager.set_group_display_name("__group__:Ran|Moca", "Band chat")
            filter_options = manager.get_chat_history_filter_options()
            history_search = manager.search_chat_history(
                keyword="group hello",
                character="Ran",
                user_key="alice",
                source="group",
                limit=10,
            )
            history_search["records"] = [
                without_times(record) for record in history_search["records"]
            ]
            group_conversations = [
                without_times(record)
                for record in manager.get_group_conversations(
                    "__group__:Ran|Moca", "alice"
                )
            ]
            group_chats = [
                without_times(record)
                for record in manager.get_group_chats("alice")
            ]
            first_user_content = manager.get_first_user_message_content(conversation)
            chat_summary = manager.get_chat_summary()

            album_conversation = manager.create_conversation("Ran", "album", "alice")
            manager.add_message(album_conversation, "user", "album private")
            manager.add_message(album_conversation, "assistant", "album reply")
            manager.add_group_message(
                "__group__:Ran|Moca",
                "group-1",
                "assistant",
                "【Moca】\nother reply",
                user_key="alice",
            )
            manager.add_character_memory(
                "Ran", "alice", "favorite", "favorite memory", 75
            )
            album_recent = []
            for item in manager.get_character_recent_messages(
                "Ran", "alice", 24, ["美竹蘭"]
            ):
                album_recent.append(
                    {
                        "id": item["id"],
                        "source": item["source"],
                        "conversation_id": item["conversation_id"],
                        "group_key": item.get("group_key", ""),
                        "role": item["role"],
                        "content": item["content"],
                        "speaker": item.get("speaker", ""),
                    }
                )
            album_chain = []
            for item in manager.get_character_conversation_chain(
                "Ran", "alice", 20, ["美竹蘭"]
            ):
                album_chain.append(
                    {
                        key: value
                        for key, value in item.items()
                        if key not in {"created_at", "first_message_at", "last_message_at"}
                    }
                )
            album_days = []
            for item in manager.get_character_album_days(
                "Ran", "alice", 30, ["美竹蘭"]
            ):
                album_days.append(
                    {
                        key: value
                        for key, value in item.items()
                        if key not in {"day", "first_at", "last_at"}
                    }
                )
            character_counts = manager.get_messages_per_character_range(0, "alice")

            external_event = {
                "platform": "napcat",
                "thread_id": "group-1",
                "thread_name": "Band",
                "message_id": "external-1",
                "sender_id": "42",
                "sender_name": "Kasumi",
                "content": "hello from chat",
                "chat_type": "group",
            }
            external_first = manager.add_external_chat_message(external_event)
            external_duplicate = manager.add_external_chat_message(external_event)
            external_marked = manager.mark_external_chat_read("napcat", "group-1")
            prune_result = None
            for index in range(51):
                prune_result = manager.add_external_chat_message(
                    {
                        "platform": "napcat",
                        "thread_id": "limit",
                        "message_id": f"limit-{index}",
                        "content": str(index),
                        "chat_type": "group",
                        "unread": False,
                    }
                )
            retained_group = manager._conn.execute(
                "SELECT COUNT(*), MIN(CAST(content AS INTEGER)), MAX(CAST(content AS INTEGER)) "
                "FROM external_chat_messages WHERE platform='napcat' AND thread_id='limit'"
            ).fetchone()
        finally:
            manager.close()

    def normalize_unread(summary: dict) -> dict:
        return {
            "total_unread": summary["total_unread"],
            "threads": [
                {
                    "platform": thread["platform"],
                    "thread_id": thread["thread_id"],
                    "thread_name": thread["thread_name"],
                    "unread_count": thread["unread_count"],
                    "messages": [
                        {
                            key: value
                            for key, value in message.items()
                            if key not in {"raw_json", "created_at"}
                        }
                        for message in thread["messages"]
                    ],
                }
                for thread in summary["threads"]
            ],
        }

    def normalize_external_result(result: dict) -> dict:
        return {
            "duplicate": result["duplicate"],
            "message_id": result["message_id"],
            "thread": without_times(result["thread"]),
            "unread": normalize_unread(result["unread"]),
        }

    return {
        "relationship": {
            "default": default_state,
            "zero": zero_state,
            "delta": delta_state,
        },
        "memory": {
            "ids": [first_memory, second_memory, repeated_memory],
            "records": memories,
        },
        "chat": {
            "ids": [first_message, second_message, third_message],
            "page": page,
            "before": before,
            "usage": usage,
        },
        "queries": {
            "group_ids": [group_user_message, group_assistant_message],
            "filter_options": filter_options,
            "history_search": history_search,
            "group_conversations": group_conversations,
            "group_chats": group_chats,
            "first_user_content": first_user_content,
            "chat_summary": chat_summary,
        },
        "album": {
            "recent": album_recent,
            "chain": album_chain,
            "days": album_days,
            "character_counts": character_counts,
        },
        "external": {
            "first": normalize_external_result(external_first),
            "duplicate": normalize_external_result(external_duplicate),
            "marked_read": {
                "marked_read": external_marked["marked_read"],
                "unread": normalize_unread(external_marked["unread"]),
            },
            "prune": {
                "last_pruned": prune_result["pruned_messages"],
                "retained": retained_group[0],
                "oldest": retained_group[1],
                "newest": retained_group[2],
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the checked-in Rust contract is out of sync",
    )
    args = parser.parse_args()
    contracts = rendered_contracts()

    if args.check:
        stale = []
        for output, expected in contracts.items():
            actual = output.read_text(encoding="utf-8") if output.exists() else ""
            if actual != expected:
                stale.append(output.relative_to(ROOT))
        for path in stale:
            print(f"out of date: {path}", file=sys.stderr)
        return int(bool(stale))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for output, content in contracts.items():
        output.write_text(content, encoding="utf-8", newline="\n")
        print(output.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
