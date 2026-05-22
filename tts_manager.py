import json
import io
import queue
import re
import struct
import urllib.error
import urllib.request
from collections import deque

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from process_utils import app_base_dir


_ACTION_TAG_RE = re.compile(r"\[(?:DONE|[A-Za-z0-9_.\-]+)\]")
_DIALOG_GROUPS_KEY = "__groups"
_WORD_RE = re.compile(r"[A-Za-z']+")


CHARACTER_TRILINGUAL_NAMES = {
    "户山香澄":   ("戸山香澄 (Toyama Kasumi)",    "Kasumi Toyama"),
    "花园多惠":    ("花園たえ (Hanazono Tae)",      "Tae Hanazono"),
    "牛込里美":    ("牛込りみ (Ushigome Rimi)",      "Rimi Ushigome"),
    "山吹沙绫":    ("山吹沙綾 (Yamabuki Saaya)",    "Saaya Yamabuki"),
    "市谷有咲":    ("市ヶ谷有咲 (Ichigaya Arisa)",   "Arisa Ichigaya"),
    "美竹兰":     ("美竹蘭 (Mitake Ran)",         "Ran Mitake"),
    "青叶摩卡":    ("青葉モカ (Aoba Moca)",        "Moca Aoba"),
    "上原绯玛丽":   ("上原ひまり (Uehara Himari)",    "Himari Uehara"),
    "宇田川巴":    ("宇田川巴 (Udagawa Tomoe)",     "Tomoe Udagawa"),
    "羽泽鸫":     ("羽沢つぐみ (Hazawa Tsugumi)",    "Tsugumi Hazawa"),
    "丸山彩":     ("丸山彩 (Maruyama Aya)",       "Aya Maruyama"),
    "冰川日菜":    ("氷川日菜 (Hikawa Hina)",       "Hina Hikawa"),
    "白鹭千圣":    ("白鷺千聖 (Shirasagi Chisato)",  "Chisato Shirasagi"),
    "大和麻弥":    ("大和麻弥 (Yamato Maya)",       "Maya Yamato"),
    "若宫伊芙":    ("若宮イヴ (Wakamiya Eve)",      "Eve Wakamiya"),
    "弦卷心":     ("弦巻こころ (Tsurumaki Kokoro)",  "Kokoro Tsurumaki"),
    "濑田薰":     ("瀬田薫 (Seta Kaoru)",         "Kaoru Seta"),
    "北泽育美":    ("北沢はぐみ (Kitazawa Hagumi)",  "Hagumi Kitazawa"),
    "松原花音":    ("松原花音 (Matsubara Kanon)",    "Kanon Matsubara"),
    "奥泽美咲":    ("奥沢美咲 (Okusawa Misaki)",     "Misaki Okusawa (Michelle)"),
    "凑友希那":    ("湊友希那 (Minato Yukina)",      "Yukina Minato"),
    "冰川纱夜":    ("氷川紗夜 (Hikawa Sayo)",       "Sayo Hikawa"),
    "今井莉莎":    ("今井リサ (Imai Lisa)",         "Lisa Imai"),
    "宇田川亚子":   ("宇田川あこ (Udagawa Ako)",     "Ako Udagawa"),
    "白金燐子":    ("白金燐子 (Shirokane Rinko)",    "Rinko Shirokane"),
    "鳰原令王那":   ("鳰原令王那 / レイヤ (Nihara Reona / PAREO)", "Reona Nihara (PAREO)"),
    "佐藤益木":    ("佐藤ますき (Satou Masuki / MASKING)", "Masuki Satou (MASKING)"),
    "和奏瑞依":    ("和奏レイ (Wakana Rei / LAYER)", "Rei Wakana (LAYER)"),
    "朝日六花":    ("朝日六花 (Asahi Rokka / LOCK)",  "Rokka Asahi (LOCK)"),
    "珠手知由":    ("珠手ちゆ (Shude Chiyu / CHU²)",  "Chiyu Shude (CHU²)"),
    "仓田真白":    ("倉田ましろ (Kurata Mashiro)",     "Mashiro Kurata"),
    "桐谷透子":    ("桐ヶ谷透子 (Kirigaya Touko)",    "Touko Kirigaya"),
    "广町七深":    ("広町七深 (Hiromachi Nanami)",     "Nanami Hiromachi"),
    "二叶筑紫":    ("二葉つくし (Futaba Tsukushi)",     "Tsukushi Futaba"),
    "八潮瑠唯":    ("八潮瑠唯 (Yashio Rui)",         "Rui Yashio"),
    "高松灯":     ("高松燈 (Takamatsu Tomori)",     "Tomori Takamatsu"),
    "千早爱音":    ("千早愛音 (Chihaya Anon)",      "Anon Chihaya"),
    "要乐奈":     ("要楽奈 (Kaname Rāna)",        "Rāna Kaname"),
    "长崎素世":    ("長崎そよ (Nagasaki Soyo)",      "Soyo Nagasaki"),
    "椎名立希":    ("椎名立希 (Shiina Taki)",        "Taki Shiina"),
    "丰川祥子":    ("豊川祥子 (Togawa Sakiko)",     "Sakiko Togawa"),
    "若叶睦":     ("若葉睦 (Wakaba Mutsumi)",      "Mutsumi Wakaba"),
    "三角初华":    ("三角初華 (Misumi Uika)",       "Uika Misumi"),
    "八幡海玲":    ("八幡海鈴 (Yahata Umiri)",       "Umiri Yahata"),
    "祐天寺若麦":   ("祐天寺にゃむ (Yūtenji Nyamu)",  "Nyamu Yūtenji"),
    "纯田真奈":    ("純田まな (Sumida Mana)",       "Mana Sumida"),
    "户山明日香":   ("戸山明日香 (Toyama Asuka)",    "Asuka Toyama"),
    "汐見蛍":     ("汐見螢 (Shiomi Hotaru)",       "Hotaru Shiomi"),
}


