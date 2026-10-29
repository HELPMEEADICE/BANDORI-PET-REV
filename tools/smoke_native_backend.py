"""Run a real native window/GPU smoke test with an isolated configuration.

python tools/smoke_native_backend.py --model models/kasumi.zst::live_default/model.json
Use --pixel to exercise the native sprite renderer. No user config is written.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bandori_core.mapped_memory import queue_file_path  # noqa: E402
from bandori_core.native_pet import native_program_and_args  # noqa: E402
from bandori_core.shared_memory_ipc import SharedMemoryLineQueue, decode_ipc_envelope, encode_ipc_envelope  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--character", default="kasumi")
    parser.add_argument("--costume", default="smoke-test")
    parser.add_argument("--pixel", action="store_true")
    parser.add_argument("--show-fps", action="store_true")
    parser.add_argument("--output", default=str(ROOT / ".runtime" / "neocari-smoke.png"))
    args = parser.parse_args()
    queues = [SharedMemoryLineQueue.create("native-smoke-" + uuid.uuid4().hex, slot_count=32) for _ in range(4)]
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="bandori-native-smoke-") as directory:
            config = Path(directory) / "config.json"
            model = {"character": args.character, "costume": args.costume, "path": args.model, "pet_mode": "pixel" if args.pixel else "live2d"}
            config.write_text(json.dumps({"models": [model], "fps": 60, "show_fps": args.show_fps, "live2d_scale": 70, "drag_locked": False}), encoding="utf-8")
            program, arguments = native_program_and_args(ROOT, args.character, args.costume, args.model, config_path=config, data_dir=ROOT)
            for flag, queue in zip(["--inbound", "--reliable-inbound", "--broadcast", "--control"], queues):
                arguments[arguments.index(flag) + 1] = str(queue_file_path(queue.key))
            env = os.environ.copy()
            env["BANDORI_PET_SNAPSHOT"] = str(Path(args.output).resolve())
            arguments.extend(["--exit-after", "30"])
            process = subprocess.Popen([program, *arguments], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            started = time.monotonic()
            ready = None
            captured = False
            requested = False
            frame_path = str(Path(args.output).with_suffix(".frame.png").resolve())
            while time.monotonic() - started < 25:
                for line in queues[1].read_available():
                    envelope = decode_ipc_envelope(line)
                    if envelope.line.startswith("NATIVE_EVENT\t"):
                        event = json.loads(envelope.line.split("\t", 1)[1])
                        if event["event"] == "error": raise RuntimeError(event["data"])
                        if event["event"] == "ready": ready = time.monotonic()
                        if event["event"] == "snapshot": captured = True
                if ready:
                    if time.monotonic() - ready > 1 and not requested:
                        queues[3].publish(encode_ipc_envelope("smoke", "NATIVE_CONTROL\t" + json.dumps({"character":args.character,"command":"snapshot","path":frame_path}), reliable=True))
                        requested = True
                    if time.monotonic() - ready > 2 and captured:
                        break
                    queues[2].publish(encode_ipc_envelope("smoke", f"LIP\t{args.character}\t0.6\t0.2"))
                if process.poll() is not None:
                    raise RuntimeError(process.communicate()[1].decode(errors="replace"))
                time.sleep(0.03)
            if ready is None: raise RuntimeError("native window did not become ready")
            if not captured: raise RuntimeError("native GPU frame capture did not complete")
            try:
                import psutil
            except ImportError:
                pass
            else:
                libraries = [mapping.path.lower() for mapping in psutil.Process(process.pid).memory_maps()]
                assert not any("qt6" in path or "luajit" in path or "python3" in path for path in libraries), "native pet loaded a legacy runtime"
            queues[3].publish(encode_ipc_envelope("smoke", "SHUTDOWN", reliable=True))
            _, error = process.communicate(timeout=5)
            if process.returncode: raise RuntimeError(error.decode(errors="replace"))
            assert Path(args.output).is_file()
            print(f"Native GPU/window/IPC smoke passed: {args.output}")
    finally:
        if process and process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        for queue in queues: queue.close()


if __name__ == "__main__":
    main()
