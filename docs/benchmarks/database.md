# Database benchmark results

Windows-10-10.0.19045-SP0 (AMD64), CPython 3.14.6, rustc 1.98.1 (48a229cea 2026-09-01) (Rev1, Built by MSYS2 project), release profile. 3 alternating rounds; 10,000 seeded messages and 1,000 memories. Python SQLite 3.50.4; bundled Rust SQLite 3.54.1. Results include file locking, SQLite and boundary conversion, so differences cannot be attributed solely to language.

| Workload | Python throughput/s | Rust throughput/s | Rust / Python |
|---|---:|---:|---:|
| insert | 2048.3 | 3625.7 | 1.77x |
| history_200 | 1810.9 | 5127.2 | 2.83x |
| substring_search | 494.9 | 473.5 | 0.96x |
| memory_50 | 3171.0 | 4152.9 | 1.31x |
| batch_200 | 128469.2 | 149276.4 | 1.16x |
| concurrent_4 | 2194.0 | 3860.7 | 1.76x |

Throughput counts messages for batch writes and individual API calls for concurrency. Latency below is per repeat (200 inserts for a batch; 400 API calls for concurrency). The legacy batch uses direct sqlite3 executemany because the old public API had no bulk method.

| Workload | Backend | p50 ms | p95 ms | CPU seconds | Baseline RSS MiB | Sampled peak RSS MiB |
|---|---|---:|---:|---:|---:|---:|
| insert | legacy | 0.456 | 0.687 | 0.1406 | 29.00 | 29.45 |
| insert | rust | 0.248 | 0.440 | 0.0781 | 29.30 | 29.51 |
| history_200 | legacy | 0.547 | 0.617 | 0.1719 | 28.91 | 29.18 |
| history_200 | rust | 0.196 | 0.211 | 0.0625 | 29.33 | 29.67 |
| substring_search | legacy | 2.006 | 2.230 | 0.1562 | 29.09 | 29.39 |
| substring_search | rust | 2.117 | 2.220 | 0.1719 | 29.25 | 30.06 |
| memory_50 | legacy | 0.314 | 0.366 | 0.1562 | 29.00 | 29.16 |
| memory_50 | rust | 0.244 | 0.254 | 0.1250 | 29.31 | 29.67 |
| batch_200 | legacy | 1.391 | 1.919 | 0.0469 | 29.09 | 29.27 |
| batch_200 | rust | 1.197 | 1.515 | 0.0312 | 29.23 | 29.76 |
| concurrent_4 | legacy | 185.891 | 195.695 | 0.6250 | 29.97 | 30.46 |
| concurrent_4 | rust | 105.243 | 117.698 | 0.0781 | 29.98 | 30.43 |
| idle_1s | legacy | 1000.069 | 1000.069 | 0.0000 | 29.10 | 29.19 |
| idle_1s | rust | 1000.088 | 1000.088 | 0.0000 | 29.35 | 29.45 |
| boundary_roundtrip_200 | rust | 0.535 | 0.569 | 0.2656 | 29.34 | 30.23 |

- Substring search retains legacy LIKE semantics; it is not an FTS index. Median throughput regressed 4.3%.
- The conversion probe measures a 200-message Python-to-Rust-to-Python round trip without SQL. History queries use a specialized typed output path; the probe is not an exact output-only cost attribution.
- RSS is sampled every 1 ms and can miss shorter peaks. Windows process high-water values, including fixture setup, are also recorded in the raw data.
- Idle CPU includes the sampler and Windows timer granularity; a recorded zero is not proof of zero instructions. There are no engine worker threads or timers.
- These are local microbenchmarks, not a cross-platform production workload guarantee.

[Raw samples and environment](database.json). Reproduce with `python tools/build_db.py` and `python tools/benchmarks/database_benchmark.py`.
