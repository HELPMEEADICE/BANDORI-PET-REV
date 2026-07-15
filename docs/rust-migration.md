# Rust + LuaJIT + Qt migration

This branch migrates BandoriPet with three fixed constraints:

- Python and Rust run in parallel until each subsystem reaches behavioral parity.
- Windows, macOS and Linux remain release targets.
- Rust owns application state and services; a thin C++ layer owns QObject/QWidget
  composition and uses `third_party/Qt-Fluent-Widgets` directly.

## Target architecture

`bandori-core` is Qt-independent and owns configuration, model metadata, database
repositories, IPC message semantics, LLM/MCP orchestration, reminders and service
lifecycle. `bandori-live2d` is also Qt-independent and owns one isolated LuaJIT
state plus renderer per pet. `bandori-qt-bridge` exposes narrow Rust QObjects
through CXX-Qt. Native Qt code owns the event loop, widgets, platform window flags,
MOC/RCC resources and Qt-Fluent-Widgets composition. Each pet remains an isolated
OS process with its own LuaJIT state and OpenGL context.

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

## Current branch status

- Complete: Cargo/CMake/CXX-Qt foundation and the native Qt-Fluent smoke shell.
- Complete: configuration, shared-memory IPC and model discovery compatibility
  cores, with Python-generated fixtures consumed by Rust tests.
- Complete: `data.db` repositories. The schema, legacy column migrations,
  cross-process lock, WAL mode, private/group message pagination, token accounting,
  relationship state/events, long-term memories, usage sessions, external-chat
  retention/unread state, group labels, cascade deletion and attachment-path
  sanitization are available in `bandori-core`. History search/filtering, group
  lists, daily/hourly analytics, character-album aggregation and atomic SQLite
  backup/restore are also ported.
- In progress: the Rust LuaJIT host, secure directory/`.zst` resource loader,
  MOC/MOC3 runtime isolation, Qt GL-procedure callback, logical/physical resize
  split, 2x MOC3 SSAA framebuffer/blit, and side-effect-free fallback redraw are
  implemented. The native
  `bandori-pet-renderer-rust` executable provides the isolated QOpenGLWidget pet
  process boundary. The Qt supervisor now owns compatible `BDIPC01!` shared
  memory queues through Rust queue C ABI calls, performs REGISTER/UNREGISTER and
  SHUTDOWN handshakes, watches the parent PID, and uses a capped restart backoff.
  ACTION messages now resolve MOC/MOC3 motion and expression metadata in Rust;
  LIP messages apply the existing 180 ms hold, smoothing and configurable mouth
  limit through persistent host parameters. Cubism 2 metadata is parsed directly
  from the model manifest, so it does not depend on a Cubism 3-only Lua helper.
  The native window now samples one physical framebuffer pixel at 16 ms intervals
  for alpha input passthrough, retains the existing threshold and short hit grace,
  and supports locked/local dragging. Optional group dragging sends cumulative
  `PEER_DRAG` updates and a reliable final state, including message-loss recovery
  and completed-session deduplication.
  Headless runtime/contract tests pass; native GL/Qt shared-memory comparison
  still awaits a workstation or CI runner with Qt 6 and a display-capable GL
  context.
- Pending: mutual gaze/peer position and higher-level pet interactions, native
  visual/driver parity, application services, full UI replacement and packaging.

The native Qt shell has not yet been compiled on the current workstation because
no Qt SDK/C++ toolchain is installed. Core and Python compatibility checks remain
independent of that local limitation.

## Build entry points

- Core checks: `cargo test -p bandori-core`
- Live2D host checks: `cargo test -p bandori-live2d`
- Contract drift: `python tools/export_rust_contracts.py --check`
- Native application: `cmake -S . -B build-rust` followed by
  `cmake --build build-rust --config Release`

The Python supervisor keeps the Python pet as the default. To replace only the
pet renderer during the compatibility window, set
`BANDORI_PET_NATIVE_RENDERER=1`. Set `BANDORI_PET_NATIVE_RENDERER_PATH` when the
native executable is outside the standard `build-rust` locations. Failure to
find the helper logs a warning and safely falls back to the Python renderer.

The native build requires Qt 6.5+ with Core, Gui, Widgets, OpenGLWidgets and Svg,
a C++17 compiler, Rust 1.85+, CMake 3.24+, and CXX-Qt 0.9. CMake can discover an
installed CXX-Qt package or fetch its pinned CMake integration at configure time.
GNU-target Windows builds of vendored LuaJIT also require a `make` command (the
MSYS2 `mingw32-make` binary can be exposed under that name); MSVC builds use the
LuaJIT MSVC path instead.
