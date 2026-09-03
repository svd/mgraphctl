"""Every registered verb is covered by a test and carries --json (spec §11)."""

import helpers
import typer.main


def walk(app):
    group = typer.main.get_group(app)
    out = {}

    def rec(cmd, prefix):
        for name, sub in cmd.commands.items():
            full = f"{prefix} {name}".strip()
            if hasattr(sub, "commands"):
                rec(sub, full)
            else:
                out[full] = sub

    rec(group, "")
    return out


def test_every_verb_is_covered(app):
    missing = sorted(v for v in walk(app) if v not in helpers.VERBS_TESTED)
    assert not missing, f"verbs without a @covers test: {missing}"


def test_every_verb_has_json_flag(app):
    for verb, cmd in walk(app).items():
        assert any("--json" in p.opts for p in cmd.params), verb
