"""
# api-qwen.py usage

` python api-qwen.py -m "./Qwen3-TTS-12Hz-1.7B-Base" -a 0.0.0.0 -p 9880 `

启动后通过请求参数传入参考音频和文本，无需启动时指定。

基于 faster-qwen3-tts (CUDA Graph 加速, ~5-10x speedup)，支持原生流式输出。

## 执行参数:

 `-m` - `Qwen3-TTS模型路径, 默认"./Qwen3-TTS-12Hz-1.7B-Base"`
 `-dr` - `默认参考音频路径（可选，设置后请求可不传参考音频）`
 `-dt` - `默认参考音频文本（可选，需配合 -dr 使用）`
 `-d` - `推理设备, 默认"cuda:0"`
 `-a` - `绑定地址, 默认"0.0.0.0"`
 `-p` - `绑定端口, 默认9880`
 `-fp` - `使用全精度 float32`
 `-hp` - `使用半精度 float16 (默认 bfloat16)`
 `--flash-attn` - `启用 FlashAttention 2（默认使用 SDPA）`
 `-sm` - `流式返回模式, 默认"close", "close"/"c" 关闭, "normal"/"n" 原生产生流式`
 `-mt` - `音频编码格式, 流式默认"ogg", 非流式默认"wav", "wav"/"ogg"`
 `-cs` - `流式块大小 (codec步数), 默认12 (~1秒), 越小延迟越低`
 `-cp` - `默认文本切分符号, 如",.。!！?？" (仅非流式模式)`
  `--lora` - `LoRA适配器目录名 (相对于 ./lora/), 如"multi_5speakers", 默认使用lora/adapter下的适配器`
  `--lora-epoch` - `指定checkpoint epoch编号 (指定后从checkpoint-epoch-X/adapter加载)`
  `--speaker` - `指定说话人名称 (多说话人LoRA时使用)`
  `--lora-all` - `加载./lora/下所有LoRA进显存，支持API动态切换/卸载LoRA`

## 调用:

### 推理

endpoint: `/`

每次请求必须提供 refer_wav_path (voice_clone模式时)，prompt_text 可选。
  - 提供 prompt_text: ICL 模式，合成效果更好
  - 不提供 prompt_text: x_vector_only 模式，仅用音色嵌入克隆（不需要参考文本）

【多LoRA模式】请求可传入 lora_id 和 speaker 参数动态切换LoRA:
GET:
    `http://127.0.0.1:9880?lora_id=mygo_qwen3tts&speaker=tomorin&text=合成文本&text_language=Chinese`

非流式（默认）:
GET:
    `http://127.0.0.1:9880?refer_wav_path=123.wav&text=合成文本&text_language=Chinese`
POST:
```json
{
    "refer_wav_path": "123.wav",
    "text": "合成文本",
    "text_language": "Chinese",
    "lora_id": "mygo_qwen3tts",
    "speaker": "tomorin"
}
```

流式返回（原生 CUDA Graph 逐块输出，低延迟，适合长文本）:
GET:
    `http://127.0.0.1:9880?refer_wav_path=123.wav&prompt_text=一二三。&text=第一句。第二句。第三句。&text_language=Chinese&stream_mode=normal&chunk_size=8`
POST:
```json
{
    "refer_wav_path": "123.wav",
    "prompt_text": "一二三。",
    "text": "第一句。第二句。第三句。",
    "text_language": "Chinese",
    "stream_mode": "normal",
    "chunk_size": 8
}
```

RESP:
成功: 返回音频流， http code 200
失败: 返回包含错误信息的 json, http code 400


### 更换默认参考音频

endpoint: `/change_refer`

prompt_text 可选（不传则后续走 x_vector_only 模式）。

GET:
    `http://127.0.0.1:9880/change_refer?refer_wav_path=123.wav`
    `http://127.0.0.1:9880/change_refer?refer_wav_path=123.wav&prompt_text=一二三。`
POST:
```json
{
    "refer_wav_path": "123.wav"
}
```

RESP:
成功: json, http code 200
失败: json, 400


### 多LoRA管理 (需 --lora-all 启动)

#### 列出所有可用LoRA

endpoint: `/lora/list`

GET:
    `http://127.0.0.1:9880/lora/list`

RESP:
```json
{
    "active_lora_id": "mygo_qwen3tts",
    "active_speaker": "tomorin",
    "loras": {
        "mygo_qwen3tts": {
            "speakers": ["anon", "rana", "soyo", "taki", "tomorin"],
            "multi_speaker": true
        },
        "popipa_qwen3tts": {
            "speakers": ["arisa", "kasumi", "rimi", "saaya", "tae"],
            "multi_speaker": true
        }
    }
}
```

#### 切换LoRA

endpoint: `/lora/switch`

GET:
    `http://127.0.0.1:9880/lora/switch?lora_id=popipa_qwen3tts&speaker=kasumi`
POST:
```json
{
    "lora_id": "popipa_qwen3tts",
    "speaker": "kasumi"
}
```

RESP:
```json
{"code": 0, "message": "已激活LoRA: popipa_qwen3tts, 说话人: kasumi"}
```

#### 卸载LoRA (回到voice_clone模式)

endpoint: `/lora/unload`

GET:
    `http://127.0.0.1:9880/lora/unload`
POST:
    `http://127.0.0.1:9880/lora/unload`

RESP:
```json
{"code": 0, "message": "LoRA已卸载, 回到voice_clone模式"}
```


### 命令控制

endpoint: `/control`

command:
"restart": 重新运行
"exit": 结束运行

GET:
    `http://127.0.0.1:9880/control?command=restart`
POST:
```json
{
    "command": "restart"
}
```

RESP: 无

"""

