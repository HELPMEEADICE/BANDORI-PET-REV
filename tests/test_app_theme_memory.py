from types import SimpleNamespace
from unittest.mock import Mock, patch

import app_theme


def test_custom_qt_process_can_skip_fluent_theme_import():
    with (
        patch.object(app_theme, "import_qfluentwidgets") as import_fluent,
        patch.object(app_theme, "apply_application_font") as apply_font,
    ):
        app_theme.apply_app_theme(False, include_fluent=False)

    import_fluent.assert_not_called()
    apply_font.assert_called_once()


def test_fluent_windows_keep_existing_theme_behavior():
    fluent = SimpleNamespace(
        Theme=SimpleNamespace(DARK="dark", LIGHT="light"),
        setTheme=Mock(),
        setThemeColor=Mock(),
    )
    with (
        patch.object(app_theme, "import_qfluentwidgets", return_value=fluent),
        patch.object(app_theme, "assert_pyside6_fluent_widgets"),
        patch.object(app_theme, "apply_application_font"),
    ):
        app_theme.apply_app_theme(True)

    fluent.setTheme.assert_called_once_with("dark")
    fluent.setThemeColor.assert_called_once_with(app_theme.BANDORI_PRIMARY_DARK)