_ONE_CHAR_SURNAMES = frozenset({"凑", "要"})


def _find_referenced_characters(text: str) -> dict:
    if not text:
        return {}
    matched: dict[str, tuple[str, str]] = {}
    for cn, (jp, en_) in CHARACTER_TRILINGUAL_NAMES.items():
        if cn in text:
            matched[cn] = (jp, en_)
            continue
        for slen in (3, 2, 1):
            if slen >= len(cn):
                continue
            surname = cn[:slen]
            given = cn[slen:]
            if slen == 1 and surname not in _ONE_CHAR_SURNAMES:
                continue
            if surname in text:
                matched[cn] = (jp, en_)
                break
            if len(given) >= 2 and given in text:
                matched[cn] = (jp, en_)
                break
    return matched


def _build_translation_system_prompt(target_language_name: str, text: str = "") -> str:
    referenced = _find_referenced_characters(text)
    if referenced:
        appendix = "\n\n### BanG Dream! Character Name Reference (CN | JP | EN)\n"
        appendix += "\n".join(
            f"  {cn}  |  {jp}  |  {en_}"
            for cn, (jp, en_) in referenced.items()
        )
        return (
            f"把用户给出的中文聊天台词翻译成自然{target_language_name}，只输出译文，不要解释。保留语气，不要输出动作标签。"
            f"翻译人物名称时请参照以下对照表，按目标语言使用对应名称：\n{appendix}"
        )
    return f"把用户给出的中文聊天台词翻译成自然{target_language_name}，只输出译文，不要解释。保留语气，不要输出动作标签。"


def flush_tts_sentence(buffer: str) -> str:
    return buffer.strip()


def strip_tts_action_tags(text: str) -> str:
    return _ACTION_TAG_RE.sub("", text).strip()


def _aux_model_enable_thinking(config: dict):
    value = config.get("llm_aux_enable_thinking", None)
    return value if value in (True, False, None) else None


_VISEME_POSES = {
    "aa": (0.55, 0.0),
    "ow": (0.34, -0.72),
    "iy": (0.28, 0.82),
    "uw": (0.22, -1.0),
    "mbp": (0.0, 0.0),
    "fv": (0.18, 0.32),
    "neutral": (0.24, 0.0),
}


