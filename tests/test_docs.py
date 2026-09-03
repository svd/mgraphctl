"""Every registered verb is documented in reference/commands.md, and SKILL.md stays short."""

import re
from pathlib import Path

from test_surface import walk

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "mgraphctl"
SHIM = "${CLAUDE_PLUGIN_ROOT}/mgraphctl"
# Every verb gets its own `### `noun verb ARGS`` heading; ARGS are upper case, so they stop the
# match and `presence set available` still counts as documentation for `presence set`.
HEADING = re.compile(r"^### `([a-z0-9-]+(?: [a-z0-9-]+)*)", re.M)


def test_every_verb_has_a_commands_md_heading(app):
    headings = HEADING.findall((SKILL_DIR / "reference" / "commands.md").read_text())
    missing = [
        verb
        for verb in sorted(walk(app))
        if not any(h == verb or h.startswith(f"{verb} ") for h in headings)
    ]
    assert not missing, f"verbs missing from reference/commands.md: {missing}"


def test_skill_md_is_short_and_names_the_shim():
    lines = (SKILL_DIR / "SKILL.md").read_text().splitlines()
    assert len(lines) <= 400
    assert sum(SHIM in line for line in lines) >= 20


def test_skill_md_frontmatter_allows_the_shim():
    _, _, rest = (SKILL_DIR / "SKILL.md").read_text().partition("---\n")
    frontmatter, separator, _ = rest.partition("\n---\n")
    assert separator, "SKILL.md has no YAML frontmatter"
    assert f"allowed-tools: Bash({SHIM} *)" in frontmatter
