# BandoriPet 聊天接入说明

这个功能用于接收外部聊天软件、机器人或脚本推送的消息，让 BandoriPet 保存最近聊天上下文，并在桌宠悬浮窗显示未读摘要。

## 1. 开启功能

1. 打开设置。
2. 进入「聊天接入」。
3. 开启「启用本地聊天接入端口」。
4. 如需悬浮提示，保持「收到消息时显示悬浮窗摘要」开启。
5. 如需让角色聊天时看到这些消息，保持「允许模型读取最近外部聊天上下文」开启。
6. 点击保存，再点击右侧「应用」。

默认端口：

```text
http://127.0.0.1:38473/chat-events
```

## 2. 推送消息

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

## 3. 标记已读

请求方式：`POST /chat-read`

```json
{
  "platform": "wechat",
  "thread_id": "room-1"
}
```

不传 `thread_id` 会清空该平台未读；连 `platform` 也不传则清空全部未读。
