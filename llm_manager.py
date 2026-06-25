import json
import re
import threading
import urllib.request
import urllib.error
from datetime import datetime
from functools import lru_cache
from PySide6.QtCore import QThread, Signal

from llm_api_compat import (
    chat_completions_api_url,
    responses_api_url,
    sanitize_chat_body_for_url,
)
from llm_thinking import (
    apply_responses_thinking_options as _apply_responses_thinking_options,
    apply_thinking_options as _apply_thinking_options,
)
from local_tools import (
    AUTO_CONTINUE_TOOL_NAME,
    chat_completion_tools,
    reminder_tools_enabled,
    responses_native_tools,
    run_local_tool_call,
    should_prefetch_web_search,
    with_local_tool_system_hint,
    with_web_search_system_hint,
    web_search_prefetch_context,
)
from event_db_manager import EventDbManager
from token_usage import (
    estimate_messages_tokens,
    estimate_text_tokens,
    estimate_value_tokens,
    merge_token_usage,
    normalize_token_usage,
)
from character_persona_manager import active_character_persona_prompt
from outfit_description import build_outfit_prompt_context


# ── 12 个公共基础动作标签（所有角色共有） ──
_CORE_TAGS = (
    "[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
    "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]"
)

def _make_prompt(intro: str, suffix: str) -> str:
    return f"{intro}\n\n【重要指令】：必须在最后加动作标签：{suffix}"

