from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_data_path

from app_info import APP_NAME
from .models import PluginError


STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PluginPaths:
    root: Path
    packages: Path
    data: Path
    staging: Path
    logs: Path
    state_file: Path

    def ensure(self) -> "PluginPaths":
        for path in (self.root, self.packages, self.data, self.staging, self.logs):
            path.mkdir(parents=True, exist_ok=True)
        return self


def plugin_paths(root: str | Path | None = None, *, create: bool = True) -> PluginPaths:
    if root is None:
        override = os.environ.get("BANDORI_PET_PLUGIN_HOME", "").strip()
        root_path = Path(override).expanduser() if override else user_data_path(APP_NAME, APP_NAME) / "plugins"
    else:
        root_path = Path(root)
    root_path = root_path.resolve()
    result = PluginPaths(
        root=root_path,
        packages=root_path / "packages",
        data=root_path / "data",
        staging=root_path / "staging",
        logs=root_path / "logs",
        state_file=root_path / "plugins.json",
    )
    return result.ensure() if create else result


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "plugins": {},
        "trusted_publishers": {},
        "native_safe_mode": False,
        "native_startup_journal": {},
    }


class PluginStateStore:
    """Atomic state storage. The main process is the only writer."""

    def __init__(self, paths: PluginPaths | None = None):
        self.paths = paths or plugin_paths()
        self._lock = threading.RLock()

    @contextmanager
    def _file_lock(self):
        lock_path = self.paths.state_file.with_suffix(".json.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock_file:
            deadline = time.monotonic() + 10.0
            if os.name == "nt":
                import msvcrt
                while True:
                    try:
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise PluginError("Timed out waiting for plugin state lock")
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                while True:
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise PluginError("Timed out waiting for plugin state lock")
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.paths.state_file.is_file():
            return _empty_state()
        try:
            raw = json.loads(self.paths.state_file.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PluginError(f"Could not read plugin state: {exc}") from exc
        if not isinstance(raw, dict):
            raise PluginError("Plugin state root must be an object")
        state = _empty_state()
        state.update(raw)
        if not isinstance(state.get("plugins"), dict):
            state["plugins"] = {}
        if not isinstance(state.get("trusted_publishers"), dict):
            state["trusted_publishers"] = {}
        return state

    def load(self) -> dict[str, Any]:
        with self._lock, self._file_lock():
            return self._load_unlocked()

    def _save_unlocked(self, state: dict[str, Any]) -> None:
        self.paths.ensure()
        payload = copy.deepcopy(state)
        payload["schema_version"] = STATE_SCHEMA_VERSION
        fd, temporary = tempfile.mkstemp(
            prefix="plugins.json.", suffix=".tmp", dir=str(self.paths.root)
        )
        temporary_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.paths.state_file)
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    def save(self, state: dict[str, Any]) -> None:
        with self._lock, self._file_lock():
            self._save_unlocked(state)

    def mutate(self, callback):
        with self._lock, self._file_lock():
            state = self._load_unlocked()
            result = callback(state)
            self._save_unlocked(state)
            return result

    def plugin(self, plugin_id: str) -> dict[str, Any]:
        state = self.load()
        item = state["plugins"].get(str(plugin_id), {})
        return copy.deepcopy(item) if isinstance(item, dict) else {}

    def set_plugin(self, plugin_id: str, value: dict[str, Any]) -> None:
        def update(state):
            state["plugins"][plugin_id] = copy.deepcopy(value)
        self.mutate(update)

    def trusted_fingerprints(self) -> set[str]:
        return set(self.load().get("trusted_publishers", {}))

    def trust_publisher(self, fingerprint: str, publisher: str = "") -> None:
        fingerprint = str(fingerprint or "").lower().strip()
        if not fingerprint:
            raise PluginError("Publisher fingerprint is required")
        def update(state):
            state["trusted_publishers"][fingerprint] = {
                "publisher": str(publisher or "").strip(),
            }
        self.mutate(update)