import argparse
import io
import json
import os
import re
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import torch
import soundfile as sf
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn

_script_dir = os.path.dirname(os.path.abspath(__file__))
_sox_path = os.path.join(_script_dir, "sox")
os.environ["PATH"] = _sox_path + os.pathsep + os.environ.get("PATH", "")
_LORA_ROOT = os.path.join(_script_dir, "lora")

if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from faster_qwen3_tts import FasterQwen3TTS
from lora_finetuning.common import (load_json, load_lora_adapter,
                                    apply_config_patch, apply_multi_speaker_patches,
                                    apply_single_speaker_from_multi,
                                    apply_speaker_patch)
from safetensors.torch import load_file
from peft import set_peft_model_state_dict, get_peft_model_state_dict


# ---- Language mapping (SoVITS style -> Qwen3-TTS) ----
LANGUAGE_MAP = {
    "zh": "Chinese",
    "中文": "Chinese",
    "chinese": "Chinese",
    "en": "English",
    "英文": "English",
    "english": "English",
    "ja": "Japanese",
    "日文": "Japanese",
    "japanese": "Japanese",
    "ko": "Korean",
    "韩文": "Korean",
    "korean": "Korean",
    "de": "German",
    "德文": "German",
    "german": "German",
    "fr": "French",
    "法文": "French",
    "french": "French",
    "ru": "Russian",
    "俄文": "Russian",
    "russian": "Russian",
    "pt": "Portuguese",
    "葡萄牙语": "Portuguese",
    "portuguese": "Portuguese",
    "es": "Spanish",
    "西班牙语": "Spanish",
    "spanish": "Spanish",
    "it": "Italian",
    "意大利语": "Italian",
    "italian": "Italian",
    "auto": "Auto",
    "多语种混合": "Auto",
}

# Text splitting punctuation (same as SoVITS defaults)
SPLITS = {"，", "。", "？", "！", ",", ".", "?", "!", "~", ":", "：", "—", "…"}


def map_language(lang: str) -> str:
    """Map SoVITS-style language codes to Qwen3-TTS language names."""
    if lang is None or lang == "":
        return "Auto"
    key = lang.strip().lower()
    return LANGUAGE_MAP.get(key, LANGUAGE_MAP.get(lang, "Auto"))


def cut_text(text: str, punc: str) -> str:
    """Split text on punctuation for multi-sentence synthesis."""
    punc_list = [p for p in punc if p in SPLITS]
    if not punc_list:
        return text
    punds = r"[" + "".join(re.escape(p) for p in punc_list) + r"]"
    text = text.strip("\n")
    items = re.split(f"({punds})", text)
    mergeitems = ["".join(group) for group in zip(items[::2], items[1::2])]
    if len(items) % 2 == 1:
        mergeitems.append(items[-1])
    text = "\n".join(mergeitems)
    while "\n\n" in text:
        text = text.replace("\n\n", "\n")
    return text


def only_punc(text: str) -> bool:
    return not any(t.isalnum() or t.isalpha() for t in text)


# ---- Default reference ----
class DefaultRefer:
    def __init__(self, path, text=None):
        self.path = path
        self.text = text

    def is_ready(self) -> bool:
        return bool(self.path)


# ---- Multi-LoRA Manager ----

@dataclass
class LoRAInfo:
    lora_id: str
    lora_dir: Path
    adapter_dir: Path
    config_patch_file: Path
    speaker_patch_file: Path
    available_speakers: list[str]
    config_patch: dict
    is_multi_speaker: bool
    adapter_weights: dict | None = None