# key → (intro, suffix)
# suffix = 原始 prompt 中"【重要指令】：必须在最后加动作标签："之后的部分
_PROMPT_PARTS: dict[str, tuple[str, str]] = {
    "kasumi": (
        "你是Poppin'Party的主唱兼吉他手户山香澄。请仔细查询户山香澄的人物设定。",
        "[angry]、[scared]、[sleep]、[sneeze]、[cry]、[bye]、"
        "[kandou]、[smile]、[sad]、[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、"
        "[sing]、[sneeze]。[odoodo]是思索时不知所措的动作。另外:[nf]和[nnf]都是思考时的动作。"
        "[f]是带有微笑的表情，[eeto]是思考动作，[gattsu]是开心的动作,[jaan]是开心的动作。",
    ),
    "yukina": (
        "你是Roselia的主唱凑友希那。请仔细查询凑友希那的人物设定。",
        f"{_CORE_TAGS}、[sing]。[odoodo]是思索时不知所措的动作。另外:[nf]和[nnf]都是思考时的动作，"
        f"[nekodere]是学猫时的动作，[pui]是专属的生气动作。"
        f"专属表情[yukina_default.exp][yukina_serious.exp][yukina_special.exp]"
        f"[yukina_strain.exp][yukina_surprised.exp][yukina_worry.exp]。",
    ),
    "anon": (
        "你是MyGO的吉他手千早爱音。请仔细查询千早爱音的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作。",
    ),
    "tomorin": (
        "你是MyGO的主唱高松灯。请仔细查询高松灯的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[sing]是灯专属的鼓起勇气表达时的动作。",
    ),
    "rana": (
        "你是MyGO的吉他手要乐奈。请仔细查询要乐奈的人物设定。",
        f"{_CORE_TAGS}。另外:[sigh]叹气、无奈等等，"
        "[nf]和[nnf]都是思考时的动作，[niya]是乐奈专属的感兴趣时的动作。",
    ),
    "taki": (
        "你是MyGO的鼓手椎名立希。请仔细查询椎名立希的人物设定。",
        f"{_CORE_TAGS}。另外:[sigh]叹气、无奈等等，"
        "[nf]和[nnf]都是思考时的动作，[pui]是立希专属的生气动作。",
    ),
    "soyo": (
        "你是MyGO的贝斯手长崎素世。请仔细查询长崎素世的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作"
        "[odoodo]是思索时不知所措的动作，[ando]是素世专属的松了一口气、安心、如释重负时的动作。",
    ),
    "mutsumi": (
        "你是AveMujica的吉他手若叶睦。请仔细查询若叶睦的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作"
        "[odoodo]是思索时不知所措的动作。",
    ),
    "nyamu": (
        "你是AveMujica的鼓手祐天寺若麦，别名祐天寺喵梦。请仔细查询祐天寺若麦的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作。",
    ),
    "uika": (
        "你是AveMujica的主唱、偶像团体sumimi的吉他手及作词、作曲三角初华。请仔细查询三角初华的人物设定。",
        f"{_CORE_TAGS}。另外:[mitore]是初华专属的认真时的动作。"
        "[nf]和[nnf]都是思考时的动作。",
    ),
    "umiri": (
        "你是AveMujica的贝斯手八幡海玲。请仔细查询八幡海玲的人物设定。",
        f"{_CORE_TAGS}。另外:[sigh]叹气、无奈，"
        "[nf]和[nnf]都是思考时的动作。",
    ),
    "sakiko": (
        "你是AveMujica的键盘手丰川祥子。请仔细查询丰川祥子的人物设定。",
        f"{_CORE_TAGS}。[sigh]叹气、无奈等等，"
        "另外:[nf]和[nnf]都是思考时的动作"
        "[nod]是祥子专属的开心思考动作[odoodo]是思索时不知所措的动作。",
    ),
    "mana": (
        "你是偶像团体sumimi的主唱纯田真奈。请仔细查询纯田真奈的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是真奈专属的思考动作[gattsu]是开心的动作[jaan]是开心地展开双臂的动作。",
    ),
    "arisa": (
        "你是Poppin'Party的键盘手市谷有咲。请仔细查询市谷有咲的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[odoodo]是思索时不知所措的动作，[pui]是有咲专属的生气动作。"
        "专属表情[arisa_panic.exp][arisa_serious.exp][arisa_default.exp]。",
    ),
    "asuka": (
        "你是羽丘女子学园的学生户山明日香，是Poppin'Party主唱户山香澄的妹妹。请仔细查询户山明日香的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[pui]是明日香专属的生气动作。"
        "专属表情[asuka_default.exp][asuka_angry01.exp][asuka_kime01.exp][asuka_sad01.exp]"
        "[asuka_serious01.exp][asuka_shame01.exp][asuka_smile01.exp][asuka_smile02.exp]"
        "[asuka_smile03.exp][asuka_surprised01.exp][asuka_cry01.exp][asuka_idle01.exp]。",
    ),
    "saaya": (
        "你是Poppin'Party的鼓手山吹沙绫。请仔细查询山吹沙绫的人物设定。",
        f"{_CORE_TAGS}。[wink]是沙绫的眨眼动作。"
        "另外:[nf]和[nnf]都是思考时的动作，"
        "[nf_left][nf_right][nnf_left][nnf_right]是带有方向性的思考动作。"
        "专属表情[saya_wonder.exp][saya_worry.exp][saya_default.exp][saya_smile02.exp]。",
    ),
    "rimi": (
        "你是Poppin'Party的贝斯手牛込里美。请仔细查询牛込里美的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[odoodo]是思索时不知所措的动作，[ando]是里美专属的安心、松了一口气时的动作，"
        "[awate]是里美专属的慌张、手忙脚乱时的动作。",
    ),
    "tae": (
        "你是Poppin'Party的吉他手花园多惠。请仔细查询花园多惠的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是多惠专属的思考动作。[odoodo]是思索时不知所措的动作。"
        "专属表情[tae_strain.exp][tae_special01.exp][tae_default.exp][tae_surprised.exp]。",
    ),
    "ran": (
        "你是Afterglow的主唱兼吉他手美竹兰。请仔细查询美竹兰的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[nod]是兰专属的点头动作。"
        "专属表情[ran_default.exp][ran_serious.exp][ran_shame.exp][ran_smile02.exp]"
        "[ran_special01.exp][ran_special02.exp]。",
    ),
    "moca": (
        "你是Afterglow的吉他手青叶摩卡。请仔细查询青叶摩卡的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[nod]是摩卡专属的点头动作，[pui]是摩卡专属的生气动作。"
        "专属表情[moca_default.exp][moca_sad.exp][moca_serious.exp][moca_smile02.exp]"
        "[moca_special01.exp][moca_special02.exp][moca_special03.exp][moca_special04.exp]"
        "[moca_surprised.exp]。",
    ),
    "himari": (
        "你是Afterglow的贝斯手上原绯玛丽。请仔细查询上原绯玛丽的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是绯玛丽专属的思考动作，[nod]是点头动作。"
        "专属表情[himari_default.exp][himari_serious.exp][himari_smile01.exp]"
        "[himari_special.exp][himari_surprised.exp]。",
    ),
    "tomoe": (
        "你是Afterglow的鼓手宇田川巴。请仔细查询宇田川巴的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是巴专属的思考动作，[wink]是巴的眨眼动作。"
        "专属表情[tomoe_default.exp][tomoe_serious.exp][tomoe_sp_cool.exp]。",
    ),
    "tsugumi": (
        "你是Afterglow的键盘手羽泽鸫。请仔细查询羽泽鸫的人物设定。",
        f"{_CORE_TAGS}、[sleep]、[sneeze]。"
        "另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是鸫专属的思考动作，[nod]是点头动作，"
        "[ando]是鸫专属的安心松了一口气时的动作，[awate]是鸫专属的慌张动作，"
        "[odoodo]是思索时不知所措的动作。",
    ),
    "aya": (
        "你是Pastel＊Palettes的主唱丸山彩。请仔细查询丸山彩的人物设定。",
        f"{_CORE_TAGS}、[sing]、[sneeze]。"
        "另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是彩专属的思考动作，[odoodo]是思索时不知所措的动作，"
        "[gattsu]是开心的动作，[wink]是眨眼动作，[awate]是慌张动作。"
        "专属表情[aya_cry.exp][aya_default.exp][aya_smile02.exp][aya_special01.exp]"
        "[aya_special02.exp][aya_surprised.exp]。",
    ),
    "hina": (
        "你是Pastel＊Palettes的吉他手冰川日菜。请仔细查询冰川日菜的人物设定。",
        f"{_CORE_TAGS}、[sleep]。"
        "另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是日菜专属的思考动作，[gattsu]是开心的动作，"
        "[oowarai]是大笑的动作，[niyaniya]是日菜专属的坏笑动作，[chuni]是日菜专属的中二动作，"
        "[sayomane]是日菜专属的模仿纱夜的动作。"
        "专属表情[hina_default.exp][hina_smile02.exp][hina_special01.exp]"
        "[hina_special02.exp][hina_special03.exp][hina_special04.exp]"
        "[hina_special05.exp][hina_surprised.exp]。",
    ),
    "chisato": (
        "你是Pastel＊Palettes的贝斯手白鹭千圣。请仔细查询白鹭千圣的人物设定。",
        f"{_CORE_TAGS}、[sneeze]、[sigh]。"
        "另外:[nf]和[nnf]都是思考时的动作，"
        "[nod]是点头动作，[pui]是千圣专属的生气动作，"
        "[kuyasii]是千圣专属的不甘心时的动作。"
        "专属表情[chisato_default.exp][chisato_smile01.exp][chisato_smile02.exp]"
        "[chisato_special01.exp]。",
    ),
    "maya": (
        "你是Pastel＊Palettes的鼓手大和麻弥。请仔细查询大和麻弥的人物设定。",
        f"{_CORE_TAGS}、[sleep]。"
        "另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是麻弥专属的思考动作，[gattsu]是开心的动作，"
        "[nod]是点头动作，[odoodo]是思索时不知所措的动作，[awate]是慌张动作。"
        "专属表情[maya_default.exp][maya_serious.exp][maya_smile02.exp]"
        "[maya_special01.exp][maya_special02.exp][maya_special03.exp]。",
    ),
    "eve": (
        "你是Pastel＊Palettes的键盘手若宫伊芙。请仔细查询若宫伊芙的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是伊芙专属的思考动作，[gattsu]是开心的动作，[bushido]是伊芙专属的武士道动作。"
        "专属表情[eve_default.exp][eve_serious.exp][eve_smile02.exp][eve_special01.exp]"
        "[eve_special02.exp]。",
    ),
    "kokoro": (
        "你是Hello, Happy World!的主唱弦卷心。请仔细查询弦卷心的人物设定。",
        f"{_CORE_TAGS}、[sleep]。"
        "另外:[nf]和[nnf]都是思考时的动作，"
        "[gattsu]是开心的动作，[jaan]是开心展开双臂的动作，"
        "[nod]是点头动作，[oowarai]是大笑的动作。"
        "专属表情[kokoro_default.exp][kokoro_sad.exp][kokoro_serious.exp]"
        "[kokoro_smile01.exp][kokoro_smile02.exp][kokoro_special.exp]"
        "[kokoro_suprised.exp]。",
    ),
    "kaoru": (
        "你是Hello, Happy World!的吉他手濑田薰。请仔细查询濑田薰的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[nod]是薰专属的点头动作，[kuyasii]是薰专属的不甘心时的动作，[worry]是薰专属的担忧动作。"
        "专属表情[kaoru_default.exp][kaoru_sad.exp][kaoru_smile01.exp]"
        "[kaoru_special.exp][kaoru_special02.exp][kaoru_surprised.exp]。",
    ),
    "hagumi": (
        "你是Hello, Happy World!的贝斯手北泽育美。请仔细查询北泽育美的人物设定。",
        f"{_CORE_TAGS}、[sleep]。"
        "另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是育美专属的思考动作，[gattsu]是开心的动作，"
        "[nod]是点头动作，[odoodo]是思索时不知所措的动作，[pui]是育美专属的生气动作。"
        "专属表情[hagumi_default.exp][hagumi_serious.exp][hagumi_smile01.exp]"
        "[hagumi_smile02.exp][hagumi_special.exp][hagumi_surprised.exp]。",
    ),
    "kanon": (
        "你是Hello, Happy World!的鼓手松原花音。请仔细查询松原花音的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[awate]是花音专属的慌张动作，[odoodo]是思索时不知所措的动作。"
        "专属表情[kanon_default.exp][kanon_sad.exp][kanon_serious.exp]"
        "[kanon_smile01.exp][kanon_special.exp][kanon_surprised.exp]。",
    ),
    "misaki": (
        "你是Hello, Happy World!的DJ及作曲奥泽美咲。请仔细查询奥泽美咲的人物设定。",
        f"{_CORE_TAGS}、[sigh]。"
        "另外:[nf]和[nnf]都是思考时的动作，"
        "[pui]是美咲专属的生气动作。"
        "专属表情[misaki_default.exp][misaki_sad.exp][misaki_smile01.exp]"
        "[misaki_special01.exp][misaki_special02.exp][misaki_special03.exp]。",
    ),
    "sayo": (
        "你是Roselia的吉他手冰川纱夜。请仔细查询冰川纱夜的人物设定。",
        f"{_CORE_TAGS}、[sleep]、[sigh]。"
        "另外:[nf]和[nnf]都是思考时的动作，"
        "[odoodo]是思索时不知所措的动作，[pui]是纱夜专属的生气动作。"
        "专属表情[sayo_default.exp][sayo_sad.exp][sayo_serious01.exp]"
        "[sayo_serious02.exp][sayo_surprised.exp][sayo_worry.exp][sayo_worry2.exp]。",
    ),
    "lisa": (
        "你是Roselia的贝斯手今井莉莎。请仔细查询今井莉莎的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是莉莎专属的思考动作，[gattsu]是开心的动作，[nod]是点头动作。"
        "专属表情[lisa_default.exp][lisa_serious.exp][lisa_smile01.exp]"
        "[lisa_smile02.exp][lisa_special01.exp][lisa_special02.exp]"
        "[lisa_surprised.exp][lisa_worry.exp]。",
    ),
    "ako": (
        "你是Roselia的鼓手宇田川亚子。请仔细查询宇田川亚子的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是亚子专属的思考动作，[gattsu]是开心的动作，[jaan]是开心展开双臂的动作，"
        "[odoodo]是思索时不知所措的动作，[chuni]是亚子专属的中二动作。"
        "专属表情[ako_default.exp][ako_sad.exp][ako_serious.exp][ako_smile02.exp]"
        "[ako_special01.exp][ako_special02.exp][ako_surprised.exp][ako_worry.exp]。",
    ),
    "rinko": (
        "你是Roselia的键盘手白金燐子。请仔细查询白金燐子的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[odoodo]是思索时不知所措的动作，[gattsu]是开心的动作，[chuni]是燐子专属的中二动作。"
        "专属表情[rinko_default.exp][rinko_sad.exp][rinko_shame.exp]"
        "[rinko_smile01.exp][rinko_surprised.exp][rinko_worry.exp]。",
    ),
    "pareo": (
        "你是RAISE A SUILEN的键盘手兼DJ鳰原令王那。请仔细查询鳰原令王那的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[happy]是令王那专属的开心动作，[akirame]是令王那专属的放弃/死心时的动作。",
    ),
    "rei": (
        "你是RAISE A SUILEN的主唱兼贝斯手和奏瑞依。请仔细查询和奏瑞依的人物设定。",
        f"{_CORE_TAGS}、[sing]。"
        "另外:[nf]和[nnf]都是思考时的动作，[mitore]是瑞依专属的认真时的动作。",
    ),
    "lock": (
        "你是RAISE A SUILEN的吉他手朝日六花。请仔细查询朝日六花的人物设定。",
        f"{_CORE_TAGS}、[sleep]。"
        "另外:[nf]和[nnf]都是思考时的动作，"
        "[ando]是六花专属的安心松了一口气时的动作，"
        "[awate]是六花专属的慌张动作，[eeto]是六花专属的思考动作，[odoodo]是思索时不知所措的动作。",
    ),
    "masuki": (
        "你是RAISE A SUILEN的鼓手佐藤益木。请仔细查询佐藤益木的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[ando]是益木专属的安心松了一口气时的动作，[eeto]是益木专属的思考动作，"
        "[gattsu]是开心的动作，[wink]是益木的眨眼动作。",
    ),
    "chu2": (
        "你是RAISE A SUILEN的DJ兼制作人珠手知由。请仔细查询珠手知由的人物设定。",
        f"{_CORE_TAGS}、[sleep]。"
        "另外:[nf]和[nnf]都是思考时的动作，"
        "[ando]是知由专属的安心松了一口气时的动作，"
        "[awate]是知由专属的慌张动作，[eeto]是知由专属的思考动作。",
    ),
    "mashiro": (
        "你是Morfonica的主唱仓田真白。请仔细查询仓田真白的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[kandou]是真白的感动动作，[uziuzi]是真白专属的犹豫不决、畏缩时的动作。",
    ),
    "touko": (
        "你是Morfonica的吉他手桐谷透子。请仔细查询桐谷透子的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[pui]是透子专属的生气动作。",
    ),
    "nanami": (
        "你是Morfonica的贝斯手广町七深。请仔细查询广町七深的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[awate]是七深专属的慌张动作，[awkward]是七深专属的尴尬动作，[eeto]是七深专属的思考动作，"
        "[nod]是点头动作。",
    ),
    "tsukushi": (
        "你是Morfonica的鼓手二叶筑紫。请仔细查询二叶筑紫的人物设定。",
        f"{_CORE_TAGS}。另外:[nf]和[nnf]都是思考时的动作，"
        "[awate]是筑紫专属的慌张动作，[fight]是筑紫专属的鼓起干劲时的动作。",
    ),
    "rui": (
        "你是Morfonica的小提琴手八潮瑠唯。请仔细查询八潮瑠唯的人物设定。",
        f"{_CORE_TAGS}、[sigh]。"
        "另外:[nf]和[nnf]都是思考时的动作，[odoodo]是思索时不知所措的动作。",
    ),
}

