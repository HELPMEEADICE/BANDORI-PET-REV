const DEFAULT_ENDPOINT = "http://127.0.0.1:38472/ai-events"
const DEFAULT_SOURCE = "opencode"
const DEFAULT_TTL_MS = 4500
const DEFAULT_TIMEOUT_MS = 900
const DEFAULT_MAX_TEXT = 240

function readEnv() {
  const global = globalThis
  return {
    ...(global.process?.env ?? {}),
    ...(global.Bun?.env ?? {}),
  }
}

function envFlag(value) {
  return ["1", "true", "yes", "on"].includes(String(value || "").toLowerCase())
}

function envNumber(value, fallback) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback
}

function compactText(value) {
  if (value == null) return ""
  if (typeof value === "string") return value.trim()
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  if (Array.isArray(value)) {
    return value.map(compactText).filter(Boolean).join(" ").trim()
  }
  if (typeof value === "object") {
    for (const key of [
      "text",
      "content",
      "delta",
      "summary",
      "message",
      "title",
      "command",
      "cmd",
      "filePath",
      "path",
      "name",
      "status",
    ]) {
      const text = compactText(value[key])
      if (text) return text
    }
  }
  return ""
}

function clipText(text, maxText) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim()
  if (!normalized || normalized.length <= maxText) return normalized
  return `${normalized.slice(0, Math.max(0, maxText - 1)).trimEnd()}...`
}

function pick(obj, paths) {
  for (const path of paths) {
    let current = obj
    for (const part of path.split(".")) {
      current = current?.[part]
    }
    if (current != null && current !== "") return current
  }
  return ""
}

function describeTool(input, output, maxText) {
  const toolName = String(pick(input, ["tool", "name"]) || pick(output, ["tool", "name"]) || "tool")
  const args = output?.args ?? input?.args ?? input?.parameters ?? {}
  const details =
    pick(args, ["command", "cmd"]) ||
    pick(args, ["filePath", "path", "pattern", "query", "url"]) ||
    compactText(args)
  return clipText(details ? `${toolName}: ${details}` : toolName, maxText)
}

function describeEvent(event, maxText) {
  return clipText(
    compactText(
      pick(event, [
        "error.message",
        "part.delta",
        "part.text",
        "part.content",
        "message.content",
        "message.text",
        "session.title",
        "session.id",
        "permission.title",
        "permission.message",
        "file.path",
        "command.command",
        "todo.items",
        "data",
        "text",
      ]) || event,
    ),
    maxText,
  )
}

function todoSummary(event) {
  const items = pick(event, ["todo.items", "items"])
  if (!Array.isArray(items)) return ""
  const total = items.length
  const done = items.filter((item) => {
    const status = String(item?.status || item?.state || "").toLowerCase()
    return ["done", "completed", "complete"].includes(status)
  }).length
  return total ? `TODO ${done}/${total}` : ""
}

