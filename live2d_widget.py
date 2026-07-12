from live2d_widget_base import (
    DIRECT_RENDER_PIPELINE,
    DEFAULT_HIT_ALPHA_THRESHOLD,
    DEFAULT_LIP_SYNC_MAX_OPEN,
    Live2DWidgetBase,
)
from live2d_widget_moc3 import (
    DEFAULT_MOC3_RENDER_SCALE,
    Live2DSSAAFramebuffer,
    MOC3_RENDER_PIPELINE,
    MOC3_BALANCED_SSAA_SCALE,
)

__all__ = [
    "DEFAULT_HIT_ALPHA_THRESHOLD",
    "DEFAULT_LIP_SYNC_MAX_OPEN",
    "DEFAULT_MOC3_RENDER_SCALE",
    "Live2DSSAAFramebuffer",
    "Live2DWidget",
    "MOC3_BALANCED_SSAA_SCALE",
    "render_pipeline_for_model",
]


def render_pipeline_for_model(model):
    if getattr(model, "renderer_format", "") == "moc3":
        return MOC3_RENDER_PIPELINE
    return DIRECT_RENDER_PIPELINE


class Live2DWidget(Live2DWidgetBase):
    def _render_pipeline_for_model(self, model):
        return render_pipeline_for_model(model)
