# BandoriPet MCP / Computer Use 教程

本文说明如何在 BandoriPet 中启用 MCP 工具和 Computer Use。设置入口：

`设置 -> 屏幕感知与工具控制`

## 1. 两种 MCP 接入方式

BandoriPet 同时支持两条路径：

1. **服务商原生 MCP**
   - 适合 OpenAI Responses 这类直接支持 `tools: [{"type":"mcp"}]` 的接口。
   - BandoriPet 会把 `transport: "native"` 或 `transport: "http"` 且带 `url` / `connector_id` 的服务器作为原生 MCP 工具传给服务商。
   - 只有服务商真正支持原生 MCP 时才会生效。

2. **本地 MCP 代理**
   - 适合 DeepSeek、OpenRouter、OpenAI-compatible Chat Completions 等只支持 `tools/function calling` 的接口。
   - BandoriPet 自己连接 MCP server，读取 `tools/list`，再把 MCP 工具转换成 Chat Completions function tools。
   - 模型返回 `tool_calls` 后，BandoriPet 执行 MCP `tools/call`，再把结果发回模型。

## 2. MCP JSON 配置

设置页里的 MCP 服务器 JSON 必须是数组。留空或 `[]` 表示不启用任何 MCP server。

编辑 JSON 后可以点击 `测试 MCP 连接`。它会直接读取当前编辑框里的配置并尝试发现工具，不需要先保存；如果是 OpenAI Responses 的原生 `connector_id`，只能提示配置可发送给服务商，最终连通性要在服务商请求时验证。

## 直接复制的模板

### 只启用 BandoriPet 自带工具

适合想让模型控制桌宠动作、状态浮层，但不碰文件系统的用户：

```json
[
  {
    "enabled": true,
    "label": "bandori",
    "transport": "stdio",
    "command": "python",
    "args": ["bandori_mcp_server.py"],
    "cwd": "C:/path/to/BANDORI-PET-FIX",
    "allowed_tools": [
      "bandori_pet_action",
      "bandori_ai_event",
      "bandori_list_characters"
    ],
    "require_approval": "never",
    "timeout_seconds": 30
  }
]
```

把 `cwd` 改成你的项目路径，例如：

```json
"cwd": "C:/Users/thoma/Documents/Codex/2026-05-10/https-github-com-thomasjjjjkooo-ops-bandori/BANDORI-PET-FIX"
```

### 本地文件系统 MCP

适合让模型读取指定目录中的文件。最稳的方式是使用项目自带的只读 Python 文件系统 MCP，不需要 Node/npm。把最后一个路径改成你愿意授权的目录：

```json
[
  {
    "enabled": true,
    "label": "filesystem",
    "transport": "stdio",
    "command": "python",
    "args": [
      "filesystem_mcp_server.py",
      "~/Documents"
    ],
    "cwd": "C:/path/to/BANDORI-PET-FIX",
    "allowed_tools": [],
    "require_approval": "never",
    "timeout_seconds": 30
  }
]
```

Windows 可以把 `~/Documents` 改成 `C:/Users/你的用户名/Documents`；macOS/Linux 可以保留 `~/Documents`，也可以改成任何你愿意授权的目录。`cwd` 请填写 BandoriPet 项目目录；Windows 用 `C:/...`，macOS/Linux 用 `/Users/...` 或 `/home/...`。

如果你更想用官方 npm filesystem server，也可以使用下面的模板：

```json
[
  {
    "enabled": true,
    "label": "filesystem",
    "transport": "stdio",
    "command": "npx",
    "args": [
      "-y",
      "@modelcontextprotocol/server-filesystem",
      "C:/Users/you/Documents"
    ],
    "cwd": "",
    "allowed_tools": [],
    "require_approval": "always",
    "timeout_seconds": 30
  }
]
```

如果 Windows 上提示 `WinError 2` 或找不到 `npx`，先安装 Node.js/npm 并重启 BandoriPet；仍失败时把 `"command": "npx"` 改成 `"command": "npx.cmd"`，或填写 `npx.cmd` 的完整路径。

### 远程 MCP / 服务商原生 MCP

适合 OpenAI Responses 等支持原生 MCP 的服务商：

```json
[
  {
    "enabled": true,
    "label": "remote_docs",
    "transport": "native",
    "url": "https://example.com/mcp",
    "allowed_tools": [],
    "require_approval": "never",
    "timeout_seconds": 30
  }
]
```

DeepSeek、OpenRouter 这类 Chat Completions 兼容接口通常不原生执行 MCP，请优先用 `stdio` 或 `http` 代理模板。

### stdio 示例

```json
[
  {
    "enabled": true,
    "label": "filesystem",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/Users/you/Documents"],
    "cwd": "",
    "allowed_tools": [],
    "require_approval": "always",
    "timeout_seconds": 30
  }
]
```

字段说明：