export const BandoriAiOverlay = async (ctx = {}) => {
  const env = readEnv()
  if (envFlag(env.BANDORI_AI_DISABLED) || env.BANDORI_AI_OVERLAY === "0") {
    return {}
  }

  const endpoint = env.BANDORI_AI_ENDPOINT || env.BANDORI_AI_URL || DEFAULT_ENDPOINT
  const token = env.BANDORI_AI_TOKEN || ""
  const source = env.BANDORI_AI_SOURCE || DEFAULT_SOURCE
  const character = env.BANDORI_AI_CHARACTER || ""
  const ttlMs = envNumber(env.BANDORI_AI_TTL_MS, DEFAULT_TTL_MS)
  const requestTimeoutMs = envNumber(env.BANDORI_AI_TIMEOUT_MS, DEFAULT_TIMEOUT_MS)
  const maxText = envNumber(env.BANDORI_AI_MAX_TEXT, DEFAULT_MAX_TEXT)
  const debug = envFlag(env.BANDORI_AI_DEBUG)
  let lastFailure = ""
  let lastPayloadKey = ""
  let lastPayloadAt = 0

  async function log(level, message, extra = {}) {
    if (!ctx.client?.app?.log) return
    try {
      await ctx.client.app.log({
        body: {
          service: "bandori-ai-overlay",
          level,
          message,
          extra,
        },
      })
    } catch {
      // Logging must never break opencode hooks.
    }
  }

  async function publish(payload, options = {}) {
    const now = Date.now()
    const event = {
      source,
      ...payload,
      state: payload.state || "stream",
      title: payload.title || "",
      text: clipText(payload.text || "", maxText),
    }
    if (character && !event.character) event.character = character
    if (ttlMs && event.state !== "clear" && event.ttl_ms == null) event.ttl_ms = ttlMs

    const key = JSON.stringify([event.state, event.title, event.text, event.mode, event.action])
    const dedupeMs = options.dedupeMs ?? 350
    if (dedupeMs && key === lastPayloadKey && now - lastPayloadAt < dedupeMs) return
    lastPayloadKey = key
    lastPayloadAt = now

    const headers = { "Content-Type": "application/json" }
    if (token) headers.Authorization = `Bearer ${token}`

    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), requestTimeoutMs)
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers,
        body: JSON.stringify(event),
        signal: controller.signal,
      })
      if (!response.ok) {
        const failure = `HTTP ${response.status}`
        if (failure !== lastFailure || debug) {
          lastFailure = failure
          await log("warn", "BandoriPet AI event was rejected", { endpoint, status: response.status })
        }
      }
    } catch (error) {
      const failure = error?.name || error?.message || String(error)
      if (debug && failure !== lastFailure) {
        lastFailure = failure
        await log("debug", "BandoriPet AI event was not delivered", { endpoint, error: failure })
      }
    } finally {
      clearTimeout(timeout)
    }
  }

  async function mirrorEvent(event) {
    const type = String(event?.type || "").toLowerCase()
    if (!type) return

    if (type === "server.connected") {
      await publish({
        state: "thinking",
        title: "opencode 已连接",
        text: "BandoriPet 状态悬浮窗插件已加载",
        action: "thinking",
        ttl_ms: 2500,
      })
      return
    }

    if (type === "session.created") {
      await publish({
        state: "thinking",
        title: "opencode 会话开始",
        text: describeEvent(event, maxText),
        action: "thinking",
      })
      return
    }

    if (type === "session.status") {
      const status = String(pick(event, ["status", "session.status"]) || "").toLowerCase()
      if (status.includes("idle")) {
        await publish({ state: "done", title: "opencode 已完成", text: "当前会话空闲", action: "smile" })
      } else if (status) {
        await publish({
          state: "thinking",
          title: "opencode 正在工作",
          text: status,
          action: "thinking",
        })
      }
      return
    }

    if (type === "session.idle") {
      await publish({ state: "done", title: "opencode 已完成", text: "任务处理完成", action: "smile" })
      return
    }

    if (type === "session.error") {
      await publish({
        state: "error",
        title: "opencode 出错",
        text: describeEvent(event, maxText),
        action: "surprised",
      })
      return
    }

    if (type === "session.deleted") {
      await publish({ state: "clear", title: "", text: "" })
      return
    }

    if (type === "permission.asked") {
      await publish({
        state: "tool",
        title: "opencode 等待确认",
        text: describeEvent(event, maxText),
        action: "surprised",
      })
      return
    }

    if (type === "permission.replied") {
      await publish({
        state: "thinking",
        title: "opencode 继续执行",
        text: describeEvent(event, maxText),
        action: "thinking",
        ttl_ms: 2500,
      })
      return
    }

    if (type === "file.edited") {
      await publish({
        state: "tool",
        title: "opencode 修改文件",
        text: describeEvent(event, maxText),
        action: "thinking",
      })
      return
    }

    if (type === "command.executed") {
      await publish({
        state: "tool",
        title: "opencode 执行命令",
        text: describeEvent(event, maxText),
        action: "thinking",
      })
      return
    }

    if (type === "todo.updated") {
      await publish({
        state: "thinking",
        title: "opencode 更新 TODO",
        text: todoSummary(event) || describeEvent(event, maxText),
        action: "thinking",
        ttl_ms: 3000,
      })
      return
    }

    if (type === "session.diff") {
      await publish({
        state: "tool",
        title: "opencode 生成变更",
        text: describeEvent(event, maxText),
        action: "thinking",
      })
      return
    }

    if (type === "message.part.updated" || type === "message.updated") {
      const text = describeEvent(event, maxText)
      if (!text) return
      const hasDelta = Boolean(pick(event, ["part.delta", "delta"]))
      await publish(
        {
          state: "stream",
          title: "opencode 输出",
          text,
          mode: hasDelta ? "append" : "replace",
        },
        { dedupeMs: 900 },
      )
    }
  }

  return {
    event: async ({ event }) => {
      await mirrorEvent(event)
    },
    "tool.execute.before": async (input, output) => {
      await publish({
        state: "tool",
        title: "opencode 正在运行工具",
        text: describeTool(input, output, maxText),
        action: "thinking",
      })
    },
    "tool.execute.after": async (input, output) => {
      const errorText = compactText(output?.error || output?.result?.error)
      if (errorText) {
        await publish({
          state: "error",
          title: "opencode 工具失败",
          text: clipText(errorText, maxText),
          action: "surprised",
        })
        return
      }
      await publish({
        state: "thinking",
        title: "opencode 继续思考",
        text: describeTool(input, output, maxText),
        action: "thinking",
        ttl_ms: 2500,
      })
    },
  }
}
