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

- Complete: Cargo/CMake/CXX-Qt foundation. The native Qt-Fluent application now
  has navigable overview, model-catalog and state pages backed by a narrow CXX-Qt
  service instead of the original smoke label. Rust merges bundled and writable
  model roots, exposes only whitelisted renderer settings (never LLM credentials),
  and supplies configured/default model launch specs to the isolated supervisor.
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
  split, quality-controlled MOC3 SSAA framebuffer/blit, and side-effect-free fallback redraw are
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
  and completed-session deduplication. `PEER_POS` broadcasts and nearest-peer
  selection now drive mutual gaze through the same global-to-logical 600 px
  clamped target used for cursor head tracking. The native child restores a
  visible saved position, accepts `PREVIEW_MOTION`, and sends reliable
  `PET_STATE` snapshots after completed drags and graceful shutdown. Both the
  Python and native supervisors persist those snapshots through the compatible
  Rust/Python atomic configuration paths without overwriting other pets. Alpha
  hit-tested single clicks now resolve per-region automatic, random, disabled,
  or explicit motion/expression feedback in Rust. Drag locking no longer
  suppresses clicks; double-clicks publish reliable `POKE_USER` events and both
  local and remote pokes receive native model/window feedback. The widget also
  exposes exact-hit right-click coordinates to a shaped native Qt radial menu.
  Its chat action bridges to the staged Python chat process, costume opens the
  settings flow, motion stays inside the Rust Live2D host, and the center lock
  persists through `PET_STATE`; pixel mode remains disabled until its renderer
  is ported. Menu open/closed lifecycle remains reliable IPC so peer z-order
  behavior can stay compatible during the dual-track migration.
  The native main application can rescan real MOC/MOC3 catalogs, select a costume,
  start/restart/stop renderers and restore every configured Live2D pet. One native
  supervisor now owns a single IPC session and independent restart state for each
  child process, so group dragging and mutual gaze cross real pet processes instead
  of being isolated by one session per pet.
  CXX-Qt generation is tested without a Qt SDK, including the generated C++
  property and invokable names.
  The settings page edits a Rust-whitelisted subset of renderer/UI options,
  persists them through the same locked atomic config path, updates the
  Qt-Fluent theme immediately, and reliably broadcasts live changes to every
  active native pet. VSync is now selected before `QApplication` creates any
  OpenGL surface; performance/balanced quality controls both Rust texture loading
  and Qt-side Cubism 3 SSAA. Changing either surface-level option restarts the
  isolated fleet, while ordinary settings remain live IPC updates. Per-model
  default motion/expression values (including `model_action_settings` fallbacks)
  cross the Rust snapshot and launch boundary, then start from the GL-ready signal;
  the configured default motion is explicitly looped by the Rust LuaJIT host.
  When no motion is configured, Rust applies the existing Idle-name rules and
  optionally rotates matching groups. A lightweight completion poll restores
  the default loop after one-shot click/IPC motions and also supplies the
  Cubism 2 compatibility path where the windowless wrapper lacks a dedicated
  `is_motion_finished` method. Temporary expressions now reset back to the
  configured or metadata-derived default instead of leaving stale feedback.
  Idle and random-action switches are writable and apply live over shared IPC.
  The global Live2D scale now preserves the Python sizing contract exactly:
  values are clamped to 25-500%, zero resolves to 100%, MOC uses a 400x500
  baseline and MOC3 uses 400x800. Native pets resize in place over IPC, so the
  OpenGL target, alpha hit testing and persisted geometry remain one window.
  Unknown fields cannot cross this write boundary.
  A cross-platform `QSystemTrayIcon` now owns the native main-process lifecycle:
  closing the control center hides it without killing pets, while the tray can
  restore the window, start/stop the configured fleet, or perform a bounded
  graceful exit.
  The first native chat surface is now wired to the compatible Rust database
  repository. It reads the existing `data.db`, filters private conversations by
  character and active user profile, selects the requested or newest thread and
  renders the latest 200 messages. History can expand in bounded 200-message
  increments up to 1000 records, with Rust reporting whether older rows remain;
  stored attachment type, name and size metadata is shown without opening paths.
  Pet radial-menu chat requests switch directly to that character. The surface
  is deliberately read-only until the LLM/tool
  orchestration path is ported, so dual-track operation cannot append orphaned
  user messages without an assistant response.
  The first transport-independent LLM protocol layer is also in Rust. The
  lightweight `bandori-llm-protocol` crate keeps database and archive native
  dependencies out of network clients while preserving the public
  `bandori-core::llm_protocol` compatibility path. It keeps
  the Python endpoint rules for Chat Completions, Responses and Google OpenAI
  compatibility, converts messages into Responses input items, builds thinking
  and tool-aware request bodies, and normalizes both SSE dialects into shared
  text, reasoning, tool-call, usage, response-id and completion events. Network
  I/O now has its own `bandori-llm` service crate: async Rust TLS transport,
  bounded SSE/error buffers, secret-redacted diagnostics, status decoding and a
  cancellation token that interrupts connect or an open stream. Local loopback
  tests exercise chunk-split UTF-8 streaming and prompt cancellation without
  contacting a real provider. The CXX-Qt backend now starts those streams on a
  named Rust worker thread, queues structured events back onto the Qt event
  loop, filters superseded request IDs and cancels work when the backend is
  destroyed. API credentials stay inside Rust and never enter QObject
  properties or event JSON. Native composer/persistence wiring and local-tool
  execution remain staged.
  Headless runtime/contract tests pass; native GL/Qt shared-memory comparison
  still awaits a workstation or CI runner with Qt 6 and a display-capable GL
  context.
- Pending: pixel pet and remaining native visual/driver parity, application
  services, full settings/chat UI replacement and packaging.

The native Qt shell has not yet been compiled on the current workstation because
no compatible Qt 6 C++ SDK/toolchain pairing is installed. Core, CXX-Qt generation
and Python compatibility checks remain independent of that local limitation.

## Build entry points

- Core checks: `cargo test -p bandori-core`
- LLM protocol and transport: `cargo test -p bandori-llm-protocol` and
  `cargo test -p bandori-llm`
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
