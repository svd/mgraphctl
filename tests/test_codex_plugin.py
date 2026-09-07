"""The Codex marketplace must distribute the skill and its complete CLI project."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_marketplace_contains_a_self_contained_plugin():
    marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
    entries = [entry for entry in marketplace["plugins"] if entry["name"] == "mgraphctl"]
    assert len(entries) == 1
    source = entries[0]["source"]
    assert source["source"] == "local"
    plugin_root = (ROOT / source["path"]).resolve()
    assert plugin_root == ROOT
    manifest = json.loads((plugin_root / ".codex-plugin/plugin.json").read_text())
    assert manifest["name"] == entries[0]["name"]
    skill = plugin_root / manifest["skills"] / "mgraphctl/SKILL.md"
    assert skill.is_file()
    # Codex resolves the executable two directories above the loaded skill directory.
    assert skill.parent.parent.parent / "mgraphctl" == plugin_root / "mgraphctl"
    for path in ("mgraphctl", "pyproject.toml", "uv.lock", "src/mgraphctl/cli.py"):
        assert (plugin_root / path).is_file(), path
