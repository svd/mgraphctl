"""Every version string in the repo must agree (spec §2.3, VERSIONING.md).

Six surfaces carry the version: the package (`mgraphctl.__version__` and the installed
metadata), the two plugin manifests, the Claude marketplace entry, and the skill's frontmatter.
`claude plugin tag` checks the two manifests against each other; this test ties the rest to them.
"""

import importlib.metadata
import json
import re
from pathlib import Path

import mgraphctl

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
SKILL_MD = ROOT / "skills" / "mgraphctl" / "SKILL.md"

# Bare X.Y.Z only: no -SNAPSHOT, no .devN. The tag is derived from this string by
# `claude plugin tag`, and a suffix would break the PEP 440 / semver agreement below.
RELEASE_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def test_versions_agree():
    assert mgraphctl.__version__ == importlib.metadata.version("mgraphctl")
    assert json.loads(PLUGIN_JSON.read_text())["version"] == mgraphctl.__version__
    codex_plugin = ROOT / ".codex-plugin" / "plugin.json"
    assert json.loads(codex_plugin.read_text())["version"] == mgraphctl.__version__


def test_marketplace_entry_agrees():
    marketplace = json.loads(MARKETPLACE_JSON.read_text())
    entries = [p for p in marketplace["plugins"] if p["name"] == "mgraphctl"]
    assert len(entries) == 1
    assert entries[0]["version"] == mgraphctl.__version__


def test_skill_frontmatter_agrees():
    _, _, rest = SKILL_MD.read_text().partition("---\n")
    frontmatter, _, _ = rest.partition("\n---\n")
    match = re.search(r'^\s+version:\s*"?([^"\n]+)"?\s*$', frontmatter, re.M)
    assert match, "SKILL.md frontmatter has no metadata.version"
    assert match.group(1) == mgraphctl.__version__


def test_version_is_a_bare_release_string():
    assert RELEASE_VERSION.match(mgraphctl.__version__), mgraphctl.__version__