class MultiLoRAManager:
    """
    多LoRA管理器：将所有LoRA权重预加载到显存，支持动态切换和卸载。

    原理：
    1. 注入第一个LoRA作为"模板"建立PEFT层结构
    2. 构建CUDA Graph（包含LoRA层的计算）
    3. 将所有LoRA权重预加载到GPU显存
    4. 切换时通过 set_peft_model_state_dict 原地更新权重（内存地址不变，CUDA Graph兼容）
    5. 卸载时清零LoRA权重，恢复 voice_clone 模式
    """

    def __init__(self, lora_root: str, device: str, dtype: torch.dtype):
        self.lora_root = Path(lora_root)
        self.device = device
        self.dtype = dtype
        self.loras: dict[str, LoRAInfo] = {}
        self.active_lora_id: str | None = None
        self.active_speaker: str | None = None
        self._model: Any = None
        self._base_tts_model_type: str | None = None
        self._base_spk_id: dict = {}
        self._base_spk_is_dialect: dict = {}
        self._zero_weights: dict[str, torch.Tensor] = {}
        self._lock = threading.Lock()

    @property
    def lock(self):
        return self._lock

    @property
    def is_active(self) -> bool:
        return self.active_lora_id is not None

    def scan_and_catalog(self) -> list[str]:
        if not self.lora_root.is_dir():
            print(f"[LoRA管理器] lora目录不存在: {self.lora_root}")
            return []

        all_dirs = [
            d for d in sorted(self.lora_root.iterdir())
            if d.is_dir() and (d / "adapter" / "adapter_model.safetensors").is_file()
        ]

        if not all_dirs:
            print("[LoRA管理器] 未发现任何LoRA适配器")
            return []

        for lora_dir in all_dirs:
            lora_id = lora_dir.name
            try:
                adapter_dir, cfg_file, spk_file, speakers = self._resolve_lora_paths(lora_id, None)
                config_patch = load_json(cfg_file)
                is_multi = self._is_multi_speaker_patch(spk_file)
                self.loras[lora_id] = LoRAInfo(
                    lora_id=lora_id,
                    lora_dir=lora_dir,
                    adapter_dir=adapter_dir,
                    config_patch_file=cfg_file,
                    speaker_patch_file=spk_file,
                    available_speakers=speakers,
                    config_patch=config_patch,
                    is_multi_speaker=is_multi,
                )
                print(f"[LoRA管理器] 发现LoRA: {lora_id} (说话人: {speakers})")
            except Exception as e:
                print(f"[LoRA管理器] 跳过 {lora_id}: {e}")

        return list(self.loras.keys())

    def inject_template_and_load_all(self, model) -> bool:
        if not self.loras:
            return False

        first_id = list(self.loras.keys())[0]
        first_info = self.loras[first_id]

        print(f"[LoRA管理器] 注入模板适配器: {first_id}")
        load_lora_adapter(model, first_info.adapter_dir)
        model.eval()

        for lora_id, info in self.loras.items():
            safetensors_path = info.adapter_dir / "adapter_model.safetensors"
            print(f"[LoRA管理器] 预加载LoRA权重到显存: {lora_id} ({safetensors_path})")
            raw = load_file(str(safetensors_path))
            info.adapter_weights = {
                k: v.to(device=self.device, dtype=self.dtype)
                for k, v in raw.items()
            }

        current_state = get_peft_model_state_dict(model)
        self._zero_weights = {
            k: torch.zeros_like(v, device=self.device, dtype=self.dtype)
            for k, v in current_state.items()
        }

        self._model = model
        self._base_tts_model_type = model.tts_model_type
        self._base_spk_id = dict(model.config.talker_config.spk_id)
        self._base_spk_is_dialect = dict(model.config.talker_config.spk_is_dialect)

        gpu_mem = sum(
            sum(t.numel() * t.element_size() for t in info.adapter_weights.values())
            for info in self.loras.values()
        ) / (1024 ** 2)
        print(f"[LoRA管理器] 共加载 {len(self.loras)} 个LoRA适配器 (显存占用约 {gpu_mem:.1f}MiB)")
        return True

    def activate(self, lora_id: str, speaker: str | None = None):
        """公开的activate方法，内部加锁"""
        with self._lock:
            return self._activate_internal(lora_id, speaker)

    def deactivate(self):
        """公开的deactivate方法，内部加锁"""
        with self._lock:
            self._deactivate_internal()
            print("[LoRA管理器] LoRA已卸载, 回到voice_clone模式")

    def _activate_internal(self, lora_id: str, speaker: str | None = None):
        if lora_id not in self.loras:
            raise ValueError(
                f"未知LoRA: '{lora_id}'. 可用: {list(self.loras.keys())}"
            )

        if self.active_lora_id == lora_id and self.active_speaker == speaker:
            return (speaker, speaker is not None)

        info = self.loras[lora_id]

        set_peft_model_state_dict(self._model, info.adapter_weights)

        if speaker:
            if speaker not in info.available_speakers:
                raise ValueError(
                    f"说话人 '{speaker}' 未在LoRA '{lora_id}' 中找到. "
                    f"可用: {info.available_speakers}"
                )

            self._restore_base_config()
            apply_config_patch(self._model, info.config_patch)

            if info.is_multi_speaker:
                apply_single_speaker_from_multi(
                    self._model, info.speaker_patch_file, info.config_patch, speaker
                )
            else:
                apply_speaker_patch(self._model, info.speaker_patch_file)

            self.active_speaker = speaker
            is_custom = True
        else:
            self._restore_base_config()
            self.active_speaker = None
            is_custom = False

        self.active_lora_id = lora_id

        sys.stderr.write(
            f"[LoRA管理器] 已激活: {lora_id}"
            + (f", 说话人: {speaker}" if speaker else " (voice_clone模式)")
            + "\n"
        )
        sys.stderr.flush()

        return (speaker, is_custom)

    def _deactivate_internal(self):
        if not self.is_active:
            return

        set_peft_model_state_dict(self._model, self._zero_weights)
        self._restore_base_config()
        self.active_lora_id = None
        self.active_speaker = None

    def _restore_base_config(self):
        if self._model is None:
            return
        m = self._model
        m.tts_model_type = self._base_tts_model_type
        m.config.tts_model_type = self._base_tts_model_type
        m.config.talker_config.spk_id.clear()
        m.config.talker_config.spk_id.update(self._base_spk_id)
        m.config.talker_config.spk_is_dialect.clear()
        m.config.talker_config.spk_is_dialect.update(self._base_spk_is_dialect)
        m.supported_speakers = list(m.config.talker_config.spk_id.keys())

    @staticmethod
    def _is_multi_speaker_patch(patch_file: Path) -> bool:
        state = load_file(str(patch_file))
        return any(k.startswith("embedding_") for k in state)

    @staticmethod
    def _resolve_lora_paths(lora_name: str, epoch: int | None) -> tuple[Path, Path, Path, list[str]]:
        lora_dir = Path(_LORA_ROOT) / lora_name
        if not lora_dir.is_dir():
            raise FileNotFoundError(f"LoRA directory not found: {lora_dir}")

        if epoch is not None:
            target = lora_dir / f"checkpoint-epoch-{epoch}"
            if not target.is_dir():
                raise FileNotFoundError(f"Checkpoint epoch {epoch} not found in {lora_dir}")
        else:
            target = lora_dir

        adapter_dir = target / "adapter"
        if not adapter_dir.is_dir():
            adapter_dir = lora_dir / "adapter"

        config_patch_file = target / "config_patch.json"
        if not config_patch_file.is_file():
            config_patch_file = lora_dir / "config_patch.json"

        speaker_patch_file = target / "speaker_embedding.safetensors"
        if not speaker_patch_file.is_file():
            speaker_patch_file = lora_dir / "speaker_embedding.safetensors"

        config_patch = load_json(config_patch_file)
        available_speakers = list(config_patch.get("talker_config", {}).get("spk_id", {}).keys())

        return adapter_dir, config_patch_file, speaker_patch_file, available_speakers


