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
