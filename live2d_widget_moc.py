from live2d_widget_base import DIRECT_RENDER_PIPELINE, Live2DWidgetBase


class Live2DWidgetMOC(Live2DWidgetBase):

    def _render_pipeline_for_model(self, model):
        del model
        return DIRECT_RENDER_PIPELINE