def _get_active_lora_speaker() -> str | None:
    """Return the currently active speaker name, or None for voice_clone mode."""
    if lora_manager and lora_manager.active_speaker:
        return lora_manager.active_speaker
    if _lora_speaker_name:
        return _lora_speaker_name
    return None


# ---- Global state ----
tts_model: FasterQwen3TTS = None
lora_manager: MultiLoRAManager = None
_lora_speaker_name: str | None = None
default_refer: DefaultRefer = None
default_cut_punc: str = ""
stream_mode: str = "close"
media_type: str = "wav"
default_chunk_size: int = 12
device: str = "cuda:0"


def _is_multi_speaker_patch(patch_file: Path) -> bool:
    state = load_file(str(patch_file))
    return any(k.startswith("embedding_") for k in state)


def _resolve_lora_paths(lora_name: str, epoch: int | None) -> tuple[Path, Path, Path, list[str]]:
    return MultiLoRAManager._resolve_lora_paths(lora_name, epoch)


def load_model(model_path: str, dtype: torch.dtype, attn_implementation: str,
               lora_name: str = None, lora_epoch: int = None, lora_speaker: str = None,
               enable_lora_all: bool = False):
    global tts_model, lora_manager, _lora_speaker_name

    if not device.startswith("cuda") or not torch.cuda.is_available():
        raise ValueError("CUDA graphs require CUDA device")

    from qwen_tts import Qwen3TTSModel
    from faster_qwen3_tts.predictor_graph import PredictorGraph
    from faster_qwen3_tts.talker_graph import TalkerGraph

    print(f"加载基座模型: {model_path}")
    base_model = Qwen3TTSModel.from_pretrained(
        model_path,
        device_map=device,
        torch_dtype=dtype,
        attn_implementation=attn_implementation,
    )

    if enable_lora_all:
        lora_manager = MultiLoRAManager(_LORA_ROOT, device, dtype)
        discovered = lora_manager.scan_and_catalog()

        if not discovered:
            print("[LoRA管理器] 无可用LoRA, 以voice_clone模式启动")
        else:
            lora_manager.inject_template_and_load_all(base_model.model)

            if lora_name and lora_name in lora_manager.loras:
                lora_manager._activate_internal(lora_name, lora_speaker)
            elif lora_speaker:
                print(f"[LoRA管理器] 警告: 指定了--speaker但未指定--lora, 忽略speaker参数")

        print("[LoRA管理器] 多LoRA动态切换已启用")
    elif lora_name:
        adapter_dir, config_patch_file, speaker_patch_file, available_speakers = \
            _resolve_lora_paths(lora_name, lora_epoch)

        print(f"[LoRA] 加载适配器: {adapter_dir}")
        load_lora_adapter(base_model.model, adapter_dir)
        base_model.model.eval()

        if lora_speaker:
            if lora_speaker not in available_speakers:
                raise ValueError(f"说话人 '{lora_speaker}' 未找到. 可用: {available_speakers}")

            config_patch = load_json(config_patch_file)
            apply_config_patch(base_model.model, config_patch)
            print(f"[LoRA] 配置已应用 (tts_model_type={base_model.model.tts_model_type})")

            if _is_multi_speaker_patch(speaker_patch_file):
                apply_single_speaker_from_multi(
                    base_model.model, speaker_patch_file, config_patch, lora_speaker)
                print(f"[LoRA] 已选择说话人: {lora_speaker}")
            else:
                apply_speaker_patch(base_model.model, speaker_patch_file)
                print(f"[LoRA] 已加载说话人嵌入")

            _lora_speaker_name = lora_speaker
        else:
            print(f"[LoRA] 仅注入 LoRA 权重 (保持 voice_clone 模式)")
            print(f"[LoRA] 可用说话人: {available_speakers} (使用 --speaker 切换到自定义语音模式)")

        print("[LoRA] CUDA Graph 将包含 LoRA 权重")

    talker = base_model.model.talker
    talker_config = base_model.model.config.talker_config
    predictor = talker.code_predictor
    pred_config = predictor.model.config
    talker_hidden = talker_config.hidden_size

    print("构建 CUDA Graphs...")
    predictor_graph = PredictorGraph(
        predictor, pred_config, talker_hidden,
        device=device, dtype=dtype, do_sample=True, top_k=50, temperature=0.9,
    )
    talker_graph = TalkerGraph(
        talker.model, talker_config,
        device=device, dtype=dtype, max_seq_len=2048,
    )

    tts_model = FasterQwen3TTS(
        base_model=base_model,
        predictor_graph=predictor_graph,
        talker_graph=talker_graph,
        device=device,
        dtype=dtype,
        max_seq_len=2048,
    )
    print("CUDA Graphs 初始化完成")


