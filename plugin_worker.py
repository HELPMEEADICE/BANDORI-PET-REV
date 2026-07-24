from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

from process_utils import configure_debug_logging, install_parent_death_watch

configure_debug_logging()

from PySide6.QtCore import QCoreApplication, QTimer

from plugin_system.models import PluginManifest
from plugin_system.protocol import RpcRemoteError, connect_local_peer
from plugin_system.worker_runtime import ManagedPluginRuntime


MAX_WORKER_RSS = 256 * 1024 * 1024


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BandoriPet managed plugin worker")
    parser.add_argument("--plugin-id", required=True)
    parser.add_argument("--plugin-root", required=True)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    root = Path(args.plugin_root).resolve()
    manifest = PluginManifest.from_bytes((root / "plugin.json").read_bytes())
    if manifest.id != args.plugin_id or manifest.execution != "managed":
        raise RuntimeError("Plugin worker identity or execution mode does not match its manifest")
    server_name = os.environ.get("BANDORI_PLUGIN_RPC_NAME", "").strip()
    token = os.environ.get("BANDORI_PLUGIN_RPC_TOKEN", "").strip()
    if not server_name or not token:
        raise RuntimeError("Plugin worker RPC environment is incomplete")

    app = QCoreApplication(sys.argv)
    install_parent_death_watch(app)
    peer = connect_local_peer(server_name, parent=app)
    runtime = ManagedPluginRuntime(root, manifest, peer)

    def invoke(params):
        if not isinstance(params, dict):
            raise ValueError("callback.invoke parameters must be an object")
        return runtime.invoke_callback(
            str(params.get("callback_id", "")),
            params.get("payload"),
        )

    def invoke_notification(params):
        try:
            invoke(params)
        except Exception as exc:
            peer.notify("plugin.fault", {
                "kind": "notification",
                "message": str(exc),
                "traceback": traceback.format_exc(),
            })

    def shutdown(params):
        reason = str(params.get("reason", "shutdown") if isinstance(params, dict) else "shutdown")
        runtime.deactivate(reason)
        QTimer.singleShot(0, app.quit)
        return {"ok": True}

    peer.register_handler("callback.invoke", invoke)
    peer.register_handler("callback.notify", invoke_notification)
    peer.register_handler("plugin.shutdown", shutdown)
    peer.register_handler("plugin.ping", lambda _params: {"ok": True})
    peer.disconnected.connect(app.quit)

    failures = {"rss": 0}
    monitor = QTimer(app)
    monitor.setInterval(2000)

    def monitor_resources():
        try:
            import psutil
            rss = psutil.Process(os.getpid()).memory_info().rss
        except Exception:
            return
        failures["rss"] = failures["rss"] + 1 if rss > MAX_WORKER_RSS else 0
        if failures["rss"] >= 3:
            peer.notify("plugin.fault", {
                "kind": "resource_limit",
                "message": f"Worker RSS exceeded {MAX_WORKER_RSS} bytes",
            })
            runtime.deactivate("resource_limit")
            app.exit(77)

    monitor.timeout.connect(monitor_resources)

    def start_plugin():
        try:
            peer.call("auth", {
                "role": "plugin",
                "plugin_id": manifest.id,
                "token": token,
            }, timeout_ms=5000)
            runtime.activate()
            peer.notify("plugin.ready", {
                "plugin_id": manifest.id,
                "language": manifest.language,
            })
            monitor.start()
        except Exception as exc:
            try:
                peer.notify("plugin.fault", {
                    "kind": "startup",
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                })
            except Exception:
                pass
            app.exit(70)

    QTimer.singleShot(0, start_plugin)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
