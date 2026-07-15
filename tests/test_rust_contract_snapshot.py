import json
from pathlib import Path

from config_manager import DEFAULTS
from tools.export_rust_contracts import rendered_contracts


def test_rust_config_defaults_snapshot_matches_python_contract():
    path = Path(__file__).resolve().parents[1] / "rust" / "compat" / "config_defaults.json"
    assert json.loads(path.read_text(encoding="utf-8")) == DEFAULTS


def test_all_rust_contract_snapshots_are_current():
    for path, expected in rendered_contracts().items():
        assert path.read_text(encoding="utf-8") == expected
