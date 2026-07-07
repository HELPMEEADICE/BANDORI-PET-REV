import json
import locale
import os
import re
import subprocess
import sys
from process_utils import app_base_dir


_SUPPORTED_LANGUAGES = {
    "de_DE",
    "en_US",
    "es_ES",
    "fr_FR",
    "ja",
    "ko",
    "pt_PT",
    "ru_RU",
    "zh_CN",
    "zh_TW",
}
_POSIX_LOCALE_NAMES = {"c", "posix", "utf8", "utf_8", "utf-8"}
_APPLE_LANGUAGE_TOKEN_RE = re.compile(r'"([^"]+)"|([A-Za-z]{2,3}(?:[-_][A-Za-z0-9]+)*)')
_LANGUAGE_ALIASES = {
    "jp": "ja",
    "ja_jp": "ja",
    "japanese": "ja",
    "cn_tw": "zh_TW",
    "zh_tw": "zh_TW",
    "zh_hk": "zh_TW",
    "zh_mo": "zh_TW",
    "zh_hant": "zh_TW",
    "tw": "zh_TW",
    "cn": "zh_CN",
    "zh": "zh_CN",
    "zh_cn": "zh_CN",
    "zh_sg": "zh_CN",
    "zh_hans": "zh_CN",
    "en": "en_US",
    "en_us": "en_US",
    "kr": "ko",
    "ko_kr": "ko",
    "korean": "ko",
    "de": "de_DE",
    "de_at": "de_DE",
    "de_ch": "de_DE",
    "de_de": "de_DE",
    "deutsch": "de_DE",
    "es": "es_ES",
    "es_419": "es_ES",
    "es_es": "es_ES",
    "es_mx": "es_ES",
    "es_us": "es_ES",
    "espanol": "es_ES",
    "espaol": "es_ES",
    "español": "es_ES",
    "fr": "fr_FR",
    "fr_be": "fr_FR",
    "fr_ca": "fr_FR",
    "fr_ch": "fr_FR",
    "fr_fr": "fr_FR",
    "franais": "fr_FR",
    "french": "fr_FR",
    "pt": "pt_PT",
    "pt_br": "pt_PT",
    "pt_pt": "pt_PT",
    "portuguese": "pt_PT",
    "portugus": "pt_PT",
    "ru": "ru_RU",
    "ru_ru": "ru_RU",
    "russian": "ru_RU",
}


def normalize_language(lang: str) -> str:
    key = str(lang or "").strip()
    if not key:
        return ""
    key = key.split(".", 1)[0].split("@", 1)[0].replace("-", "_")
    key = re.sub(r"[^A-Za-z0-9_]", "", key)
    if not key:
        return ""
    lower_key = key.lower()
    if lower_key in _POSIX_LOCALE_NAMES:
        return ""
    alias = _LANGUAGE_ALIASES.get(lower_key)
    if alias:
        return alias

    parts = [part for part in lower_key.split("_") if part]
    primary = parts[0] if parts else ""
    qualifiers = set(parts[1:])
    if primary == "zh":
        if qualifiers & {"tw", "hk", "mo", "hant"}:
            return "zh_TW"
        return "zh_CN"
    if primary == "ja":
        return "ja"
    if primary == "en":
        return "en_US"
    if primary == "de":
        return "de_DE"
    if primary == "es":
        return "es_ES"
    if primary == "fr":
        return "fr_FR"
    if primary == "pt":
        return "pt_PT"
    if primary == "ru":
        return "ru_RU"
    return key


def _first_supported_language(candidates) -> str:
    for candidate in candidates:
        lang = normalize_language(candidate)
        if lang in _SUPPORTED_LANGUAGES:
            return lang
    return ""


def _environment_language_candidates() -> list[str]:
    result = []
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        raw = os.environ.get(name, "")
        for part in str(raw or "").split(":"):
            part = part.strip()
            if part:
                result.append(part)
    return result


def _read_macos_global_default(key: str) -> str:
    try:
        completed = subprocess.run(
            ["defaults", "read", "-g", key],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout


def _macos_language_candidates() -> list[str]:
    candidates = []
    apple_languages = _read_macos_global_default("AppleLanguages")
    for match in _APPLE_LANGUAGE_TOKEN_RE.finditer(apple_languages):
        token = match.group(1) or match.group(2)
        if token:
            candidates.append(token)

    apple_locale = _read_macos_global_default("AppleLocale").strip()
    if apple_locale:
        candidates.append(apple_locale.splitlines()[0].strip())
    return candidates


def _locale_language_candidates() -> list[str]:
    candidates = []
    try:
        lang_code, _ = locale.getlocale()
        if lang_code:
            candidates.append(lang_code)
    except Exception:
        pass
    try:
        lang_code, _ = locale.getdefaultlocale()
        if lang_code:
            candidates.append(lang_code)
    except Exception:
        pass
    return candidates


class I18nManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._translations = {}
        self._current_lang = "en_US"
        self._lang_dir = app_base_dir() / "lang"

    def set_language(self, lang: str):
        self._current_lang = normalize_language(lang) or "en_US"
        self._load()

    def _load(self):
        path = self._lang_dir / f"{self._current_lang}.json"
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    loaded = json.load(f)
                self._translations = loaded if isinstance(loaded, dict) else {}
            except (json.JSONDecodeError, OSError):
                self._translations = {}
        else:
            self._translations = {}

    def get_translation(self, key: str, default: str = None, **kwargs) -> str:
        if not self._translations:
            self._load()
        text = self._translations.get(key)
        if text is None:
            text = default if default is not None else key
        if kwargs:
            try:
                text = text.format(**kwargs)
            except KeyError:
                pass
        return text

    @property
    def current_language(self) -> str:
        return self._current_lang

    @property
    def available_languages(self) -> list[str]:
        return sorted(f.stem for f in self._lang_dir.glob("*.json"))


_i18n = I18nManager()


def tr(key: str, default: str = None, **kwargs) -> str:
    return _i18n.get_translation(key, default, **kwargs)


def date_picker_months() -> list[str]:
    defaults = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    return [
        tr(f"SettingsWindow.date_picker_month_{index}", default=default)
        for index, default in enumerate(defaults, start=1)
    ]


def set_language(lang: str):
    _i18n.set_language(lang)


def current_language() -> str:
    return _i18n.current_language


def available_languages() -> list[str]:
    return _i18n.available_languages


def detect_system_language() -> str:
    if sys.platform == "darwin":
        lang = _first_supported_language(_macos_language_candidates())
        if lang:
            return lang

    lang = _first_supported_language(_environment_language_candidates())
    if lang:
        return lang

    lang = _first_supported_language(_locale_language_candidates())
    if lang:
        return lang

    return "en_US"
