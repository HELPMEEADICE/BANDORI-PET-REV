from settings_window.constants import *


def _responses_api_url(api_url: str) -> str:
    return responses_api_url(api_url)


def _chat_completions_api_url(api_url: str) -> str:
    return chat_completions_api_url(api_url)


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


class McpConnectionTestWorker(QThread):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = dict(config or {})

    def run(self):
        try:
            from mcp_bridge import test_mcp_servers

            success, details = test_mcp_servers(self._config)
            if success:
                self.finished.emit(details)
            else:
                self.error.emit(details)
        except Exception as exc:
            self.error.emit(str(exc))


class ModelPackageDownloadWorker(QThread):
    progress = Signal(dict)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, package_keys: list[str], models_dir, parent=None):
        super().__init__(parent)
        self._package_keys = list(package_keys)
        self._models_dir = models_dir
        self._downloaded_bytes = 0
        self._total_bytes = 0
        self._known_sizes: dict[str, int] = {}
        self._done = 0
        self._total = len(self._package_keys)
        self._started_at = 0.0
        self._lock = threading.Lock()

    def run(self):
        if not self._package_keys:
            self.finished.emit({"downloaded": 0, "failed": []})
            return
        self._started_at = time.monotonic()
        downloaded = 0
        failed = []
        try:
            with ThreadPoolExecutor(max_workers=min(8, len(self._package_keys))) as executor:
                futures = {
                    executor.submit(self._download_one, package_key): package_key
                    for package_key in self._package_keys
                }
                for future in as_completed(futures):
                    if self.isInterruptionRequested():
                        break
                    package_key = futures[future]
                    try:
                        future.result()
                        downloaded += 1
                    except Exception as exc:
                        failed.append(f"{package_key}: {exc}")
                    with self._lock:
                        self._done += 1
                    self._emit_progress(package_key)
        except Exception as exc:
            self.error.emit(str(exc))
            return
        self.finished.emit({"downloaded": downloaded, "failed": failed})

    def _download_one(self, package_key: str):
        if self.isInterruptionRequested():
            return
        url = f"{MODEL_PACKAGE_BASE_URL}/{urllib.parse.quote(package_key, safe='')}.zst"
        target = self._models_dir / f"{package_key}.zst"
        part = self._models_dir / f"{package_key}.zst.part"
        if target.exists() and target.stat().st_size > 0:
            return
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass
        req = urllib.request.Request(url, headers={"User-Agent": "Bandori-Pet/1.0"}, method="GET")
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            length = int(resp.headers.get("Content-Length") or 0)
            if length:
                with self._lock:
                    self._known_sizes[package_key] = length
                    self._total_bytes = sum(self._known_sizes.values())
                self._emit_progress(package_key)
            with part.open("wb") as file:
                while True:
                    if self.isInterruptionRequested():
                        raise RuntimeError("cancelled")
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    file.write(chunk)
                    with self._lock:
                        self._downloaded_bytes += len(chunk)
                    self._emit_progress(package_key)
        if part.stat().st_size <= 0:
            raise RuntimeError("empty response")
        if target.exists():
            target.unlink()
        part.replace(target)

    def _emit_progress(self, current: str):
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


class TestConnectionWorker(QThread):
    finished = Signal()
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
                self.finished.emit()
            except urllib.error.HTTPError as e:
                if self._api_mode == "responses" and e.code in (400, 403, 404, 422):
                    self._test_chat_completions_request(urllib.request, json, headers, ctx)
                    self.finished.emit()
                    return
                raise
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                msg = err_body.get("error", {}).get("message", str(e))
            except Exception:
                msg = str(e)
            self.error.emit(f"HTTP {e.code}: {msg}")
        except urllib.error.URLError as e:
            self.error.emit(f"Network error: {e.reason}")
        except Exception as e:
            self.error.emit(str(e))

    def _test_responses_request(self, urllib_request, json_module, headers: dict, ctx):
        url = _responses_api_url(self._api_url)
        body = json_module.dumps({
            "model": self._model_id,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": "Hi"}]}],
        }).encode("utf-8")
        req = urllib_request.Request(url, data=body, headers=headers, method="POST")
        with urllib_request.urlopen(req, timeout=30, context=ctx) as resp:
            data = json_module.loads(resp.read().decode("utf-8"))
            if not data.get("id"):
                raise ValueError("Unexpected response format")

    def _test_chat_completions_request(self, urllib_request, json_module, headers: dict, ctx):
        url = _chat_completions_api_url(self._api_url)
        body_obj = {
            "model": self._model_id,
            "messages": [{"role": "user", "content": "Hi"}],
        }
        sanitize_chat_body_for_url(body_obj, url)
        body = json_module.dumps(body_obj).encode("utf-8")
        req = urllib_request.Request(url, data=body, headers=headers, method="POST")
        with urllib_request.urlopen(req, timeout=30, context=ctx) as resp:
            data = json_module.loads(resp.read().decode("utf-8"))
            if not data.get("choices", []):
                raise ValueError("Unexpected response format")


class FetchModelsWorker(QThread):
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

            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("data", [])
                ids = [m.get("id", "") for m in models if m.get("id")]
                self.finished.emit(sorted(ids))
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                msg = err_body.get("error", {}).get("message", str(e))
            except Exception:
                msg = str(e)
            self.error.emit(f"HTTP {e.code}: {msg}")
        except urllib.error.URLError as e:
            self.error.emit(f"Network error: {e.reason}")
        except Exception as e:
            self.error.emit(str(e))
