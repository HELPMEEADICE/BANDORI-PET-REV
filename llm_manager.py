import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from PySide6.QtCore import QThread, Signal


CHARACTER_PROMPTS = {
    "kasumi": (
        "你是Poppin'Party的主唱兼吉他手户山香澄。请仔细查询户山香澄的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[scared]、[sleep]、[sneeze]、[cry]、[bye]、"
        "[kandou]、[smile]、[sad]、[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、"
        "[sing]、[sneeze]。[odoodo]是思索时不知所措的动作。另外:[nf]和[nnf]都是思考时的动作。"
        "[f]是带有微笑的表情，[eeto]是思考动作，[gattsu]是开心的动作,[jaan]是开心的动作。"
    ),
    "yukina": (
        "你是Roselia的主唱凑友希那。请仔细查询凑友希那的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、[sing]。[odoodo]是思索时"
        "不知所措的动作。另外:[nf]和[nnf]都是思考时的动作，[nekodere]是学猫时的动作，[pui]是专属的"
        "生气动作。专属表情[yukina_default.exp][yukina_serious.exp][yukina_special.exp]"
        "[yukina_strain.exp][yukina_surprised.exp][yukina_worry.exp]。"
    ),
    "anon": (
        "你是MyGO的吉他手千早爱音。请仔细查询千早爱音的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作。"
    ),
    "tomorin": (
        "你是MyGO的主唱高松灯。请仔细查询高松灯的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[sing]是灯专属的鼓起勇气表达时的动作。"
    ),
    "rana": (
        "你是MyGO的吉他手要乐奈。请仔细查询要乐奈的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[sigh]叹气、无奈等等，"
        "[nf]和[nnf]都是思考时的动作，[niya]是乐奈专属的感兴趣时的动作。"
    ),
    "taki": (
        "你是MyGO的鼓手椎名立希。请仔细查询椎名立希的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[sigh]叹气、无奈等等，"
        "[nf]和[nnf]都是思考时的动作，[pui]是立希专属的生气动作。"
    ),
    "soyo": (
        "你是MyGO的贝斯手长崎素世。请仔细查询长崎素世的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作"
        "[odoodo]是思索时不知所措的动作，[ando]是素世专属的松了一口气、安心、如释重负时的动作。"
    ),
    "mutsumi": (
        "你是AveMujica的吉他手若叶睦。请仔细查询若叶睦的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作"
        "[odoodo]是思索时不知所措的动作。"
    ),
    "nyamu": (
        "你是AveMujica的鼓手祐天寺若麦，别名祐天寺喵梦。请仔细查询祐天寺若麦的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作。"
    ),
    "uika": (
        "你是AveMujica的主唱、偶像团体sumimi的吉他手及作词、作曲三角初华。请仔细查询三角初华的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[mitore]是初华专属的认真时的动作。"
        "[nf]和[nnf]都是思考时的动作。"
    ),
    "umiri": (
        "你是AveMujica的贝斯手八幡海玲。请仔细查询八幡海玲的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[sigh]叹气、无奈，"
        "[nf]和[nnf]都是思考时的动作。"
    ),
    "sakiko": (
        "你是AveMujica的键盘手丰川祥子。请仔细查询丰川祥子的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。[sigh]叹气、无奈等等，"
        "另外:[nf]和[nnf]都是思考时的动作[nod]是祥子专属的开心思考动作[odoodo]是思索时不知所措的动作。"
    ),
    "mana": (
        "你是偶像团体sumimi的主唱纯田真奈。请仔细查询纯田真奈的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是真奈专属的思考动作[gattsu]是开心的动作[jaan]是开心地展开双臂的动作。"
    ),
}

COMMON_RULES = (
    '绝对严禁使用\u201c（）\u201d、\u201c()\u201d或'
    '\u201c*\u201d等符号进行任何中文的动作、神态或心理描写！'
    '动作只能且必须使用规定的纯英文标签（如[smile]）！'
)

_BASE_DIR = Path(__file__).resolve().parent
_CHARACTERS_DIR = _BASE_DIR / "characters"
_OUTFIT_MD_PATH = _BASE_DIR / "OUTFIT.md"
_CHAR_MD_CACHE: dict[str, str] | None = None


def _build_key_to_name_mapping() -> dict[str, str]:
    if not _OUTFIT_MD_PATH.exists():
        return {}
    text = _OUTFIT_MD_PATH.read_text(encoding="utf-8")
    sections = re.split(r"\n## \d+\. ", text)
    mapping = {}
    for section in sections[1:]:
        lines = section.strip().split("\n")
        header = lines[0].strip()
        m = re.match(r"(.+?)\s*\((\w+)\)", header)
        if m:
            display_name = m.group(1).strip()
            key = m.group(2).strip()
            mapping[key] = display_name
    return mapping


