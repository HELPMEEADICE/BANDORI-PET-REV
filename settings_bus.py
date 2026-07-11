import json

from ipc_bus import send_ipc_message
from process_utils import log_swallowed


def publish_settings(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    try:
        payload = json.dumps(data, ensure_ascii=False)
        return send_ipc_message(f"SETTINGS\t{payload}\n") is not False
    except Exception as exc:
        log_swallowed("settings_bus.publish_settings", exc)
        return False
