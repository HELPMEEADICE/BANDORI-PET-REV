from pet_window import PetWindow


class BoundsWidget:
    def __init__(self, bounds=None, union=None, dragging=False):
        self._bounds = dict(bounds or {})
        self._union = union
        self._dragging = dragging

    def hit_area_bounds(self, name):
        return self._bounds.get(name)

    def hit_area_union_bounds(self):
        return self._union


class BoundsHarness:
    _click_motion_area_bounds = PetWindow._click_motion_area_bounds
    _compact_window_target = PetWindow._compact_window_target

    def __init__(self, widget):
        self._live2d_widget = widget
        self._pixel_mode = False
        self._compact_ai_drag_bounds = None
        self._compact_ai_bounds_cache = None

    @staticmethod
    def width():
        return 500


def test_click_motion_bounds_prefer_named_area_then_union():
    head = (10, 90, 20, 100)
    union = (5, 120, 10, 300)
    harness = BoundsHarness(BoundsWidget(bounds={"head": head}, union=union))

    assert harness._click_motion_area_bounds("head") == head
    assert harness._click_motion_area_bounds("face") == union
    assert harness._click_motion_area_bounds("unknown") == union


def test_compact_window_uses_projected_union_and_window_fallback():
    union = (20, 140, 30, 320)
    harness = BoundsHarness(BoundsWidget(union=union))

    assert harness._compact_window_target() == (120, union)

    harness = BoundsHarness(BoundsWidget())
    assert harness._compact_window_target() == (360, None)