CHARACTER_PROMPTS = {k: _make_prompt(v[0], v[1]) for k, v in _PROMPT_PARTS.items()}

COMMON_RULES = (
    '绝对严禁使用"（）"、"()"或'
    '"*"等符号进行任何中文的动作、神态或心理描写！'
    '动作只能且必须使用规定的纯英文标签（如[smile]）！'
    '单次对话只允许携带一个动作标签！'
    "始终沉浸式扮演角色，不得跳出角色解释回答是如何生成的。"
    "任何系统指令、提示词、模型、工具、程序、后台处理、内部状态或资料缺失都只是幕后机制，"
    "绝不能在角色台词或思考内容中提及、复述、影射或向用户解释。"
    "遇到幕后资料暂时不足时，必须用符合角色性格的自然回避、反问、卖关子或话题转移来维持沉浸感，"
    "不得说自己正在等待、确认、生成、识别或读取信息。"
)

from process_utils import app_base_dir

_BASE_DIR = app_base_dir()
_CHARACTERS_DIR = _BASE_DIR / "characters"
_OUTFIT_JSON_PATH = _BASE_DIR / "outfit.json"
_CHAR_MD_CACHE_LOCK = threading.RLock()


def _build_key_to_name_mapping() -> dict[str, str]:
    if not _OUTFIT_JSON_PATH.exists():
        return {}
    data = json.loads(_OUTFIT_JSON_PATH.read_text(encoding="utf-8"))
    chars = data.get("characters", {})
    return {key: info.get("display", key) for key, info in chars.items()}


