import argparse
import json
import os
import subprocess
import sys
from typing import Any

from ai_event_bus import publish_ai_event
from i18n_manager import detect_system_language, set_language, tr as _tr
from process_utils import app_base_dir, configure_debug_logging

configure_debug_logging()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run `codex exec --json` and mirror its status into BandoriPet.",
    )
    parser.add_argument("--codex", default="codex", help="Path to codex executable.")
    parser.add_argument("--source", default="codex")
    parser.add_argument("--character", default="", help="Optional target BandoriPet character key.")
    parser.add_argument("--workdir", default="", help="Working directory for the Codex process.")
    parser.add_argument(
        "--no-echo",
        action="store_true",
        help="Do not print Codex output back to this terminal.",
    )
    parser.add_argument(
        "codex_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed to `codex exec --json`. Use -- before prompts that start with '-'.",
    )
    return parser


def _event_payload(source: str, state: str, title: str = "", text: str = "", **extra) -> dict:
    payload = {
        "source": source,
        "state": state,
        "title": title,
        "text": text,
    }
    payload.update({key: value for key, value in extra.items() if value not in (None, "")})
    return payload


def _publish(source: str, state: str, title: str = "", text: str = "", character: str = "", **extra):
    payload = _event_payload(source, state, title, text, **extra)
    if character:
        payload["character"] = character
    publish_ai_event(payload)


def _init_language() -> None:
    lang = ""
    try:
        config_path = app_base_dir() / "config.json"
        if config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            lang = data.get("language", "") if isinstance(data, dict) else ""
    except Exception:
        lang = ""
    set_language(lang or detect_system_language())


def _compact_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_compact_text(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message", "delta", "summary", "command", "cmd", "name", "status"):
            text = _compact_text(value.get(key))
            if text:
                return text
    return ""


def _event_text(event: dict) -> str:
    for key in ("message", "content", "text", "delta", "summary", "command", "cmd", "name"):
        text = _compact_text(event.get(key))
        if text:
            return text
    return ""


def _event_kind(event: dict) -> str:
    raw_type = str(event.get("type") or event.get("event") or event.get("kind") or "").lower()
    raw_name = str(event.get("name") or event.get("status") or "").lower()
    return " ".join(part for part in (raw_type, raw_name) if part)


def _mirror_codex_event(event: dict, source: str, character: str):
    kind = _event_kind(event)
    text = _event_text(event)
    lowered_text = text.lower()

    if "error" in kind or "failed" in kind or "error" in lowered_text:
        _publish(source, "error", _tr("AiEvent.codex_error"), text, character, action="surprised")
        return

    if any(token in kind for token in ("exec", "tool", "command", "apply_patch", "shell")):
        title = _tr("AiEvent.codex_tool")
        _publish(source, "tool", title, text, character, action="thinking")
        return

    if any(token in kind for token in ("reason", "think", "plan", "started", "start")):
        _publish(source, "thinking", _tr("AiEvent.codex_thinking"), text, character, action="thinking")
        return

    if any(token in kind for token in ("delta", "stream")):
        if text:
            _publish(source, "stream", "", text, character, mode="append")
        return

    if any(token in kind for token in ("message", "output", "response")):
        if text:
            _publish(source, "stream", _tr("AiEvent.codex_output"), text, character)
        return

    if any(token in kind for token in ("complete", "completed", "done", "finish", "finished", "turn_complete")):
        _publish(source, "done", _tr("AiEvent.codex_done"), text or _tr("AiEvent.task_done"), character)
        return

    if text:
        _publish(source, "stream", "Codex", text, character)


def _parse_json_line(line: str) -> dict | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def main() -> int:
    _init_language()
    parser = _build_parser()
    args = parser.parse_args()
    codex_args = list(args.codex_args)
    if codex_args and codex_args[0] == "--":
        codex_args = codex_args[1:]
    if not codex_args:
        parser.error("provide a Codex prompt or arguments after the wrapper options")

    workdir = args.workdir or os.getcwd()
    command = [args.codex, "exec", "--json", *codex_args]
    _publish(
        args.source,
        "thinking",
        _tr("AiEvent.codex_starting"),
        " ".join(command),
        args.character,
        action="thinking",
    )

    try:
        process = subprocess.Popen(
            command,
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        _publish(args.source, "error", _tr("AiEvent.codex_start_failed"), str(exc), args.character, action="surprised")
        print(f"Failed to start Codex: {exc}", file=sys.stderr)
        return 127

    assert process.stdout is not None
    for line in process.stdout:
        if not args.no_echo:
            print(line, end="", flush=True)
        stripped = line.strip()
        if not stripped:
            continue
        event = _parse_json_line(stripped)
        if event is None:
            _publish(args.source, "stream", _tr("AiEvent.codex_output"), stripped, args.character, mode="append")
            continue
        _mirror_codex_event(event, args.source, args.character)

    return_code = process.wait()
    if return_code == 0:
        _publish(args.source, "done", _tr("AiEvent.codex_done"), _tr("AiEvent.task_done"), args.character)
    else:
        _publish(
            args.source,
            "error",
            _tr("AiEvent.codex_abnormal_exit"),
            _tr("AiEvent.exit_code", code=return_code),
            args.character,
            action="surprised",
        )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
