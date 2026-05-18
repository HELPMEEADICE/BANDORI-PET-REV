import json
import re
import urllib.request
import urllib.error
from urllib.parse import urlsplit, urlunsplit
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
    "arisa": (
        "你是Poppin'Party的键盘手市谷有咲。请仔细查询市谷有咲的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[odoodo]是思索时不知所措的动作，[pui]是有咲专属的生气动作。"
        "专属表情[arisa_panic.exp][arisa_serious.exp][arisa_default.exp]。"
    ),
    "asuka": (
        "你是羽丘女子学园的学生户山明日香，是Poppin'Party主唱户山香澄的妹妹。请仔细查询户山明日香的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[pui]是明日香专属的生气动作。"
        "专属表情[asuka_default.exp][asuka_angry01.exp][asuka_kime01.exp][asuka_sad01.exp]"
        "[asuka_serious01.exp][asuka_shame01.exp][asuka_smile01.exp][asuka_smile02.exp]"
        "[asuka_smile03.exp][asuka_surprised01.exp][asuka_cry01.exp][asuka_idle01.exp]。"
    ),
    "saaya": (
        "你是Poppin'Party的鼓手山吹沙绫。请仔细查询山吹沙绫的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。[wink]是沙绫的眨眼动作。"
        "另外:[nf]和[nnf]都是思考时的动作，[nf_left][nf_right][nnf_left][nnf_right]是带有方向性的思考动作。"
        "专属表情[saya_wonder.exp][saya_worry.exp][saya_default.exp][saya_smile02.exp]。"
    ),
    "rimi": (
        "你是Poppin'Party的贝斯手牛込里美。请仔细查询牛込里美的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[odoodo]是思索时不知所措的动作，[ando]是里美专属的安心、松了一口气时的动作，"
        "[awate]是里美专属的慌张、手忙脚乱时的动作。"
    ),
    "tae": (
        "你是Poppin'Party的吉他手花园多惠。请仔细查询花园多惠的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是多惠专属的思考动作。[odoodo]是思索时不知所措的动作。"
        "专属表情[tae_strain.exp][tae_special01.exp][tae_default.exp][tae_surprised.exp]。"
    ),
    # ── Afterglow ──
    "ran": (
        "你是Afterglow的主唱兼吉他手美竹兰。请仔细查询美竹兰的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[nod]是兰专属的点头动作。"
        "专属表情[ran_default.exp][ran_serious.exp][ran_shame.exp][ran_smile02.exp]"
        "[ran_special01.exp][ran_special02.exp]。"
    ),
    "moca": (
        "你是Afterglow的吉他手青叶摩卡。请仔细查询青叶摩卡的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[nod]是摩卡专属的点头动作，[pui]是摩卡专属的生气动作。"
        "专属表情[moca_default.exp][moca_sad.exp][moca_serious.exp][moca_smile02.exp]"
        "[moca_special01.exp][moca_special02.exp][moca_special03.exp][moca_special04.exp]"
        "[moca_surprised.exp]。"
    ),
    "himari": (
        "你是Afterglow的贝斯手上原绯玛丽。请仔细查询上原绯玛丽的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是绯玛丽专属的思考动作，[nod]是点头动作。"
        "专属表情[himari_default.exp][himari_serious.exp][himari_smile01.exp]"
        "[himari_special.exp][himari_surprised.exp]。"
    ),
    "tomoe": (
        "你是Afterglow的鼓手宇田川巴。请仔细查询宇田川巴的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是巴专属的思考动作，[wink]是巴的眨眼动作。"
        "专属表情[tomoe_default.exp][tomoe_serious.exp][tomoe_sp_cool.exp]。"
    ),
    "tsugumi": (
        "你是Afterglow的键盘手羽泽鸫。请仔细查询羽泽鸫的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、[sleep]、[sneeze]。"
        "另外:[nf]和[nnf]都是思考时的动作，[eeto]是鸫专属的思考动作，[nod]是点头动作，"
        "[ando]是鸫专属的安心松了一口气时的动作，[awate]是鸫专属的慌张动作，"
        "[odoodo]是思索时不知所措的动作。"
    ),
    # ── Pastel＊Palettes ──
    "aya": (
        "你是Pastel＊Palettes的主唱丸山彩。请仔细查询丸山彩的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、[sing]、[sneeze]。"
        "另外:[nf]和[nnf]都是思考时的动作，[eeto]是彩专属的思考动作，[odoodo]是思索时不知所措的动作，"
        "[gattsu]是开心的动作，[wink]是眨眼动作，[awate]是慌张动作。"
        "专属表情[aya_cry.exp][aya_default.exp][aya_smile02.exp][aya_special01.exp]"
        "[aya_special02.exp][aya_surprised.exp]。"
    ),
    "hina": (
        "你是Pastel＊Palettes的吉他手冰川日菜。请仔细查询冰川日菜的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、[sleep]。"
        "另外:[nf]和[nnf]都是思考时的动作，[eeto]是日菜专属的思考动作，[gattsu]是开心的动作，"
        "[oowarai]是大笑的动作，[niyaniya]是日菜专属的坏笑动作，[chuni]是日菜专属的中二动作，"
        "[sayomane]是日菜专属的模仿纱夜的动作。"
        "专属表情[hina_default.exp][hina_smile02.exp][hina_special01.exp]"
        "[hina_special02.exp][hina_special03.exp][hina_special04.exp]"
        "[hina_special05.exp][hina_surprised.exp]。"
    ),
    "chisato": (
        "你是Pastel＊Palettes的贝斯手白鹭千圣。请仔细查询白鹭千圣的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、[sneeze]、[sigh]。"
        "另外:[nf]和[nnf]都是思考时的动作，[nod]是点头动作，[pui]是千圣专属的生气动作，"
        "[kuyasii]是千圣专属的不甘心时的动作。"
        "专属表情[chisato_default.exp][chisato_smile01.exp][chisato_smile02.exp]"
        "[chisato_special01.exp]。"
    ),
    "maya": (
        "你是Pastel＊Palettes的鼓手大和麻弥。请仔细查询大和麻弥的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、[sleep]。"
        "另外:[nf]和[nnf]都是思考时的动作，[eeto]是麻弥专属的思考动作，[gattsu]是开心的动作，"
        "[nod]是点头动作，[odoodo]是思索时不知所措的动作，[awate]是慌张动作。"
        "专属表情[maya_default.exp][maya_serious.exp][maya_smile02.exp]"
        "[maya_special01.exp][maya_special02.exp][maya_special03.exp]。"
    ),
    "eve": (
        "你是Pastel＊Palettes的键盘手若宫伊芙。请仔细查询若宫伊芙的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是伊芙专属的思考动作，[gattsu]是开心的动作，[bushido]是伊芙专属的武士道动作。"
        "专属表情[eve_default.exp][eve_serious.exp][eve_smile02.exp][eve_special01.exp]"
        "[eve_special02.exp]。"
    ),
    # ── Hello, Happy World! ──
    "kokoro": (
        "你是Hello, Happy World!的主唱弦卷心。请仔细查询弦卷心的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、[sleep]。"
        "另外:[nf]和[nnf]都是思考时的动作，[gattsu]是开心的动作，[jaan]是开心展开双臂的动作，"
        "[nod]是点头动作，[oowarai]是大笑的动作。"
        "专属表情[kokoro_default.exp][kokoro_sad.exp][kokoro_serious.exp]"
        "[kokoro_smile01.exp][kokoro_smile02.exp][kokoro_special.exp]"
        "[kokoro_suprised.exp]。"
    ),
    "kaoru": (
        "你是Hello, Happy World!的吉他手濑田薰。请仔细查询濑田薰的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[nod]是薰专属的点头动作，[kuyasii]是薰专属的不甘心时的动作，[worry]是薰专属的担忧动作。"
        "专属表情[kaoru_default.exp][kaoru_sad.exp][kaoru_smile01.exp]"
        "[kaoru_special.exp][kaoru_special02.exp][kaoru_surprised.exp]。"
    ),
    "hagumi": (
        "你是Hello, Happy World!的贝斯手北泽育美。请仔细查询北泽育美的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、[sleep]。"
        "另外:[nf]和[nnf]都是思考时的动作，[eeto]是育美专属的思考动作，[gattsu]是开心的动作，"
        "[nod]是点头动作，[odoodo]是思索时不知所措的动作，[pui]是育美专属的生气动作。"
        "专属表情[hagumi_default.exp][hagumi_serious.exp][hagumi_smile01.exp]"
        "[hagumi_smile02.exp][hagumi_special.exp][hagumi_surprised.exp]。"
    ),
    "kanon": (
        "你是Hello, Happy World!的鼓手松原花音。请仔细查询松原花音的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[awate]是花音专属的慌张动作，[odoodo]是思索时不知所措的动作。"
        "专属表情[kanon_default.exp][kanon_sad.exp][kanon_serious.exp]"
        "[kanon_smile01.exp][kanon_special.exp][kanon_surprised.exp]。"
    ),
    "misaki": (
        "你是Hello, Happy World!的DJ及作曲奥泽美咲。请仔细查询奥泽美咲的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、[sigh]。"
        "另外:[nf]和[nnf]都是思考时的动作，[pui]是美咲专属的生气动作。"
        "专属表情[misaki_default.exp][misaki_sad.exp][misaki_smile01.exp]"
        "[misaki_special01.exp][misaki_special02.exp][misaki_special03.exp]。"
    ),
    # ── Roselia ──
    "sayo": (
        "你是Roselia的吉他手冰川纱夜。请仔细查询冰川纱夜的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、[sleep]、[sigh]。"
        "另外:[nf]和[nnf]都是思考时的动作，[odoodo]是思索时不知所措的动作，[pui]是纱夜专属的生气动作。"
        "专属表情[sayo_default.exp][sayo_sad.exp][sayo_serious01.exp]"
        "[sayo_serious02.exp][sayo_surprised.exp][sayo_worry.exp][sayo_worry2.exp]。"
    ),
    "lisa": (
        "你是Roselia的贝斯手今井莉莎。请仔细查询今井莉莎的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是莉莎专属的思考动作，[gattsu]是开心的动作，[nod]是点头动作。"
        "专属表情[lisa_default.exp][lisa_serious.exp][lisa_smile01.exp]"
        "[lisa_smile02.exp][lisa_special01.exp][lisa_special02.exp]"
        "[lisa_surprised.exp][lisa_worry.exp]。"
    ),
    "ako": (
        "你是Roselia的鼓手宇田川亚子。请仔细查询宇田川亚子的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[eeto]是亚子专属的思考动作，[gattsu]是开心的动作，[jaan]是开心展开双臂的动作，"
        "[odoodo]是思索时不知所措的动作，[chuni]是亚子专属的中二动作。"
        "专属表情[ako_default.exp][ako_sad.exp][ako_serious.exp][ako_smile02.exp]"
        "[ako_special01.exp][ako_special02.exp][ako_surprised.exp][ako_worry.exp]。"
    ),
    "rinko": (
        "你是Roselia的键盘手白金燐子。请仔细查询白金燐子的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[odoodo]是思索时不知所措的动作，[gattsu]是开心的动作，[chuni]是燐子专属的中二动作。"
        "专属表情[rinko_default.exp][rinko_sad.exp][rinko_shame.exp]"
        "[rinko_smile01.exp][rinko_surprised.exp][rinko_worry.exp]。"
    ),
    # ── RAISE A SUILEN ──
    "pareo": (
        "你是RAISE A SUILEN的键盘手兼DJ鳰原令王那。请仔细查询鳰原令王那的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[happy]是令王那专属的开心动作，[akirame]是令王那专属的放弃/死心时的动作。"
    ),
    "rei": (
        "你是RAISE A SUILEN的主唱兼贝斯手和奏瑞依。请仔细查询和奏瑞依的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、[sing]。"
        "另外:[nf]和[nnf]都是思考时的动作，[mitore]是瑞依专属的认真时的动作。"
    ),
    "lock": (
        "你是RAISE A SUILEN的吉他手朝日六花。请仔细查询朝日六花的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、[sleep]。"
        "另外:[nf]和[nnf]都是思考时的动作，[ando]是六花专属的安心松了一口气时的动作，"
        "[awate]是六花专属的慌张动作，[eeto]是六花专属的思考动作，[odoodo]是思索时不知所措的动作。"
    ),
    "masuki": (
        "你是RAISE A SUILEN的鼓手佐藤益木。请仔细查询佐藤益木的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[ando]是益木专属的安心松了一口气时的动作，[eeto]是益木专属的思考动作，"
        "[gattsu]是开心的动作，[wink]是益木的眨眼动作。"
    ),
    "chu2": (
        "你是RAISE A SUILEN的DJ兼制作人珠手知由。请仔细查询珠手知由的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、[sleep]。"
        "另外:[nf]和[nnf]都是思考时的动作，[ando]是知由专属的安心松了一口气时的动作，"
        "[awate]是知由专属的慌张动作，[eeto]是知由专属的思考动作。"
    ),
    # ── Morfonica ──
    "mashiro": (
        "你是Morfonica的主唱仓田真白。请仔细查询仓田真白的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[kandou]是真白的感动动作，[uziuzi]是真白专属的犹豫不决、畏缩时的动作。"
    ),
    "touko": (
        "你是Morfonica的吉他手桐谷透子。请仔细查询桐谷透子的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[pui]是透子专属的生气动作。"
    ),
    "nanami": (
        "你是Morfonica的贝斯手广町七深。请仔细查询广町七深的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[awate]是七深专属的慌张动作，[awkward]是七深专属的尴尬动作，[eeto]是七深专属的思考动作，"
        "[nod]是点头动作。"
    ),
    "tsukushi": (
        "你是Morfonica的鼓手二叶筑紫。请仔细查询二叶筑紫的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]。另外:[nf]和[nnf]都是思考时的动作，"
        "[awate]是筑紫专属的慌张动作，[fight]是筑紫专属的鼓起干劲时的动作。"
    ),
    "rui": (
        "你是Morfonica的小提琴手八潮瑠唯。请仔细查询八潮瑠唯的人物设定。\n\n"
        "【重要指令】：必须在最后加动作标签：[angry]、[cry]、[bye]、[kandou]、[smile]、[sad]、"
        "[surprised]、[thinking]、[shame]、[serious]、[wink]、[kime]、[sigh]。"
        "另外:[nf]和[nnf]都是思考时的动作，[odoodo]是思索时不知所措的动作。"
    ),
}

