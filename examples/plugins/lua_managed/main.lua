local plugin = {}
local context = nil

local function before_chat(payload)
    local text = tostring(payload["text"] or "")
    if text ~= "" then
        return { action = "continue", patch = { text = text .. " [Lua plugin]" } }
    end
    return nil
end

local function ui_changed(payload)
    if payload["plugin_id"] ~= context.plugin_id then return nil end
    if payload["control_id"] == "enabled" then
        context.storage.set("enabled", payload["value"] == true)
    elseif payload["control_id"] == "wave" then
        context.services.call("pet.motion.play", { motion = "", expression = "" })
    end
    return nil
end

local function radial_action(payload)
    local action = tostring(payload["action"] or "")
    if string.find(action, "plugin:" .. context.plugin_id .. ":", 1, true) == 1 then
        local count = tonumber(context.storage.get("waves", 0)) or 0
        context.storage.set("waves", count + 1)
        context.services.call("pet.motion.play", { motion = "", expression = "" })
    end
    return nil
end

local function hello_command(payload)
    return { text = "Lua plugin received: " .. tostring(payload["arguments"] or "") }
end

local function state_tool(payload)
    return { stored_waves = tonumber(context.storage.get("waves", 0)) or 0, arguments = payload }
end

function plugin.activate(ctx)
    context = ctx
    ctx.events.on("chat.message.before", before_chat, 10)
    ctx.events.on("ui.changed", ui_changed, 0)
    ctx.events.on("radial.action", radial_action, 0)
    ctx.commands.register(
        { name = "luahello", triggers = { "/luahello" }, description = "Lua plugin command" },
        hello_command
    )
    ctx.tools.register(
        {
            name = "lua_plugin_state",
            description = "Read the Lua example plugin state.",
            parameters = { type = "object", properties = {} }
        },
        state_tool
    )
    ctx.ui.register({
        schema_version = 1,
        id = "lua-example-settings",
        location = "settings_page",
        title = "Lua example",
        description = "The same declarative controls are available to Lua.",
        children = {
            { id = "enabled", type = "switch", label = "Enable suffix", value = ctx.storage.get("enabled", true) },
            { id = "wave", type = "button", label = "Trigger pet action" }
        }
    })
    ctx.ui.register({
        schema_version = 1,
        id = "lua-example-radial",
        location = "radial_menu",
        label = "Lua wave",
        glyph = "L",
        color = { 14, 165, 233 }
    })
    ctx.log.info("Lua managed example activated")
end

function plugin.deactivate(reason)
    if context ~= nil then context.log.info("Lua managed example stopped: " .. tostring(reason)) end
end

return plugin