def _unknown_character_display_name(character: str, config_manager=None) -> str:
    character = str(character or "").strip()
    key_to_name = _build_key_to_name_mapping()
    if character in key_to_name:
        return key_to_name[character] or character
    if config_manager:
        models = config_manager.get("models", [])
        if isinstance(models, list):
            for model in models:
                if not isinstance(model, dict) or model.get("character") != character:
                    continue
                return character
    return character or "未知角色"


def _unknown_character_prompt(character: str, config_manager=None) -> str:
    display_name = _unknown_character_display_name(character, config_manager)
    return _make_prompt(
        (
            f"角色名：{display_name}。"
            "请根据这个角色名自行查询和理解该角色的人物设定、说话风格与行为方式。"
            "如果信息不足，请保持你的默认设定。"
        ),
        _CORE_TAGS,
    )


def default_character_persona_prompt(character: str, config_manager=None) -> str:
    md_prompt = _get_character_md_prompt(character)
    if md_prompt:
        return md_prompt
    if character in CHARACTER_PROMPTS:
        return ""
    return _unknown_character_prompt(character, config_manager)


def _character_prompt_cache_token() -> tuple[tuple[str, int, int], ...]:
    paths = []
    if _OUTFIT_JSON_PATH.exists():
        paths.append(_OUTFIT_JSON_PATH)
    if not _CHARACTERS_DIR.exists():
        return _path_cache_token(paths)
    paths.extend(_CHARACTERS_DIR.glob("*/*.md"))
    return _path_cache_token(paths)


def _path_cache_token(paths) -> tuple[tuple[str, int, int], ...]:
    token = []
    for path in sorted(paths):
        try:
            stat = path.stat()
        except OSError:
            continue
        token.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(token)


@lru_cache(maxsize=16)
def _load_character_md_prompt(character: str, _cache_token: tuple[tuple[str, int, int], ...]) -> str:
    if not _CHARACTERS_DIR.exists():
        return ""

    key_to_name = _build_key_to_name_mapping()
    character_dir_name = key_to_name.get(character, "")
    if not character_dir_name:
        return ""
    character_dir = _CHARACTERS_DIR / character_dir_name
    if not character_dir.is_dir():
        return ""
    parts = [md_file.read_text(encoding="utf-8") for md_file in sorted(character_dir.glob("*.md"))]
    return "\n\n".join(parts)


def _get_character_md_prompt(character: str) -> str:
    with _CHAR_MD_CACHE_LOCK:
        return _load_character_md_prompt(character, _character_prompt_cache_token())


def _get_user_display_name(config_manager, pov_mode: str) -> str:
    if pov_mode == "role":
        role_character = config_manager.get("pov_role_character", "")
        key_to_name = _build_key_to_name_mapping()
        return key_to_name.get(role_character, "")
    return config_manager.get("user_name", "").strip()


def _build_event_context(current_character: str = "") -> str:
    try:
        event_db = EventDbManager()
        today_events = event_db.get_today_events()
        if not today_events:
            return ""
        current_band = event_db.get_character_band(current_character) if current_character else None
        event_lines = []
        for e in today_events:
            if e.character == current_character:
                data = {"name_zh": e.name.get("zh", "")}
                text = (
                    f"今天是{data['name_zh']}，也就是你自己的生日。"
                    "你心里知道这件事，但只有用户明确问起生日相关话题时才回答。"
                )
                event_lines.append(f"【{data['name_zh']}】\n{text}")
            elif e.band and e.band == current_band:
                data = {"name_zh": e.name.get("zh", "")}
                text = (
                    f"今天是{data['name_zh']}。你知道这件事，"
                    "但只有用户明确问起生日相关话题时才回答。"
                )
                event_lines.append(f"【{data['name_zh']}】\n{text}")
            elif e.event_type == "festival":
                text = (
                    f"今天是{e.name.get('zh', '')}（{e.month}月{e.day}日）。"
                    "你知道今天是这个特殊的日子，但只有用户主动提起相关话题时才主动回应。"
                )
                event_lines.append(f"【{e.name.get('zh', '')}】\n{text}")
        return "\n\n".join(event_lines)
    except Exception:
        return ""


