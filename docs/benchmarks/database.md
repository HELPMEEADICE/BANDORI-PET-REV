# Database benchmark results

Windows-10-10.0.19045-SP0 (AMD64), CPython 3.14.6, rustc 1.98.1 (48a229cea 2026-09-01) (Rev1, Built by MSYS2 project), release profile. 3 alternating rounds; 10,000 seeded messages and 1,000 memories. Python SQLite 3.50.4; bundled Rust SQLite 3.54.1. Results include file locking, SQLite and boundary conversion, so differences cannot be attributed solely to language.

| Workload | Python throughput/s | Rust throughput/s | Rust / Python |
|---|---:|---:|---:|
| insert | 1944.6 | 3388.4 | 1.74x |
| history_200 | 1773.8 | 4978.0 | 2.81x |
| substring_search | 483.4 | 461.8 | 0.96x |
| memory_50 | 2997.4 | 4035.2 | 1.35x |
| batch_200 | 125323.2 | 130943.5 | 1.04x |
| concurrent_4 | 1998.7 | 3417.7 | 1.71x |

Throughput counts messages for batch writes and individual API calls for concurrency. Latency below is per repeat (200 inserts for a batch; 400 API calls for concurrency). The legacy batch uses direct sqlite3 executemany because the old public API had no bulk method.

| Workload | Backend | p50 ms | p95 ms | CPU seconds | Baseline RSS MiB | Sampled peak RSS MiB |
|---|---|---:|---:|---:|---:|---:|
| insert | legacy | 0.490 | 0.715 | 0.2500 | 29.36 | 29.73 |
| insert | rust | 0.268 | 0.483 | 0.1094 | 29.54 | 29.79 |
| history_200 | legacy | 0.550 | 0.663 | 0.1562 | 29.36 | 29.67 |
| history_200 | rust | 0.201 | 0.210 | 0.0625 | 29.53 | 29.89 |
| substring_search | legacy | 2.046 | 2.240 | 0.1719 | 29.45 | 29.71 |
| substring_search | rust | 2.146 | 2.295 | 0.1719 | 29.60 | 30.37 |
| memory_50 | legacy | 0.319 | 0.426 | 0.1719 | 29.41 | 29.56 |
| memory_50 | rust | 0.248 | 0.273 | 0.1250 | 29.61 | 29.87 |
| batch_200 | legacy | 1.406 | 1.952 | 0.0312 | 29.52 | 29.77 |
| batch_200 | rust | 1.325 | 1.875 | 0.0312 | 29.60 | 30.09 |
| concurrent_4 | legacy | 201.566 | 221.930 | 0.7500 | 30.30 | 30.79 |
| concurrent_4 | rust | 116.257 | 127.673 | 0.2188 | 30.17 | 30.64 |
| idle_1s | legacy | 1000.131 | 1000.131 | 0.0000 | 29.32 | 29.41 |
| idle_1s | rust | 1000.462 | 1000.462 | 0.0000 | 29.51 | 29.61 |
| boundary_roundtrip_200 | rust | 0.538 | 0.573 | 0.2656 | 29.84 | 30.73 |

- Substring search retains legacy LIKE semantics; it is not an FTS index. Median throughput regressed 4.5%.
- The conversion probe measures a 200-message Python-to-Rust-to-Python round trip without SQL. History queries use a specialized typed output path; the probe is not an exact output-only cost attribution.
- RSS is sampled every 1 ms and can miss shorter peaks. Windows process high-water values, including fixture setup, are also recorded in the raw data.
- Idle CPU includes the sampler and Windows timer granularity; a recorded zero is not proof of zero instructions. There are no engine worker threads or timers.
- These are local microbenchmarks, not a cross-platform production workload guarantee.

[Raw samples and environment](database.json). Reproduce with `python tools/build_db.py` and `python tools/benchmarks/database_benchmark.py`.
