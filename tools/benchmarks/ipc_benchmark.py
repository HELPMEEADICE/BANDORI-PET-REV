"""Reproduce old/new IPC throughput, latency and process CPU on one machine.

Build a release extension and release ipc_peer first; see docs/rust-ipc.md.
Events coordinate cross-process batches without a spin loop. Event/OS wakeup
cost is included equally for both implementations. Never run on production keys.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def queue_type(implementation):
    if implementation == "legacy":
        from tools.benchmarks.legacy_ipc import SharedMemoryLineQueue
    else:
        from bandori_core.shared_memory_ipc import SharedMemoryLineQueue
    return SharedMemoryLineQueue


def new_key():
    return "benchmark-" + uuid.uuid4().hex


def summary(samples, wall, cpu, count):
    samples = sorted(samples)
    return {
        "messages": count,
        "messages_per_second": count / wall,
        "mean_us": statistics.fmean(samples) / 1000,
        "p95_us": samples[min(len(samples) - 1, math.ceil(len(samples) * 0.95) - 1)] / 1000,
        "p99_us": samples[min(len(samples) - 1, math.ceil(len(samples) * 0.99) - 1)] / 1000,
        "wall_seconds": wall,
        "cpu_seconds": cpu,
        "cpu_percent_one_core": cpu / wall * 100,
    }


def single(implementation, count, size, slots, raw=False):
    q = queue_type(implementation).create(new_key(), slot_count=slots, slot_size=size)
    handle = q._queue if raw else q
    payload = "x" * size
    try:
        for _ in range(200):
            assert handle.publish(payload)
            assert handle.read_available() == [payload]
        samples = []
        cpu_start, start = time.process_time(), time.perf_counter()
        for _ in range(count):
            before = time.perf_counter_ns()
            assert handle.publish(payload)
            assert handle.read_available() == [payload]
            samples.append(time.perf_counter_ns() - before)
        wall, cpu = time.perf_counter() - start, time.process_time() - cpu_start
        result = summary(samples, wall, cpu, count)
        result["scenario"] = "same_process_raw_ffi" if raw else "same_process"
        result["implementation"] = implementation
        return result
    finally:
        q.close()


def consumer(implementation, name, request, ack, result, count, batch):
    q = None
    try:
        q = queue_type(implementation).attach(name, start_at_tail=False)
        samples = []
        cpu_start = time.process_time()
        ack.set()
        for _ in range(0, count, batch):
            if not request.wait(15):
                raise TimeoutError("publisher did not signal")
            request.clear()
            lines = q.read_available()
            now = time.perf_counter_ns()
            if len(lines) != min(batch, count - len(samples)):
                raise RuntimeError("cross-process loss or corruption")
            samples.extend(now - int(line[:20]) for line in lines)
            ack.set()
        result.send({"samples": samples, "cpu": time.process_time() - cpu_start})
    except Exception as error:
        result.send({"error": repr(error)})
        ack.set()
    finally:
        if q is not None:
            q.close()
        result.close()


def cross_process(implementation, count, size, slots, batch):
    context = mp.get_context("spawn")
    q = queue_type(implementation).create(new_key(), slot_count=slots, slot_size=size)
    request, ack = context.Event(), context.Event()
    output, child_output = context.Pipe(duplex=False)
    child = context.Process(target=consumer, args=(implementation, q.key, request, ack, child_output, count, batch))
    child.start()
    child_output.close()
    try:
        if not ack.wait(15):
            raise TimeoutError("consumer startup")
        ack.clear()
        cpu_start, start = time.process_time(), time.perf_counter()
        for offset in range(0, count, batch):
            for _ in range(min(batch, count - offset)):
                payload = f"{time.perf_counter_ns():020d}" + "x" * (size - 20)
                assert q.publish(payload)
            request.set()
            if not ack.wait(15):
                raise TimeoutError("consumer acknowledgment")
            ack.clear()
        wall, cpu = time.perf_counter() - start, time.process_time() - cpu_start
        if not output.poll(15):
            raise TimeoutError("consumer results")
        received = output.recv()
        if "error" in received:
            raise RuntimeError(received["error"])
        child.join(timeout=5)
        if child.exitcode != 0:
            raise RuntimeError(f"consumer exit: {child.exitcode}")
        result = summary(received["samples"], wall, cpu + received["cpu"], count)
        result.update(scenario="cross_process", implementation=implementation, batch=batch)
        return result
    finally:
        if child.is_alive():
            child.kill()
            child.join(timeout=5)
        output.close()
        q.close()


def rust_direct(binary, count, size, slots):
    import psutil
    from bandori_core.mapped_memory import queue_file_path
    peer = subprocess.Popen([str(binary), "create", str(queue_file_path(new_key())), str(slots), str(size)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8")
    try:
        assert json.loads(peer.stdout.readline())["ready"]
        process = psutil.Process(peer.pid)
        before = process.cpu_times()
        command = {"op": "bench", "count": count, "line": "x" * size}
        peer.stdin.write(json.dumps(command) + "\n")
        peer.stdin.flush()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(peer.stdout.readline)
            try:
                stdout = future.result(timeout=30)
            except Exception:
                peer.kill()
                peer.wait(timeout=5)
                raise
        after = process.cpu_times()
        _, stderr = peer.communicate(timeout=5)
        if peer.returncode:
            raise RuntimeError(stderr)
        result = json.loads(stdout)
        result.update(scenario="same_process_native", implementation="rust", messages=count)
        result["cpu_seconds"] = after.user + after.system - before.user - before.system
        result["cpu_percent_one_core"] = result["cpu_seconds"] / result["wall_seconds"] * 100
        result["cpu_note"] = "psutil CPU delta includes command parsing and result formatting; wall/latency are timed inside Rust."
        return result
    finally:
        if peer.poll() is None:
            peer.kill()
            peer.communicate(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=40000)
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--slots", type=int, default=256)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--rust-peer", type=Path, default=ROOT / "native/pet_backend/target/release/examples" / ("ipc_peer.exe" if os.name == "nt" else "ipc_peer"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.count < 1 or args.repeats < 1 or args.size < 64 or not 1 <= args.batch <= args.slots:
        parser.error("invalid queue or benchmark parameters")
    report = {"platform": platform.platform(), "machine": platform.machine(), "python": sys.version,
              "processor": platform.processor(), "logical_cpus": os.cpu_count(),
              "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "baseline_commit": "10a804c",
              "parameters": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
              "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
              "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "results": []}
    for repeat in range(args.repeats):
        # Alternate execution order to reduce warm-cache/order bias.
        implementations = ["legacy", "rust"] if repeat % 2 == 0 else ["rust", "legacy"]
        for implementation in implementations:
            for result in (single(implementation, args.count, args.size, args.slots),
                           cross_process(implementation, args.count, args.size, args.slots, args.batch)):
                result["repeat"] = repeat
                report["results"].append(result)
                print(json.dumps(result), flush=True)
        result = single("rust", args.count, args.size, args.slots, raw=True)
        result["repeat"] = repeat
        report["results"].append(result)
        result = rust_direct(args.rust_peer, args.count, args.size, args.slots)
        result["repeat"] = repeat
        report["results"].append(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
