# Native Music Bounce

## Audit and migration design

Baseline: `main` before `refactor/rust-native-music-bounce`. The production
`NativePetServices._poll` runs every 30 ms, starts one Python Core Audio worker
(60 Hz), maintains one Python spring per role and broadcasts one JSON
`music_scale` per role per poll. Each role is a separate native process.
`MusicBounceController` has no production callers; its 16 ms timer and per-window
monitor are legacy test-only interfaces. Configuration defaults to false on all
platforms; only Windows supports output metering.

The native executable gains a non-graphical `--music-service PATH` mode, managed
by Python through QProcess. One service serves all roles belonging to that main
application session. Its stdin pipe is the lifetime lease (EOF ends sampling).
No Python interpreter, GUI, GPU or audio stream capture is initialized in this mode.
Reusing the packaged executable covers source, frozen Windows, Linux and macOS
layouts without a second payload. Non-Windows output metering remains unsupported.

`pet-ipc` supplies a fixed latest-value mapping using its existing owner/lease
locks and last-participant cleanup. Python announces only source changes over
the existing reliable control lane; peaks never travel through Python. A new
random path per service generation prevents reconnecting to stale mappings.
Each role advances its independent f64 MusicSpring in the existing frame loop,
then uses the existing matrix setter for drawing and inverse hit testing.
All constants, time-step cap, substeps and scale limits retain the Python baseline.
The Python oracle is frozen under tests/baselines, never imported by production.

Implementation, verification and benchmark results are recorded below as work
completes.