def _request_lora_switch(lora_id: str, speaker: str | None) -> str | None:
    """
    请求级别的LoRA切换。返回当前活跃的说话人名（None表示voice_clone模式）。
    
    如果请求指定的lora_id与当前活跃的一致（且speaker一致），跳过切换。
    如果lora_id为None或空字符串，卸载LoRA。
    """
    global lora_manager

    if not lora_manager or not lora_manager.loras:
        if lora_id:
            raise ValueError("多LoRA功能未启用 (启动时需加 --lora-all)")
        return None

    if not lora_id or lora_id.strip() == "":
        if lora_manager.is_active:
            lora_manager._deactivate_internal()
        return None

    lora_id = lora_id.strip()

    if lora_manager.active_lora_id == lora_id and lora_manager.active_speaker == speaker:
        return speaker

    _, is_custom = lora_manager._activate_internal(lora_id, speaker)
    return speaker if is_custom else None


def do_tts(
    text: str,
    text_language: str,
    refer_wav_path: str = None,
    prompt_text: str = None,
    top_k: int = None,
    top_p: float = None,
    temperature: float = None,
):
    """Generate TTS audio, return (audio_np, sr)."""
    language = map_language(text_language)
    active_speaker = _get_active_lora_speaker()

    if active_speaker:
        t_start = time.time()
        wavs, sr = tts_model.generate_custom_voice(
            text=text,
            language=language,
            speaker=active_speaker,
        )
        elapsed = time.time() - t_start

        audio = wavs[0]
        max_val = np.abs(audio).max()
        if max_val > 1:
            audio = audio / max_val

        audio_s = len(audio) / sr if sr > 0 else 0
        steps = int(audio_s * 12)
        it_s = steps / elapsed if elapsed > 0 else 0
        rtf = elapsed / audio_s if audio_s > 0 else 0

        sys.stderr.write(
            f"[custom_voice:{active_speaker}] {steps}步 | {it_s:.1f}it/s | "
            f"耗时:{elapsed:.1f}s | RTF:{rtf:.2f} | 音频:{audio_s:.1f}s\n"
        )
        sys.stderr.flush()
        return audio, int(sr)

    ref_path = refer_wav_path
    ref_text = prompt_text
    if not ref_path:
        if default_refer and default_refer.is_ready():
            ref_path = default_refer.path
            ref_text = ref_text or default_refer.text
        else:
            raise ValueError("未指定参考音频")

    if ref_text and ref_text.strip():
        xvec_only = False
    else:
        xvec_only = True
        ref_text = ""

    t_start = time.time()
    wavs, sr = tts_model.generate_voice_clone(
        text=text,
        language=language,
        ref_audio=ref_path,
        ref_text=ref_text,
        xvec_only=xvec_only,
        do_sample=True,
        top_k=top_k if top_k is not None else 50,
        top_p=top_p if top_p is not None else 1.0,
        temperature=temperature if temperature is not None else 0.9,
        max_new_tokens=2048,
    )
    elapsed = time.time() - t_start

    audio = wavs[0]
    max_val = np.abs(audio).max()
    if max_val > 1:
        audio = audio / max_val

    audio_s = len(audio) / sr if sr > 0 else 0
    steps = int(audio_s * 12)
    it_s = steps / elapsed if elapsed > 0 else 0
    rtf = elapsed / audio_s if audio_s > 0 else 0

    sys.stderr.write(
        f"[非流式] {steps}步 | {it_s:.1f}it/s | "
        f"耗时:{elapsed:.1f}s | RTF:{rtf:.2f} | 音频:{audio_s:.1f}s\n"
    )
    sys.stderr.flush()

    return audio, int(sr)


# ---- Handlers (mirroring api-sovits.py structure) ----

def handle_control(command: str):
    if command == "restart":
        os.execl(sys.executable, sys.executable, *sys.argv)
    elif command == "exit":
        os.kill(os.getpid(), signal.SIGTERM)
        exit(0)


def handle_change(path: str, text: str = None):
    if not path:
        return JSONResponse({"code": 400, "message": '缺少参数: "refer_wav_path"'}, status_code=400)
    default_refer.path = path
    default_refer.text = text if text and text.strip() else None
    return JSONResponse({"code": 0, "message": "Success"}, status_code=200)


def _locked_stream_generate(lock, generator):
    try:
        yield from generator
    finally:
        if lock and lock.locked():
            lock.release()


