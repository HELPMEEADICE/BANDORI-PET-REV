"""Launch the standalone Neocari pet; no Qt or Lua runtime is loaded here."""
import os
import json
from pathlib import Path
import sys

from bandori_core.ipc_bus import (
    ipc_inbound_queue_key, ipc_reliable_inbound_queue_key,
    ipc_broadcast_queue_key, ipc_control_queue_key,
)
from bandori_core.mapped_memory import queue_file_path


def native_executable(base_dir) -> Path:
    override = os.environ.get("BANDORI_PET_NATIVE", "")
    suffix = ".exe" if sys.platform == "win32" else ""
    name = "bandori-pet-native" + suffix
    root = Path(base_dir)
    candidates = [Path(override)] if override else [
        root / name,
        root / "native" / "pet_backend" / "target" / "release" / name,
        root / "native" / "pet_backend" / "target" / "debug" / name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "Neocari pet backend is missing. Run: "
        "cargo build --release --manifest-path native/pet_backend/Cargo.toml "
        "-p bandori-pet-native -p pet-assets --locked"
    )


def native_program_and_args(base_dir, character, costume, model_path, *, config_path=None, data_dir=None, index=0):
    from bandori_core.process_utils import app_data_dir, process_program_and_args
    data_dir = Path(data_dir or app_data_dir())
    args = [
        "--character", character, "--costume", costume, "--model-path", model_path,
        "--root", str(data_dir), "--config", str(config_path or data_dir / "config.json"),
        "--parent-pid", str(os.getpid()),
        "--assets-root", str(base_dir), "--index", str(index),
        "--restart-command", json.dumps(list(process_program_and_args(str(base_dir), "main.py", [])), ensure_ascii=False),
    ]
    for flag, key in (
        ("--inbound", ipc_inbound_queue_key()),
        ("--reliable-inbound", ipc_reliable_inbound_queue_key()),
        ("--broadcast", ipc_broadcast_queue_key()),
        ("--control", ipc_control_queue_key()),
    ):
        args.extend([flag, str(queue_file_path(key))])
    return str(native_executable(base_dir)), args


class _PreviewModule:
    def dispose(self):
        pass

preview_module = _PreviewModule()
