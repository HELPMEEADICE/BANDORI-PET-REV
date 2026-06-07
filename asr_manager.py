import io
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from process_utils import app_base_dir


_NUMPY_MODULE = None
_REQUESTS_MODULE = None
_SOUNDDEVICE_MODULE = None
_SOUNDFILE_MODULE = None
ASR_LOCAL_API_URL = "http://127.0.0.1:8000/v1/audio/transcriptions"
ASR_LOCAL_SERVER_DIR = app_base_dir() / ".runtime" / "asr-server"
ASR_LOCAL_MODEL = "Systran/faster-whisper-small"
ASR_LOCAL_DEVICE = "cpu"
ASR_LOCAL_COMPUTE_TYPE = "int8"
_LOCAL_ASR_PROCESS = None
_LOCAL_ASR_LOCK = threading.Lock()


_LOCAL_ASR_REQUIREMENTS = """fastapi
uvicorn
python-multipart
faster-whisper
"""


_LOCAL_ASR_SERVER = '''import os
import tempfile

from fastapi import FastAPI, File, Form, UploadFile
from faster_whisper import WhisperModel


MODEL_NAME = os.environ.get("ASR_MODEL", "Systran/faster-whisper-small")
DEVICE = os.environ.get("ASR_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("ASR_COMPUTE_TYPE", "int8")
HOST = os.environ.get("ASR_HOST", "127.0.0.1")
PORT = int(os.environ.get("ASR_PORT", "8000"))

app = FastAPI()
model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)


@app.get("/health")
def health():
    return {"ok": True, "model": MODEL_NAME, "device": DEVICE, "host": HOST, "port": PORT}


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model_name: str = Form("", alias="model"),
    language: str = Form("", alias="language"),
):
    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        temp.write(await file.read())
        temp_path = temp.name

    try:
        segments, _info = model.transcribe(
            temp_path,
            language=language or None,
            vad_filter=True,
        )
        text = "".join(segment.text for segment in segments).strip()
        return {"text": text}
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
'''


_LOCAL_ASR_START_PS1 = '''$ErrorActionPreference = "Stop"
$env:ASR_MODEL = if ($env:ASR_MODEL) { $env:ASR_MODEL } else { "Systran/faster-whisper-small" }
$env:ASR_DEVICE = if ($env:ASR_DEVICE) { $env:ASR_DEVICE } else { "cpu" }
$env:ASR_COMPUTE_TYPE = if ($env:ASR_COMPUTE_TYPE) { $env:ASR_COMPUTE_TYPE } else { "int8" }
$env:ASR_HOST = if ($env:ASR_HOST) { $env:ASR_HOST } else { "127.0.0.1" }
$env:ASR_PORT = if ($env:ASR_PORT) { $env:ASR_PORT } else { "8000" }
& "$PSScriptRoot\\.venv\\Scripts\\python.exe" "$PSScriptRoot\\server.py"
'''


def _local_asr_python() -> Path:
    if sys.platform == "win32":
        return ASR_LOCAL_SERVER_DIR / ".venv" / "Scripts" / "python.exe"
    return ASR_LOCAL_SERVER_DIR / ".venv" / "bin" / "python"


def _is_windows_store_python_alias(executable: str) -> bool:
    if sys.platform != "win32":
        return False
    normalized = os.path.normcase(os.path.normpath(executable))
    windows_apps = os.path.normcase(os.path.normpath(
        os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Microsoft",
            "WindowsApps",
        )
    ))
    return bool(windows_apps) and (
        normalized == windows_apps
        or normalized.startswith(windows_apps + os.sep)
    )


def _windows_python_install_candidates() -> list[str]:
    candidates = []
    roots = []
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        roots.append(Path(local_app_data) / "Programs" / "Python")
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(env_name, "").strip()
        if value:
            roots.append(Path(value))
    patterns = ("Python*/python.exe", "Python/python.exe")
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in patterns:
            candidates.extend(str(path) for path in sorted(root.glob(pattern), reverse=True))
    return candidates


