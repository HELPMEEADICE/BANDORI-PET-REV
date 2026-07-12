from live2d_widget_base import Live2DWidgetBase


class Live2DWidgetMOC(Live2DWidgetBase):

    def _create_ssaa_fbo(self):
        return None

    def _default_moc3_render_scale(self) -> float:
        return 1.0

    def _moc3_ssaa_scale(self) -> int:
        return 1