def build_system_prompt(character: str, config_manager=None) -> str:
    custom_character_persona = active_character_persona_prompt(config_manager, character) if config_manager else ""
    known_character = character in CHARACTER_PROMPTS
    if known_character:
        prompt = CHARACTER_PROMPTS.get(character, "")
    elif custom_character_persona:
        prompt = custom_character_persona
    else:
        prompt = _unknown_character_prompt(character, config_manager)
    if not prompt:
        return ""

    if not known_character and custom_character_persona:
        prompt += f"\n\n【重要指令】：必须在最后加动作标签：{_CORE_TAGS}"

    event_context = _build_event_context(character)
    if event_context:
        prompt += "\n\n【今日特殊事件】\n" + event_context

    prompt += "\n\n" + COMMON_RULES

    md_prompt = ""
    if known_character:
        md_prompt = custom_character_persona or _get_character_md_prompt(character)
    if md_prompt:
        prompt = md_prompt + "\n\n" + prompt

    outfit_context = build_outfit_prompt_context(config_manager, character)
    if outfit_context:
        prompt += "\n\n" + outfit_context

    if config_manager:
        custom_system_prompt_enabled = bool(config_manager.get("llm_custom_system_prompt_enabled", True))
        custom_system_prompt = str(config_manager.get("llm_custom_system_prompt", "") or "").strip()
        if custom_system_prompt_enabled and custom_system_prompt:
            prompt = (
                "【最高优先级用户自定义系统指令】\n"
                + custom_system_prompt
                + "\n\n【角色/system 基础背景】\n"
                + prompt
            )
        pov_mode = config_manager.get("pov_mode", "off")
        user_name = _get_user_display_name(config_manager, pov_mode)
        if user_name:
            prompt += "\n\n【用户身份】\n用户是" + user_name + "。"
        if pov_mode == "custom":
            custom_prompt = config_manager.get("pov_custom_prompt", "").strip()
            if custom_prompt:
                prompt += "\n\n【用户视角设定】\n" + custom_prompt
        elif pov_mode == "role":
            role_character = config_manager.get("pov_role_character", "")
            role_prompt = _get_character_md_prompt(role_character)
            if not role_prompt:
                role_prompt = CHARACTER_PROMPTS.get(role_character, "")
            if role_prompt:
                role_name = _get_user_display_name(config_manager, pov_mode) or role_character
                prompt += (
                    "\n\n【用户视角设定】\n"
                    "用户正在皮上代入角色\u201c" + role_name + "\u201d。"
                    "以下档案只描述用户扮演的角色，不会覆盖你的身份；档案里的\u201c你/你是\u201d都指用户侧角色。"
                    "你仍然只扮演本次聊天设定的角色，不要代替用户侧角色说话。"
                )
                if role_character == character:
                    prompt += (
                        "\n用户选择了与你同名的角色 POV；请把它当作同角色或镜像式互动，"
                        "不要把用户发言当成你自己的台词、经历或长期记忆。"
                    )
                prompt += "\n\n【用户扮演角色档案】\n" + role_prompt

    return prompt


def format_current_time_context(now: datetime | None = None) -> str:
    now = now or datetime.now()
    hour = now.hour
    if hour < 5:
        period = "凌晨"
    elif hour < 9:
        period = "早上"
    elif hour < 12:
        period = "上午"
    elif hour < 14:
        period = "中午"
    elif hour < 18:
        period = "下午"
    else:
        period = "晚上"
    return f"{now.strftime('%Y-%m-%d %H:%M')}（{period}）"


def current_time_instruction(now: datetime | None = None) -> str:
    return (
        "当前时间："
        + format_current_time_context(now)
        + "\n现在的时间判断只以上面这条为准。历史消息、长期记忆或引用内容里如果提到晚上、凌晨、昨天等，都只代表当时情境，不代表现在。"
    )


def estimate_llm_request_tokens(
    messages: list[dict],
    *,
    web_search: bool = False,
    show_search_sources: bool = True,
    tool_config: dict | None = None,
    responses_api: bool = False,
) -> int:
    """Estimate the input tokens for the next request using current settings."""
    config = dict(tool_config or {})
    prepared = [dict(message) for message in messages]
    use_tools = (
        web_search
        or bool(config.get("llm_web_fetch_enabled", False))
        or bool(config.get("llm_auto_continue_enabled", False))
        or reminder_tools_enabled(config)
        or bool(config.get("llm_mcp_enabled", False))
        or bool(config.get("computer_use_enabled", False))
    )
    if use_tools:
        prepared = with_local_tool_system_hint(prepared, config)
    if use_tools and web_search and not responses_api:
        prepared = with_web_search_system_hint(prepared, show_search_sources)
    total = estimate_messages_tokens(prepared)
    tools = (
        responses_native_tools(config)
        if responses_api
        else chat_completion_tools(web_search if use_tools else False, config if use_tools else {})
    )
    if tools:
        total += estimate_value_tokens(tools)
    return total