def _venv_python_candidates() -> list[list[str]]:
    if not getattr(sys, "frozen", False):
        return [[sys.executable]]

    candidates = []
    configured_python = os.environ.get("BANDORI_ASR_PYTHON", "").strip()
    if configured_python:
        candidates.append([configured_python])

    if sys.platform == "win32":
        launcher = shutil.which("py")
        if launcher:
            candidates.append([launcher, "-3"])
        for name in ("python", "python3"):
            executable = shutil.which(name)
            if executable and not _is_windows_store_python_alias(executable):
                candidates.append([executable])
        candidates.extend([path] for path in _windows_python_install_candidates())
    else:
        for name in ("python3", "python"):
            executable = shutil.which(name)
            if executable:
                candidates.append([executable])

    unique = []
    seen = set()
    for command in candidates:
        key = tuple(os.path.normcase(part) for part in command)
        if key not in seen:
            seen.add(key)
            unique.append(command)
    return unique


def _python_can_create_venv(command: list[str]) -> bool:
    executable = command[0]
    if _is_windows_store_python_alias(executable):
        return False
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        result = subprocess.run(
            [
                *command,
                "-c",
                "import sys, venv; raise SystemExit(0 if sys.version_info.major == 3 else 1)",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            startupinfo=startupinfo,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _venv_create_command() -> list[str]:
    for command in _venv_python_candidates():
        if _python_can_create_venv(command):
            return [
                *command,
                "-m",
                "venv",
                str(ASR_LOCAL_SERVER_DIR / ".venv"),
            ]
    raise RuntimeError(
        "未找到可用于安装本地 ASR 的 Python 3。"
        "请从 https://www.python.org/downloads/windows/ 安装 Python 3，"
        "安装时勾选“Add Python to PATH”，然后重新点击一键安装。"
        "WindowsApps 目录中的 python.exe 只是 Microsoft Store 启动别名，无法创建 ASR 环境。"
    )


def _local_asr_log_path() -> Path:
    return ASR_LOCAL_SERVER_DIR / "server.log"


def _local_asr_runtime_endpoint() -> tuple[str, int]:
    host = str(os.environ.get("ASR_HOST", "127.0.0.1") or "127.0.0.1").strip()
    try:
        port = int(os.environ.get("ASR_PORT", "8000") or "8000")
    except (TypeError, ValueError):
        port = 8000
    return host, port


def _local_asr_connect_host(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::"} else host


def _local_asr_api_url(host: str, port: int) -> str:
    connect_host = _local_asr_connect_host(host)
    if ":" in connect_host and not connect_host.startswith("["):
        connect_host = f"[{connect_host}]"
    return f"http://{connect_host}:{port}/v1/audio/transcriptions"


def _is_local_asr_port_open(host: str = "127.0.0.1", port: int = 8000, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _write_local_asr_files() -> None:
    ASR_LOCAL_SERVER_DIR.mkdir(parents=True, exist_ok=True)
    (ASR_LOCAL_SERVER_DIR / "requirements.txt").write_text(_LOCAL_ASR_REQUIREMENTS, encoding="utf-8")
    (ASR_LOCAL_SERVER_DIR / "server.py").write_text(_LOCAL_ASR_SERVER, encoding="utf-8")
    (ASR_LOCAL_SERVER_DIR / "start_asr_server.ps1").write_text(_LOCAL_ASR_START_PS1, encoding="utf-8")


def _run_command(command: list[str], cwd: Path, timeout: float | None = None) -> str:
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    result = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        startupinfo=startupinfo,
    )
    output = (result.stdout or "").strip()
    if result.returncode != 0:
        raise RuntimeError(output or f"Command failed with exit code {result.returncode}: {' '.join(command)}")
    return output


def _tail_local_asr_log(max_chars: int = 1800) -> str:
    path = _local_asr_log_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-max_chars:].strip()


def _launch_local_asr_server() -> tuple[bool, str]:
    global _LOCAL_ASR_PROCESS
    with _LOCAL_ASR_LOCK:
        return _launch_local_asr_server_locked()


def _launch_local_asr_server_locked() -> tuple[bool, str]:
    global _LOCAL_ASR_PROCESS
    host, port = _local_asr_runtime_endpoint()
    connect_host = _local_asr_connect_host(host)
    if _is_local_asr_port_open(connect_host, port):
        return True, f"ASR local server is already listening on {connect_host}:{port}."
    python = _local_asr_python()
    server = ASR_LOCAL_SERVER_DIR / "server.py"
    if not python.exists() or not server.exists():
        raise RuntimeError("Local ASR server is not installed yet.")

    env = os.environ.copy()
    env.setdefault("ASR_MODEL", ASR_LOCAL_MODEL)
    env.setdefault("ASR_DEVICE", ASR_LOCAL_DEVICE)
    env.setdefault("ASR_COMPUTE_TYPE", ASR_LOCAL_COMPUTE_TYPE)
    env.setdefault("ASR_HOST", host)
    env.setdefault("ASR_PORT", str(port))
    log = _local_asr_log_path().open("a", encoding="utf-8", errors="replace")
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        _LOCAL_ASR_PROCESS = subprocess.Popen(
            [str(python), str(server)],
            cwd=str(ASR_LOCAL_SERVER_DIR),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    finally:
        log.close()
    for _ in range(80):
        if _is_local_asr_port_open(connect_host, port, timeout=0.15):
            return True, "ASR local server is ready."
        if _LOCAL_ASR_PROCESS.poll() is not None:
            detail = _tail_local_asr_log()
            raise RuntimeError(detail or "Local ASR server exited before it became ready.")
        time.sleep(0.25)
    return False, "ASR local server started. The first model load may still be downloading."


class ASRLocalServerInstallWorker(QThread):
    progress = Signal(str)
    installed = Signal(dict)
    error = Signal(str)

    def run(self):
        try:
            self.progress.emit("正在准备本地 ASR 服务目录...")
            _write_local_asr_files()

            python = _local_asr_python()
            if not python.exists():
                self.progress.emit("正在创建独立 Python 环境...")
                _run_command(_venv_create_command(), app_base_dir())

            self.progress.emit("正在安装 ASR 后端依赖，首次可能需要几分钟...")
            _run_command(
                [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt"],
                ASR_LOCAL_SERVER_DIR,
            )

            self.progress.emit("正在启动本地 ASR 服务...")
            ready, message = _launch_local_asr_server()
            host, port = _local_asr_runtime_endpoint()
            self.installed.emit({
                "api_url": _local_asr_api_url(host, port),
                "server_dir": str(ASR_LOCAL_SERVER_DIR),
                "ready": ready,
                "message": message,
            })
        except Exception as exc:
            self.error.emit(str(exc))


def _numpy():
    global _NUMPY_MODULE
    if _NUMPY_MODULE is None:
        import numpy as module
        _NUMPY_MODULE = module
    return _NUMPY_MODULE


def _requests():
    global _REQUESTS_MODULE
    if _REQUESTS_MODULE is None:
        import requests as module
        _REQUESTS_MODULE = module
    return _REQUESTS_MODULE


def _sounddevice():
    global _SOUNDDEVICE_MODULE
    if _SOUNDDEVICE_MODULE is None:
        import sounddevice as module
        _SOUNDDEVICE_MODULE = module
    return _SOUNDDEVICE_MODULE


def _soundfile():
    global _SOUNDFILE_MODULE
    if _SOUNDFILE_MODULE is None:
        import soundfile as module
        _SOUNDFILE_MODULE = module
    return _SOUNDFILE_MODULE


def normalize_asr_api_url(url: str) -> str:
    url = str(url or "").strip() or ASR_LOCAL_API_URL
    if "://" not in url:
        url = f"http://{url}"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme and parsed.netloc and parsed.path in ("", "/"):
        return urllib.parse.urlunparse(parsed._replace(path="/v1/audio/transcriptions"))
    normalized_path = parsed.path.rstrip("/").lower()
    if normalized_path == "/v1":
        return urllib.parse.urlunparse(parsed._replace(path=parsed.path.rstrip("/") + "/audio/transcriptions"))
    if normalized_path == "/v1/audio":
        return urllib.parse.urlunparse(parsed._replace(path=parsed.path.rstrip("/") + "/transcriptions"))
    if parsed.scheme and parsed.netloc and parsed.path.endswith("/"):
        return urllib.parse.urlunparse(parsed._replace(path=parsed.path + "v1/audio/transcriptions"))
    return url


def _response_text_excerpt(response, max_chars: int = 600) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = getattr(response, "text", "") or ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            payload = error.get("message") or error.get("detail") or payload
        elif isinstance(error, str):
            payload = error
        elif "detail" in payload:
            payload = payload.get("detail")
    text = str(payload or "").strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "..."
    return text


def format_asr_request_error(exc: Exception, url: str) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        detail = _response_text_excerpt(response)
        suffix = f"；服务返回：{detail}" if detail else ""
        return f"ASR 请求失败: HTTP {response.status_code} {response.reason}，地址 {url}{suffix}"

    try:
        requests_module = _requests()
    except Exception:
        return f"ASR 请求失败: {exc}"
    if isinstance(exc, requests_module.exceptions.MissingSchema):
        return f"ASR 请求失败: API 地址缺少 http:// 或 https://，当前地址 {url}"
    if isinstance(exc, requests_module.exceptions.ConnectionError):
        return f"ASR 请求失败: 无法连接到 {url}，请确认 Whisper 服务已启动、监听地址不是仅限容器/服务器本机的 127.0.0.1，并检查端口和防火墙。"
    if isinstance(exc, requests_module.exceptions.Timeout):
        return f"ASR 请求失败: 连接 {url} 超时，模型可能仍在加载或服务端处理过慢。"
    return f"ASR 请求失败: {exc}"


class ASRRecorderWorker(QThread):
    audio_ready = Signal(bytes, str)
    level_changed = Signal(float)
    error = Signal(str)

    def __init__(self, config: dict | None = None, parent=None):
        super().__init__(parent)
        self._config = dict(config or {})

    def run(self):
        sample_rate = int(self._config.get("asr_sample_rate", 16000) or 16000)
        max_seconds = max(1.0, float(self._config.get("asr_max_record_seconds", 60) or 60))
        channels = 1
        chunks = []
        started = time.monotonic()
        np = _numpy()

        def callback(indata, frames, time_info, status):
            if status:
                pass
            block = indata.copy()
            chunks.append(block)
            if block.size:
                level = float(min(1.0, max(0.0, np.sqrt(np.mean(np.square(block))) * 8.0)))
                self.level_changed.emit(level)

        try:
            with _sounddevice().InputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
                callback=callback,
            ):
                while not self.isInterruptionRequested():
                    if time.monotonic() - started >= max_seconds:
                        break
                    self.msleep(40)
        except Exception as exc:
            self.error.emit(f"ASR 录音失败: {exc}")
            return

        if not chunks:
            self.error.emit("没有录到可识别的音频。")
            return
        try:
            audio = np.concatenate(chunks, axis=0)
            buffer = io.BytesIO()
            _soundfile().write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
            self.audio_ready.emit(buffer.getvalue(), "audio/wav")
        except Exception as exc:
            self.error.emit(f"ASR 音频编码失败: {exc}")


class ASRRequestWorker(QThread):
    text_ready = Signal(str)
    error = Signal(str)

    def __init__(self, audio: bytes, media_type: str, config: dict | None = None, parent=None):
        super().__init__(parent)
        self._audio = bytes(audio or b"")
        self._media_type = media_type or "audio/wav"
        self._config = dict(config or {})

    def run(self):
        if not self._audio:
            self.error.emit("没有可提交的录音。")
            return
        url = normalize_asr_api_url(self._config.get("asr_api_url", ""))
        api_key = str(self._config.get("asr_api_key", "") or "").strip()
        model = str(self._config.get("asr_model_id", "") or "").strip() or "whisper-large-v3"
        language = str(self._config.get("asr_language", "") or "").strip()
        timeout = max(5.0, float(self._config.get("asr_timeout_seconds", 60) or 60))
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        data = {"model": model}
        if language:
            data["language"] = language
        files = {
            "file": ("speech.wav", self._audio, self._media_type),
        }
        try:
            response = _requests().post(url, headers=headers, data=data, files=files, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            self.error.emit(format_asr_request_error(exc, url))
            return

        text = ""
        if isinstance(payload, dict):
            for key in ("text", "transcript", "result"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    break
            if not text and isinstance(payload.get("segments"), list):
                text = "".join(str(item.get("text", "")) for item in payload["segments"] if isinstance(item, dict)).strip()
        if not text:
            self.error.emit("ASR 服务没有返回可用文本。")
            return
        self.text_ready.emit(text)
