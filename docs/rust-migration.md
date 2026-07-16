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
  of three tool rounds for `poke_user`, `create_alarm`, `start_pomodoro`,
  `web_search` and `web_fetch`,
  persists sanitized tool traces, and delivers pet/reminder effects through the
  reliable native IPC lane. The web tools are configured from the redacted
  Qt-Fluent LLM page and execute asynchronously in Rust with cancellation,
  public-DNS validation, per-redirect revalidation, DNS pinning, proxy bypass,
  textual-content checks and bounded response bodies. Generic MCP orchestration
  is native too: HTTP JSON-RPC and stdio servers initialize on the LLM worker,
  discover bounded tool schemas, preserve session/protocol headers, enforce
  allowed-tool and approval policies, propagate cancellation, and return
  bounded text/structured results. OpenAI Responses may instead receive
  provider-native MCP definitions when the server requires no approval;
  Chat Completions and other endpoints use the local proxy definitions.
  Computer Use is native on the chat worker path as well. Rust owns dynamic tool
  definitions, saved-permission revalidation, bounded rounds, cancellation,
  timeout handling and result filtering; a CXX-Qt request/response broker performs
  desktop capture and input on the Qt main thread. Screenshots return as bounded
  PNG data URLs with virtual-desktop origin/scale metadata so follow-up mouse
  coordinates map correctly across scaled and negative-origin displays. The
  Qt-Fluent page keeps screenshot, mouse, keyboard, clipboard and wait permissions
  opt-in, while the system prompt blocks purchases, deletion, messaging,
  publishing, login and security-setting changes. Windows has native pointer,
  click, wheel and Unicode/shortcut injection. Non-Windows builds currently fail
  closed for global click/keyboard injection; capture, pointer move, clipboard and
  cancellable wait remain available there. The database layer now also starts private chat
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
  JSON through CXX-Qt without exposing the API key. Event-calendar context,
  Computer Use, web/MCP tools, group prompts and the other
  supported native local tools are included in the current path. Completed
  responses are cleaned with Python-generated
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
  confirmation and blocks restore while a chat response is active. The same
  Qt-Fluent page now reports attachment file count, size and upload range, saves
  a bounded 1-3650 day retention policy, and offers confirmed expired/all-file
  cleanup. Rust scopes every scan and deletion to `chat_attachments` beside the
  selected `data.db`, sanitizes broken private/group message references, and can
  run the saved policy once at native startup.
  Native TTS is now owned by the Rust `bandori-tts` transport and a whitelisted
  core settings boundary. It preserves GPT-SoVITS reference-audio, Japanese
  prompt and optional LoRA metadata, strips action/source metadata, bounds text
  and audio, supports cancellation, parses framed OGG incrementally and retries
  incompatible streaming endpoints once with WAV. CXX-Qt carries structured
  metadata plus binary audio without JSON/base64 expansion. The Qt-Fluent page
  edits and tests the service; Qt Multimedia queues temporary OGG/WAV chunks,
  chat and reminder completions trigger serialized synthesis, and playback drives
  the existing native `LIP` lane for approximate mouth motion. Optional
  non-Chinese translation uses the auxiliary LLM and safely falls back to the
  original line.
  Native ASR now records with Qt Multimedia, prefers 16 kHz mono signed PCM,
  falls back to the input device's supported format, and writes a bounded WAV
  container without Python audio libraries. The Rust `bandori-asr` transport
  normalizes OpenAI-compatible transcription routes, builds bounded multipart
  requests, keeps Bearer credentials out of QObject state and parses compatible
  `text`, `transcript`, `result` or segmented responses. The Qt-Fluent settings
  page preserves blank secrets, supports language, append/replace, duration and
  auto-send behavior, while the chat page exposes a record/stop voice control.
  The legacy faster-whisper installer remains usable as an external compatible
  local endpoint; replacing that Python-managed installer with a packaged native
  offline sidecar belongs to distribution work rather than the GUI process.
  Native screen awareness now persists its whitelisted schedule, character,
  capture, model, delivery and privacy controls through Rust and synchronizes the
  interval with the shared proactive-care cooldown. Qt composites every display,
  scales the longest edge to 640-1920 px, PNG-encodes within a 24 MiB bound and,
  on Windows, adds only the explicitly enabled foreground process/title fields.
  A single-shot timer prevents overlapping captures. Rust supplies persona and
  relationship context, supports direct main-model vision or an auxiliary-model
  summary with main-model image fallback, honors cancellation and `NO_SPEAK`, and
  returns only bounded text/actions. Qt then routes the result through the native
  system tray or floating pet event and the existing TTS/LIP queue.
  Native special events now load the bounded birthday and festival databases in
  Rust, append character-aware daily context to private chat, group chat and
  screen awareness, and safely handle recurring leap-day entries. Qt polls once
  at startup and after each local midnight, shows festival tray notices and
  optionally birthday notices, with that preference persisted through the
  whitelisted native settings boundary. No Python timer or event-calendar helper
  remains on this runtime path.
  Pixel pets now run inside the same isolated native Qt renderer as Live2D pets.
  Qt validates and animates the bounded `pixels/frames.json` sprite sheet,
  preserves nearest-neighbor drawing and alpha hit testing, performs autonomous
  screen-bounded wandering, and exposes live Live2D/pixel switching through the
  native radial menu. The Rust config boundary persists `pet_mode` and separate
  pixel coordinates without overwriting the corresponding Live2D geometry; the
  compatibility Python supervisor passes the same mode and position contract.
  Native local HTTP integrations now run in `bandori-core` instead of Python.
  Fixed worker pools listen only on `127.0.0.1`, bound request headers/bodies and
  apply five-second I/O timeouts, constant-time bearer/header/query-token checks,
  and the compatible JSON/form/text/query endpoints. The chat webhook normalizes
  OneBot messages, writes duplicate-safe unread state through the Rust database,
  emits compact pet overlays, and clears persisted unread state only through
  `/chat-read`; the AI status webhook forwards authenticated objects through the
  same reliable native IPC lane. Qt-Fluent-Widgets exposes redacted settings,
  atomically saves or generates tokens, restarts both services, and stops them
  during application shutdown. The native pet now consumes `CHAT_EVENT` and
  `AI_EVENT`, including targeted actions, compact bubbles and explicit clear
  events, without routing through a Python process.
  The NapCat forward-WebSocket adapter is also native. Qt WebSockets owns the
  authenticated `ws://`/`wss://` connection, bounded incoming messages and
  three-second reconnect timer; Rust owns OneBot normalization, self-message
  suppression, duplicate-safe persistence, overlay-only/private-only policies,
  per-chat retention, @self reply eligibility and an independent cancellable
  LLM reply lane. Outbound private/group actions reuse the same socket, optional
  sender mentions and action-tag stripping as the Python implementation. The
  Qt-Fluent-Widgets page saves redacted NapCat settings and stops both socket
  and reply workers during shutdown.
  Native distribution entry points are now present for all release targets.
  CMake installs the control center, sibling renderer, Qt runtime dependencies,
  Qt-Fluent resources and the minimal trusted Live2D Lua module tree, then CPack
  produces ZIP/NSIS on Windows, DragNDrop on macOS, and TGZ/DEB on Linux. The two
  third-party source trees are pinned outer-repository submodules so a clean clone
  is buildable. Packaged applications discover their read-only resource root
  relative to the executable or app bundle, while `config.json`, `data.db`, chat
  attachments and downloaded models use Qt's writable AppData location. Explicit
  `--project-root`, `--data-root`, `--config` and `--user-models` overrides keep
  source-tree and portable workflows available. Repository models are excluded by
  default to avoid an accidental 1.4 GB package and can be included deliberately
  with `-DBANDORI_PET_PACKAGE_BUNDLED_MODELS=ON`.
  Headless runtime/contract tests pass; native GL/Qt shared-memory comparison
  still awaits a workstation or CI runner with Qt 6 and a display-capable GL
  context.
