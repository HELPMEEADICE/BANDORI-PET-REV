"""Isolated, reproducible legacy/Rust API benchmark (never opens user data).

Build the release extension first: python tools/build_db.py
python tools/benchmarks/database_benchmark.py --output docs/benchmarks/database.json
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import gc
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def seed(db, rows):
    cid = db.create_conversation("灯🐈", "benchmark", "user")
    db._conn.executemany(
        "INSERT INTO messages(conversation_id,role,content,tool_trace_json) VALUES(?,?,?,?)",
        ((cid, "assistant" if i % 2 else "user", f"{i}: 中文・日本語🐈 needle {i % 100}",
          '{"llm_usage":{"input_tokens":5,"output_tokens":7,"total_tokens":12}}') for i in range(rows)),
    )
    db._conn.executemany(
        "INSERT INTO character_memories(character,user_key,content,importance) VALUES(?,?,?,?)",
        ((f"character-{i % 10}", "user", f"记忆🐈 {i}", i % 100) for i in range(1000)),
    )
    db._conn.commit()
    return cid


def measure(action, repeats, operations=1):
    import psutil
    proc = psutil.Process()
    rss_start = proc.memory_info().rss
    peak = [rss_start]
    stop = threading.Event()
    def sample():
        while not stop.wait(0.001):
            peak[0] = max(peak[0], proc.memory_info().rss)
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    gc.collect()
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    latencies = []
    try:
        for _ in range(repeats):
            start = time.perf_counter_ns()
            action()
            latencies.append((time.perf_counter_ns() - start) / 1e6)
    finally:
        wall, cpu = time.perf_counter() - wall_start, time.process_time() - cpu_start
        peak[0] = max(peak[0], proc.memory_info().rss)
        stop.set()
        sampler.join()
    latencies.sort()
    info = proc.memory_info()
    return {
        "repeats": repeats, "operations_per_repeat": operations,
        "wall_seconds": wall, "cpu_seconds": cpu,
        "throughput_per_second": repeats * operations / wall,
        "latency_p50_ms": statistics.median(latencies),
        "latency_p95_ms": latencies[min(len(latencies)-1, int(len(latencies)*.95))],
        "rss_baseline_bytes": rss_start, "rss_peak_sampled_bytes": peak[0],
        "process_peak_rss_bytes": getattr(info, "peak_wset", None),
    }


def worker(backend, workload, rows):
    from bandori_core.database_manager import DatabaseManager
    from tests.baselines.legacy_database import DatabaseManager as LegacyDatabase
    factory = DatabaseManager if backend == "rust" else LegacyDatabase
    with tempfile.TemporaryDirectory(prefix="bandori-db-benchmark-") as temp:
        path = str(Path(temp) / "bench.db")
        with closing(factory(path)) as db:
            cid = seed(db, rows)
            if workload == "insert":
                result = measure(lambda: db.add_message(cid, "user", "中文・日本語🐈"), 1000)
            elif workload == "history_200":
                result = measure(lambda: db.get_messages(cid, limit=200), 300)
            elif workload == "substring_search":
                result = measure(lambda: db.search_chat_history(keyword="needle 99", limit=300), 80)
            elif workload == "memory_50":
                result = measure(lambda: db.get_character_memories("character-1", "user", limit=50), 500)
            elif workload == "batch_200":
                payload = [{"role": "user", "content": "批量中文🐈"} for _ in range(200)]
                if backend == "rust":
                    action = lambda: db.add_messages(cid, payload)
                else:
                    def action():
                        # Legacy has no bulk API: measure its best available
                        # sqlite3 executemany in one original file-lock/transaction.
                        with db._lock:
                            db._conn.executemany("INSERT INTO messages(conversation_id,role,content) VALUES(?,?,?)",
                                                 ((cid, item["role"], item["content"]) for item in payload))
                            db._conn.commit()
                result = measure(action, 30, 200)
            elif workload == "concurrent_4":
                def run(connection):
                    for _ in range(50):
                        connection.add_message(cid, "user", "并发🐈")
                        connection.get_messages(cid, limit=30)
                peers = [factory(path) for _ in range(4)]
                try:
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        result = measure(lambda: list(pool.map(run, peers)), 5, 400)
                finally:
                    for peer in peers:
                        peer.close()
            elif workload == "boundary_roundtrip_200":
                from bandori_core._pet_db import NativeDatabase
                payload = db.get_messages(cid, limit=200)
                result = measure(lambda: NativeDatabase._conversion_probe(payload), 500)
            elif workload == "idle_1s":
                result = measure(lambda: time.sleep(1), 1)
            else:
                raise ValueError(workload)
            result.update(backend=backend, workload=workload, seed_rows=rows)
            return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=("legacy", "rust"))
    parser.add_argument("--workload")
    parser.add_argument("--rows", type=int, default=10000)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/benchmarks/database.json")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker, args.workload, args.rows)))
        return
    results = []
    for iteration in range(args.rounds):
        for workload in ("insert", "history_200", "substring_search", "memory_50", "batch_200", "concurrent_4", "idle_1s", "boundary_roundtrip_200"):
            for backend in (("rust",) if workload.startswith("boundary_") else (("legacy", "rust") if iteration % 2 == 0 else ("rust", "legacy"))):
                completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", backend,
                                            "--workload", workload, "--rows", str(args.rows)], cwd=ROOT,
                                           text=True, encoding="utf-8", capture_output=True, check=True, timeout=120)
                result = json.loads(completed.stdout)
                result["round"] = iteration + 1
                results.append(result)
                print(f"{iteration+1} {backend:6} {workload:24} {result['throughput_per_second']:.1f}/s", flush=True)
    import psutil
    from bandori_core import _pet_db
    output = {
        "environment": {"platform": platform.platform(), "machine": platform.machine(),
                        "python": sys.version, "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
                        "psutil": psutil.__version__, "rust": subprocess.check_output(["rustc", "--version"], text=True).strip(),
                        "extension_build": "release, workspace profile (opt-level=s, LTO=fat)",
                        "legacy_commit": "b0994b9:tests/baselines/legacy_database.py",
                        "sqlite_python": sqlite3.sqlite_version, "sqlite_rust": _pet_db.SQLITE_VERSION,
                        "memory_sampling_interval_ms": 1},
        "notes": ["Temporary databases only; normal WAL and durability defaults; fresh worker process per sample.",
                  "Latency is per request/repeat; batch latency covers 200 inserts; concurrent latency covers 400 API calls.",
                  "Batch legacy uses direct executemany because no batch API existed; Rust uses the new atomic domain API.",
                  "Search preserves LIKE substring semantics; this is not an FTS index benchmark.",
                  "Boundary probe measures Python -> owned Rust values -> Python, no SQL. It is not output-only conversion time.",
                  "RSS peak sampling can miss sub-millisecond peaks; Windows process high-water includes fixture setup.",
                  "idle_1s CPU includes the memory sampler; it is an upper bound, not isolated engine CPU."],
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
