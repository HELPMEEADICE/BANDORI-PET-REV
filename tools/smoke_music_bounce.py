"""Real native window/GPU music smoke using deterministic test-only audio levels.

Build bandori-pet-native and pet-ipc's level_peer example first. This checks the
same production shared-memory consumer and render loop without depending on a
playing music track. Pass --pixel for sprites, or a .vrm/.model3.json/model.json.
"""
import argparse
from contextlib import ExitStack
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
from bandori_core.mapped_memory import queue_file_path
from bandori_core.native_pet import native_program_and_args
from bandori_core.shared_memory_ipc import SharedMemoryLineQueue, decode_ipc_envelope, encode_ipc_envelope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--character", default="arisa")
    parser.add_argument("--pixel", action="store_true")
    parser.add_argument("--binary", type=Path, default=ROOT / "native/pet_backend/target/debug" / ("bandori-pet-native.exe" if os.name == "nt" else "bandori-pet-native"))
    args = parser.parse_args()
    os.environ["BANDORI_PET_NATIVE"] = str(args.binary.resolve(strict=True))
    queues = [SharedMemoryLineQueue.create("music-smoke-" + uuid.uuid4().hex, slot_count=64) for _ in range(4)]
    processes = []
    def stop_processes():
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
    try:
        with tempfile.TemporaryDirectory(prefix="music-render-smoke-") as directory, ExitStack() as cleanup:
            cleanup.callback(stop_processes)
            directory = Path(directory)
            model = {"character":args.character,"costume":"music-smoke","path":args.model,
                     "pet_mode":"pixel" if args.pixel else "live2d"}
            config = directory / "config.json"
            config.write_text(json.dumps({"models":[model],"music_bounce_enabled":True,
                "fps":60,"live2d_scale":50,"drag_locked":False}), encoding="utf-8")
            program, arguments = native_program_and_args(ROOT, args.character, "music-smoke", args.model,
                                                        config_path=config, data_dir=ROOT)
            for flag, queue in zip(["--inbound","--reliable-inbound","--broadcast","--control"], queues):
                arguments[arguments.index(flag)+1] = str(queue_file_path(queue.key))
            arguments.extend(["--exit-after","20"])
            pet = subprocess.Popen([program,*arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            processes.append(pet)
            pending, geometry = [], []

            def send(line):
                assert queues[3].publish(encode_ipc_envelope("music-smoke", line, reliable=True))

            def control(command, **data):
                send("NATIVE_CONTROL\t" + json.dumps({"character":args.character,"command":command,**data}))

            def poll():
                for queue in queues[:2]:
                    for raw in queue.read_available():
                        line = decode_ipc_envelope(raw).line
                        if line.startswith("NATIVE_EVENT\t"):
                            item = json.loads(line.split("\t",1)[1])
                            if item["event"] == "error": raise RuntimeError(item)
                            pending.append(item)
                        elif line.startswith("PEER_POS\t"):
                            p = json.loads(line.split("\t",1)[1])
                            geometry.append(tuple(p[k] for k in ("x","y","w","h")))
                if pet.poll() is not None:
                    raise RuntimeError(pet.communicate()[1].decode(errors="replace"))

            def receive(kind):
                deadline = time.monotonic()+8
                while time.monotonic()<deadline:
                    poll()
                    for i,item in enumerate(pending):
                        if item["event"] == kind: return pending.pop(i)["data"]
                    time.sleep(0.005)
                raise TimeoutError(kind)

            def status():
                control("status")
                return receive("status")

            receive("ready")
            assert status()["music_scale"] == 1.0
            peer = ROOT / "native/pet_backend/target/debug/examples" / ("level_peer.exe" if os.name=="nt" else "level_peer")
            path = directory / "level.shm"
            producer = subprocess.Popen([str(peer),"producer",str(path)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            processes.append(producer)
            assert producer.stdout.readline().strip() == "READY"
            send("NATIVE_MUSIC_SOURCE\t"+json.dumps({"path":str(path)}))
            scales = []
            start = time.monotonic()
            while time.monotonic()-start < 2.5:
                t = time.monotonic()-start
                peak = 0.8 if t % 0.7 < 0.09 else 0.0
                producer.stdin.write(f"{peak} {time.time_ns()//1_000_000}\n")
                producer.stdin.flush()
                producer.stdout.readline()
                scales.append(status()["music_scale"])
                time.sleep(0.015)
            assert min(scales)<0.85 and max(scales)>1.05, scales
            assert geometry and len(set(geometry))==1, geometry
            control("snapshot", path=str(directory / "bouncing.png"))
            receive("snapshot")
            assert (directory / "bouncing.png").stat().st_size > 100
            send('SETTINGS\t{"music_bounce_enabled":false}')
            assert status()["music_scale"]==1.0
            send('SETTINGS\t{"music_bounce_enabled":true}')
            control("visibility", visible=False)
            assert status()["music_scale"]==1.0
            control("visibility", visible=True)
            assert status()["music_active"] == (os.name == "nt")
            send("SHUTDOWN")
            assert pet.wait(timeout=5)==0
            producer.stdin.close()
            assert producer.wait(timeout=5)==0
            assert not path.exists()
            print(json.dumps({"model":args.model,"pixel":args.pixel,"min_scale":min(scales),
                "max_scale":max(scales),"geometry":geometry[0],"disable_reset":True,"gpu_snapshot":True}))
    finally:
        stop_processes()
        for queue in queues: queue.close()


if __name__=="__main__":
    main()
