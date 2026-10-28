from unittest.mock import patch


def test_macos_fluent_font_families_prefer_native_fonts():
    from bandori_core.app_theme import platform_ui_font_families

    with patch("bandori_core.app_theme.sys.platform", "darwin"):
        families = platform_ui_font_families()

    assert families[0] == "PingFang SC"
    assert "Segoe UI" not in families