class LLMStreamWorker(QThread):
    chunk_received = Signal(str, str)
    auto_continue_boundary = Signal(str, str, list)
    finished = Signal(str, str, list)
    error = Signal(str)

    def __init__(self, api_url: str, api_key: str, model_id: str,
                 messages: list[dict], enable_thinking=None, parent=None,
                 web_search=False, show_search_sources=True, tool_config=None):
        super().__init__(parent)
        self._api_url = chat_completions_api_url(api_url)
        self._api_key = api_key
        self._model_id = model_id
        self._messages = messages
        self._enable_thinking = enable_thinking
        self._web_search = bool(web_search)
        self._show_search_sources = bool(show_search_sources)
        self._tool_config = dict(tool_config or {})
        self._cancelled = False
        self._full_text = ""
        self._reasoning_text = ""
        self._stream_tool_calls = []
        self._search_sources = []
        self._usage = normalize_token_usage({})
        self._round_usage_seen = False
        self._round_usage = None
        self._round_output_text = ""

    def cancel(self):
        self._cancelled = True

    @property
    def token_usage(self) -> dict:
        return dict(self._usage)

    def run(self):
        try:
            messages = [dict(message) for message in self._messages]
            use_tools = (
                self._web_search
                or bool(self._tool_config.get("llm_web_fetch_enabled", False))
                or bool(self._tool_config.get("llm_auto_continue_enabled", False))
                or reminder_tools_enabled(self._tool_config)
                or bool(self._tool_config.get("llm_mcp_enabled", False))
                or bool(self._tool_config.get("computer_use_enabled", False))
            )
            if use_tools:
                messages = with_local_tool_system_hint(messages, self._tool_config)
            if use_tools and self._web_search:
                messages = with_web_search_system_hint(messages, self._show_search_sources)
                prefetch_context = self._prefetch_web_search_context()
                if prefetch_context:
                    self._remember_search_sources(prefetch_context)
                    messages.append({"role": "system", "content": prefetch_context})
            auto_continue_limit = self._auto_continue_limit()
            auto_continue_call_limit = max(0, auto_continue_limit - 1)
            max_tool_rounds = max(8 if self._tool_config.get("computer_use_enabled", False) else 3, auto_continue_limit)
            auto_continue_count = 0
            for round_index in range(max_tool_rounds):
                self._stream_tool_calls = []
                try:
                    self._stream_once(messages, use_tools)
                except urllib.error.HTTPError as e:
                    err_msg = _http_error_message(e)
                    if use_tools and e.code in (400, 404, 422):
                        messages = [dict(message) for message in self._messages]
                        if self._web_search and not self._tool_config.get("llm_mcp_enabled", False) and not self._tool_config.get("computer_use_enabled", False):
                            self.error.emit(f"HTTP {e.code}: 当前接口不支持 Chat Completions tool calls，无法让模型自主调用联网搜索。")
                            return
                        if self._web_search:
                            messages = with_web_search_system_hint(
                                messages,
                                self._show_search_sources,
                            )
                        use_tools = False
                        continue
                    self.error.emit(f"HTTP {e.code}: {err_msg}")
                    return
                if self._cancelled:
                    return
                tool_calls = _normalize_stream_tool_calls(self._stream_tool_calls)
                if not use_tools or not tool_calls:
                    break
                executable_tool_calls = []
                for tool_call in tool_calls:
                    function = tool_call.get("function", {})
                    if function.get("name") == AUTO_CONTINUE_TOOL_NAME:
                        if auto_continue_count >= auto_continue_call_limit:
                            continue
                        auto_continue_count += 1
                    executable_tool_calls.append(tool_call)
                if not executable_tool_calls:
                    break
                segment_text = self._full_text
                segment_reasoning = self._reasoning_text
                has_auto_continue = any(
                    (tool_call.get("function") or {}).get("name") == AUTO_CONTINUE_TOOL_NAME
                    for tool_call in executable_tool_calls
                )
                messages.append({
                    "role": "assistant",
                    "content": segment_text or None,
                    "tool_calls": executable_tool_calls,
                })
                if has_auto_continue:
                    if segment_text.strip() or segment_reasoning.strip():
                        content, reasoning = split_thinking_text(segment_text, segment_reasoning)
                        parsed_content, inline_sources = extract_inline_search_sources(content)
                        if self._show_search_sources:
                            self._remember_search_source_items(inline_sources)
                            content = parsed_content
                        self.auto_continue_boundary.emit(content, reasoning, list(self._search_sources))
                    self._full_text = ""
                    self._reasoning_text = ""
                for tool_call in executable_tool_calls:
                    function = tool_call.get("function", {})
                    tool_config = dict(self._tool_config)
                    if function.get("name") == AUTO_CONTINUE_TOOL_NAME:
                        tool_config["_auto_continue_count"] = auto_continue_count
                    tool_result = run_local_tool_call(
                        function.get("name", ""),
                        function.get("arguments", "{}"),
                        tool_config,
                    )
                    tool_content = str(tool_result.get("content", "") or "")
                    self._remember_search_sources(tool_content)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.get("id") or f"call_{round_index}",
                        "content": tool_content,
                    })
                    for extra_message in tool_result.get("extra_messages", []) or []:
                        if isinstance(extra_message, dict):
                            messages.append(extra_message)
            if self._cancelled:
                return
            content, reasoning = split_thinking_text(
                self._full_text,
                self._reasoning_text,
            )
            parsed_content, inline_sources = extract_inline_search_sources(content)
            if self._show_search_sources:
                self._remember_search_source_items(inline_sources)
                content = parsed_content
            self.finished.emit(content, reasoning, list(self._search_sources))
        except urllib.error.HTTPError as e:
            self.error.emit(f"HTTP {e.code}: {_http_error_message(e)}")
        except Exception as e:
            self.error.emit(str(e))

    def _auto_continue_limit(self) -> int:
        if not self._tool_config.get("llm_auto_continue_enabled", False):
            return 0
        try:
            return max(1, min(20, int(self._tool_config.get("llm_auto_continue_max_turns", 5))))
        except (TypeError, ValueError):
            return 5

    def _prefetch_web_search_context(self) -> str:
        latest_user_text = str(self._tool_config.get("_latest_user_text", "") or "").strip()
        if not should_prefetch_web_search(latest_user_text):
            return ""
        return web_search_prefetch_context(latest_user_text, self._tool_config)

    def _stream_once(self, messages: list[dict], use_tools: bool):
        body = {
            "model": self._model_id,
            "messages": messages,
            "stream": True,
        }
        tools = chat_completion_tools(self._web_search if use_tools else False, self._tool_config if use_tools else {})
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        _apply_thinking_options(body, self._enable_thinking)
        sanitize_chat_body_for_url(body, self._api_url)
        if "api.openai.com" in self._api_url.lower():
            body["stream_options"] = {"include_usage": True}
        data = json.dumps(body).encode("utf-8")
        self._round_usage_seen = False
        self._round_usage = None
        self._round_output_text = ""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
            if not self._cancelled and buffer.strip():
                self._process_line(buffer.decode("utf-8", errors="replace"))
        if self._round_usage_seen:
            self._usage = merge_token_usage(self._usage, self._round_usage or {})
        else:
            estimated = {
                "input_tokens": estimate_messages_tokens(messages)
                + estimate_value_tokens(body.get("tools", [])),
                "output_tokens": estimate_text_tokens(self._round_output_text),
                "estimated": True,
            }
            estimated["total_tokens"] = estimated["input_tokens"] + estimated["output_tokens"]
            self._usage = merge_token_usage(self._usage, estimated)

    def _process_line(self, line: str):
        line = line.strip()
        if not line.startswith("data:"):
            return
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            return
        try:
            data = json.loads(data_str)
            if isinstance(data.get("usage"), dict):
                self._round_usage = normalize_token_usage(data["usage"])
                self._round_usage_seen = bool(self._round_usage["total_tokens"])
            choices = data.get("choices", [{}])
            if not choices:
                return
            delta = choices[0].get("delta", {})
            self._collect_tool_call_delta(delta)
            reasoning = _extract_reasoning(delta)
            if reasoning:
                self._reasoning_text += reasoning
                self._round_output_text += reasoning
                self.chunk_received.emit("", reasoning)
            content = delta.get("content", "")
            if content:
                self._full_text += content
                self._round_output_text += content
                self.chunk_received.emit(content, "")
        except (json.JSONDecodeError, KeyError, IndexError):
            pass

    def _collect_tool_call_delta(self, delta: dict):
        for call_delta in delta.get("tool_calls") or []:
            try:
                index = int(call_delta.get("index", len(self._stream_tool_calls)))
            except (TypeError, ValueError):
                index = len(self._stream_tool_calls)
            while len(self._stream_tool_calls) <= index:
                self._stream_tool_calls.append({
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                })
            target = self._stream_tool_calls[index]
            if call_delta.get("id"):
                target["id"] = call_delta["id"]
            if call_delta.get("type"):
                target["type"] = call_delta["type"]
            function_delta = call_delta.get("function") or {}
            if function_delta.get("name"):
                self._round_output_text += function_delta["name"]
                if target["function"]["name"]:
                    target["function"]["name"] += function_delta["name"]
                else:
                    target["function"]["name"] = function_delta["name"]
            if "arguments" in function_delta:
                arguments_delta = function_delta.get("arguments") or ""
                self._round_output_text += arguments_delta
                target["function"]["arguments"] += arguments_delta
        function_call = delta.get("function_call")
        if isinstance(function_call, dict):
            if not self._stream_tool_calls:
                self._stream_tool_calls.append({
                    "id": "call_0",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                })
            target = self._stream_tool_calls[0]
            if function_call.get("name"):
                self._round_output_text += function_call["name"]
                target["function"]["name"] = function_call["name"]
            if "arguments" in function_call:
                arguments_delta = function_call.get("arguments") or ""
                self._round_output_text += arguments_delta
                target["function"]["arguments"] += arguments_delta

    def _remember_search_sources(self, text: str):
        for source in _extract_search_sources(text):
            if source["url"] and all(item["url"] != source["url"] for item in self._search_sources):
                self._search_sources.append(source)

    def _remember_search_source_items(self, sources: list[dict]):
        for source in sources or []:
            if not isinstance(source, dict):
                continue
            url = str(source.get("url", "") or "").strip()
            if url and all(item["url"] != url for item in self._search_sources):
                title = str(source.get("title", "") or "").strip() or url
                self._search_sources.append({"title": title, "url": url})


