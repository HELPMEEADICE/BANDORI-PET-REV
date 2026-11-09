"""Verify the actual frozen helper publishes through its bundled Rust IPC.

Uses a private session name and never launches the UI or touches user settings.
Run with the build directory (or a macOS app's Contents/MacOS directory).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def smoke(directory):
    from bandori_core.shared_memory_ipc import SharedMemoryLineQueue, decode_ipc_envelope

    session = "frozen-ipc-smoke-" + uuid.uuid4().hex
    env = os.environ.copy()
    env["BANDORI_PET_IPC_SERVER_NAME"] = session
    # Resolve the same key without changing the parent process environment.
    from bandori_core.shared_memory_ipc import make_shared_memory_key
    name = make_shared_memory_key(session, "main-in")
    q = SharedMemoryLineQueue.create(name, slot_count=4, slot_size=4096)
    helper = Path(directory).resolve() / ("bandori-ai-event.exe" if os.name == "nt" else "bandori-ai-event")
    event = {"source": "ipc-smoke", "state": "done", "text": "中文・日本語🐈"}
    try:
        # Remove source/venv search paths so this tests the frozen payload.
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        result = subprocess.run([str(helper), "--raw-json", json.dumps(event, ensure_ascii=False)],
                                cwd=helper.parent, env=env, capture_output=True, timeout=20,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode:
            raise RuntimeError(f"Frozen helper failed: {result.stderr.decode(errors='replace')}")
        lines = [decode_ipc_envelope(raw).line for raw in q.read_available()]
        if len(lines) != 1 or not lines[0].startswith("AI_EVENT\t") or json.loads(lines[0].split("\t", 1)[1]) != event:
            raise RuntimeError(f"Frozen Rust IPC did not deliver the Unicode event: {lines!r}")
        print(f"Frozen Rust IPC smoke passed: {helper}")
    finally:
        q.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    smoke(parser.parse_args().directory)