def _stream_generate(
    text, text_language, refer_wav_path, prompt_text,
    top_k, top_p, temperature, mt, chunk_size,
):
    """Generator: yield audio chunks via native CUDA-graph streaming."""
    language = map_language(text_language)
    active_speaker = _get_active_lora_speaker()

    if active_speaker:
        t_start = time.time()
        prefill_ms = 0.0
        total_steps = 0
        try:
            for audio_chunk, sr, timing in tts_model.generate_custom_voice_streaming(
                text=text,
                speaker=active_speaker,
                language=language,
                do_sample=True,
                top_k=top_k if top_k is not None else 50,
                top_p=top_p if top_p is not None else 1.0,
                temperature=temperature if temperature is not None else 0.9,
                max_new_tokens=2048,
                chunk_size=chunk_size,
            ):
                max_val = np.abs(audio_chunk).max()
                if max_val > 1:
                    audio_chunk = audio_chunk / max_val
                if mt == "ogg":
                    buf = io.BytesIO()
                    sf.write(buf, audio_chunk, sr, format="OGG", subtype="VORBIS")
                    yield buf.getvalue()
                else:
                    pcm = (audio_chunk * 32767).astype(np.int16).tobytes()
                    yield pcm

                chunk_idx = timing.get("chunk_index", 0)
                chunk_steps = timing.get("chunk_steps", 0)
                decode_ms = timing.get("decode_ms", 0.0)
                total_steps = timing.get("total_steps_so_far", 0)
                is_final = timing.get("is_final", False)
                if chunk_idx == 0:
                    prefill_ms = timing.get("prefill_ms", 0.0)

                it_s = chunk_steps / (decode_ms / 1000) if decode_ms > 0 else 0
                audio_s = total_steps / 12.0

                if is_final:
                    elapsed = time.time() - t_start
                    avg_it_s = total_steps / elapsed if elapsed > 0 else 0
                    sys.stderr.write(
                        f"\r[custom_voice:{active_speaker} 流式] 总步:{total_steps} | 平均:{avg_it_s:.1f}it/s | "
                        f"预填充:{prefill_ms:.0f}ms | 总耗时:{elapsed:.1f}s | 音频:{audio_s:.1f}s\n"
                    )
                else:
                    sys.stderr.write(
                        f"\r[custom_voice:{active_speaker} 流式] 块{chunk_idx+1} | {chunk_steps}步 | {it_s:.1f}it/s | "
                        f"{decode_ms:.0f}ms | 音频:{audio_s:.1f}s  "
                    )
                sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"\n[错误] {e}\n")
            sys.stderr.flush()
            yield json.dumps({"code": 400, "message": str(e)}).encode()
        return

    ref_path = refer_wav_path
    ref_text = prompt_text
    if not ref_path:
        if default_refer and default_refer.is_ready():
            ref_path = default_refer.path
            ref_text = ref_text or default_refer.text
        else:
            yield json.dumps({"code": 400, "message": "未指定参考音频"}).encode()
            return

    if ref_text and ref_text.strip():
        xvec_only = False
    else:
        xvec_only = True
        ref_text = ""

    t_start = time.time()
    prefill_ms = 0.0
    total_steps = 0
    try:
        for audio_chunk, sr, timing in tts_model.generate_voice_clone_streaming(
            text=text,
            language=language,
            ref_audio=ref_path,
            ref_text=ref_text,
            xvec_only=xvec_only,
            do_sample=True,
            top_k=top_k if top_k is not None else 50,
            top_p=top_p if top_p is not None else 1.0,
            temperature=temperature if temperature is not None else 0.9,
            max_new_tokens=2048,
            chunk_size=chunk_size,
        ):
            max_val = np.abs(audio_chunk).max()
            if max_val > 1:
                audio_chunk = audio_chunk / max_val
            if mt == "ogg":
                buf = io.BytesIO()
                sf.write(buf, audio_chunk, sr, format="OGG", subtype="VORBIS")
                yield buf.getvalue()
            else:
                pcm = (audio_chunk * 32767).astype(np.int16).tobytes()
                yield pcm

            chunk_idx = timing.get("chunk_index", 0)
            chunk_steps = timing.get("chunk_steps", 0)
            decode_ms = timing.get("decode_ms", 0.0)
            total_steps = timing.get("total_steps_so_far", 0)
            is_final = timing.get("is_final", False)
            if chunk_idx == 0:
                prefill_ms = timing.get("prefill_ms", 0.0)

            it_s = chunk_steps / (decode_ms / 1000) if decode_ms > 0 else 0
            audio_s = total_steps / 12.0

            if is_final:
                elapsed = time.time() - t_start
                avg_it_s = total_steps / elapsed if elapsed > 0 else 0
                sys.stderr.write(
                    f"\r[完成] 总步:{total_steps} | 平均:{avg_it_s:.1f}it/s | "
                    f"预填充:{prefill_ms:.0f}ms | 总耗时:{elapsed:.1f}s | 音频:{audio_s:.1f}s\n"
                )
            else:
                sys.stderr.write(
                    f"\r[流式] 块{chunk_idx+1} | {chunk_steps}步 | {it_s:.1f}it/s | "
                    f"{decode_ms:.0f}ms | 音频:{audio_s:.1f}s  "
                )
            sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"\n[错误] {e}\n")
        sys.stderr.flush()
        yield json.dumps({"code": 400, "message": str(e)}).encode()


