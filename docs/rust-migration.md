# Rust + LuaJIT + Qt migration

This branch migrates BandoriPet with three fixed constraints:

- Python and Rust run in parallel until each subsystem reaches behavioral parity.
- Windows, macOS and Linux remain release targets.
- Rust owns application state and services; a thin C++ layer owns QObject/QWidget
  composition and uses `third_party/Qt-Fluent-Widgets` directly.

## Target architecture

`bandori-core` is Qt-independent and owns configuration, model metadata, database
repositories, IPC message semantics, LLM/MCP orchestration, reminders and service
lifecycle. `bandori-qt-bridge` exposes narrow Rust QObjects through CXX-Qt. Native
Qt code owns the event loop, widgets, platform window flags, MOC/RCC resources and
Qt-Fluent-Widgets composition. Each pet remains an isolated OS process with its
own LuaJIT state and OpenGL context.

LuaJIT is embedded from Rust with `mlua`'s LuaJIT backend. Existing Cubism 2 and
Cubism 3 Lua modules remain the semantic baseline. The Rust renderer supplies the
same resource callbacks, GL procedure loader and render/update split currently
provided by the Lupa adapters; MOC and MOC3 never share a runtime or renderer.

## Compatibility gates

1. `config.json` retains its current key set, legacy migrations, per-model fields,
   three-way concurrent-save behavior and durable atomic replacement.
2. `data.db` is opened in place. Schema and query fixture tests must pass against
   copies made by both implementations before Rust is allowed to write user data.
3. Shared-memory IPC keeps `BDIPC01!`, version 1, little-endian headers, slot sizes,
   JSON envelopes, reliable/lossy lanes, message names and coalescing behavior.
   Python-generated vectors under `rust/compat/` are consumed directly by Rust tests.
4. Model discovery keeps directory and `.zst` archive precedence, MOC/MOC3 format
   isolation, OUTFIT display names, motion/expression metadata and resource paths.
5. Live2D comparison covers gaze, hit areas, alpha passthrough, motion looping,
   Physics3 input/output isolation, render-only redraw, SSAA fallback and disposal.
6. UI comparison covers settings navigation, save/apply semantics, chat pagination,
   attachments, compact overlay, radial menu, system tray and theme/i18n updates.

## Delivery sequence

1. Establish the Cargo workspace, CMake/CXX-Qt bridge, Qt-Fluent smoke window and
   checked-in Python/Rust contract snapshots.
2. Port configuration, model indexing, database repositories and shared-memory IPC;
   run both implementations against generated fixtures and real read-only copies.
3. Port the LuaJIT adapters and QOpenGLWidget renderer, then replace one pet process
   behind a development flag while the Python supervisor remains available.
4. Replace the supervisor and background services, followed by settings, chat,
   compact overlay and radial-menu processes.
5. Build installers on all three platforms, run performance/leak/kill-recovery
   suites, switch the default launcher, and remove Python packaging only after the
   rollback window and parity matrix are clean.

## Build entry points

- Core checks: `cargo test -p bandori-core`
- Contract drift: `python tools/export_rust_contracts.py --check`
- Native application: `cmake -S . -B build-rust` followed by
  `cmake --build build-rust --config Release`

The native build requires Qt 6.5+ with Core, Gui, Widgets and Svg, a C++17 compiler,
Rust 1.85+, CMake 3.24+, and CXX-Qt 0.9. CMake can discover an installed CXX-Qt
package or fetch its pinned CMake integration at configure time.