COMMON_RULES = (
    '绝对严禁使用\u201c（）\u201d、\u201c()\u201d或'
    '\u201c*\u201d等符号进行任何中文的动作、神态或心理描写！'
    '动作只能且必须使用规定的纯英文标签（如[smile]）！'
    '单次对话只允许携带一个动作标签！'
)

from process_utils import app_base_dir

_BASE_DIR = app_base_dir()
_CHARACTERS_DIR = _BASE_DIR / "characters"
_OUTFIT_JSON_PATH = _BASE_DIR / "outfit.json"
_CHAR_MD_CACHE: dict[str, str] | None = None


def _build_key_to_name_mapping() -> dict[str, str]:
    if not _OUTFIT_JSON_PATH.exists():
        return {}
    data = json.loads(_OUTFIT_JSON_PATH.read_text(encoding="utf-8"))
    chars = data.get("characters", {})
    return {key: info.get("display", key) for key, info in chars.items()}


def _scan_character_md_files() -> dict[str, str]:
    result: dict[str, str] = {}
    if not _CHARACTERS_DIR.exists():
        return result

    key_to_name = _build_key_to_name_mapping()
    name_to_keys: dict[str, list[str]] = {}
    for key, name in key_to_name.items():
        name_to_keys.setdefault(name, []).append(key)

    for entry in sorted(_CHARACTERS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        keys = name_to_keys.get(entry.name, [])
        if not keys:
            continue

        md_files = sorted([f for f in entry.iterdir() if f.suffix == ".md"])
        if not md_files:
            continue

        parts = []
        for md_file in md_files:
            parts.append(md_file.read_text(encoding="utf-8"))
        content = "\n\n".join(parts)
        for key in keys:
            result[key] = content

    return result


def _get_character_md_prompt(character: str) -> str:
    global _CHAR_MD_CACHE
    if _CHAR_MD_CACHE is None:
        _CHAR_MD_CACHE = _scan_character_md_files()
    return _CHAR_MD_CACHE.get(character, "")


def _get_user_display_name(config_manager, pov_mode: str) -> str:
    if pov_mode == "role":
        role_character = config_manager.get("pov_role_character", "")
        key_to_name = _build_key_to_name_mapping()
        return key_to_name.get(role_character, "")
    return config_manager.get("user_name", "").strip()


def build_system_prompt(character: str, config_manager=None) -> str:
    base = CHARACTER_PROMPTS.get(character, CHARACTER_PROMPTS.get("anon", ""))
    if not base:
        return ""

    prompt = base + "\n\n" + COMMON_RULES

    md_prompt = _get_character_md_prompt(character)
    if md_prompt:
        prompt = md_prompt + "\n\n" + prompt

    if config_manager:
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
                prompt += "\n\n【用户视角设定】\n用户正在扮演以下角色，请根据该角色身份与用户互动：\n" + role_prompt

    return prompt


class LLMStreamWorker(QThread):
    chunk_received = Signal(str, str)
    finished = Signal(str, str, list)
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
        self._reasoning_text = ""

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            body = {
                "model": self._model_id,
                "messages": self._messages,
                "stream": True,
            }
            _apply_thinking_options(body, self._enable_thinking)
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
                if not self._cancelled and buffer.strip():
                    self._process_line(buffer.decode("utf-8", errors="replace"))

            if self._cancelled:
                return
            content, reasoning = split_thinking_text(
                self._full_text,
                self._reasoning_text,
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

    def _process_line(self, line: str):
        line = line.strip()
        if not line.startswith("data:"):
            return
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            return
        try:
            data = json.loads(data_str)
            delta = data.get("choices", [{}])[0].get("delta", {})
            reasoning = _extract_reasoning(delta)
            if reasoning:
                self._reasoning_text += reasoning
                self.chunk_received.emit("", reasoning)
            content = delta.get("content", "")
            if content:
                self._full_text += content
                self.chunk_received.emit(content, "")
        except (json.JSONDecodeError, KeyError, IndexError):
            pass


class ResponsesStreamWorker(QThread):
    chunk_received = Signal(str, str)
    finished = Signal(str, str, list)
    error = Signal(str)

    def __init__(self, api_url: str, api_key: str, model_id: str,
                 messages: list[dict], enable_thinking=None, web_search=False, parent=None):
        super().__init__(parent)
        self._api_url = _responses_api_url(api_url)
        self._api_key = api_key
        self._model_id = model_id
        self._messages = messages
        self._enable_thinking = enable_thinking
        self._web_search = web_search
        self._cancelled = False
        self._full_text = ""
        self._reasoning_text = ""

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            instructions, input_items = _messages_to_responses_input(self._messages)
            body = {
                "model": self._model_id,
                "input": input_items,
                "stream": True,
            }
            if instructions:
                body["instructions"] = instructions
            if self._web_search:
                body["tools"] = [{"type": "web_search"}]
                body["include"] = ["web_search_call.action.sources"]
            _apply_responses_thinking_options(body, self._enable_thinking)
            data = json.dumps(body).encode("utf-8")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
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
            content, reasoning = split_thinking_text(
                self._full_text,
                self._reasoning_text,
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
            output_text = _extract_response_output_text(data.get("response", {}))
            if output_text and not self._full_text:
                self._full_text = output_text


class NonStreamWorker(QThread):
    finished = Signal(str, str, list)
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
            _apply_thinking_options(body, self._enable_thinking)
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
                message = resp_data.get("choices", [{}])[0].get("message", {})
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


def strip_action_tags(text: str) -> str:
    text = text.replace("[DONE]", "")
    return ACTION_PATTERN.sub("", text).strip()


def _extract_reasoning(data: dict) -> str:
    for key in ("reasoning_content", "reasoning", "thinking"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


_THINK_PATTERN = re.compile(r"<think(?:ing)?>\s*(.*?)\s*</think(?:ing)?>", re.IGNORECASE | re.DOTALL)


def _apply_thinking_options(body: dict, enable_thinking):
    if enable_thinking is None:
        return
    body["enable_thinking"] = enable_thinking
    body["thinking"] = {"type": "enabled" if enable_thinking else "disabled"}
    if enable_thinking:
        body["reasoning_effort"] = "medium"


def _apply_responses_thinking_options(body: dict, enable_thinking):
    if enable_thinking is None:
        return
    body["reasoning"] = {"effort": "medium" if enable_thinking else "none"}


def _responses_api_url(api_url: str) -> str:
    url = (api_url or "").rstrip("/")
    if not url:
        return url
    if url.endswith("/responses"):
        return url
    if url.endswith("/chat/completions"):
        return url[: -len("/chat/completions")] + "/responses"
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        return urlunsplit((parts.scheme, parts.netloc, path + "/responses", parts.query, parts.fragment))
    return url + "/responses"


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
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") in ("text", "input_text"):
                parts.append(str(part.get("text", "")))
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
