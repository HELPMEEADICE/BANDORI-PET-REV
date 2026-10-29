from pathlib import Path


def _source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")




def test_config_loading_does_not_import_vision_or_outfit_workers():
    source = _source("bandori_core/config_manager.py")
    eager_imports = source.split("CONFIG_FILE_LOCK_TIMEOUT_SECONDS", 1)[0]

    assert "from bandori_platform.screen_awareness import" not in eager_imports
    assert "from bandori_models.outfit_description import" not in eager_imports




def test_visible_process_starts_before_background_services():
    source = _source("main.py")
    startup = source.split("    init_tray()", 1)[1].split(
        "    def _handle_signal", 1
    )[0]

    assert "launch_pet(persist_config=False, rescan_models=False)" in startup
    assert source.index("launch_pet(persist_config=False, rescan_models=False)") < source.index(
        "QTimer.singleShot(750, init_ai_status_server)"
    )


def test_pet_process_defers_mcp_network_import_until_shutdown():
    source = _source("pet_process.py")
    eager_imports = source.split("def _parse_args", 1)[0]

    assert "from bandori_tools.mcp_bridge import close_mcp_clients" not in eager_imports
    assert "mcp_bridge" not in source


def test_non_fluent_processes_skip_the_fluent_theme_graph():
    main_source = _source("main.py")
    pet_source = _source("pet_process.py")

    assert 'apply_app_theme(cfg.get("dark_theme", False), include_fluent=False)' in main_source
    assert "app_theme" not in pet_source


def test_controller_passes_the_known_model_format_to_pet_processes():
    source = _source("main.py")

    assert "native_program_and_args(" in source
    assert '"pet_process.py"' not in source




def test_controller_limits_duplicated_qt_pixmap_cache():
    source = _source("main.py")

    assert "QPixmapCache.setCacheLimit(1024)" in source
