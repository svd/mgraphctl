"""Every registered verb is documented under reference/commands/, and SKILL.md stays short."""

import re
from pathlib import Path

from test_surface import walk

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "mgraphctl"
SHIM = "${CLAUDE_PLUGIN_ROOT}/mgraphctl"
COMMANDS = SKILL_DIR / "reference" / "commands"
INDEX = SKILL_DIR / "reference" / "commands.md"
# Every verb gets its own `### `noun verb ARGS`` heading; ARGS are upper case, so they stop the
# match and `presence set available` still counts as documentation for `presence set`.
HEADING = re.compile(r"^### `([a-z0-9-]+(?: [a-z0-9-]+)*)", re.M)
# The index links each noun file once, as `[`commands/<slug>.md`](commands/<slug>.md)`.
INDEX_LINK = re.compile(r"\]\(commands/([a-z0-9-]+\.md)\)")


def test_every_verb_has_a_command_file_heading(app):
    headings = [h for path in COMMANDS.glob("*.md") for h in HEADING.findall(path.read_text())]
    missing = [
        verb
        for verb in sorted(walk(app))
        if not any(h == verb or h.startswith(f"{verb} ") for h in headings)
    ]
    assert not missing, f"verbs missing from reference/commands/: {missing}"


def test_the_index_links_every_command_file():
    """A file nobody links to is a file nobody reads; a dead link sends the skill nowhere."""
    linked = set(INDEX_LINK.findall(INDEX.read_text()))
    on_disk = {path.name for path in COMMANDS.glob("*.md")}
    assert linked == on_disk


def test_command_files_link_back_to_the_shared_conventions():
    """Paging, argument resolution and exit codes live only in the index."""
    for path in sorted(COMMANDS.glob("*.md")):
        assert "(../commands.md)" in path.read_text(), path.name


def test_skill_md_is_short_and_names_the_shim():
    lines = (SKILL_DIR / "SKILL.md").read_text().splitlines()
    assert len(lines) <= 400
    assert sum(SHIM in line for line in lines) >= 20


def test_skill_md_frontmatter_allows_the_shim():
    _, _, rest = (SKILL_DIR / "SKILL.md").read_text().partition("---\n")
    frontmatter, separator, _ = rest.partition("\n---\n")
    assert separator, "SKILL.md has no YAML frontmatter"
    assert f"allowed-tools: Bash({SHIM} *)" in frontmatter


# --- Frontmatter rules from the Agent Skills documentation --------------------------------
#
# `name`: 1-64 chars, lower-case letters, digits and hyphens, no "anthropic"/"claude".
# `description`: 1-1024 chars, no XML-shaped tags. Nothing here is inferred beyond those rules.

NAME_RE = re.compile(r"^[a-z0-9-]+$")
XML_TAG_RE = re.compile(r"</?[A-Za-z_:][A-Za-z0-9._:-]*(?:\s[^<>]*)?/?>")


def _frontmatter() -> dict[str, str]:
    """Parse the two scalars the rules care about. `description: >` folds indented lines."""
    _, _, rest = (SKILL_DIR / "SKILL.md").read_text().partition("---\n")
    text, separator, _ = rest.partition("\n---\n")
    assert separator, "SKILL.md has no YAML frontmatter"
    out: dict[str, str] = {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        key, sep, value = line.partition(":")
        if not sep or line.startswith((" ", "\t")):
            continue
        value = value.strip()
        if value in (">", ">-", "|", "|-"):
            block = []
            for cont in lines[i + 1 :]:
                if cont.startswith((" ", "\t")):
                    block.append(cont.strip())
                else:
                    break
            value = " ".join(block)
        out[key.strip()] = value.strip('"')
    return out


def test_skill_name_follows_the_rules():
    name = _frontmatter()["name"]
    assert 1 <= len(name) <= 64
    assert NAME_RE.match(name), name
    assert "anthropic" not in name and "claude" not in name
    assert name == SKILL_DIR.name


def test_skill_description_follows_the_rules():
    description = _frontmatter()["description"]
    assert 1 <= len(description) <= 1024, len(description)
    assert not XML_TAG_RE.search(description), "description contains an XML-shaped tag"
