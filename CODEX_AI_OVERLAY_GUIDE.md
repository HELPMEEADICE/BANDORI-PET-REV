# BandoriPet AI App 状态悬浮窗接入教程

本文说明如何把 Codex 或其他 AI App 的工作状态显示到 Live2D 角色上方的悬浮窗。

## 1. 在 BandoriPet 中开启功能

1. 启动 BandoriPet。
2. 打开设置。
3. 进入「悬浮窗设置」。
4. 开启「接收 AI App 状态事件」。
5. 如果要让其他 App 通过 HTTP 推送事件，继续开启「启用本地 AI 状态端口」。
6. 端口默认使用 `38472`。
7. Token 可以留空；如果要给第三方 App 使用，建议填写一个随机字符串。
8. 点击「保存」。
9. 点击右侧「应用」让当前桌宠进程刷新设置。

## 2. Codex 接入方式

当前接入方式是 wrapper 模式：用 `bandori_codex_runner.py` 启动 Codex CLI，wrapper 读取 `codex exec --json` 的事件流，再转成 BandoriPet 状态事件。

这能显示由 wrapper 启动的 Codex 过程，但不能监听一个已经打开的 Codex Desktop 会话。Codex Desktop 目前没有为本项目暴露稳定的外部状态 hook。

### 2.1 开发环境运行

进入项目目录：

```powershell
cd C:\Users\thoma\Documents\Codex\2026-05-10\https-github-com-thomasjjjjkooo-ops-bandori\BANDORI-PET-FIX
```

运行一个 Codex 任务：

```powershell
C:\Users\thoma\AppData\Local\Programs\Python\Python311\python.exe bandori_codex_runner.py -- "帮我总结这个项目的结构"
```

指定工作目录：

```powershell
C:\Users\thoma\AppData\Local\Programs\Python\Python311\python.exe bandori_codex_runner.py --workdir C:\Users\thoma\Documents\Codex\2026-05-10\https-github-com-thomasjjjjkooo-ops-bandori\BANDORI-PET-FIX -- "解释 pet_window.py 的事件流"
```

给 Codex 传参数时，把参数放在 wrapper 的 `--` 后面：

```powershell
C:\Users\thoma\AppData\Local\Programs\Python\Python311\python.exe bandori_codex_runner.py -- -m gpt-5.4 "检查这个项目的潜在问题"
```

指定只让某个角色显示：

```powershell
C:\Users\thoma\AppData\Local\Programs\Python\Python311\python.exe bandori_codex_runner.py --character kasumi -- "帮我检查设置页代码"
```

### 2.2 打包后运行

打包后可使用：

```powershell
bandori-codex-runner.exe -- "帮我总结这个项目"
```

## 3. 本地状态端口接入方式

开启「启用本地 AI 状态端口」后，BandoriPet 会监听：

```text
http://127.0.0.1:38472/ai-events
```

只接收 `POST` JSON。事件格式：

```json
{
  "source": "codex",
  "state": "thinking",
  "title": "正在分析项目",
  "text": "读取 pet_window.py...",
  "progress": 0.35,
  "action": "thinking",
  "ttl_ms": 4500
}
```

常用字段：

| 字段 | 说明 |
| --- | --- |
| `source` | 来源名称，例如 `codex`、`claude`、`ollama` |
| `state` | `idle`、`thinking`、`tool`、`stream`、`error`、`done`、`clear` |
| `title` | 悬浮窗第一行标题 |
| `text` | 主要显示内容 |
| `mode` | `replace` 或 `append`；`stream` 默认追加，其他状态默认替换 |
| `progress` | 进度，支持 `0.35` 或 `35` |
| `action` | 可选 Live2D 动作，如 `thinking`、`smile`、`surprised` |
| `character` | 可选目标角色 key；留空会广播给所有桌宠 |
| `ttl_ms` | 可选自动清空时间，单位毫秒 |

### 3.1 PowerShell 示例

无 Token：

```powershell
$body = @{
  source = "external"
  state = "thinking"
  title = "正在处理"
  text = "外部 App 已连接 BandoriPet"
} | ConvertTo-Json -Compress

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:38472/ai-events" -ContentType "application/json" -Body $body
```

使用 Token：

```powershell
$token = "your-token"
$body = @{
  source = "external"
  state = "tool"
  title = "正在运行工具"
  text = "读取项目文件"
  progress = 0.5
} | ConvertTo-Json -Compress

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:38472/ai-events" `
  -Headers @{ Authorization = "Bearer $token" } `
  -ContentType "application/json" `
  -Body $body
```

### 3.2 curl 示例

```powershell
curl.exe -X POST http://127.0.0.1:38472/ai-events `
  -H "Content-Type: application/json" `
  -d "{\"source\":\"curl\",\"state\":\"done\",\"text\":\"任务完成\"}"
```

带 Token：

```powershell
curl.exe -X POST http://127.0.0.1:38472/ai-events `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer your-token" `
  -d "{\"source\":\"curl\",\"state\":\"thinking\",\"text\":\"正在思考\"}"
```

### 3.3 Python 示例

```python
import json
import urllib.request

event = {
    "source": "python",
    "state": "stream",
    "mode": "append",
    "text": "追加一段模型输出..."
}

request = urllib.request.Request(
    "http://127.0.0.1:38472/ai-events",
    data=json.dumps(event, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(request) as response:
    print(response.read().decode("utf-8"))
```

## 4. 排错

- 手动运行 `bandori_ai_event.py` 能显示，但 Codex 不显示：说明总线正常；请确认 Codex 是通过 `bandori_codex_runner.py` 启动的。
- HTTP 请求返回 `401`：设置页里填写了 Token，请发送 `Authorization: Bearer <token>` 或 `X-Bandori-Token: <token>`。
- HTTP 请求连接失败：确认「启用本地 AI 状态端口」已打开，并点击了「应用」。
- 有多个桌宠都显示：在事件里加 `"character": "kasumi"` 之类的角色 key。
- 只想清空悬浮窗：发送 `{ "state": "clear" }`。
