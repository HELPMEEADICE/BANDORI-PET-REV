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
  Its chat action opens the native control-center chat flow, costume opens the
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
  now includes a multiline composer, Ctrl+Enter/send controls, cancellation,
  reasoning/text stream preview and terminal persistence. Character and
  conversation selectors are frozen while a request is active; failures and
  cancellations leave the already-saved user turn visible instead of losing it.
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
  properties or event JSON. The native chat loop now executes a bounded maximum
  of three tool rounds for `poke_user`, `create_alarm` and `start_pomodoro`,
  persists sanitized tool traces, and delivers pet/reminder effects through the
  reliable native IPC lane. Generic MCP, web and computer-use tools remain
  staged. The database layer now also starts private chat
  turns transactionally, validates that a selected conversation belongs to the
  active character/user pair, and binds a successful streamed request back to
  that conversation before the Qt bridge may save its assistant response and
  token-usage trace. Character/system prompt composition is now native as well:
  Python exports the built-in personas, action rules and exact prompt fixtures;
  Rust safely loads direct per-character Markdown files through `outfit.json`,
  applies custom persona/system/POV, outfit and MOC3 rules, and reproduces the
  relationship/mood/memory wording from Python-generated fixtures. A native
  request builder verifies conversation ownership, applies the compatible
  0-or-2..100 history limit, appends relationship and Qt-formatted current-time
  context only to the latest user message, and exposes the resulting request
  JSON through CXX-Qt without exposing the API key. Event-calendar context and
  generic MCP/web/computer-use tools remain staged rather than being silently
  approximated; group prompts and the supported native local tools are included
  in the current path. Completed responses are cleaned with Python-generated
  action-tag fixtures before persistence; parsed actions cross the reliable native IPC lane
  to the matching Live2D process. Empty active-profile keys also normalize to
  Python's `__default__` user partition. Request state retains the exact
  character, user partition and latest user turn entirely inside Rust until the
  terminal response is saved; the Python-compatible fallback interaction
  analyzer applies affection, trust, familiarity, mood and intensity deltas to
  the same relationship row when no memory model is configured. Model-assisted
  long-term memory extraction is now the native post-response stage as well.
  Python-generated fixtures pin its full system prompt, saved-memory context,
  tolerant JSON parsing, bounds, scopes and superseded-memory aliases. Rust uses
  the auxiliary LLM profile with primary-profile fallback on a cancellable worker,
  writes successful relationship analysis as `chat_model`, replaces exact stale
  global/character memory lines, and associates new memories with the source user
  message. A transport or startup failure applies the heuristic relationship
  update exactly once; it is never pre-applied and then doubled by a late model
  result. A cancelled extraction skips fallback and persistence once cancellation
  is observed, including the normal backend-destruction path.
  Native private chat attachments are now supported end to end: Rust copies
  selected local files into the compatible `chat_attachments` root with a 25 MB
  per-file bound and create-new names, refuses references outside that root, and
  owns cleanup of unsent native copies. Qt exposes selection, pending-file status
  and clear/send controls without reading file content itself. Request composition
  inlines bounded UTF-8 text-file previews and only emits raw image data URLs for
  the latest user message, so historical images are not repeatedly expanded.
  Cross-chat context is also native and pinned to a Python-generated fixture:
  Rust reads at most three recent private conversations and 24 relevant group
  chats for the active user partition, compacts attachment counts, preserves
  speaker labels, globally orders excerpts by timestamp/id and keeps the latest
  18 entries. Unrelated group members and other user profiles never cross into
  the prompt.
  The native private-chat page can draft a new conversation without creating an
  empty database row, then creates it transactionally on first send. Saved
  conversations can be deleted only after Rust verifies the selected character
  and user partition; cascading message deletion is followed by canonical-root
  cleanup of deduplicated attachment copies.
  The native group-chat core now preserves Python-owned behavior through generated
  fixtures for canonical member keys, group-only system rules, scheduler JSON
  parsing, priority-speaker ordering and single-speaker reply cleanup. Group user
  turns are inserted atomically into an exact user/group partition, planner and
  per-speaker prompts read only that partition, group history is paginated, and
  safe deletion also removes copied attachments. Qt orchestration for the planner
  and sequential speaker streams now has a generated CXX-Qt bridge contract:
  planner and speaker requests have distinct cancellable states, a prepared group
  turn survives across sequential speakers, and each saved response keeps its
  speaker label, Live2D actions, relationship update and group-message memory
  source. The Qt control center now exposes private/group mode, saved-group switching,
  multi-select member composition and shared conversation history controls. A
  group send persists its user turn, runs the auxiliary planner with fallback,
  streams each selected speaker sequentially, refreshes history between speakers,
  dispatches actions to that speaker's pet and keeps the whole sequence locked
  behind one cancelable busy state. This UI path is generation/static tested but
  still awaits a Qt 6 SDK for a native compile and interactive run.
  Reminder ownership is now native too. Rust validates and persists alarms and
  Pomodoro sessions, runs the reminder service, routes notification actions and
  supports add/toggle/delete management from a Qt-Fluent settings page. Chat tool
  calls use that same core instead of a parallel Qt implementation.
  LLM settings and profiles now have a separate Qt-Fluent page backed by Rust.
  Provider URLs, protocol modes, history/prompt bounds and primary/auxiliary
  profile selection are validated in the core. Secret fields are write-only:
  blank edits preserve an existing key, explicit clear removes it, and neither
  summaries nor QObject properties expose stored credentials. Provider model
  discovery and connection probes also run natively on background workers. They
  reuse the Rust URL/authentication contract, enforce 30-second and bounded JSON
  limits, and fall back from an unsupported Responses probe to Chat Completions;
  the Qt page exposes separate primary and auxiliary model selectors.
  Relationship state and scoped long-term memory can now be inspected and edited
  from the native memory page. Rust enforces the selected character/user scope,
  including the compatible `__global__` scope, and the page refreshes after chat
  memory analysis. Native user-profile create/edit/activate/delete support keeps
  stable profile keys, synchronizes the legacy top-level identity fields and
  immediately refreshes chat and memory partitions when the active user changes.
  POV and character-persona management is native as well. Rust normalizes custom
  POV presets and per-character persona collections, owns activation and atomic
  CRUD, loads read-only default Markdown previews, and enforces the compatible
  `__role__:<character>` chat/relationship/memory partition when role POV is
  active. The Qt-Fluent page also imports local Markdown/text documents without
  moving configuration rules into C++.
  A separate native history-search page now queries private and group messages
  through one Rust database path. Keyword, calendar-date, character/member,
  user-partition, speaker and source filters are bounded and whitelisted, with
  count-aware 50-row pagination in Qt. Character album-chain ordering also uses
  the latest matching speaker message, so a later reply from another group
  member cannot reorder the selected character's conversation chain.
  Native statistics now aggregate relationship events, application usage,
  per-character and daily message counts, and a seven-day hourly heatmap for the
  active user/role partition. The Qt-Fluent page renders these through standard
  tables and cards, so the native SDK requirement does not grow to include the
  optional Qt Charts module; group messages remain attributed through validated
  character display aliases. Native data management now exports and imports the
  same whitelisted settings categories as the Python page, including merged
  relationship/memory data. Rust strips root and nested API keys plus integration
  tokens on export and preserves local secrets on import. Complete SQLite backup
  and restore use the existing locked backup API; Qt requires destructive-action
  confirmation and blocks restore while a chat response is active.
  Headless runtime/contract tests pass; native GL/Qt shared-memory comparison
  still awaits a workstation or CI runner with Qt 6 and a display-capable GL
  context.
- Pending: pixel pet and remaining native visual/driver parity; TTS, ASR,
  screen-awareness and remaining integration services; the remaining
  attachment-retention controls; default-launcher cutover, packaging and
  multi-platform validation.

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