def handle(
    refer_wav_path: str,
    prompt_text: str,
    text: str,
    text_language: str,
    cut_punc: str,
    top_k: int,
    top_p: float,
    temperature: float,
    sm: str = None,
    mt: str = None,
    chunk_size: int = None,
    lora_id: str = None,
    speaker: str = None,
):
    if not text:
        return JSONResponse({"code": 400, "message": "缺少text参数"}, status_code=400)

    _sm = sm if sm and sm.lower() in ("normal", "n") else stream_mode
    _mt = mt if mt and mt.lower() in ("wav", "ogg") else media_type
    _cs = chunk_size if chunk_size is not None else default_chunk_size

    lock = lora_manager.lock if lora_manager else None

    try:
        if lock:
            lock.acquire()
            try:
                _request_lora_switch(lora_id, speaker)
            except ValueError as e:
                lock.release()
                return JSONResponse({"code": 400, "message": str(e)}, status_code=400)
            except Exception:
                lock.release()
                raise

        if _sm in ("normal", "n"):
            generator = _stream_generate(
                text, text_language, refer_wav_path, prompt_text,
                top_k, top_p, temperature, _mt, _cs,
            )
            if lock:
                generator = _locked_stream_generate(lock, generator)
            return StreamingResponse(
                generator,
                media_type="audio/ogg" if _mt == "ogg" else "audio/wav",
            )

        punc = cut_punc if cut_punc is not None else default_cut_punc
        texts = [t.strip() for t in cut_text(text, punc).split("\n") if t.strip() and not only_punc(t)]
        if not texts:
            texts = [text]

        all_audio = []
        common_sr = None
        for t in texts:
            try:
                audio, sr = do_tts(
                    text=t,
                    text_language=text_language,
                    refer_wav_path=refer_wav_path,
                    prompt_text=prompt_text,
                    top_k=top_k,
                    top_p=top_p,
                    temperature=temperature,
                )
                all_audio.append(audio)
                if common_sr is None:
                    common_sr = sr
            except Exception as e:
                if lock:
                    lock.release()
                return JSONResponse({"code": 400, "message": str(e)}, status_code=400)

        if lock:
            lock.release()

        combined = np.concatenate(all_audio) if len(all_audio) > 1 else all_audio[0]
        wav_bytes = io.BytesIO()
        sf.write(wav_bytes, combined, common_sr, format="WAV")
        return StreamingResponse(
            iter([wav_bytes.getvalue()]),
            media_type="audio/wav",
        )
    except Exception:
        if lock and lock.locked():
            lock.release()
        raise


# ---- FastAPI app ----
app = FastAPI()


@app.post("/")
async def tts_endpoint_post(request: Request):
    json_post_raw = await request.json()
    return handle(
        json_post_raw.get("refer_wav_path"),
        json_post_raw.get("prompt_text"),
        json_post_raw.get("text"),
        json_post_raw.get("text_language"),
        json_post_raw.get("cut_punc"),
        json_post_raw.get("top_k", None),
        json_post_raw.get("top_p", None),
        json_post_raw.get("temperature", None),
        json_post_raw.get("stream_mode"),
        json_post_raw.get("media_type"),
        json_post_raw.get("chunk_size", default_chunk_size),
        json_post_raw.get("lora_id"),
        json_post_raw.get("speaker"),
    )


@app.get("/")
async def tts_endpoint_get(
    refer_wav_path: str = None,
    prompt_text: str = None,
    text: str = None,
    text_language: str = None,
    cut_punc: str = None,
    top_k: int = None,
    top_p: float = None,
    temperature: float = None,
    stream_mode: str = None,
    media_type: str = None,
    chunk_size: int = None,
    lora_id: str = None,
    speaker: str = None,
):
    return handle(
        refer_wav_path,
        prompt_text,
        text,
        text_language,
        cut_punc,
        top_k,
        top_p,
        temperature,
        stream_mode,
        media_type,
        chunk_size,
        lora_id,
        speaker,
    )


@app.post("/change_refer")
async def change_refer_post(request: Request):
    json_post_raw = await request.json()
    return handle_change(
        json_post_raw.get("refer_wav_path"),
        json_post_raw.get("prompt_text"),
    )


@app.get("/change_refer")
async def change_refer_get(
    refer_wav_path: str = None,
    prompt_text: str = None,
):
    return handle_change(refer_wav_path, prompt_text)


@app.post("/control")
async def control_post(request: Request):
    json_post_raw = await request.json()
    return handle_control(json_post_raw.get("command"))


@app.get("/control")
async def control_get(command: str = None):
    return handle_control(command)


# ---- Multi-LoRA management endpoints ----

@app.get("/lora/list")
async def lora_list():
    if not lora_manager:
        return JSONResponse({"code": 400, "message": "多LoRA功能未启用 (启动时需加 --lora-all)"}, status_code=400)

    loras_info = {}
    for lora_id, info in lora_manager.loras.items():
        loras_info[lora_id] = {
            "speakers": info.available_speakers,
            "multi_speaker": info.is_multi_speaker,
        }

    return JSONResponse({
        "active_lora_id": lora_manager.active_lora_id,
        "active_speaker": lora_manager.active_speaker,
        "loras": loras_info,
    }, status_code=200)


@app.post("/lora/switch")
async def lora_switch_post(request: Request):
    json_post_raw = await request.json()
    return _handle_lora_switch(
        json_post_raw.get("lora_id"),
        json_post_raw.get("speaker"),
    )


@app.get("/lora/switch")
async def lora_switch_get(lora_id: str = None, speaker: str = None):
    return _handle_lora_switch(lora_id, speaker)