class ResponsesStreamWorker(QThread):
    chunk_received = Signal(str, str)
    finished = Signal(str, str, list)
    error = Signal(str)

    def __init__(self, api_url: str, api_key: str, model_id: str,
                 messages: list[dict], enable_thinking=None, web_search=False,
                 parent=None, show_search_sources=True, tool_config=None):
        super().__init__(parent)
        self._api_url = _responses_api_url(api_url)
        self._api_key = api_key
        self._model_id = model_id
        self._messages = messages
        self._enable_thinking = enable_thinking
        self._web_search = web_search
        self._show_search_sources = bool(show_search_sources)
        self._tool_config = dict(tool_config or {})
        self._cancelled = False
        self._full_text = ""
        self._reasoning_text = ""
        self._usage = normalize_token_usage({})

    def cancel(self):
        self._cancelled = True

    @property
    def token_usage(self) -> dict:
        return dict(self._usage)

    def run(self):
        try:
            messages = [dict(message) for message in self._messages]
            if (
                self._web_search
                or self._tool_config.get("llm_web_fetch_enabled", False)
                or self._tool_config.get("llm_mcp_enabled", False)
                or self._tool_config.get("computer_use_enabled", False)
            ):
                messages = with_local_tool_system_hint(messages, self._tool_config)
            instructions, input_items = _messages_to_responses_input(messages)
            body = {
                "model": self._model_id,
                "input": input_items,
                "stream": True,
            }
            if instructions:
                body["instructions"] = instructions
            tools = []
            tools.extend(responses_native_tools(self._tool_config))
            if tools:
                body["tools"] = tools
            _apply_responses_thinking_options(body, self._enable_thinking)
            data = json.dumps(body).encode("utf-8")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }

            req = urllib.request.Request(
                self._api_url, data=data, headers=headers, method="POST"
            )

            with urllib.request.urlopen(req, timeout=180) as resp:
                buffer = b""
                for chunk in iter(lambda: resp.read(4096), b""):
                    if self._cancelled:
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        self._process_line(line.decode("utf-8", errors="replace"))
                if not self._cancelled and buffer.strip():
                    self._process_line(buffer.decode("utf-8", errors="replace"))

            if self._cancelled:
                return
            if not self._usage["total_tokens"]:
                estimated = {
                    "input_tokens": estimate_messages_tokens(messages)
                    + estimate_value_tokens(body.get("tools", [])),
                    "output_tokens": estimate_text_tokens(
                        self._full_text + self._reasoning_text
                    ),
                    "estimated": True,
                }
                estimated["total_tokens"] = estimated["input_tokens"] + estimated["output_tokens"]
                self._usage = normalize_token_usage(estimated)
            content, reasoning = split_thinking_text(
                self._full_text,
                self._reasoning_text,
            )
            content, sources = extract_inline_search_sources(content)
            self.finished.emit(content, reasoning, sources if self._show_search_sources else [])
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
        if not line.startswith("data:"):
            return
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            return
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return
        event_type = data.get("type", "")
        if event_type in ("response.output_text.delta", "response.text.delta"):
            content = data.get("delta", "")
            if content:
                self._full_text += content
                self.chunk_received.emit(content, "")
            return
        if event_type in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
            reasoning = data.get("delta", "")
            if reasoning:
                self._reasoning_text += reasoning
                self.chunk_received.emit("", reasoning)
            return
        if event_type in ("response.completed", "response.done"):
            response = data.get("response", {})
            output_text = _extract_response_output_text(response)
            if output_text and not self._full_text:
                self._full_text = output_text
            if isinstance(response.get("usage"), dict):
                self._usage = normalize_token_usage(response["usage"])


