"""Every registered verb is covered by a test and carries --json (spec §11)."""

import importlib
from pathlib import Path

import helpers
from mgraphctl.mcp.discover import walk

# `@covers` fills helpers.VERBS_TESTED at import time, so this file has to pull every CLI test
# module in itself — otherwise `pytest tests/test_surface.py` alone sees an empty registry.
for _path in sorted(Path(__file__).parent.glob("test_cli_*.py")):
    importlib.import_module(_path.stem)


def test_every_verb_is_covered(app):
    missing = sorted(v for v in walk(app) if v not in helpers.VERBS_TESTED)
    assert not missing, f"verbs without a @covers test: {missing}"


def test_every_verb_has_json_flag(app):
    for verb, cmd in walk(app).items():
        assert any("--json" in p.opts for p in cmd.params), verb
