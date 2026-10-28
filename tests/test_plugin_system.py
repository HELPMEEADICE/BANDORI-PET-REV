import json
import os
import struct
import tempfile
import unittest
import uuid
import zipfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QProcess, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QLabel

from plugin_system.installer import PluginInstaller
from plugin_system.models import PluginError, PluginManifest
from plugin_system.paths import PluginStateStore, plugin_paths
from plugin_system.protocol import FrameDecoder, RpcPeer, RpcRemoteError, encode_message, request_message
from plugin_system.registry import ContributionRegistry, PluginEventBus, PluginServiceRegistry
from plugin_system.scanner import scan_plugin_directory, sha256_directory
from plugin_system.redaction import redact_secrets, restore_secrets
from plugin_system.signing import build_signed_files_document
from plugin_system.bridge import PluginComponentBridge
from plugin_system.native import NativePluginLoader
from plugin_system.supervisor import LocalPluginTransport, MAX_STORAGE_BYTES, PluginSupervisor
from plugin_system.sdk import PluginContext
from plugin_system.worker_runtime import ManagedPluginRuntime
from bandori_tools.local_tools import chat_completion_tools, run_local_tool_call


def manifest(version="1.0.0", **overrides):
    value = {
        "schema_version": 1,
        "id": "com.example.test",
        "name": "Test Plugin",
        "version": version,
        "api": ">=1.0,<2.0",
        "app": ">=3.1.4,<4.0",
        "language": "python",
        "execution": "managed",
        "entrypoints": {"worker": "main.py"},
        "permissions": {},
        "platforms": ["windows", "macos", "linux"],
    }
    value.update(overrides)
    return value


def write_plugin(root: Path, value: dict, source="def activate(ctx):\n    ctx.storage.set('started', True)\n"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "plugin.json").write_text(json.dumps(value), encoding="utf-8")
    entry = next(iter(value["entrypoints"].values()))
    (root / entry).write_text(source, encoding="utf-8")


def wait_until(predicate, timeout_ms=8000):
    if predicate():
        return True
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(20)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    poll.start()
    timeout.start(timeout_ms)
    loop.exec()
    poll.stop()
    timeout.stop()
    return bool(predicate())


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.events = []

    def call(self, method, params=None, *, timeout_ms=10_000):
        self.calls.append((method, params, timeout_ms))
        if method == "storage.get":
            return params.get("default")
        return {"ok": True}

    def notify(self, method, params=None):
        self.events.append((method, params))


class PluginSystemTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_storage_initialization_and_normal_operations(self):
        for initial in (None, b"{}", b"\xef\xbb\xbf{}"):
            with self.subTest(initial=initial), tempfile.TemporaryDirectory() as directory:
                supervisor = PluginSupervisor(paths=plugin_paths(Path(directory) / "home"))
                try:
                    path = supervisor._storage_path("com.example.test")
                    if initial is not None:
                        path.parent.mkdir(parents=True)
                        path.write_bytes(initial)
                    storage = PluginContext("com.example.test", LocalPluginTransport(
                        supervisor, "com.example.test"
                    )).storage
                    self.assertEqual("fallback", storage.get("missing", "fallback"))
                    self.assertEqual([], storage.keys())
                    if initial is None:
                        self.assertFalse(path.exists())
                    storage.set("key", {"value": 42})
                    self.assertEqual({"value": 42}, storage.get("key"))
                    self.assertEqual(["key"], storage.keys())
                    storage.delete("key")
                    storage.delete("missing")
                    self.assertEqual({}, json.loads(path.read_bytes()))
                finally:
                    supervisor.close()

    def test_storage_corruption_rejects_all_operations_without_changing_bytes(self):
        for original in (b'', b'{"secret":', b'\xff', b'[]', b'"secret"', b'42', b'null', b'true'):
            with self.subTest(original=original), tempfile.TemporaryDirectory() as directory:
                supervisor = PluginSupervisor(paths=plugin_paths(Path(directory) / "home"))
                try:
                    path = supervisor._storage_path("com.example.test")
                    path.parent.mkdir(parents=True)
                    path.write_bytes(original)
                    storage = PluginContext("com.example.test", LocalPluginTransport(
                        supervisor, "com.example.test"
                    )).storage
                    for operation in (lambda: storage.get("key", "fallback"),
                                      lambda: storage.set("key", 1),
                                      lambda: storage.delete("key"), storage.keys):
                        with self.subTest(operation=operation), self.assertRaises(RpcRemoteError) as caught:
                            operation()
                        self.assertEqual("storage_corrupt", caught.exception.code)
                        self.assertNotIn("secret", str(caught.exception))
                        self.assertEqual(original, path.read_bytes())
                    self.assertEqual([path], list(path.parent.iterdir()))
                finally:
                    supervisor.close()

    def test_storage_read_errors_do_not_initialize_or_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            supervisor = PluginSupervisor(paths=plugin_paths(Path(directory) / "home"))
            try:
                path = supervisor._storage_path("com.example.test")
                path.parent.mkdir(parents=True)
                original = b'{"key": "old"}'
                path.write_bytes(original)
                for failure in (PermissionError(13, "denied"), OSError(5, "I/O failure")):
                    for method in ("get", "set", "delete", "keys"):
                        with self.subTest(failure=failure, method=method):
                            with patch.object(Path, "read_text", side_effect=failure):
                                with self.assertRaises(RpcRemoteError) as caught:
                                    supervisor._storage_call("com.example.test", "storage." + method,
                                                             {"key": "key", "value": 1})
                            self.assertEqual("storage_read_error", caught.exception.code)
                            self.assertEqual(failure.errno, caught.exception.data["errno"])
                            self.assertEqual(original, path.read_bytes())
                path.unlink()
                path.mkdir()
                with self.assertRaises(RpcRemoteError) as caught:
                    supervisor._storage_call("com.example.test", "storage.keys", {})
                self.assertEqual("storage_read_error", caught.exception.code)
                self.assertTrue(path.is_dir())
            finally:
                supervisor.close()

    def test_storage_write_limit_and_atomic_write_failures_preserve_original(self):
        with tempfile.TemporaryDirectory() as directory:
            supervisor = PluginSupervisor(paths=plugin_paths(Path(directory) / "home"))
            try:
                path = supervisor._storage_path("com.example.test")
                path.parent.mkdir(parents=True)
                original = b'{"key": "old"}'
                path.write_bytes(original)
                with self.assertRaises(RpcRemoteError) as caught:
                    supervisor._storage_call("com.example.test", "storage.set",
                                             {"key": "key", "value": "x" * MAX_STORAGE_BYTES})
                self.assertEqual("storage_limit", caught.exception.code)
                self.assertEqual(original, path.read_bytes())
                for target in ("pathlib.Path.write_bytes", "plugin_system.supervisor.os.replace"):
                    with self.subTest(target=target), patch(target, side_effect=OSError("write failed")):
                        with self.assertRaises(OSError):
                            supervisor._storage_call("com.example.test", "storage.set",
                                                     {"key": "key", "value": "new"})
                    self.assertEqual(original, path.read_bytes())
                    self.assertEqual([path], list(path.parent.iterdir()))
                overhead = len(json.dumps({"key": ""}, ensure_ascii=False, indent=2).encode("utf-8"))
                supervisor._storage_call("com.example.test", "storage.set",
                                         {"key": "key", "value": "x" * (MAX_STORAGE_BYTES - overhead)})
                self.assertEqual(MAX_STORAGE_BYTES, len(path.read_bytes()))
            finally:
                supervisor.close()

    def test_uninstall_preserves_corrupt_storage_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            supervisor = PluginSupervisor(paths=plugin_paths(root / "home"))
            try:
                write_plugin(root / "plugin", manifest())
                supervisor.installer.commit(supervisor.installer.stage_local(root / "plugin"), enable=False)
                path = supervisor._storage_path("com.example.test")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"corrupt")
                supervisor.installer.uninstall("com.example.test")
                self.assertEqual(b"corrupt", path.read_bytes())
            finally:
                supervisor.close()

    def test_storage_errors_cross_rpc_and_managed_python_and_lua_sdk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            supervisor = PluginSupervisor(paths=plugin_paths(root / "home"))
            server = QLocalServer()
            client = QLocalSocket()
            host_socket = None
            try:
                self.assertTrue(server.listen("storage-test-" + uuid.uuid4().hex))
                client.connectToServer(server.serverName())
                self.assertTrue(client.waitForConnected(1000))
                self.assertTrue(server.waitForNewConnection(1000))
                host_socket = server.nextPendingConnection()
                host = RpcPeer(host_socket)
                remote = RpcPeer(client)
                supervisor._sessions[host] = {
                    "authenticated": True, "role": "plugin", "identity": "com.example.test",
                }
                for method in ("get", "set", "delete", "keys"):
                    name = "storage." + method
                    host.register_handler(name, lambda params, name=name:
                                          supervisor._peer_plugin_call(host, name, params))
                path = supervisor._storage_path("com.example.test")
                path.parent.mkdir(parents=True)
                path.write_bytes(b'{"secret":')
                storage = PluginContext("com.example.test", remote).storage
                operations = (lambda: storage.get("key", "fallback"),
                              lambda: storage.set("key", 1),
                              lambda: storage.delete("key"), storage.keys)
                for code in ("storage_corrupt", "storage_read_error"):
                    for operation in operations:
                        with self.subTest(code=code, operation=operation):
                            failure = PermissionError(13, "denied")
                            read_failure = (patch.object(Path, "read_text", side_effect=failure)
                                            if code == "storage_read_error" else nullcontext())
                            with read_failure:
                                with self.assertRaises(RpcRemoteError) as caught:
                                    operation()
                            self.assertEqual(code, caught.exception.code)
                            self.assertNotIn("secret", str(caught.exception))
                            if code == "storage_read_error":
                                self.assertEqual({"errno": 13}, caught.exception.data)
                for language in ("python", "lua"):
                    with self.subTest(language=language):
                        entry = "main.py" if language == "python" else "main.lua"
                        value = manifest(language=language, entrypoints={"worker": entry})
                        source = ('def activate(ctx):\n    ctx.storage.get("key", "fallback")\n'
                                  if language == "python" else
                                  'return {activate=function(ctx) '
                                  'local ok, err = pcall(ctx.storage.get, "key", "fallback"); '
                                  'assert(not ok); '
                                  'assert(tostring(err) == "Plugin storage is not a valid JSON object") end}')
                        write_plugin(root / language, value, source)
                        runtime = ManagedPluginRuntime(root / language, PluginManifest.from_dict(value),
                                                       remote, install_audit_hook=False)
                        try:
                            if language == "lua":
                                runtime.activate()
                            else:
                                with self.assertRaises(RpcRemoteError) as caught:
                                    runtime.activate()
                                self.assertEqual("storage_corrupt", caught.exception.code)
                        finally:
                            runtime.deactivate("test")
                self.assertEqual(b'{"secret":', path.read_bytes())
            finally:
                client.abort()
                if host_socket is not None:
                    host_socket.abort()
                server.close()
                supervisor.close()

    def test_manifest_rejects_native_lua(self):
        raw = manifest(language="lua", execution="native", entrypoints={"pet": "main.lua"})
        with self.assertRaises(PluginError):
            PluginManifest.from_dict(raw)

    def test_frame_decoder_handles_partial_frames_and_limits(self):
        frame = encode_message(request_message("ping", {"value": 1}, "abc"))
        decoder = FrameDecoder()
        self.assertEqual([], decoder.feed(frame[:3]))
        decoded = decoder.feed(frame[3:])
        self.assertEqual("ping", decoded[0]["method"])
        with self.assertRaises(Exception):
            FrameDecoder(max_message_bytes=4).feed(frame)

    def test_frame_decoder_rejects_malformed_message_schema_and_nonfinite_json(self):
        missing_id = json.dumps({
            "v": 1, "kind": "request", "method": "ping", "params": {},
        }).encode("utf-8")
        with self.assertRaises(Exception):
            FrameDecoder().feed(struct.pack(">I", len(missing_id)) + missing_id)
        nonfinite = b'{"v":1,"kind":"event","method":"ping","params":{"x":NaN}}'
        with self.assertRaises(Exception):
            FrameDecoder().feed(struct.pack(">I", len(nonfinite)) + nonfinite)

    def test_event_order_patch_and_cancel(self):
        bus = PluginEventBus()
        calls = []
        bus.subscribe("z.plugin", "z", "chat.message.before", 10, lambda payload: (
            calls.append("z") or {"patch": {"text": payload["text"] + "z"}}
        ))
        bus.subscribe("a.plugin", "a", "chat.message.before", 10, lambda payload: (
            calls.append("a") or {"action": "cancel", "reason": "blocked"}
        ))
        result = bus.dispatch("chat.message.before", {"text": "x"})
        self.assertEqual(["a"], calls)
        self.assertTrue(result["cancelled"])

    def test_event_subscription_ids_are_namespaced_per_plugin(self):
        bus = PluginEventBus()
        calls = []
        bus.subscribe("a.plugin", "same", "app.started", 0, lambda _payload: calls.append("a"))
        bus.subscribe("b.plugin", "same", "app.started", 0, lambda _payload: calls.append("b"))
        bus.dispatch("app.started", {})
        self.assertEqual(["a", "b"], calls)

    def test_scanner_blocks_managed_dynamic_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = manifest()
            write_plugin(root, value, "def activate(ctx):\n    eval('1 + 1')\n")
            parsed = PluginManifest.from_dict(value)
            report = scan_plugin_directory(
                root, parsed, package_sha256=sha256_directory(root)
            )
            self.assertTrue(report.blocked)
            finding = next(item for item in report.findings if item.rule == "PY_DYNAMIC_EXEC")
            self.assertEqual(2, finding.line)

    def test_installer_rejects_traversal_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = plugin_paths(root / "home")
            installer = PluginInstaller(paths, PluginStateStore(paths))
            bad = root / "bad.bdplugin"
            with zipfile.ZipFile(bad, "w") as archive:
                archive.writestr("plugin.json", json.dumps(manifest()))
                archive.writestr("../escape.py", "pass")
            with self.assertRaises(PluginError):
                installer.stage_local(bad)

            first = root / "first"
            write_plugin(first, manifest("1.0.0", permissions={"config": {"read": True}}))
            preview = installer.stage_local(first)
            installer.commit(preview, enable=False)
            second = root / "second"
            write_plugin(second, manifest("1.1.0", permissions={"pet": {"control": True}}))
            installer.commit(installer.stage_local(second), enable=False)
            rolled_back = installer.rollback("com.example.test")
            self.assertEqual("1.0.0", rolled_back["active_version"])
            self.assertEqual({"config": {"read": True}}, rolled_back["granted_permissions"])

    def test_ed25519_signed_archive(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = manifest()
            files = {
                "plugin.json": json.dumps(value).encode("utf-8"),
                "main.py": b"def activate(ctx):\n    pass\n",
            }
            document = build_signed_files_document(files, publisher="Example Publisher")
            key = Ed25519PrivateKey.generate()
            public = key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            package = root / "signed.bdplugin"
            with zipfile.ZipFile(package, "w") as archive:
                for name, payload in files.items():
                    archive.writestr(name, payload)
                archive.writestr("META-INF/files.json", document)
                archive.writestr("META-INF/public_key.ed25519", public)
                archive.writestr("META-INF/signature.ed25519", key.sign(document))
            paths = plugin_paths(root / "home")
            preview = PluginInstaller(paths, PluginStateStore(paths)).stage_local(package)
            self.assertEqual("valid_untrusted", preview.report.signature.status)
            self.assertFalse(preview.report.blocked)

    def test_lua_tables_are_marshaled_through_sdk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = manifest(language="lua", entrypoints={"worker": "main.lua"})
            source = """
local p = {}
function p.activate(ctx)
  ctx.storage.set("value", {enabled=true, values={1, 2, 3}})
end
return p
"""
            write_plugin(root, value, source)
            transport = FakeTransport()
            runtime = ManagedPluginRuntime(
                root, PluginManifest.from_dict(value), transport,
                install_audit_hook=False,
            )
            runtime.activate()
            method, params, _timeout = transport.calls[0]
            self.assertEqual("storage.set", method)
            self.assertEqual([1, 2, 3], params["value"]["values"])
            runtime.deactivate("test")

    def test_lua_callback_results_are_marshaled_to_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = manifest(language="lua", entrypoints={"worker": "main.lua"})
            source = """
local p = {}
function p.activate(ctx)
  ctx.events.on("chat.message.before", function(payload)
    local seen = false
    for key, value in pairs(payload) do
      if key == "text" and value == "hello" then seen = true end
    end
    return {action="continue", patch={text=tostring(payload["text"]) .. (seen and "!" or "?")}}
  end, 5)
end
return p
"""
            write_plugin(root, value, source)
            transport = FakeTransport()
            runtime = ManagedPluginRuntime(
                root, PluginManifest.from_dict(value), transport,
                install_audit_hook=False,
            )
            runtime.activate()
            subscribe = next(params for method, params, _timeout in transport.calls if method == "events.subscribe")
            result = runtime.invoke_callback(subscribe["subscription_id"], {"text": "hello"})
            self.assertEqual("hello!", result["patch"]["text"])
            runtime.deactivate("test")

    def test_component_bridge_invokes_registered_contribution(self):
        class Peer:
            connected = True

            def __init__(self):
                self.calls = []

            def call(self, method, params, *, timeout_ms):
                self.calls.append((method, params, timeout_ms))
                return {"ok": True, "echo": params["payload"]}

        bridge = PluginComponentBridge("chat")
        peer = Peer()
        bridge.peer = peer
        result = bridge.invoke_contribution("tools", "tool-id", {"value": 7})
        self.assertEqual({"value": 7}, result["echo"])
        self.assertEqual("component.contribution.invoke", peer.calls[0][0])
        bridge.peer = None

    def test_declarative_ui_ids_are_namespaced_per_plugin(self):
        registry = ContributionRegistry()
        registry.register("ui", "a.plugin", "shared", {"location": "tray", "label": "A"})
        registry.register("ui", "b.plugin", "shared", {"location": "tray", "label": "B"})
        self.assertEqual(2, len(registry.list("ui", location="tray")))
        registry.update("ui", "a.plugin", "shared", {"label": "A2"})
        a_item = registry.get_for_plugin("ui", "a.plugin", "shared")
        b_item = registry.get_for_plugin("ui", "b.plugin", "shared")
        self.assertEqual("A2", a_item["spec"]["label"])
        self.assertEqual("B", b_item["spec"]["label"])

    def test_service_wrappers_resolve_the_next_priority(self):
        services = PluginServiceRegistry()
        services.register("llm.provider", lambda value: value, owner="core", priority=0)
        services.register(
            "llm.provider", lambda value: value,
            owner="plugin:a.plugin", priority=100, permission="llm.use",
        )
        self.assertEqual("plugin:a.plugin", services.resolve("llm.provider").owner)
        self.assertEqual(
            "core",
            services.resolve_after("llm.provider", "plugin:a.plugin").owner,
        )
        self.assertEqual(("llm.use",), services.required_permissions("llm.provider"))
        services.register(
            "config.get", lambda value: value,
            owner="core", priority=0, permission="config.read",
        )
        services.register(
            "config.get", lambda value: value,
            owner="plugin:a.plugin", priority=100, permission="",
        )
        self.assertEqual(("config.read",), services.required_permissions("config.get"))

    def test_managed_settings_redaction_preserves_host_secrets(self):
        original = {
            "theme": "dark",
            "llm_api_key": "host-secret",
            "nested": {"access_token": "nested-secret", "enabled": True},
        }
        visible = redact_secrets(original)
        self.assertNotIn("host-secret", json.dumps(visible))
        visible["theme"] = "light"
        visible["llm_api_key"] = "plugin-replacement"
        visible["nested"].pop("access_token")
        restored = restore_secrets(visible, original)
        self.assertEqual("light", restored["theme"])
        self.assertEqual("host-secret", restored["llm_api_key"])
        self.assertEqual("nested-secret", restored["nested"]["access_token"])

    def test_ui_update_cannot_escalate_location_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = plugin_paths(root / "home")
            source = root / "plugin"
            value = manifest(permissions={"ui": {"settings_page": True}})
            write_plugin(source, value)
            supervisor = PluginSupervisor(paths=paths)
            try:
                supervisor.installer.commit(
                    supervisor.installer.stage_local(source), enable=False
                )
                supervisor.handle_plugin_call(
                    value["id"],
                    "ui.register",
                    {"spec": {
                        "schema_version": 1,
                        "id": "settings",
                        "location": "settings_page",
                    }},
                    peer=None,
                )
                with self.assertRaises(RpcRemoteError):
                    supervisor.handle_plugin_call(
                        value["id"],
                        "ui.update",
                        {"component_id": "settings", "patch": {"location": "tray"}},
                        peer=None,
                    )
            finally:
                supervisor.close()

    def test_network_scope_rejects_unapproved_origins_and_host_header(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = plugin_paths(root / "home")
            source = root / "plugin"
            value = manifest(permissions={
                "network": {"origins": ["https://api.example.com"]}
            })
            write_plugin(source, value)
            supervisor = PluginSupervisor(paths=paths)
            try:
                supervisor.installer.commit(
                    supervisor.installer.stage_local(source), enable=False
                )
                with self.assertRaises(RpcRemoteError):
                    supervisor.handle_plugin_call(
                        value["id"], "network.request",
                        {"url": "https://other.example.com/value"}, peer=None,
                    )
                with self.assertRaises(RpcRemoteError):
                    supervisor.handle_plugin_call(
                        value["id"], "network.request",
                        {
                            "url": "https://api.example.com/value",
                            "headers": {"Host": "other.example.com"},
                        },
                        peer=None,
                    )
            finally:
                supervisor.close()

    def test_safe_mode_never_hot_starts_managed_plugins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = plugin_paths(root / "home")
            source = root / "plugin"
            write_plugin(source, manifest())
            supervisor = PluginSupervisor(paths=paths, safe_mode=True)
            try:
                supervisor.installer.commit(
                    supervisor.installer.stage_local(source), enable=False
                )
                item = supervisor.set_enabled("com.example.test", True)
                self.assertTrue(item["enabled"])
                self.assertNotIn("com.example.test", supervisor._processes)
                with self.assertRaises(PluginError):
                    supervisor.start_plugin("com.example.test")
            finally:
                supervisor.close()

    def test_shipped_managed_examples_activate_and_patch_chat(self):
        repository = Path(__file__).resolve().parents[1]
        for name in ("python_managed", "lua_managed"):
            with self.subTest(name=name):
                root = repository / "examples" / "plugins" / name
                parsed = PluginManifest.from_bytes((root / "plugin.json").read_bytes())
                transport = FakeTransport()
                runtime = ManagedPluginRuntime(
                    root, parsed, transport, install_audit_hook=False
                )
                runtime.activate()
                methods = [method for method, _params, _timeout in transport.calls]
                self.assertEqual(2, methods.count("ui.register"))
                self.assertIn("commands.register", methods)
                self.assertIn("tools.register", methods)
                subscription = next(
                    params for method, params, _timeout in transport.calls
                    if method == "events.subscribe" and params["event"] == "chat.message.before"
                )
                result = runtime.invoke_callback(
                    subscription["subscription_id"], {"text": "hello"}
                )
                self.assertIn("hello", result["patch"]["text"])
                runtime.deactivate("test")

    def test_shipped_native_example_replaces_private_host_behavior(self):
        class PetHost:
            def __init__(self):
                self.original_calls = 0

            def _bring_to_front(self, force=False):
                self.original_calls += 1
                return force

        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            paths = plugin_paths(Path(directory) / "home")
            supervisor = PluginSupervisor(paths=paths)
            loader = None
            try:
                preview = supervisor.installer.stage_local(
                    repository / "examples" / "plugins" / "python_native"
                )
                supervisor.installer.commit(preview, enable=True)
                pet = PetHost()
                loader = NativePluginLoader(
                    "pet",
                    paths=paths,
                    transport_factory=supervisor.local_transport,
                    window=pet,
                    controller=pet,
                )
                loaded = loader.load_all()
                self.assertEqual(["com.bandoripet.example.native"], [item.plugin_id for item in loaded])
                pet._bring_to_front(force=False)
                self.assertEqual(0, pet.original_calls)
                loaded[0].context.register_widget_factory(
                    "settings_page", lambda parent: QLabel("Native", parent), "example"
                )
                widgets = loader.create_widgets("settings_page")
                self.assertEqual("Native", widgets[0].text())
                widgets[0].deleteLater()
            finally:
                if loader is not None:
                    loader.close()
                supervisor.close()

    def test_managed_worker_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = plugin_paths(root / "home")
            source = root / "plugin"
            write_plugin(source, manifest())
            supervisor = PluginSupervisor(paths=paths)
            try:
                supervisor.installer.commit(
                    supervisor.installer.stage_local(source), enable=False
                )
                loop = QEventLoop()
                supervisor.plugin_started.connect(lambda _plugin_id: loop.quit())
                supervisor.set_enabled("com.example.test", True)
                timeout = QTimer()
                timeout.setSingleShot(True)
                timeout.timeout.connect(loop.quit)
                timeout.start(8000)
                loop.exec()
                self.assertIn("com.example.test", supervisor._plugin_peers)
                self.assertTrue(
                    supervisor._read_storage("com.example.test").get("started")
                )
            finally:
                supervisor.close()

    def test_managed_update_restarts_worker_on_new_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = plugin_paths(root / "home")
            first = root / "first"
            second = root / "second"
            write_plugin(
                first,
                manifest("1.0.0"),
                "def activate(ctx):\n    ctx.storage.set('running_version', '1.0.0')\n",
            )
            write_plugin(
                second,
                manifest("1.1.0"),
                "def activate(ctx):\n    ctx.storage.set('running_version', '1.1.0')\n",
            )
            supervisor = PluginSupervisor(paths=paths)
            try:
                supervisor.installer.commit(
                    supervisor.installer.stage_local(first), enable=True
                )
                supervisor.start_plugin("com.example.test")
                self.assertTrue(wait_until(
                    lambda: supervisor._read_storage("com.example.test").get("running_version") == "1.0.0"
                ))
                preview = supervisor.installer.stage_local(second)
                component = object()
                supervisor._sessions[component] = {
                    "authenticated": True,
                    "role": "component",
                    "identity": "settings",
                }
                supervisor._component_plugin_admin(component, "commit", {
                    "token": preview.token,
                    "enable": True,
                })
                self.assertTrue(wait_until(
                    lambda: supervisor._read_storage("com.example.test").get("running_version") == "1.1.0"
                ))
                self.assertEqual(
                    "1.1.0",
                    supervisor.state.plugin("com.example.test")["active_version"],
                )
            finally:
                supervisor.close()

    def test_stop_plugin_disconnects_worker_when_shutdown_rpc_fails(self):
        disconnected = []

        def failed_shutdown(*_args, **_kwargs):
            raise TimeoutError("worker is still waiting for a nested RPC")

        peer = SimpleNamespace(
            connected=True,
            call=failed_shutdown,
            socket=SimpleNamespace(abort=lambda: disconnected.append(True)),
        )
        supervisor = SimpleNamespace(
            _cancel_startup_timer=lambda _plugin_id: None,
            _plugin_peers={"com.example.test": peer},
            _processes={},
            _expected_stops=set(),
            _cleanup_plugin=lambda _plugin_id: None,
        )

        PluginSupervisor.stop_plugin(supervisor, "com.example.test")

        self.assertEqual([True], disconnected)

    def test_stop_plugin_reaps_worker_before_cleanup(self):
        class StubbornProcess:
            exits_normally = False
            terminated = False
            killed = False
            reaped = False

            def state(self):
                return QProcess.ProcessState.Running

            def terminate(self):
                self.terminated = True

            def kill(self):
                self.killed = True

            def waitForFinished(self, _timeout):
                self.reaped = self.exits_normally or self.killed
                return self.reaped

        for exits_normally in (True, False):
            with self.subTest(exits_normally=exits_normally):
                process = StubbornProcess()
                process.exits_normally = exits_normally
                cleanup_states = []
                supervisor = SimpleNamespace(
                    _cancel_startup_timer=lambda _plugin_id: None,
                    _plugin_peers={},
                    _processes={"com.example.test": process},
                    _expected_stops=set(),
                    _cleanup_plugin=lambda _plugin_id: cleanup_states.append(process.reaped),
                )

                PluginSupervisor.stop_plugin(supervisor, "com.example.test")

                self.assertEqual(not exits_normally, process.terminated)
                self.assertEqual(not exits_normally, process.killed)
                self.assertEqual([True], cleanup_states)

    def test_app_started_reaches_plugin_after_async_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = plugin_paths(root / "home")
            source = root / "plugin"
            write_plugin(
                source,
                manifest(permissions={"events": {"observe": ["app.started"]}}),
                """
CONTEXT = None
def on_started(payload):
    CONTEXT.storage.set('app_started_value', payload.get('value'))
def activate(ctx):
    global CONTEXT
    CONTEXT = ctx
    ctx.events.on('app.started', on_started)
""",
            )
            supervisor = PluginSupervisor(paths=paths)
            try:
                supervisor.installer.commit(
                    supervisor.installer.stage_local(source), enable=True
                )
                supervisor.start_plugin("com.example.test")
                supervisor.mark_app_started({"value": 42})
                self.assertTrue(wait_until(
                    lambda: supervisor._read_storage("com.example.test").get("app_started_value") == 42
                ))
            finally:
                supervisor.close()

    def test_shipped_examples_pass_install_scan(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            paths = plugin_paths(Path(directory) / "home")
            installer = PluginInstaller(paths, PluginStateStore(paths))
            for name in ("python_managed", "lua_managed", "python_native"):
                with self.subTest(name=name):
                    preview = installer.stage_local(repository / "examples" / "plugins" / name)
                    self.assertFalse(preview.report.blocked)
                    installer.cancel(preview)

    def test_plugin_llm_tool_schema_and_invocation(self):
        calls = []
        config = {
            "_plugin_tools": [{
                "id": "tool-registration",
                "spec": {
                    "name": "plugin_echo",
                    "description": "Echo arguments",
                    "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
                },
            }],
            "_plugin_tool_runner": lambda item_id, arguments: calls.append((item_id, arguments)) or {"echo": arguments["text"]},
        }
        tools = chat_completion_tools(False, config)
        self.assertTrue(any(item.get("function", {}).get("name") == "plugin_echo" for item in tools))
        result = run_local_tool_call("plugin_echo", '{"text":"hello"}', config)
        self.assertIn("hello", result["content"])
        self.assertEqual("tool-registration", calls[0][0])


if __name__ == "__main__":
    unittest.main()
