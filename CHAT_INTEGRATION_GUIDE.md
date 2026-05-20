# BandoriPet 聊天接入说明

这个功能用于接收外部聊天软件、机器人或脚本推送的消息，让 BandoriPet 保存最近聊天上下文，并在桌宠悬浮窗显示未读摘要。

## 推荐配置流程

1. 打开设置，进入「聊天接入」。
2. 开启「启用本地聊天接入端口」。
3. 点击「生成 Token」。如果只是自己电脑上的本地脚本，也可以留空。
4. 点击「保存聊天接入配置」。
5. 点击「发送测试消息」。看到测试成功后，说明端口已经可用。
6. 点击「复制接入信息」，把接收地址、Token 和字段说明粘贴到聊天软件的 Webhook/HTTP 转发配置里。

默认接收地址：

```text
http://127.0.0.1:38473/chat-events
```

设置页里的端口如果改成别的数字，接收地址也会自动变。

## QQ 接入建议

QQ 不能像普通网页服务那样直接填写账号密码读取所有聊天。推荐把 QQ 侧单独作为一个“消息转发器”，再把消息转发到 BandoriPet 的本地接收地址。

### 一键脚本：NapCat 接入 BandoriPet

项目内置了 Windows 脚本：

```text
tools\setup_napcat_bandori.cmd
```

双击运行后会自动完成这些事：

1. 从 NapCat GitHub Release 下载最新 Windows 包并解压到 `.runtime\napcat`。
2. 写入 NapCat OneBot HTTP 客户端配置，上报地址为 `http://127.0.0.1:38473/chat-events`。
3. 启动 NapCat。
4. 打开 NapCat WebUI。
5. 等你在 WebUI 中用手机 QQ 扫码登录。
6. 检测到 `onebot11_<QQ号>.json` 后，再次把 BandoriPet 上报配置写入当前 QQ 账号配置。

