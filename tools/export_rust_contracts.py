"""Export Python-owned compatibility contracts consumed by the Rust port."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "rust" / "compat"


def rendered_contracts() -> dict[Path, str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from config_manager import DEFAULTS
    from ipc_bus import is_control_ipc_line, is_reliable_ipc_line
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
        OUTPUT_DIR / "database_schema.json": json.dumps(
            database_contract, ensure_ascii=False, indent=2
        )
        + "\n",
        OUTPUT_DIR / "database_vectors.json": json.dumps(
            database_vectors, ensure_ascii=False, indent=2
        )
        + "\n",
    }


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
