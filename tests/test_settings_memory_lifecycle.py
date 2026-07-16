from types import SimpleNamespace
from unittest.mock import Mock

from settings_window.settings_window import SettingsWindow


def test_hiding_keep_alive_settings_releases_preview_and_pixmap_cache():
    cache = {"kasumi": object(), "mashiro": object()}
    window = SimpleNamespace(
        _keep_alive_on_close=True,
        _dispose_live2d_preview=Mock(),
        _detail_image_pixmap_cache=cache,
        _launched=True,
        hide=Mock(),
    )
    event = Mock()

    SettingsWindow.closeEvent(window, event)

    window._dispose_live2d_preview.assert_called_once_with()
    assert cache == {}
    assert window._launched is False
    event.ignore.assert_called_once_with()
    window.hide.assert_called_once_with()
