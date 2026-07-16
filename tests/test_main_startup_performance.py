from pathlib import Path


def _source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_main_startup_does_not_import_renderer_or_optional_services_eagerly():
    source = _source("main.py")
    eager_imports = source.split("class AiEventBridge", 1)[0]

    assert "from live2d_widget import Live2DWidget" not in eager_imports
    assert "from alarm_manager import ReminderScheduler" not in eager_imports
    assert "from database_manager import DatabaseManager" not in eager_imports
    assert "from napcat_adapter import NapcatClient" not in eager_imports


def test_config_loading_does_not_import_vision_or_outfit_workers():
    source = _source("config_manager.py")
    eager_imports = source.split("CONFIG_FILE_LOCK_TIMEOUT_SECONDS", 1)[0]

    assert "from screen_awareness import" not in eager_imports
    assert "from outfit_description import" not in eager_imports


def test_pet_window_defers_outfit_worker_until_recognition_runs():
    source = _source("pet_window.py")
    eager_imports = source.split("_OUTFIT_DESCRIPTION_AUTH_FAILURE_MARKERS", 1)[0]

    assert "OutfitDescriptionWorker" not in eager_imports
    assert "image_to_data_url" not in eager_imports
    assert "from network_worker import" not in eager_imports


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

    assert "from mcp_bridge import close_mcp_clients" not in eager_imports
    assert "def close_mcp_clients_on_shutdown():" in source


def test_non_fluent_processes_skip_the_fluent_theme_graph():
    main_source = _source("main.py")
    pet_source = _source("pet_process.py")

    assert 'apply_app_theme(cfg.get("dark_theme", False), include_fluent=False)' in main_source
    assert 'apply_app_theme(cfg.get("dark_theme", False), include_fluent=False)' in pet_source


def test_controller_passes_the_known_model_format_to_pet_processes():
    source = _source("main.py")

    assert 'model_format = mgr.get_model_format(' in source
    assert '"--model-format", model_format' in source


def test_pet_adapter_defers_luajit_and_imports_only_the_selected_format():
    adapter_source = _source("live2d_lua_adapter.py")
    eager_imports = adapter_source.split("def _model_manifest_format", 1)[0]
    pet_source = _source("pet_process.py")

    assert "from live2d_lua_adapter_base import" not in eager_imports
    assert "from live2d_lua_adapter_moc import" not in eager_imports
    assert "from live2d_lua_adapter_moc3 import" not in eager_imports
    assert "live2d_for_format(args.model_format)" in pet_source
    assert "QPixmapCache.setCacheLimit(2048)" in pet_source
