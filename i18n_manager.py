import json
import locale
from process_utils import app_base_dir


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
        self._current_lang = lang
        self._load()

    def _load(self):
        path = self._lang_dir / f"{self._current_lang}.json"
        if path.exists():
            with open(path, "r", encoding="utf-8-sig") as f:
                self._translations = json.load(f)
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


def set_language(lang: str):
    _i18n.set_language(lang)


def current_language() -> str:
    return _i18n.current_language


def available_languages() -> list[str]:
    return _i18n.available_languages


def detect_system_language() -> str:
    try:
        lang_code, _ = locale.getdefaultlocale()
        if lang_code:
            lang_code = lang_code.replace("-", "_")
            if lang_code.startswith("zh"):
                if "tw" in lang_code.lower() or "hk" in lang_code.lower() or "hant" in lang_code.lower():
                    return "zh_TW"
                return "zh_CN"
            if lang_code.startswith("ja"):
                return "ja"
            return "en_US"
    except Exception:
        pass
    return "en_US"