如果你在 BandoriPet 聊天接入里设置了 Token，请用命令行运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\setup_napcat_bandori.ps1 -BandoriToken "你的Token"
```

常用参数：

| 参数 | 作用 |
| --- | --- |
| `-BandoriPort 38473` | BandoriPet 聊天接入端口 |
| `-BandoriToken "..."` | BandoriPet 聊天接入 Token |
| `-InstallDir "D:\NapCat"` | 自定义 NapCat 安装目录 |
| `-WaitLoginMinutes 10` | 等待 QQ 扫码登录并生成账号配置的分钟数 |
| `-SkipDownload` | 已经安装 NapCat 时跳过下载 |

脚本不会读取或保存 QQ 密码。QQ 登录必须由用户在 NapCat WebUI 中扫码确认。

### 方案一：官方 QQ 机器人

适合想走正规平台能力、能接受“群聊通常需要 @机器人 才触发”的用户。

1. 打开 [QQ 开放平台](https://q.qq.com/)。
2. 创建 QQ 机器人应用，记录 `AppID` 和 `AppSecret`。
3. 在机器人权限/事件里启用需要的消息类型，例如 C2C 私聊、QQ群 @ 消息、频道消息。
4. 测试阶段按平台要求添加沙箱测试用户或测试群。
5. 使用支持 QQ 官方 Bot API 的机器人框架或自己的桥接脚本接收 QQ 消息。
6. 收到 QQ 消息后，把消息整理成下面的 JSON，并 POST 到 BandoriPet 的接收地址。

```json
{
  "platform": "qq",
  "thread_id": "QQ群号或私聊ID",
  "thread_name": "群名或私聊名",
  "sender_id": "发送者QQ或OpenID",
  "sender_name": "发送者昵称",
  "text": "消息正文",
  "message_id": "QQ消息ID"
}
```

注意：

- 官方机器人不等于个人 QQ 客户端 API，不能直接读取你个人号里所有好友/群消息。
- QQ 群聊通常只会把 `@机器人` 的消息投递给机器人。
- 新机器人常见默认是沙箱环境，正式接入前可能需要配置权限或审核。

### 方案二：OneBot 兼容转发

适合已经在使用 NapCat、LLOneBot、Lagrange 等 OneBot 兼容服务的用户。

推荐让 OneBot 侧或中间桥接脚本把事件转成 BandoriPet 字段：

| OneBot 常见字段 | BandoriPet 字段 |
| --- | --- |
| `group_id` | `thread_id` |
| `sender.nickname` / `sender.card` | `sender_name` |
| `user_id` | `sender_id` |
| `raw_message` | `text` |
| `message_id` | `message_id` |

如果 OneBot 工具支持“自定义 HTTP 上报模板”，可以按上面的 JSON 模板发到：

```text
http://127.0.0.1:38473/chat-events
```

如果只能转发原始 OneBot 事件，也可以直接发到这个地址。BandoriPet 会自动识别 `post_type=message` 的私聊/群聊事件，并忽略心跳、通知等非消息事件。

### 不推荐的方式

不建议在 BandoriPet 主程序里直接内置个人 QQ 协议登录。非官方协议方案可能有账号风控、协议变动和合规风险；更稳的做法是让 QQ 适配器独立运行，BandoriPet 只接收本地 Webhook。

## 低门槛 URL 模式

如果你的聊天软件或机器人面板只能填写一个 URL，可以使用查询参数：

```text
http://127.0.0.1:38473/chat-events?platform=qq&thread_id=default&thread_name=群聊名&sender_name=发送人&text=消息内容
```

如果设置了 Token，在 URL 最后追加：

```text
&token=你的Token
```

常见字段对应：

| 字段 | 填什么 |
| --- | --- |
| `text` | 消息正文，必填 |
| `sender_name` | 发送者昵称 |
| `thread_name` | 群聊名或私聊名 |
| `thread_id` | 会话 ID，不知道就填 `default` |
| `platform` | 来源，例如 `qq`、`wechat`、`telegram`、`discord` |

## JSON 模式

请求方式：`POST /chat-events`

最小 JSON：

```json
{
  "platform": "wechat",
  "thread_id": "room-1",
  "sender_name": "香澄",
  "text": "晚上可以和你一起睡吗?"
}
```

推荐字段：

| 字段 | 说明 |
| --- | --- |
| `platform` | 来源，例如 `wechat`、`qq`、`telegram`、`discord` |
| `thread_id` | 会话 ID，用于区分群聊或私聊 |
| `thread_name` | 会话显示名 |
| `sender_id` | 发送者 ID |
| `sender_name` | 发送者显示名 |
| `text` | 消息正文 |
| `message_id` | 外部消息 ID；填写后可避免重复入库 |
| `character` | 可选目标角色 key；留空会广播给所有桌宠 |

PowerShell 示例：

```powershell
$body = @{
  platform = "wechat"
  thread_id = "room-1"
  thread_name = "私聊"
  sender_name = "香澄"
  text = "晚上可以和你一起睡吗?"
} | ConvertTo-Json -Compress

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:38473/chat-events" `
  -ContentType "application/json" `
  -Body $body
```

如果设置了 Token：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:38473/chat-events" `
  -Headers @{ Authorization = "Bearer your-token" } `
  -ContentType "application/json" `
  -Body $body
```

## 表单模式

一些低代码工具会发送 `application/x-www-form-urlencoded` 表单，也可以直接接入：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:38473/chat-events" `
  -ContentType "application/x-www-form-urlencoded" `
  -Body "platform=qq&thread_id=default&sender_name=发送人&text=消息内容"
```

## 纯文本模式

如果工具只能发送一段文本，可以用 `text/plain`。BandoriPet 会把整段内容当成消息正文：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:38473/chat-events" `
  -ContentType "text/plain" `
  -Body "消息内容"
```

## 标记已读

请求方式：`POST /chat-read`

```json
{
  "platform": "wechat",
  "thread_id": "room-1"
}
```

不传 `thread_id` 会清空该平台未读；连 `platform` 也不传则清空全部未读。