- `label`: 服务名，会参与生成 function tool 名称。
- `transport`: `stdio`、`http` 或 `native`。
- `command` / `args`: stdio MCP server 的启动命令。
- `cwd`: 可选工作目录；留空时使用 BandoriPet 当前工作目录。
- `allowed_tools`: 只暴露指定工具；空数组表示暴露该服务器返回的全部工具。
- `require_approval`: `always` 会阻止本地代理实际调用；`never` 才允许自动执行。建议先用 `always` 测试工具发现，再改成 `never`。
- `timeout_seconds`: MCP 请求超时。

### 让模型调用 BandoriPet 自己

项目内置了一个 stdio MCP server：`bandori_mcp_server.py`。它可以给外部 Agent 暴露：

- `bandori_pet_action`: 触发角色动作。
- `bandori_ai_event`: 显示 AI 状态浮层。
- `bandori_lip_sync`: 设置口型同步强度。
- `bandori_list_characters`: 列出角色。
- `bandori_health`: 健康检查。

把它加到 MCP JSON：

```json
[
  {
    "enabled": true,
    "label": "bandori",
    "transport": "stdio",
    "command": "python",
    "args": ["bandori_mcp_server.py"],
    "cwd": "C:/path/to/BANDORI-PET-FIX",
    "allowed_tools": ["bandori_pet_action", "bandori_ai_event", "bandori_list_characters"],
    "require_approval": "never"
  }
]
```

如果是外部 MCP 客户端，例如 Claude Desktop、Codex、Cursor，请把同样的 `command` / `args` 填到对应客户端的 MCP 配置里，并确保工作目录是 BandoriPet 项目根目录，或把 `bandori_mcp_server.py` 写成绝对路径。

### OpenAI Responses 原生 MCP 示例

```json
[
  {
    "enabled": true,
    "label": "docs",
    "transport": "native",
    "url": "https://example.com/mcp",
    "allowed_tools": ["search", "fetch"],
    "require_approval": "never"
  }
]
```

如果你正在用 DeepSeek / OpenRouter，这类 `native` 配置不会由服务商原生执行；请改用 `stdio` 或 `http` 代理。

注意：BandoriPet 当前没有原生 MCP 审批弹窗循环，所以原生 MCP 只会发送 `require_approval: "never"` 的服务器。需要人工审批的 MCP server 请先走本地代理，并保持 `require_approval: "always"` 阻止实际调用。

## 3. Computer Use

Computer Use 会把屏幕截图发给模型，并可按设置页授权执行鼠标、键盘、剪贴板和等待动作。

安装依赖：

```bash
pip install -r requirements.txt
```

Windows 下鼠标移动、点击、滚动带有系统 API fallback；键盘输入和剪贴板仍建议安装完整依赖。

建议配置：

- 初次使用只开启 `允许截屏` 和 `向模型发送操作后的截图`。
- 开启 `让模型按自然语义自行判断是否使用` 后，用户说“点一下那个”“把鼠标放左边”“看看现在窗口里是什么”这类模糊表达时，模型也可以自行决定是否调用 Computer Use。
- 确认模型行为稳定后，再开启鼠标。
- 键盘和剪贴板权限风险更高，只给可信任务临时开启。
- 不要让模型处理密码、支付、删除、购买、发帖、发邮件、登录、修改安全设置等不可逆操作。

DeepSeek / OpenRouter 等兼容接口会把 Computer Use 当作普通 function tools 使用。模型需要支持图片输入，才能稳定理解屏幕截图。

坐标说明：设置页的“截图最长边像素”只是发给模型的图片尺寸。鼠标工具现在会把“截图图片坐标”自动映射到真实桌面坐标，所以即使截图最长边是 1280，也可以点击或移动到 1920/2560 等更宽屏幕的右侧。

## 4. 沉浸模式

如果开启 `沉浸模式隐藏工具细节`，BandoriPet 会提示模型不要在角色回复中主动说出：

- MCP
- tool calls / function calling
- Computer Use
- JSON schema
- 工具调用过程

这只影响最终角色回复，不影响实际工具执行。

## 5. 常见问题

### 工具没有被调用

检查：

- 当前模型是否支持 tool calls。
- 当前 API 是否接受 `tools` 参数。
- MCP JSON 是否有效。
- `require_approval` 是否仍为 `always`。
- `llm_mcp_enabled` 或 `computer_use_enabled` 是否开启。

### API 连接报错

部分 OpenAI-compatible 服务商会拒绝复杂工具 schema 或图片消息。BandoriPet 会尽量在工具请求被拒绝时回退到普通聊天，但工具能力不会生效。可以尝试：

- 换支持 tool calling 的模型。
- 在 OpenRouter 选择 Tool Call Error Rate 更低的模型。
- 关闭 Computer Use 的截图回传。
- 减少 MCP `allowed_tools` 数量。

### MCP server 启动失败

stdio MCP 需要本机能直接执行 `command`。例如 `npx` 必须在 PATH 中可用；Windows 上可尝试 `npx.cmd`。建议先在终端手动运行 MCP server，确认依赖和权限没问题。
