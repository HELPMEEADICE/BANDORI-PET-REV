# BandoriPet ASR 语音输入教程

本文说明如何为 BandoriPet 配置 ASR 语音识别输入：准备识别后端、加载 ASR 模型、在设置页启用功能，并在聊天窗口用麦克风输入文字。

## 1. 功能工作方式

BandoriPet 本体不直接运行 ASR 模型。它负责：

1. 从系统麦克风录音。
2. 把录音编码为 `wav`。
3. 以 OpenAI-compatible 的 `multipart/form-data` 请求提交到 ASR 后端。
4. 读取后端返回的文本，填入聊天输入框。

默认 ASR 接口地址：

```text
http://127.0.0.1:8000/v1/audio/transcriptions
```

后端需要支持下面这种请求：

```http
POST /v1/audio/transcriptions
Content-Type: multipart/form-data

file=@speech.wav
model=whisper-large-v3
language=zh
```

返回 JSON 中只要包含 `text` 字段即可：

```json
{
  "text": "你好，今天想聊些什么？"
}
```

## 2. 准备 ASR 后端

如果你已经有兼容 `/v1/audio/transcriptions` 的服务，可以跳到「3. 在 BandoriPet 中启用」。

如果没有，可以单独开一个本地 Python 环境，用 faster-whisper 包一层简单 API 服务。这个服务与 BandoriPet 分开运行，方便之后替换模型或升级后端。

### 2.1 创建本地 ASR 服务目录

在项目目录下执行：

```powershell
mkdir .runtime\asr-server
cd .runtime\asr-server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install fastapi uvicorn python-multipart faster-whisper
```

### 2.2 新建 `server.py`

在 `.runtime/asr-server/server.py` 写入：

```python
import os
import tempfile

from fastapi import FastAPI, File, Form, UploadFile
from faster_whisper import WhisperModel


MODEL_NAME = os.environ.get("ASR_MODEL", "Systran/faster-whisper-small")
DEVICE = os.environ.get("ASR_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("ASR_COMPUTE_TYPE", "int8")

app = FastAPI()
model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)


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

    uvicorn.run(app, host="127.0.0.1", port=8000)
```

这里真正“加载 ASR 模型”的代码是：

```python
model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
```

服务启动时会加载模型；第一次启动可能会下载模型文件，之后会使用本地缓存。

## 3. 选择和加载模型

### CPU 推荐

适合没有 NVIDIA 显卡，或只想轻量使用：

```powershell
$env:ASR_MODEL="Systran/faster-whisper-small"
$env:ASR_DEVICE="cpu"
$env:ASR_COMPUTE_TYPE="int8"
python server.py
```

如果机器较慢，可以把模型换成：

```powershell
$env:ASR_MODEL="Systran/faster-whisper-base"
```

### NVIDIA GPU 推荐

适合显存较充足、追求识别质量和速度：

```powershell
$env:ASR_MODEL="Systran/faster-whisper-large-v3"
$env:ASR_DEVICE="cuda"
$env:ASR_COMPUTE_TYPE="float16"
python server.py
```

如果显存不够，优先降模型大小，例如：

```powershell
$env:ASR_MODEL="Systran/faster-whisper-medium"
```

### 模型选择建议

| 模型 | 适合场景 |
| --- | --- |
| `Systran/faster-whisper-base` | CPU 轻量测试，速度快，准确率一般 |
| `Systran/faster-whisper-small` | CPU/GPU 通用，日常中文输入比较均衡 |
| `Systran/faster-whisper-medium` | 准确率更好，需要更多内存或显存 |
| `Systran/faster-whisper-large-v3` | 质量优先，推荐 GPU 使用 |

## 4. 在 BandoriPet 中启用

1. 启动 ASR 后端，确认终端里服务监听在 `127.0.0.1:8000`。
2. 启动 BandoriPet。
3. 打开设置面板。
4. 进入「语音输入」。
5. 开启「启用聊天语音输入」。
6. 「ASR API 地址」填写：

```text
http://127.0.0.1:8000/v1/audio/transcriptions
```

7. 「ASR API Key」本地服务可留空。
8. 「ASR 模型名」填写后端需要的模型名。使用上面的示例服务时，这里可以填 `whisper-large-v3`，实际加载哪个模型由服务启动时的 `ASR_MODEL` 决定。
9. 「识别语言」建议中文用户选「中文」。
10. 「识别文本插入方式」建议先用「追加到输入框」。
11. 「识别完成后自动发送」建议先关闭，确认识别准确后再开启。
12. 点击「保存」。

## 5. 测试识别

在「语音输入」设置页：

1. 点击「开始录音」。
2. 对麦克风说一句话。
3. 再次点击「停止并识别」。
4. 下方文本框出现识别结果，说明服务可用。

如果测试成功，回到聊天窗口就可以直接使用输入框旁边的麦克风按钮。

## 6. 聊天窗口使用方式

1. 打开聊天窗口。
2. 点击输入框左侧的麦克风按钮。
3. 看到状态提示「正在录音」后开始说话。
4. 再次点击麦克风按钮，停止录音并开始识别。
5. 识别成功后，文本会填入聊天输入框。
6. 检查或修改文字后，按回车或点击发送。

如果开启了「识别完成后自动发送」，第 5 步后会自动发送。

## 7. 常见问题

### 麦克风按钮是灰色的

检查：

- 设置页「语音输入」是否已启用。
- 是否已经点击「保存」。
- 当前 Python 环境是否安装了 `sounddevice` 和 `soundfile`。项目默认依赖里已经包含它们。

### 点击停止后提示 ASR 请求失败

检查：

- ASR 后端是否正在运行。
- API 地址是否填写为 `http://127.0.0.1:8000/v1/audio/transcriptions`。
- 端口是否被防火墙或其他程序占用。
- 后端终端是否有模型加载失败、CUDA 不可用、显存不足等报错。

### 第一次启动很慢

首次加载模型可能需要下载模型文件或初始化推理环境。后续启动会快一些。

### GPU 启动失败

把启动参数改成 CPU 测试：

```powershell
$env:ASR_DEVICE="cpu"
$env:ASR_COMPUTE_TYPE="int8"
python server.py
```

如果 CPU 可用，说明 BandoriPet 侧配置没问题，问题集中在 GPU/CUDA/模型后端环境。

### 识别文本不准

可以依次尝试：

- 在设置页把「识别语言」固定为中文。
- 减少环境噪声，离麦克风近一些。
- 从 `base/small` 升到 `medium/large-v3`。
- 关闭「自动发送」，先人工改字再发送。

## 8. 接入其他 ASR 服务

只要服务兼容下面的接口，就可以替换上面的示例后端：

```text
POST http://host:port/v1/audio/transcriptions
```

请求字段：

| 字段 | 说明 |
| --- | --- |
| `file` | BandoriPet 上传的 wav 录音文件 |
| `model` | 设置页填写的模型名 |
| `language` | 设置页选择的语言，例如 `zh`、`ja`、`en` |

返回字段：

| 字段 | 说明 |
| --- | --- |
| `text` | 最终识别文本 |

BandoriPet 也会兼容部分服务返回的 `transcript`、`result` 或 `segments[].text`。
