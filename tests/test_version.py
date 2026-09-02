"""The three version strings must agree (spec §2.3)."""

import importlib.metadata
import json
from pathlib import Path

import mgraphctl

PLUGIN_JSON = Path(__file__).resolve().parents[1] / ".claude-plugin" / "plugin.json"


def test_versions_agree():
    assert mgraphctl.__version__ == importlib.metadata.version("mgraphctl")
    assert json.loads(PLUGIN_JSON.read_text())["version"] == mgraphctl.__version__
