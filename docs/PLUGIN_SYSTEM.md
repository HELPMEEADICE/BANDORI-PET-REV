# BandoriPet plugin system

BandoriPet 3.1.4 exposes plugin API 1.0. Plugins are installed from a directory, a
`.bdplugin` ZIP, or a public HTTP/HTTPS URL. There is no market and updates are never
installed silently.

## Execution modes

- `managed`: Python and Lua. Every plugin has a dedicated `plugin_worker` process and
  reaches the application through permission-checked JSON-RPC capabilities. Managed
  Python blocks common direct imports and operations, but this is defense in depth,
  not an adversarial Python sandbox.
- `native`: Python only. An entrypoint is imported in each named target process and is
  given its `QApplication`, window/controller and selected host objects. Native code
  has complete host authority. Enable, disable, update, and rollback take effect after
  the target process restarts.

Start the application with `--safe-mode` to suppress all third-party managed and native
plugins. `BANDORI_PET_PLUGIN_HOME` overrides the platform user-data plugin directory.

## Package manifest

The package root must contain `plugin.json`:

```json
{
  "schema_version": 1,
  "id": "com.example.plugin",
  "name": "Example",
  "version": "1.0.0",
  "api": ">=1.0,<2.0",
  "app": ">=3.1.4,<4.0",
  "language": "python",
  "execution": "managed",
  "entrypoints": {"worker": "main.py"},
  "permissions": {},
  "platforms": ["windows", "macos", "linux"],
  "update_url": "https://example.com/update.json"
}
```

Managed packages have exactly one `worker` entrypoint. Native Python packages instead
use one or more of `main`, `pet`, `chat`, `settings`, and `radial`. Vendored Python
source belongs in `vendor/`; managed packages reject bytecode and native extensions.

Package limits are 256 MiB compressed, 1 GiB expanded, 20,000 files, and 256 MiB per
file. Archive paths are normalized and checked for traversal, symlinks, reserved names,
Unicode/case collisions, and size expansion before extraction.

## Lifecycle and SDK

Python:

```python
def activate(ctx):
    ctx.log.info("started")

def deactivate(reason):
    pass
```

Lua returns a table with `activate(ctx)` and optional `deactivate(reason)`. Lua calls
Python-backed API methods with dot syntax, for example `ctx.storage.set("key", value)`.

`ctx` exposes:

- `events.on(name, callback, priority=0)`, `off(id)`, `emit(name, payload)`
- `services.call(name, payload)`, `call_next(name, payload)`,
  `register(name, handler, ...)`, `unregister(...)`
- `commands.register(spec, handler)` and `tools.register(spec, handler)`
- `ui.register(spec)`, `update(id, patch)`, `remove(id)`
- `storage.get/set/delete/keys`
- `network.request({method, url, headers, body/body_base64})` for GET, HEAD, POST,
  PUT, PATCH, and DELETE
- `filesystem.read_text/write_text/list`
- `temporary.read/release` for authorized large-response references
- `log.debug/info/warning/error`

Before-events run serially by descending priority, then plugin ID and subscription ID.
A handler may return `{"action":"continue","patch":{...}}`,
`{"action":"cancel","reason":"..."}`, or `null`. Patches use JSON merge-patch
semantics. Interactive hooks time out after 500 ms; commands, tools, services and
providers time out after 10 seconds. Three faults within ten minutes trip the circuit
breaker and disable the plugin.

Implemented stable event families include:

- `app.started`, `app.shutdown`, `config.write.before`, `config.written`
- `settings.apply.before`
- `pet.click.before`, `pet.clicked`, `pet.motion.before`, `pet.motion.started`,
  `pet.position.changed`
- `chat.message.before`, `chat.message.sent`, `llm.prompt.before`,
  `llm.request.before`, `llm.response.before`, `llm.response.received`
- `chat.message.received`, `tts.request.before`, `tts.audio.ready`,
  `tts.playback.finished`, `asr.request.before`, `asr.result.before`,
  `asr.result.received`
- `tray.action.before`, `tray.action`, `radial.action.before`, `radial.action`,
  `chat.action.before`, `chat.action`, `pet.overlay.action.before`,
  `pet.overlay.action`, `ui.changed`

