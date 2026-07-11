import ssl
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

from settings_window.constants import *
from network_worker import CancelableNetworkWorker


class UpdateCheckWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def run(self):
        try:
            from app_update import check_for_updates

            self.finished.emit(check_for_updates())
        except Exception as exc:
            self.error.emit(str(exc))


class UpdateApplyWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, update_info, parent=None):
        super().__init__(parent)
        self._update_info = update_info

    def run(self):
        try:
            from app_update import apply_update

            self.finished.emit(apply_update(self._update_info))
        except Exception as exc:
            self.error.emit(str(exc))


class McpConnectionTestWorker(CancelableNetworkWorker):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = dict(config or {})

    def run(self):
        try:
            from mcp_bridge import test_mcp_servers

            self._config["_cancel_event"] = self.cancel_event
            success, details = test_mcp_servers(self._config)
            if self.cancelled():
                return
            if success:
                self.finished.emit(details)
            else:
                self.error.emit(details)
        except Exception as exc:
            if not self.cancelled():
                self.error.emit(str(exc))


class ModelPackageDownloadWorker(QThread):
    progress = Signal(dict)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, package_keys: list[str], models_dir, parent=None, overwrite: bool = False):
        super().__init__(parent)
        self._package_keys = list(package_keys)
        self._models_dir = models_dir
        self._overwrite = bool(overwrite)
        self._downloaded_bytes = 0
        self._total_bytes = 0
        self._known_sizes: dict[str, int] = {}
        self._done = 0
        self._total = len(self._package_keys)
        self._started_at = 0.0
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._active_responses = set()

    def requestInterruption(self):
        self._cancel_event.set()
        with self._lock:
            responses = list(self._active_responses)
        for response in responses:
            try:
                response.close()
            except Exception:
                pass
        super().requestInterruption()

    def _cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def run(self):
        if not self._package_keys:
            self.finished.emit({"downloaded": 0, "failed": []})
            return
        self._started_at = time.monotonic()
        downloaded = 0
        failed = []
        executor = ThreadPoolExecutor(max_workers=min(8, len(self._package_keys)))
        futures = {
            executor.submit(self._download_one, package_key): package_key
            for package_key in self._package_keys
        }
        try:
            for future in as_completed(futures):
                if self._cancelled():
                    break
                package_key = futures[future]
                try:
                    outcome = future.result()
                    if outcome == "downloaded":
                        downloaded += 1
                except Exception as exc:
                    failed.append(f"{package_key}: {exc}")
                with self._lock:
                    self._done += 1
                self._emit_progress(package_key)
        except Exception as exc:
            if not self._cancelled():
                self.error.emit(str(exc))
            return
        finally:
            if self._cancelled():
                for future in futures:
                    future.cancel()
            executor.shutdown(wait=not self._cancelled(), cancel_futures=True)
        if self._cancelled():
            return
        self.finished.emit({"downloaded": downloaded, "failed": failed})

    def _download_one(self, package_key: str):
        url = f"{MODEL_PACKAGE_BASE_URL}/{urllib.parse.quote(package_key, safe='')}.zst"
        target = self._models_dir / f"{package_key}.zst"
        part = self._models_dir / f"{package_key}.zst.part"
        if self._cancelled():
            part.unlink(missing_ok=True)
            return "cancelled"
        if not self._overwrite and target.exists() and target.stat().st_size > 0:
            return "skipped"
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass
        req = urllib.request.Request(url, headers={"User-Agent": "Bandori-Pet/1.0"}, method="GET")
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                with self._lock:
                    self._active_responses.add(resp)
                length = int(resp.headers.get("Content-Length") or 0)
                if length:
                    with self._lock:
                        self._known_sizes[package_key] = length
                        self._total_bytes = sum(self._known_sizes.values())
                    self._emit_progress(package_key)
                with part.open("wb") as file:
                    while True:
                        if self._cancelled():
                            return "cancelled"
                        chunk = resp.read(1024 * 256)
                        if not chunk:
                            break
                        if self._cancelled():
                            return "cancelled"
                        file.write(chunk)
                        with self._lock:
                            self._downloaded_bytes += len(chunk)
                        self._emit_progress(package_key)
            if self._cancelled():
                return "cancelled"
            if part.stat().st_size <= 0:
                raise RuntimeError("empty response")
            if target.exists():
                target.unlink()
            part.replace(target)
            return "downloaded"
        finally:
            with self._lock:
                self._active_responses.discard(locals().get("resp"))
            if self._cancelled():
                part.unlink(missing_ok=True)

    def _emit_progress(self, current: str):
        if self._cancelled():
            return
        elapsed = max(time.monotonic() - self._started_at, 0.001)
        with self._lock:
            downloaded_bytes = self._downloaded_bytes
            total_bytes = self._total_bytes
            done = self._done
            known_count = len(self._known_sizes)
        self.progress.emit({
            "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes,
            "known_count": known_count,
            "done": done,
            "total": self._total,
            "speed": downloaded_bytes / elapsed,
            "current": current,
        })


class ModelDetailMetadataWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, model_manager, item: dict, custom_profiles: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self._model_manager = model_manager
        self._item = dict(item or {})
        self._custom_profiles = [dict(profile) for profile in (custom_profiles or [])]

    def run(self):
        try:
            character = self._item.get("character", "")
            costume = self._item.get("costume", "")
            motions = self._model_manager.get_motion_names(character, costume)
            if self.isInterruptionRequested():
                return
            expressions = self._model_manager.get_expression_names(character, costume)
            if self.isInterruptionRequested():
                return
            actions = normalize_click_motion_actions(
                self._item.get("click_motion_actions", {}),
                motions,
                expressions,
            )
            profile_name = self._matching_click_motion_profile_name(
                motions,
                expressions,
                actions,
            )
            if self.isInterruptionRequested():
                return
            self.finished.emit({
                "character": character,
                "costume": costume,
                "motions": motions,
                "expressions": expressions,
                "click_motion_actions": actions,
                "click_motion_profile_name": profile_name,
            })
        except Exception as exc:
            self.error.emit(str(exc))

    def _profile_actions(self, name: str, motions: list[str], expressions: list[str]) -> dict | None:
        from click_motion_presets import BUILTIN_CLICK_MOTION_PROFILES, BUILTIN_PROFILE_NAMES, resolve_preset_to_actions

        name = str(name or "").strip()
        if not name:
            return None
        character = self._item.get("character", "")
        if name in BUILTIN_PROFILE_NAMES:
            preset = next((p for p in BUILTIN_CLICK_MOTION_PROFILES if p["name"] == name), None)
            if not preset:
                return None
            return normalize_click_motion_actions(
                resolve_preset_to_actions(preset, motions, expressions, character),
                motions,
                expressions,
            )
        profile = next((p for p in self._custom_profiles if p.get("name") == name), None)
        if not profile:
            return None
        return normalize_click_motion_actions(
            profile.get("click_motion_actions", {}),
            motions,
            expressions,
        )

    def _profile_matches(self, name: str, motions: list[str], expressions: list[str], actions: dict) -> bool:
        profile_actions = self._profile_actions(name, motions, expressions)
        return profile_actions is not None and profile_actions == actions

    def _matching_click_motion_profile_name(self, motions: list[str], expressions: list[str], actions: dict) -> str:
        from click_motion_presets import BUILTIN_CLICK_MOTION_PROFILES, BUILTIN_PROFILE_NAMES

        stored_name = str(self._item.get("click_motion_profile_name", "") or "").strip()
        if stored_name:
            if stored_name in BUILTIN_PROFILE_NAMES:
                return stored_name
            if self._profile_matches(stored_name, motions, expressions, actions):
                return stored_name

        for preset in BUILTIN_CLICK_MOTION_PROFILES:
            name = preset.get("name", "")
            if name and self._profile_matches(name, motions, expressions, actions):
                return name

        for profile in self._custom_profiles:
            name = str(profile.get("name", "") or "").strip()
            if name and name not in BUILTIN_PROFILE_NAMES and self._profile_matches(name, motions, expressions, actions):
                return name
        return ""


