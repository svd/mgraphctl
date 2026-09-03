"""Root app behaviour (spec §6.1, §6.5)."""

import json

import httpx
import pytest

from helpers import GRAPH


def test_version_flag(invoke):
    r = invoke("--version")
    assert r.exit_code == 0 and r.stdout == "mgraphctl 0.1.0\n"


def test_no_args_prints_help_exit_0(invoke):
    r = invoke()
    assert r.exit_code == 0 and "Usage:" in r.stdout and "me" in r.stdout


def test_noun_without_verb_prints_help_exit_0():
    # Real noun groups arrive in Phase 1 (each group's tests assert `invoke("<noun>")` → help,
    # exit 0); here an ad-hoc group proves make_noun_app's callback path.
    from typer.testing import CliRunner

    from mgraphctl.cli import build_app, make_noun_app

    root = build_app()
    root.add_typer(make_noun_app("Probe group."), name="probe")
    r = CliRunner().invoke(root, ["probe"], catch_exceptions=False)
    assert r.exit_code == 0 and "Usage:" in r.stdout


def test_tz_propagates_to_prefer(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/me").mock(return_value=httpx.Response(200, json={"id": "1"}))
    assert (
        invoke(
            "--tz", "Asia/Tokyo", "api", "GET", "/me", "--query", "$select=id", "--outlook-tz"
        ).exit_code
        == 0
    )
    assert route.calls.last.request.headers["Prefer"] == 'outlook.timezone="Asia/Tokyo"'


def test_bad_tz_is_usage_error(invoke):
    r = invoke("--tz", "Mars/Olympus", "me")
    assert r.exit_code == 2 and r.stderr.startswith(
        "error[USAGE]: unknown time zone 'Mars/Olympus'"
    )


def test_beta_switches_base(invoke, graph):
    route = graph.get(f"{GRAPH}/beta/me").mock(return_value=httpx.Response(200, json={"id": "1"}))
    assert invoke("--beta", "me", "--json").exit_code == 0 and route.called


def test_errors_never_on_stdout_and_json_never_on_stderr(invoke, graph):
    graph.get(f"{GRAPH}/v1.0/me").mock(
        return_value=httpx.Response(404, json={"error": {"code": "NotFound", "message": "x"}})
    )
    r = invoke("me", "--json")
    assert r.exit_code == 4 and r.stdout == "" and r.stderr.startswith("error[NotFound]: x\n")


def test_unknown_option_is_click_usage_error(invoke):
    assert invoke("me", "--bogus").exit_code == 2


def test_debug_logs_to_stderr(invoke, graph):
    graph.get(f"{GRAPH}/v1.0/me").mock(return_value=httpx.Response(200, json={"id": "1"}))
    r = invoke("--debug", "me", "--json")
    assert r.exit_code == 0 and json.loads(r.stdout)["id"] == "1"
    assert "GET https://graph.microsoft.com/v1.0/me" in r.stderr and "Bearer" not in r.stderr


def test_registry_lists_every_noun():
    from mgraphctl.commands import NOUNS

    assert [n.name for n in NOUNS] == [
        "mail",
        "mailbox",
        "calendar",
        "people",
        "org",
        "groups",
        "teams",
        "chats",
        "presence",
        "meetings",
        "onedrive",
        "sharepoint",
        "onenote",
        "planner",
        "todo",
        "search",
    ]
    assert [n.name for n in NOUNS if n.kind == "command"] == ["search"]


def test_register_all_skips_a_missing_noun_but_not_a_broken_import(monkeypatch):
    import typer

    from mgraphctl import commands

    ghost = commands.Noun("ghost", "mgraphctl.commands.ghost", "Not written yet.")
    monkeypatch.setattr(commands, "NOUNS", [ghost])
    root = typer.Typer()
    commands.register_all(root)
    assert root.registered_groups == [] and root.registered_commands == []

    def explode(name):
        raise ModuleNotFoundError("No module named 'nope'", name="nope")

    monkeypatch.setattr(commands.importlib, "import_module", explode)
    with pytest.raises(ModuleNotFoundError):
        commands.register_all(root)
