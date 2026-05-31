import io
import time
import urllib.parse

from PySide6.QtCore import QThread, Signal


_NUMPY_MODULE = None
_REQUESTS_MODULE = None
_SOUNDDEVICE_MODULE = None
_SOUNDFILE_MODULE = None


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
    url = str(url or "").strip() or "http://127.0.0.1:8000/v1/audio/transcriptions"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme and parsed.netloc and parsed.path in ("", "/"):
        return url.rstrip("/") + "/v1/audio/transcriptions"
    lowered = url.rstrip("/").lower()
    if lowered.endswith("/v1") or lowered.endswith("/v1/audio"):
        return url.rstrip("/") + "/audio/transcriptions" if lowered.endswith("/v1") else url.rstrip("/") + "/transcriptions"
    if url.endswith("/"):
        return url + "v1/audio/transcriptions"
    return url


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
            self.error.emit(f"ASR 请求失败: {exc}")
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