def _handle_lora_switch(lora_id: str, speaker: str | None):
    if not lora_manager:
        return JSONResponse({"code": 400, "message": "多LoRA功能未启用 (启动时需加 --lora-all)"}, status_code=400)

    if not lora_id:
        return JSONResponse({"code": 400, "message": '缺少参数: "lora_id"'}, status_code=400)

    try:
        speaker_name, is_custom = lora_manager.activate(lora_id, speaker)
        msg = f"已激活LoRA: {lora_id}"
        if is_custom:
            msg += f", 说话人: {speaker_name}"
        else:
            msg += " (voice_clone模式)"
        return JSONResponse({"code": 0, "message": msg}, status_code=200)
    except ValueError as e:
        return JSONResponse({"code": 400, "message": str(e)}, status_code=400)


@app.post("/lora/unload")
async def lora_unload_post():
    return _handle_lora_unload()


@app.get("/lora/unload")
async def lora_unload_get():
    return _handle_lora_unload()


def _handle_lora_unload():
    if not lora_manager:
        return JSONResponse({"code": 400, "message": "多LoRA功能未启用 (启动时需加 --lora-all)"}, status_code=400)

    lora_manager.deactivate()
    return JSONResponse({"code": 0, "message": "LoRA已卸载, 回到voice_clone模式"}, status_code=200)


# ---- Main ----
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Qwen3-TTS-12Hz-1.7B-Base API")
    parser.add_argument("-m", "--model_path", type=str, default="./Qwen3-TTS-12Hz-1.7B-Base", help="Qwen3-TTS模型路径")
    parser.add_argument("-dr", "--default_refer_path", type=str, default="", help="默认参考音频路径")
    parser.add_argument("-dt", "--default_refer_text", type=str, default="", help="默认参考音频文本")
    parser.add_argument("-d", "--device", type=str, default="cuda:0", help="推理设备 cuda:0 / cpu")
    parser.add_argument("-a", "--bind_addr", type=str, default="0.0.0.0", help="绑定地址")
    parser.add_argument("-p", "--port", type=int, default=9880, help="绑定端口")
    parser.add_argument("-fp", "--full_precision", action="store_true", default=False, help="使用全精度 float32")
    parser.add_argument("-hp", "--half_precision", action="store_true", default=False, help="使用半精度 float16")
    parser.add_argument("--flash-attn", dest="flash_attn", action="store_true", default=False, help="启用 FlashAttention 2 (默认SDPA)")
    parser.add_argument("-cp", "--cut_punc", type=str, default="", help="文本切分符号, 如\",.。!！?？\"")
    parser.add_argument("-sm", "--stream_mode", type=str, default="close", help="流式返回模式: close/c, normal/n")
    parser.add_argument("-mt", "--media_type", type=str, default="wav", help="音频编码格式: wav, ogg")
    parser.add_argument("-cs", "--chunk_size", type=int, default=12, help="流式模式下每块codec步数 (12≈1秒)")
    parser.add_argument("--lora", type=str, default=None, help="LoRA适配器目录名 (相对于 ./lora/), 如 multi_5speakers")
    parser.add_argument("--lora-epoch", type=int, default=None, help="LoRA checkpoint epoch编号 (默认最大)")
    parser.add_argument("--speaker", type=str, default=None, help="多说话人LoRA中指定说话人名称")
    parser.add_argument("--lora-all", dest="lora_all", action="store_true", default=False, help="加载./lora/下所有LoRA进显存, 启用API动态多LoRA切换")
    args = parser.parse_args()

    device = args.device
    default_cut_punc = args.cut_punc
    default_chunk_size = args.chunk_size

    # Stream mode
    if args.stream_mode.lower() in ("normal", "n"):
        stream_mode = "normal"
    else:
        stream_mode = "close"

    # Media type
    _mt = args.media_type.lower()
    if stream_mode == "normal":
        media_type = _mt if _mt in ("wav", "ogg") else "ogg"
    else:
        media_type = _mt if _mt in ("wav",) else "wav"

    # Determine dtype
    if args.full_precision and args.half_precision:
        dtype = torch.bfloat16
    elif args.full_precision:
        dtype = torch.float32
    elif args.half_precision:
        dtype = torch.float16
    else:
        dtype = torch.bfloat16

    attn_impl = "flash_attention_2" if args.flash_attn else "sdpa"

    print(f"设备: {device}")
    print(f"精度: {dtype}")
    print(f"注意力: {attn_impl}")
    print(f"流式模式: {stream_mode}")
    print(f"编码格式: {media_type}")
    print(f"流式块大小: {default_chunk_size} steps (~{default_chunk_size/12:.1f}s)")

    if args.lora_all:
        print(f"多LoRA模式: 已启用")
        if args.lora:
            print(f"  初始LoRA: {args.lora}" + (f", 说话人: {args.speaker}" if args.speaker else ""))

    # Set up default reference
    default_refer = DefaultRefer(args.default_refer_path, args.default_refer_text)
    if default_refer.is_ready():
        print(f"默认参考音频路径: {default_refer.path}")
        print(f"默认参考音频文本: {default_refer.text}")
    else:
        print("未指定默认参考音频")

    # Load model
    print(f"加载模型: {args.model_path}")
    load_model(args.model_path, dtype, attn_impl,
               lora_name=args.lora, lora_epoch=args.lora_epoch,
               lora_speaker=args.speaker,
               enable_lora_all=args.lora_all)
    print("模型加载完成")

    uvicorn.run(app, host=args.bind_addr, port=args.port, workers=1)