def _estimate_viseme_units(text: str, language: str = "") -> list[str]:
    text = str(text or "").strip()
    if not text:
        return []
    language = str(language or "").lower()
    units: list[str] = []
    for token in re.findall(r"[A-Za-z']+|[\u3040-\u30ff]+|[\u3400-\u9fff]+|.", text):
        if not token or token.isspace():
            continue
        if _WORD_RE.fullmatch(token):
            units.extend(_estimate_latin_word_visemes(token.lower()))
        elif all("\u3040" <= ch <= "\u30ff" for ch in token):
            units.extend(_estimate_kana_visemes(token))
        elif any("\u3400" <= ch <= "\u9fff" for ch in token):
            fallback = "aa" if language in {"chinese", "zh", "中文"} else "neutral"
            units.extend([fallback] * len(token))
        elif token in ",，.。!！?？:：;；、~～-":
            units.append("mbp")
        else:
            units.append("neutral")
    return units


def _estimate_latin_word_visemes(word: str) -> list[str]:
    units: list[str] = []
    i = 0
    while i < len(word):
        pair3 = word[i:i + 3]
        pair2 = word[i:i + 2]
        ch = word[i]
        if pair2 in {"mb", "mp"}:
            units.append("mbp")
            i += 2
            continue
        if ch in "mbp":
            units.append("mbp")
        elif ch in "fv":
            units.append("fv")
        elif pair3 in {"you", "yoo"} or pair2 in {"oo", "uu", "ew"}:
            units.append("uw")
            i += 3 if pair3 in {"you", "yoo"} else 2
            continue
        elif pair2 in {"ow", "oh", "oa", "ou", "aw", "au"}:
            units.append("ow")
            i += 2
            continue
        elif pair2 in {"ee", "ea", "ie"} or ch in "iy":
            units.append("iy")
        elif ch == "u":
            units.append("uw")
        elif ch == "o":
            units.append("ow")
        elif ch in "ae":
            units.append("aa")
        elif ch in "rlwn":
            units.append("neutral")
        else:
            units.append("aa")
        i += 1
    return units


def _estimate_kana_visemes(text: str) -> list[str]:
    units: list[str] = []
    for ch in text:
        if ch in "まみむめもマミムメモばびぶべぼバビブベボぱぴぷぺぽパピプペポんン":
            units.append("mbp")
        elif ch in "ふフゔヴ":
            units.append("fv")
        elif ch in "いきぎしじちぢにひびぴみりイキギシジチヂニヒビピミリぇェゃャ":
            units.append("iy")
        elif ch in "うくぐすずつづぬぶぷむゆるウクグスズツヅヌブプムユルぅゥゅュ":
            units.append("uw")
        elif ch in "おこごそぞとのほぼぽもよろをオコゴソゾトノホボポモヨロヲぉォょョ":
            units.append("ow")
        elif ch in "ぁァあかがさざただなはばぱやらわアカガサザタダナハバパヤラワ":
            units.append("aa")
        else:
            units.append("neutral")
    return units


