CONTEXT = None


def _before_chat(payload):
    text = str(payload.get("text", ""))
    if text and not text.endswith(" [Python plugin]"):
        return {"action": "continue", "patch": {"text": text + " [Python plugin]"}}
    return None


def _ui_changed(payload):
    if payload.get("plugin_id") != CONTEXT.plugin_id:
        return None
    if payload.get("control_id") == "enabled":
        CONTEXT.storage.set("enabled", bool(payload.get("value")))
    if payload.get("control_id") == "wave":
        CONTEXT.services.call("pet.motion.play", {"motion": "", "expression": ""})
    return None


def _radial_action(payload):
    action = str(payload.get("action", ""))
    if action.startswith("plugin:" + CONTEXT.plugin_id + ":"):
        count = int(CONTEXT.storage.get("waves", 0)) + 1
        CONTEXT.storage.set("waves", count)
        CONTEXT.services.call("pet.motion.play", {"motion": "", "expression": ""})
    return None


def _hello_command(payload):
    return {"text": "Python plugin received: " + str(payload.get("arguments", ""))}


def _state_tool(payload):
    return {"stored_waves": int(CONTEXT.storage.get("waves", 0)), "arguments": payload}


def activate(ctx):
    global CONTEXT
    CONTEXT = ctx
    ctx.events.on("chat.message.before", _before_chat, priority=20)
    ctx.events.on("ui.changed", _ui_changed)
    ctx.events.on("radial.action", _radial_action)
    ctx.commands.register(
        {"name": "pyhello", "triggers": ["/pyhello"], "description": "Python plugin command"},
        _hello_command,
    )
    ctx.tools.register(
        {
            "name": "python_plugin_state",
            "description": "Read the Python example plugin state.",
            "parameters": {"type": "object", "properties": {}}
        },
        _state_tool,
    )
    ctx.ui.register({
        "schema_version": 1,
        "id": "python-example-settings",
        "location": "settings_page",
        "title": "Python example",
        "description": "This UI is rendered from JSON and runs in the settings process.",
        "children": [
            {"id": "enabled", "type": "switch", "label": "Enable suffix", "value": ctx.storage.get("enabled", True)},
            {"id": "wave", "type": "button", "label": "Trigger pet action"}
        ]
    })
    ctx.ui.register({
        "schema_version": 1,
        "id": "python-example-radial",
        "location": "radial_menu",
        "label": "Plugin wave",
        "glyph": "P",
        "color": [124, 58, 237]
    })
    ctx.log.info("Python managed example activated")


def deactivate(reason):
    if CONTEXT is not None:
        CONTEXT.log.info("Python managed example stopped: " + str(reason))
