import json
import io
import queue
import re
import struct
import urllib.error
import urllib.request

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from process_utils import app_base_dir


_ACTION_TAG_RE = re.compile(r"\[(?:DONE|[A-Za-z0-9_.\-]+)\]")


def flush_tts_sentence(buffer: str) -> str:
    return buffer.strip()


def strip_tts_action_tags(text: str) -> str:
    return _ACTION_TAG_RE.sub("", text).strip()


class TTSTranslationWorker(QThread):
    translated = Signal(int, int, str, str)
    error = Signal(str)

    def __init__(self, sequence: int, generation: int, text: str, character: str, config: dict, parent=None):
        super().__init__(parent)
        self.sequence = sequence
        self.generation = generation
        self._text = text
        self._character = character
        self._config = config

    def run(self):
        try:
            selected_language = self._config.get("tts_language", "Chinese") or "Chinese"
            text = strip_tts_action_tags(self._text)
            if not text:
                return
            if self._should_translate(selected_language):
                translated = self._translate_to_selected_language(text, selected_language)
                if translated:
                    text = translated
            self.translated.emit(self.sequence, self.generation, text, self._character)
        except Exception as exc:
            self.error.emit(f"TTS translation: {exc}")
            text = strip_tts_action_tags(self._text)
            if text:
                self.translated.emit(self.sequence, self.generation, text, self._character)

    def _should_translate(self, text_language: str) -> bool:
        if not self._config.get("tts_translate_to_selected_language", True):
            return False
        return text_language not in {"Chinese", "zh", "中文"}

    def _translate_to_selected_language(self, text: str, target_language: str) -> str:
        api_url = str(self._config.get("llm_api_url", "") or "").strip()
        api_key = str(self._config.get("llm_api_key", "") or "").strip()
        model_id = str(self._config.get("llm_aux_model_id", "") or "").strip() or str(self._config.get("llm_model_id", "") or "").strip()
        if not api_url or not api_key or not model_id:
            return ""
        body = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": f"把用户给出的中文聊天台词翻译成自然{self._language_name(target_language)}，只输出译文，不要解释。保留语气，不要输出动作标签。"},
                {"role": "user", "content": text},
            ],
            "stream": False,
        }
        req = urllib.request.Request(
            api_url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

    @staticmethod
    def _language_name(language: str) -> str:
        names = {
            "Japanese": "日语",
            "ja": "日语",
            "日文": "日语",
            "English": "英语",
            "en": "英语",
            "英文": "英语",
        }
        return names.get(language, language)


class TTSRequestWorker(QThread):
    audio_ready = Signal(int, int, bytes, str)
    error = Signal(str)

    def __init__(self, sequence: int, generation: int, text: str, character: str, config: dict, parent=None):
        super().__init__(parent)
        self.sequence = sequence
        self.generation = generation
        self._text = text
        self._character = character
        self._config = config

    def run(self):
        try:
            selected_language = self._config.get("tts_language", "Chinese") or "Chinese"
            text_language = selected_language
            text = strip_tts_action_tags(self._text)
            if not text:
                return
            if self._should_translate(selected_language):
                translated = self._translate_to_selected_language(text, selected_language)
                if translated:
                    text = translated

            payload = {
                "refer_wav_path": self._reference_audio_path(),
                "text": text,
                "text_language": text_language,
                "cut_punc": "",
                "stream_mode": "normal" if self._config.get("tts_streaming", True) else "close",
            }
            try:
                payload["temperature"] = max(0.01, min(2.0, float(self._config.get("tts_temperature", 0.9))))
            except (TypeError, ValueError):
                payload["temperature"] = 0.9
            streaming = bool(self._config.get("tts_streaming", True))
            if streaming:
                payload["media_type"] = "ogg"
                payload["stream_format"] = "framed"
                payload["chunk_size"] = 8
            else:
                payload["media_type"] = "wav"
            prompt_text = self._reference_prompt_text(selected_language)
            if prompt_text:
                payload["prompt_text"] = prompt_text

            response = requests.post(self._tts_url(), json=payload, stream=streaming, timeout=120)
            if response.status_code != 200:
                self.error.emit(f"TTS HTTP {response.status_code}: {response.text[:240]}")
                return
            if streaming:
                content_type = response.headers.get("Content-Type", "")
                if "application/octet-stream" in content_type:
                    self._read_framed_stream(response)
                else:
                    for chunk in response.iter_content(chunk_size=None):
                        if self.isInterruptionRequested():
                            response.close()
                            return
                        if chunk:
                            self.audio_ready.emit(self.sequence, self.generation, chunk, "ogg")
            elif response.content:
                self.audio_ready.emit(self.sequence, self.generation, response.content, "wav")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            self.error.emit(f"TTS HTTP {exc.code}: {body[:240]}")
        except Exception as exc:
            self.error.emit(f"TTS: {exc}")

    def _read_framed_stream(self, response):
        buffer = bytearray()
        expected_size = None
        for chunk in response.iter_content(chunk_size=65536):
            if self.isInterruptionRequested():
                response.close()
                return
            if not chunk:
                continue
            buffer.extend(chunk)
            while True:
                if expected_size is None:
                    if len(buffer) < 4:
                        break
                    expected_size = struct.unpack(">I", buffer[:4])[0]
                    del buffer[:4]
                if len(buffer) < expected_size:
                    break
                audio = bytes(buffer[:expected_size])
                del buffer[:expected_size]
                expected_size = None
                if audio:
                    self.audio_ready.emit(self.sequence, self.generation, audio, "ogg")

    def _tts_url(self) -> str:
        url = str(self._config.get("tts_api_url", "") or "").strip() or "http://127.0.0.1:9880/"
        return url if url.endswith("/") else url + "/"

    def _reference_audio_path(self) -> str:
        ref_char = str(self._config.get("tts_reference_character", "") or "").strip() or self._character
        ref_dir = app_base_dir() / "audio_reference"
        for suffix in (".mp3", ".wav", ".flac", ".ogg", ".m4a"):
            path = ref_dir / f"{ref_char}{suffix}"
            if path.exists():
                return str(path)
        return str(ref_dir / f"{ref_char}.mp3")

    def _reference_prompt_text(self, text_language: str) -> str:
        if text_language not in {"Japanese", "ja", "日文"}:
            return ""
        ref_char = str(self._config.get("tts_reference_character", "") or "").strip() or self._character
        path = app_base_dir() / "audio_reference" / "dialog.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        value = data.get(ref_char, "")
        return value if isinstance(value, str) else ""

    def _should_translate(self, text_language: str) -> bool:
        if not self._config.get("tts_translate_to_selected_language", True):
            return False
        return text_language not in {"Chinese", "zh", "中文"}

    def _translate_to_selected_language(self, text: str, target_language: str) -> str:
        api_url = str(self._config.get("llm_api_url", "") or "").strip()
        api_key = str(self._config.get("llm_api_key", "") or "").strip()
        model_id = str(self._config.get("llm_aux_model_id", "") or "").strip() or str(self._config.get("llm_model_id", "") or "").strip()
        if not api_url or not api_key or not model_id:
            return ""
        body = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": f"把用户给出的中文聊天台词翻译成自然{self._language_name(target_language)}，只输出译文，不要解释。保留语气，不要输出动作标签。"},
                {"role": "user", "content": text},
            ],
            "stream": False,
        }
        req = urllib.request.Request(
            api_url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

    @staticmethod
    def _language_name(language: str) -> str:
        names = {
            "Japanese": "日语",
            "ja": "日语",
            "日文": "日语",
            "English": "英语",
            "en": "英语",
            "英文": "英语",
        }
        return names.get(language, language)


class TTSPlayer(QObject):
    error = Signal(str)
    level_changed = Signal(float)
    playback_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream = None
        self._sample_rate = 0
        self._channels = 1
        self._current_chunk = None
        self._current_pos = 0
        self._level = 0.0
        self._playback_active = False
        self._level_timer = QTimer(self)
        self._level_timer.setInterval(33)
        self._level_timer.timeout.connect(self._emit_level)

    def stop(self):
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        self._stream = None
        self._current_chunk = None
        self._current_pos = 0
        self._level = 0.0
        self._playback_active = False
        self.level_changed.emit(0.0)
        self._level_timer.stop()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def enqueue(self, audio: bytes, media_type: str = "wav"):
        if not audio:
            return
        del media_type
        try:
            data, sample_rate = sf.read(io.BytesIO(audio), dtype="float32")
        except Exception as exc:
            self.error.emit(f"TTS audio decode failed: {exc}")
            return
        if data.size == 0:
            return
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        if self._stream is not None and sample_rate != self._sample_rate:
            self.stop()
        self._ensure_stream(sample_rate, data.shape[1])
        self._queue.put_nowait(data)
        self._playback_active = True
        if not self._level_timer.isActive():
            self._level_timer.start()

    def is_idle(self) -> bool:
        return (
            not self._playback_active
            or (
                self._queue.empty()
                and (self._current_chunk is None or self._current_pos >= len(self._current_chunk))
            )
        )

    def _ensure_stream(self, sample_rate: int, channels: int):
        if self._stream is not None:
            return
        self._sample_rate = sample_rate
        self._channels = max(1, channels)
        try:
            self._stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=self._channels,
                dtype="float32",
                callback=self._audio_callback,
                blocksize=0,
            )
            self._stream.start()
            if not self._level_timer.isActive():
                self._level_timer.start()
        except Exception as exc:
            self._stream = None
            self.error.emit(f"TTS playback failed: {exc}")

    def _audio_callback(self, outdata, frames, time_info, status):
        del time_info, status
        outdata.fill(0)
        filled = 0
        while filled < frames:
            if self._current_chunk is None or self._current_pos >= len(self._current_chunk):
                try:
                    self._current_chunk = self._queue.get_nowait()
                except queue.Empty:
                    return
                self._current_pos = 0

            available = len(self._current_chunk) - self._current_pos
            take = min(available, frames - filled)
            chunk = self._current_chunk[self._current_pos:self._current_pos + take]
            rms = float(np.sqrt(np.mean(chunk * chunk)))
            peak = float(np.max(np.abs(chunk)))
            self._level = max(self._level, min(max(rms * 4.0, peak * 0.35), 0.55))
            if chunk.shape[1] == self._channels:
                outdata[filled:filled + take] = chunk
            elif self._channels == 1:
                outdata[filled:filled + take, 0] = chunk[:, 0]
            else:
                outdata[filled:filled + take, :chunk.shape[1]] = chunk
            self._current_pos += take
            filled += take

    def _emit_level(self):
        level = self._level
        self._level *= 0.55
        done = (
            self._queue.empty()
            and (self._current_chunk is None or self._current_pos >= len(self._current_chunk))
        )
        if done and level < 0.01:
            self._level_timer.stop()
            self.level_changed.emit(0.0)
            if self._playback_active:
                self._playback_active = False
                self.playback_finished.emit()
            return
        self.level_changed.emit(level)
