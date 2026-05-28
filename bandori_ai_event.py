import argparse
import json
import sys

from ai_event_bus import publish_ai_event
from process_utils import configure_debug_logging

configure_debug_logging()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish a BandoriPet AI status event.")
    parser.add_argument("--source", default="")
    parser.add_argument("--state", default="stream")
    parser.add_argument("--title", default="")
    parser.add_argument("--text", default="")
    parser.add_argument("--mode", choices=("replace", "append"), default="")
    parser.add_argument("--progress", type=float, default=None)
    parser.add_argument("--action", default="")
    parser.add_argument("--character", default="")
    parser.add_argument("--ttl-ms", type=int, default=None)
    parser.add_argument("--raw-json", default="", help="Complete JSON event payload.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.raw_json:
        try:
            event = json.loads(args.raw_json)
        except json.JSONDecodeError as exc:
            print(f"Invalid --raw-json: {exc}", file=sys.stderr)
            return 2
        if not isinstance(event, dict):
            print("--raw-json must decode to an object.", file=sys.stderr)
            return 2
    else:
        event = {
            "source": args.source,
            "state": args.state,
            "title": args.title,
            "text": args.text,
        }
        if args.mode:
            event["mode"] = args.mode
        if args.progress is not None:
            event["progress"] = args.progress
        if args.action:
            event["action"] = args.action
        if args.character:
            event["character"] = args.character
        if args.ttl_ms is not None:
            event["ttl_ms"] = args.ttl_ms

    publish_ai_event(event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