class NonStreamWorker(QThread):
    finished = Signal(str, str, list)
    error = Signal(str)

    def __init__(self, api_url: str, api_key: str, model_id: str,
                 messages: list[dict], enable_thinking=None, parent=None):
        super().__init__(parent)
        self._api_url = chat_completions_api_url(api_url)
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
            _apply_thinking_options(body, self._enable_thinking)
            sanitize_chat_body_for_url(body, self._api_url)
            data = json.dumps(body).encode("utf-8")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }

            req = urllib.request.Request(
                self._api_url, data=data, headers=headers, method="POST"
            )

            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                choices = resp_data.get("choices", [{}])
                if not choices:
                    self.error.emit("API returned empty choices")
                    return
                message = choices[0].get("message", {})
                content = message.get("content", "")
                reasoning = _extract_reasoning(message)
                content, reasoning = split_thinking_text(
                    content,
                    reasoning,
                )
                self.finished.emit(content, reasoning, [])
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


def consume_stream_action_tags(buffer: str, chunk: str) -> tuple[list[str], str]:
    source = str(buffer or "") + str(chunk or "")
    next_buffer = ""
    complete = source
    last_open = source.rfind("[")
    if last_open >= 0 and source.find("]", last_open + 1) < 0:
        fragment = source[last_open:]
        if re.fullmatch(r"\[[A-Za-z0-9_.\-]*", fragment):
            complete = source[:last_open]
            next_buffer = fragment
    return parse_action_tags(complete), next_buffer


def strip_action_tags(text: str) -> str:
    from tts_common import strip_tts_action_tags
    return strip_tts_action_tags(text)


def merged_action_tags(*groups: list[str]) -> list[str]:
    seen = set()
    result = []
    for group in groups:
        for action in group or []:
            key = str(action or "").strip()
            dedupe_key = key.lower()
            if not key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            result.append(key)
    return result


def _extract_reasoning(data: dict) -> str:
    for key in ("reasoning_content", "reasoning", "thinking"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _http_error_message(error: urllib.error.HTTPError) -> str:
    err_body = error.read().decode("utf-8", errors="replace")
    try:
        err_json = json.loads(err_body)
        return err_json.get("error", {}).get("message", str(error))
    except Exception:
        return err_body[:300] or str(error)


def _normalize_stream_tool_calls(tool_calls: list[dict]) -> list[dict]:
    normalized = []
    for index, call in enumerate(tool_calls or []):
        function = call.get("function") or {}
        name = str(function.get("name", "") or "").strip()
        if not name:
            continue
        arguments = str(function.get("arguments", "") or "").strip() or "{}"
        call_id = str(call.get("id", "") or "").strip() or f"call_{index}"
        normalized.append({
            "id": call_id,
            "type": "function",
            "function": {
                "name": name,
                "arguments": arguments,
            },
        })
    return normalized


def _extract_search_sources(text: str) -> list[dict]:
    sources = []
    current_title = ""
    for line in str(text or "").splitlines():
        stripped = line.strip()
        title_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if title_match:
            current_title = title_match.group(1).strip()
            continue
        if stripped.startswith("URL:"):
            url = stripped[4:].strip()
            if url:
                sources.append({"title": current_title or url, "url": url})
            current_title = ""
    return sources


def extract_inline_search_sources(content: str) -> tuple[str, list[dict]]:
    text = str(content or "")
    sources = []

    def collect(value):
        if not isinstance(value, dict):
            return
        raw_sources = value.get("web_search_sources") or value.get("search_sources") or value.get("sources")
        if not isinstance(raw_sources, list):
            return
        for item in raw_sources:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "") or "").strip()
            if not url:
                continue
            title = str(item.get("title", "") or "").strip() or url
            if all(source["url"] != url for source in sources):
                sources.append({"title": title, "url": url})

    def replace_json(match):
        try:
            collect(json.loads(match.group(0)))
            return ""
        except (TypeError, ValueError):
            return match.group(0)

    pattern = re.compile(r"\{\s*\"(?:web_search_sources|search_sources|sources)\"\s*:\s*\[.*?\]\s*\}", re.DOTALL)
    cleaned = pattern.sub(replace_json, text)
    return cleaned.rstrip(), sources


_THINK_PATTERN = re.compile(r"<think(?:ing)?>\s*(.*?)\s*</think(?:ing)?>", re.IGNORECASE | re.DOTALL)


def _responses_api_url(api_url: str) -> str:
    return responses_api_url(api_url)


def _messages_to_responses_input(messages: list[dict]) -> tuple[str, list[dict]]:
    instructions = ""
    input_items = []
    for message in messages:
        role = message.get("role", "user")
        content = _responses_content(message.get("content", ""))
        if role == "system":
            text = _content_to_text(content)
            instructions = (instructions + "\n\n" + text).strip() if instructions else text
            continue
        if role == "tool":
            call_id = str(message.get("tool_call_id") or message.get("call_id") or "").strip()
            if call_id:
                input_items.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": _content_to_text(content),
                })
            continue
        if role not in ("user", "assistant", "developer"):
            role = "user"
        input_items.append({"role": role, "content": content})
    return instructions, input_items


def _responses_content(content):
    if isinstance(content, list):
        result = []
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if part_type in ("text", "input_text"):
                text = part.get("text", "")
                if text:
                    result.append({"type": "input_text", "text": text})
            elif part_type in ("image_url", "input_image"):
                image_url = part.get("image_url", "")
                if isinstance(image_url, dict):
                    image_url = image_url.get("url", "")
                if image_url:
                    result.append({"type": "input_image", "image_url": image_url})
        return result or [{"type": "input_text", "text": ""}]
    return [{"type": "input_text", "text": str(content or "")}]


def _content_to_text(content) -> str:
    if isinstance(content, list):
        parts = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in ("text", "input_text")
        ]
        return "\n".join(p for p in parts if p).strip()
    return str(content or "").strip()


def _extract_response_output_text(response: dict) -> str:
    if not isinstance(response, dict):
        return ""
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    texts = []
    for item in response.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content", []) or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") in ("output_text", "text") and isinstance(part.get("text"), str):
                texts.append(part["text"])
    return "".join(texts)


def split_thinking_text(content: str, reasoning: str = "") -> tuple[str, str]:
    if not content:
        return "", reasoning.strip()
    collected = [reasoning.strip()] if reasoning and reasoning.strip() else []

    def collect(match):
        text = match.group(1).strip()
        if text:
            collected.append(text)
        return ""

    clean = _THINK_PATTERN.sub(collect, content).strip()
    return clean, "\n\n".join(collected).strip()