def _estimate_units_per_second(language: str) -> float:
    language = str(language or "").lower()
    if language in {"english", "en", "英文"}:
        return 10.0
    if language in {"japanese", "ja", "日文"}:
        return 8.0
    return 7.0


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
        api_url = str(self._config.get("llm_aux_api_url", "") or "").strip() or str(self._config.get("llm_api_url", "") or "").strip()
        api_key = str(self._config.get("llm_aux_api_key", "") or "").strip() or str(self._config.get("llm_api_key", "") or "").strip()
        model_id = str(self._config.get("llm_aux_model_id", "") or "").strip() or str(self._config.get("llm_model_id", "") or "").strip()
        if not api_url or not api_key or not model_id:
            return ""
        body = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": _build_translation_system_prompt(self._language_name(target_language), text)},
                {"role": "user", "content": text},
            ],
            "stream": False,
        }
        enable_thinking = _aux_model_enable_thinking(self._config)
        if enable_thinking is not None:
            body["enable_thinking"] = enable_thinking
            body["thinking"] = {"type": "enabled" if enable_thinking else "disabled"}
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
        self.prepared_text = ""
        self.prepared_language = ""

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
            self.prepared_text = text
            self.prepared_language = text_language

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
            self._apply_qwen_lora(payload)

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

    def _reference_character(self) -> str:
        return str(self._config.get("tts_reference_character", "") or "").strip() or self._character

    def _reference_audio_path(self) -> str:
        ref_char = self._reference_character()
        ref_dir = app_base_dir() / "audio_reference"
        for suffix in (".mp3", ".wav", ".flac", ".ogg", ".m4a"):
            path = ref_dir / f"{ref_char}{suffix}"
            if path.exists():
                return str(path)
        return str(ref_dir / f"{ref_char}.mp3")

    def _reference_prompt_text(self, text_language: str) -> str:
        if text_language not in {"Japanese", "ja", "日文"}:
            return ""
        ref_char = self._reference_character()
        path = app_base_dir() / "audio_reference" / "dialog.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        value = data.get(ref_char, "")
        return value if isinstance(value, str) else ""

    def _apply_qwen_lora(self, payload: dict):
        loras = self._available_qwen_loras()
        if loras is None:
            return
        lora_id = self._reference_lora_id()
        if lora_id and lora_id in loras:
            payload["lora_id"] = lora_id
            return
        self._unload_qwen_lora()

    def _available_qwen_loras(self) -> dict | None:
        try:
            response = requests.get(self._tts_url() + "lora/list", timeout=5)
            if response.status_code != 200:
                return None
            loras = response.json().get("loras")
            return loras if isinstance(loras, dict) else None
        except Exception:
            return None

    def _unload_qwen_lora(self):
        try:
            requests.post(self._tts_url() + "lora/unload", timeout=5)
        except Exception:
            pass

    def _reference_lora_id(self) -> str:
        path = app_base_dir() / "audio_reference" / "dialog.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        groups = data.get(_DIALOG_GROUPS_KEY, {})
        if not isinstance(groups, dict):
            return ""
        ref_char = self._reference_character()
        for group in groups.values():
            if not isinstance(group, dict):
                continue
            members = group.get("characters", [])
            if ref_char in members:
                return str(group.get("lora_id", "") or "").strip()
        return ""

    def _should_translate(self, text_language: str) -> bool:
        if not self._config.get("tts_translate_to_selected_language", True):
            return False
        return text_language not in {"Chinese", "zh", "中文"}

    def _translate_to_selected_language(self, text: str, target_language: str) -> str:
        api_url = str(self._config.get("llm_aux_api_url", "") or "").strip() or str(self._config.get("llm_api_url", "") or "").strip()
        api_key = str(self._config.get("llm_aux_api_key", "") or "").strip() or str(self._config.get("llm_api_key", "") or "").strip()
        model_id = str(self._config.get("llm_aux_model_id", "") or "").strip() or str(self._config.get("llm_model_id", "") or "").strip()
        if not api_url or not api_key or not model_id:
            return ""
        body = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": _build_translation_system_prompt(self._language_name(target_language), text)},
                {"role": "user", "content": text},
            ],
            "stream": False,
        }
        enable_thinking = _aux_model_enable_thinking(self._config)
        if enable_thinking is not None:
            body["enable_thinking"] = enable_thinking
            body["thinking"] = {"type": "enabled" if enable_thinking else "disabled"}
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
    mouth_pose_changed = Signal(float, float)
    playback_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = queue.Queue()
        self._stream = None
        self._sample_rate = 0
        self._channels = 1
        self._current_chunk = None
        self._current_visemes = ()
        self._current_pos = 0
        self._level = 0.0
        self._mouth_open_base = 0.0
        self._mouth_form_base = 0.0
        self._playback_active = False
        self._pending_visemes: deque[str] = deque()
        self._pending_language = ""
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
        self._current_visemes = ()
        self._current_pos = 0
        self._level = 0.0
        self._mouth_open_base = 0.0
        self._mouth_form_base = 0.0
        self._playback_active = False
        self._pending_visemes.clear()
        self._pending_language = ""
        self.level_changed.emit(0.0)
        self.mouth_pose_changed.emit(0.0, 0.0)
        self._level_timer.stop()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def prepare_lip_sync_text(self, text: str, language: str = ""):
        self._pending_visemes = deque(_estimate_viseme_units(text, language))
        self._pending_language = str(language or "")

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
        visemes = self._allocate_chunk_visemes(len(data), sample_rate)
        self._queue.put_nowait((data, tuple(visemes)))
        self._playback_active = True
        if not self._level_timer.isActive():
            self._level_timer.start()

    def _allocate_chunk_visemes(self, frame_count: int, sample_rate: int) -> list[tuple[int, float, float]]:
        if frame_count <= 0 or sample_rate <= 0:
            return []
        duration = frame_count / float(sample_rate)
        count = max(1, int(round(duration * _estimate_units_per_second(self._pending_language))))
        raw_units: list[str] = []
        while self._pending_visemes and len(raw_units) < count:
            raw_units.append(self._pending_visemes.popleft())
        if not raw_units:
            raw_units.append("neutral")
        per_unit = max(1, frame_count // len(raw_units))
        result: list[tuple[int, float, float]] = []
        for index, name in enumerate(raw_units, start=1):
            end_frame = frame_count if index == len(raw_units) else min(frame_count, per_unit * index)
            open_value, form_value = _VISEME_POSES.get(name, _VISEME_POSES["neutral"])
            result.append((end_frame, open_value, form_value))
        return result

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
                    self._current_chunk, self._current_visemes = self._queue.get_nowait()
                except queue.Empty:
                    return
                self._current_pos = 0

            available = len(self._current_chunk) - self._current_pos
            take = min(available, frames - filled)
            chunk = self._current_chunk[self._current_pos:self._current_pos + take]
            rms = float(np.sqrt(np.mean(chunk * chunk)))
            peak = float(np.max(np.abs(chunk)))
            self._level = max(self._level, min(max(rms * 4.0, peak * 0.35), 0.55))
            self._update_mouth_pose_for_range(self._current_pos, take)
            if chunk.shape[1] == self._channels:
                outdata[filled:filled + take] = chunk
            elif self._channels == 1:
                outdata[filled:filled + take, 0] = chunk[:, 0]
            else:
                outdata[filled:filled + take, :chunk.shape[1]] = chunk
            self._current_pos += take
            filled += take

    def _update_mouth_pose_for_range(self, start_frame: int, frame_count: int):
        if not self._current_visemes:
            self._mouth_open_base, self._mouth_form_base = _VISEME_POSES["neutral"]
            return
        probe = start_frame + max(0, frame_count // 2)
        for end_frame, open_value, form_value in self._current_visemes:
            if probe < end_frame:
                self._mouth_open_base = open_value
                self._mouth_form_base = form_value
                return
        self._mouth_open_base, self._mouth_form_base = self._current_visemes[-1][1:]

    def _emit_level(self):
        level = self._level
        self._level *= 0.55
        if self._mouth_open_base < 0.05:
            mouth_open = min(level * 0.2, 0.04)
            mouth_form = 0.0
        else:
            activity = min(1.0, level / 0.18) if level > 0.01 else 0.0
            mouth_open = min(0.55, max(level * 0.9, self._mouth_open_base * activity))
            mouth_form = self._mouth_form_base * max(0.25, activity) if activity > 0.0 else 0.0
        done = (
            self._queue.empty()
            and (self._current_chunk is None or self._current_pos >= len(self._current_chunk))
        )
        if done and level < 0.01:
            self._level_timer.stop()
            self.level_changed.emit(0.0)
            self.mouth_pose_changed.emit(0.0, 0.0)
            if self._playback_active:
                self._playback_active = False
                self.playback_finished.emit()
            return
        self.level_changed.emit(level)
        self.mouth_pose_changed.emit(mouth_open, max(-1.0, min(1.0, mouth_form)))