Core services currently include `app.info`, `config.get`, `config.set`, `app.quit`,
`windows.open_chat`, `windows.open_settings`, `pet.reload`, `pet.info`,
`pet.motion.play`, `pet.expression.set`, `pet.position.set`, `pet.visibility.set`,
`chat.info`, `chat.send`, `chat.message.local`, `chat.interrupt`, and `settings.info`.
Component services are available whenever that component process is running.

Commands declare `name` and/or `triggers`; the chat window invokes their handler with
`text`, `arguments`, `character`, and `group`. Registered services are priority ordered
and can replace a lower-priority core/provider implementation. A wrapper calls
`ctx.services.call_next` to delegate to the next implementation in that priority chain.

## Declarative UI

`ui.register` accepts `schema_version: 1`. Current locations are `settings_page`,
`tray`, `radial_menu`, `chat_action`, and `pet_overlay`. A settings page has `title`,
optional `description`, and `children`.
Supported control types are `group`, `text`, `switch`, `number`, `select`, `color`,
`file`, and `button`. Changes emit `ui.changed` with plugin/component/control IDs and
the JSON value. Radial items accept `label`, `glyph`, RGB `color`, and `enabled`.

Native Python receives `activate_native(host)`. `host.api` is the regular SDK and
`host.application`, `host.controller`, `host.window`, and `host.objects` expose the
target process directly. A returned callable or `deactivate_native(reason)` is used for
clean teardown. A settings-target native plugin may call
`host.register_widget_factory("settings_page", factory)`; the factory receives the
parent widget and returns a process-local `QWidget`.

## Permissions

Permissions default to denied. Common declarations are:

```json
{
  "events": {"observe": true, "intercept": true, "emit": true},
  "config": {"read": true, "write": true},
  "pet": {"read": true, "control": true},
  "chat": {"read": true, "send": true, "write": true, "control": true},
  "commands": {"register": true},
  "services": {"register": true},
  "llm": {"tools": true},
  "ui": {"settings_page": true, "radial_menu": true},
  "network": {"origins": ["https://api.example.com", "https://*.example.org"]},
  "filesystem": {"read": ["$PLUGIN_DATA"], "write": ["$PLUGIN_DATA"]}
}
```

Private JSON storage needs no permission and is limited to 1 MiB. Network traffic is
restricted to public HTTP(S), revalidates DNS and every redirect, strips credentials on
cross-origin redirects, and has a 16 MiB response limit. Responses above 1 MiB use a
ten-minute authorized temporary reference with 512 KiB chunk reads. Text filesystem
operations have a 2 MiB limit. Native manifests are
intent documentation only and cannot constrain native code.

Managed settings/configuration events replace token, password, API-key and secret
values with opaque markers. The host restores the original values after event patches;
reading secrets is only available through an explicitly granted `secrets.read`
capability. Native plugins are not redacted.

## Scan and signing

Every install/update performs structural, Python AST, Lua lexical, binary, encoded
payload, secret, URL, and declared-vs-inferred permission checks. Reports contain the
scanner version, package SHA-256, severity, rule, file, line, evidence, inferred
permissions, and remediation. Managed high-risk boundary bypasses block activation;
authors must remove them or explicitly publish a native Python plugin.

Signed packages contain:

- `META-INF/files.json`: canonical JSON with `algorithm: sha256`, publisher, and a map
  of every non-signature payload path to its SHA-256.
- `META-INF/public_key.ed25519`: raw/base64/PEM Ed25519 public key.
- `META-INF/signature.ed25519`: raw or base64 signature over the exact `files.json`
  bytes.

An incomplete or invalid signature blocks installation. Unsigned packages can be
installed only after a warning. Once the user trusts a publisher fingerprint, a broken
signature cannot be bypassed.

An update descriptor is HTTPS JSON containing `id`, `version`, `package_url`, and
`sha256`. Checking is read-only; installation repeats download, signature, scan,
permission review, and explicit confirmation. The previous version remains available
for rollback, while uninstall retains `data/<plugin-id>` unless the user explicitly
requests deletion.

## Examples

See `examples/plugins/python_managed`, `examples/plugins/lua_managed`, and
`examples/plugins/python_native`. Install those directories from Settings → Plugin
management. The managed examples add settings and radial UI, alter outbound chat,
register a command, trigger a pet action, and persist state. The native example replaces
an internal pet-window method and therefore intentionally demonstrates full trust.
