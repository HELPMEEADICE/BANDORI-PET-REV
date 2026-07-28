#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wayland.installer import companion_status, install_companion, remove_companion


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage BandoriPet Wayland companions.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--status", action="store_true")
    action.add_argument("--install", action="store_true")
    action.add_argument("--remove", action="store_true")
    parser.add_argument("--compositor", choices=("plasma", "gnome", "hyprland", "generic"))
    args = parser.parse_args()

    if args.status:
        print(json.dumps(companion_status(), ensure_ascii=False, indent=2))
        return 0
    ok, detail = (
        install_companion(args.compositor)
        if args.install
        else remove_companion(args.compositor)
    )
    print(detail)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