class TestConnectionWorker(CancelableNetworkWorker):
    succeeded = Signal()
    error = Signal(str)

    def __init__(self, api_url: str, api_key: str, model_id: str, api_mode: str = "chat_completions", parent=None):
        super().__init__(parent)
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id
        self._api_mode = api_mode

    def run(self):
        try:
            ctx = ssl.create_default_context()

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            }

            try:
                if self._api_mode == "responses" and not is_google_generative_language_url(self._api_url):
                    self._test_responses_request(urllib.request, json, headers, ctx)
                else:
                    self._test_chat_completions_request(urllib.request, json, headers, ctx)
                if not self.cancelled():
                    self.succeeded.emit()
            except urllib.error.HTTPError as e:
                if self._api_mode == "responses" and e.code in (400, 403, 404, 422):
                    self._test_chat_completions_request(urllib.request, json, headers, ctx)
                    if not self.cancelled():
                        self.succeeded.emit()
                    return
                raise
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                msg = err_body.get("error", {}).get("message", str(e))
            except Exception:
                msg = str(e)
            if not self.cancelled():
                self.error.emit(f"HTTP {e.code}: {msg}")
        except urllib.error.URLError as e:
            if not self.cancelled():
                self.error.emit(f"Network error: {e.reason}")
        except Exception as e:
            if not self.cancelled():
                self.error.emit(str(e))

    def _test_responses_request(self, urllib_request, json_module, headers: dict, ctx):
        url = responses_api_url(self._api_url)
        body = json_module.dumps({
            "model": self._model_id,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": "Hi"}]}],
        }).encode("utf-8")
        req = urllib_request.Request(url, data=body, headers=headers, method="POST")
        resp = self.open_url(req, timeout=30, context=ctx)
        if resp is None:
            return
        try:
            with resp:
                data = json_module.loads(resp.read().decode("utf-8"))
        finally:
            self._release_response(resp)
        if not data.get("id"):
            raise ValueError("Unexpected response format")

    def _test_chat_completions_request(self, urllib_request, json_module, headers: dict, ctx):
        url = chat_completions_api_url(self._api_url)
        body_obj = {
            "model": self._model_id,
            "messages": [{"role": "user", "content": "Hi"}],
        }
        sanitize_chat_body_for_url(body_obj, url)
        body = json_module.dumps(body_obj).encode("utf-8")
        req = urllib_request.Request(url, data=body, headers=headers, method="POST")
        resp = self.open_url(req, timeout=30, context=ctx)
        if resp is None:
            return
        try:
            with resp:
                data = json_module.loads(resp.read().decode("utf-8"))
        finally:
            self._release_response(resp)
        if not data.get("choices", []):
            raise ValueError("Unexpected response format")


class FetchModelsWorker(CancelableNetworkWorker):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, models_url: str, api_key: str, parent=None):
        super().__init__(parent)
        self._models_url = models_url
        self._api_key = api_key

    def run(self):
        try:
            ctx = ssl.create_default_context()

            headers = {
                "Authorization": f"Bearer {self._api_key}",
            }

            req = urllib.request.Request(
                self._models_url, headers=headers, method="GET"
            )

            resp = self.open_url(req, timeout=30, context=ctx)
            if resp is None:
                return
            try:
                with resp:
                    data = json.loads(resp.read().decode("utf-8"))
            finally:
                self._release_response(resp)
            models = data.get("data", [])
            ids = [m.get("id", "") for m in models if m.get("id")]
            if not self.cancelled():
                self.finished.emit(sorted(ids))
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                msg = err_body.get("error", {}).get("message", str(e))
            except Exception:
                msg = str(e)
            if not self.cancelled():
                self.error.emit(f"HTTP {e.code}: {msg}")
        except urllib.error.URLError as e:
            if not self.cancelled():
                self.error.emit(f"Network error: {e.reason}")
        except Exception as e:
            if not self.cancelled():
                self.error.emit(str(e))