- Pending: remaining native visual/driver parity, non-Windows Computer Use input
  drivers, packaged offline ASR sidecar, default-launcher cutover, release
  signing/notarization and multi-platform package validation.

The native Qt shell has not yet been compiled on the current workstation because
no compatible Qt 6 C++ SDK/toolchain pairing is installed. Core, CXX-Qt generation
and Python compatibility checks remain independent of that local limitation.

## Build entry points

- Core checks: `cargo test -p bandori-core`
- LLM protocol and transport: `cargo test -p bandori-llm-protocol` and
  `cargo test -p bandori-llm`
- TTS transport: `cargo test -p bandori-tts`
- ASR transport: `cargo test -p bandori-asr`
- Live2D host checks: `cargo test -p bandori-live2d`
- Contract drift: `python tools/export_rust_contracts.py --check`
- Native application: `cmake -S . -B build-rust` followed by
  `cmake --build build-rust --config Release`
- Native packages: `cmake --build build-rust --config Release --target package`.
  The platform generator emits ZIP/NSIS, DragNDrop, or TGZ/DEB artifacts under
  `build-rust`. Add `-DBANDORI_PET_PACKAGE_BUNDLED_MODELS=ON` at configure time
  only for a deliberately model-inclusive release.

Initialize the pinned native dependencies before configuring a clean checkout:

```bash
git submodule update --init --recursive
```

The Python supervisor keeps the Python pet as the default. To replace only the
pet renderer during the compatibility window, set
`BANDORI_PET_NATIVE_RENDERER=1`. Set `BANDORI_PET_NATIVE_RENDERER_PATH` when the
native executable is outside the standard `build-rust` locations. Failure to
find the helper logs a warning and safely falls back to the Python renderer.

The native build requires Qt 6.5+ with Core, Gui, Widgets, Multimedia,
OpenGLWidgets, Svg and WebSockets,
a C++17 compiler, Rust 1.85+, CMake 3.24+, and CXX-Qt 0.9. CMake can discover an
installed CXX-Qt package or fetch its pinned CMake integration at configure time.
GNU-target Windows builds of vendored LuaJIT also require a `make` command (the
MSYS2 `mingw32-make` binary can be exposed under that name); MSVC builds use the
LuaJIT MSVC path instead.
