from PySide6.QtCore import QThread, Signal

from i18n_manager import tr as _tr
from screen_capture import capture_screenshot_data_url
from vision_fallback import analyze_images_with_aux_model


SCREEN_AWARENESS_MIN_INTERVAL_MINUTES = 1
SCREEN_AWARENESS_MAX_INTERVAL_MINUTES = 120
SCREEN_AWARENESS_MODEL_MODE_MAIN = "main"
SCREEN_AWARENESS_MODEL_MODE_AUX = "aux"


def clamp_screen_awareness_interval(value) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = 30
    return max(SCREEN_AWARENESS_MIN_INTERVAL_MINUTES, min(SCREEN_AWARENESS_MAX_INTERVAL_MINUTES, minutes))


def clamp_screen_awareness_screenshot_width(value) -> int:
    try:
        width = int(value)
    except (TypeError, ValueError):
        width = 1920
    return max(640, min(1920, width))


def normalize_screen_awareness_model_mode(value) -> str:
    mode = str(value or SCREEN_AWARENESS_MODEL_MODE_MAIN).strip().lower()
    if mode == SCREEN_AWARENESS_MODEL_MODE_AUX:
        return SCREEN_AWARENESS_MODEL_MODE_AUX
    return SCREEN_AWARENESS_MODEL_MODE_MAIN


def screen_awareness_aux_config(config) -> tuple[str, str, str]:
    api_url = str(config.get("llm_aux_api_url", "") or "").strip()
    api_key = str(config.get("llm_aux_api_key", "") or "").strip()
    model_id = str(config.get("llm_aux_model_id", "") or "").strip()
    if not api_url:
        api_url = str(config.get("llm_api_url", "") or "").strip()
    if not api_key:
        api_key = str(config.get("llm_api_key", "") or "").strip()
    return api_url, api_key, model_id


class ScreenAwarenessVisionWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = dict(config or {})

    def run(self):
        try:
            max_width = clamp_screen_awareness_screenshot_width(
                self._config.get("screen_awareness_max_screenshot_width", 1920)
            )
            data_url, width, height, desktop_width, desktop_height = capture_screenshot_data_url(max_width)
            metrics = {
                "image_width": width,
                "image_height": height,
                "desktop_width": desktop_width,
                "desktop_height": desktop_height,
            }
            mode = normalize_screen_awareness_model_mode(
                self._config.get("screen_awareness_model_mode", SCREEN_AWARENESS_MODEL_MODE_MAIN)
            )
            result = {
                "mode": mode,
                "metrics": metrics,
                "screen_observation": "",
                "screen_image_data_url": "",
            }
            if mode == SCREEN_AWARENESS_MODEL_MODE_MAIN:
                result["screen_image_data_url"] = data_url
            else:
                api_url, api_key, model_id = screen_awareness_aux_config(self._config)
                if not api_url or not api_key or not model_id:
                    raise RuntimeError(_tr(
                        "ScreenAwareness.aux_not_configured",
                        default="屏幕感知已选择辅助模型，但辅助模型未配置完整。",
                    ))
                prompt = _tr(
                    "ScreenAwareness.vision_prompt",
                    default=(
                        "请观察这张桌面截图，客观概括用户当前可能正在做什么。"
                        "重点包括应用/网页/代码/错误信息/文档/游戏/聊天等可见线索。"
                        "不要输出隐私敏感细节，不要逐字复述窗口标题或聊天内容；"
                        "不要角色扮演，不要建议用户做事，只输出 2 到 5 条紧凑观察，用用户当前界面语言回复。"
                    ),
                )
                summary = analyze_images_with_aux_model(
                    api_url,
                    api_key,
                    model_id,
                    [data_url],
                    prompt,
                    None,
                    timeout=120,
                )
                result["screen_observation"] = str(summary or "").strip()
                if not result["screen_observation"]:
                    raise RuntimeError(_tr(
                        "ScreenAwareness.empty_observation",
                        default="辅助模型没有返回屏幕观察结果。",
                    ))
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