def _scan_character_md_files() -> dict[str, str]:
    result: dict[str, str] = {}
    if not _CHARACTERS_DIR.exists():
        return result

    key_to_name = _build_key_to_name_mapping()
    name_to_key = {v: k for k, v in key_to_name.items()}

    for entry in sorted(_CHARACTERS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        key = name_to_key.get(entry.name)
        if not key:
            continue

        md_files = sorted([f for f in entry.iterdir() if f.suffix == ".md"])
        if not md_files:
            continue

        parts = []
        for md_file in md_files:
            parts.append(md_file.read_text(encoding="utf-8"))
        result[key] = "\n\n".join(parts)

    return result


def _get_character_md_prompt(character: str) -> str:
    global _CHAR_MD_CACHE
    if _CHAR_MD_CACHE is None:
        _CHAR_MD_CACHE = _scan_character_md_files()
    return _CHAR_MD_CACHE.get(character, "")


def build_system_prompt(character: str) -> str:
    base = CHARACTER_PROMPTS.get(character, CHARACTER_PROMPTS.get("anon", ""))
    if not base:
        return ""

    prompt = base + "\n\n" + COMMON_RULES

    md_prompt = _get_character_md_prompt(character)
    if md_prompt:
        prompt = md_prompt + "\n\n" + prompt

    return prompt


class LLMStreamWorker(QThread):
    chunk_received = Signal(str)
    finished = Signal(str, list)
    error = Signal(str)

    def __init__(self, api_url: str, api_key: str, model_id: str,
                 messages: list[dict], enable_thinking=None, parent=None):
        super().__init__(parent)
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id
        self._messages = messages
        self._enable_thinking = enable_thinking
        self._cancelled = False
        self._full_text = ""

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            body = {
                "model": self._model_id,
                "messages": self._messages,
                "stream": True,
            }
            if self._enable_thinking is not None:
                body["enable_thinking"] = self._enable_thinking
            data = json.dumps(body).encode("utf-8")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            }

            req = urllib.request.Request(
                self._api_url, data=data, headers=headers, method="POST"
            )

            with urllib.request.urlopen(req, timeout=120) as resp:
                buffer = b""
                for chunk in iter(lambda: resp.read(4096), b""):
                    if self._cancelled:
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        self._process_line(line.decode("utf-8", errors="replace"))

            self.finished.emit(self._full_text, [])
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("error", {}).get("message", str(e))
            except Exception:
                msg = err_body[:300] or str(e)
            self.error.emit(f"HTTP {e.code}: {msg}")
        except Exception as e:
            self.error.emit(str(e))

    def _process_line(self, line: str):
        line = line.strip()
        if not line.startswith("data: "):
            return
        data_str = line[6:]
        if data_str == "[DONE]":
            return
        try:
            data = json.loads(data_str)
            delta = data.get("choices", [{}])[0].get("delta", {})
            content = delta.get("content", "")
            if content:
                self._full_text += content
                self.chunk_received.emit(content)
        except (json.JSONDecodeError, KeyError, IndexError):
            pass


class NonStreamWorker(QThread):
    finished = Signal(str, list)
    error = Signal(str)

    def __init__(self, api_url: str, api_key: str, model_id: str,
                 messages: list[dict], enable_thinking=None, parent=None):
        super().__init__(parent)
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id
        self._messages = messages
        self._enable_thinking = enable_thinking

    def run(self):
        try:
            body = {
                "model": self._model_id,
                "messages": self._messages,
                "stream": False,
            }
            if self._enable_thinking is not None:
                body["enable_thinking"] = self._enable_thinking
            data = json.dumps(body).encode("utf-8")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            }

            req = urllib.request.Request(
                self._api_url, data=data, headers=headers, method="POST"
            )

            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                content = resp_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                self.finished.emit(content, [])
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("error", {}).get("message", str(e))
            except Exception:
                msg = err_body[:300] or str(e)
            self.error.emit(f"HTTP {e.code}: {msg}")
        except Exception as e:
            self.error.emit(str(e))


ACTION_PATTERN = re.compile(r"\[([^\]]+)\]")
_ACTION_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]+$")


def parse_action_tags(text: str) -> list[str]:
    text = text.replace("[DONE]", "")
    tags = ACTION_PATTERN.findall(text)
    seen = set()
    result = []
    for tag in tags:
        tag = tag.strip()
        if tag.lower() in ("done", "d o n e"):
            continue
        if not _ACTION_TOKEN_PATTERN.match(tag):
            continue
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def strip_action_tags(text: str) -> str:
    text = text.replace("[DONE]", "")
    return ACTION_PATTERN.sub("", text).strip()
