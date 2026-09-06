"""Root app behaviour (spec §6.1, §6.5)."""

import json

import httpx
import pytest

from helpers import GRAPH
from mgraphctl import __version__


def test_version_flag(invoke):
    r = invoke("--version")
    assert r.exit_code == 0 and r.stdout == f"mgraphctl {__version__}\n"


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
    # Our own request lines are the ones carrying the attempt count; httpx logs the same
    # request at INFO, and the level prefix is now the record's real level, not a fixed "DEBUG".
    request_lines = [ln for ln in r.stderr.splitlines() if "/v1.0/me" in ln and "[attempt " in ln]
    assert request_lines and all(ln.startswith("DEBUG ") for ln in request_lines)
    assert any(ln.startswith("INFO ") for ln in r.stderr.splitlines())


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


def test_local_io_error_is_an_error_block_not_a_traceback(invoke, graph):
    r = invoke("api", "POST", "/x", "--body", "@/nonexistent.json")
    assert r.exit_code == 1 and r.stdout == "" and graph.calls.call_count == 0
    assert r.stderr.startswith("error[IO]: ")
    assert "/nonexistent.json" in r.stderr and "Traceback" not in r.stderr


def test_unexpected_exception_is_an_error_block_and_a_traceback_only_with_debug(
    invoke, monkeypatch
):
    from mgraphctl.graph import users

    def boom(client, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(users, "get_me", boom)
    r = invoke("me")
    assert r.exit_code == 1 and r.stdout == ""
    assert r.stderr.startswith("error[INTERNAL]: RuntimeError: kaboom\n")
    assert "Traceback" not in r.stderr
    r = invoke("--debug", "me")
    assert r.exit_code == 1 and r.stderr.startswith("error[INTERNAL]: RuntimeError: kaboom\n")
    assert "Traceback (most recent call last)" in r.stderr


def test_page_bounds_defaults_and_conflict():
    from mgraphctl.cli import page_bounds
    from mgraphctl.errors import UsageError

    assert page_bounds(None, False, default=10) == (10, False)
    assert page_bounds(5, False, default=10) == (5, False)
    assert page_bounds(None, True, default=10) == (10, True)
    with pytest.raises(UsageError) as excinfo:
        page_bounds(5, True, default=10)
    assert excinfo.value.exit_code == 2


@pytest.mark.scopes(["User.Read"])
def test_gate_checks_the_token_against_the_scopes_it_is_given():
    from mgraphctl.cli import gate
    from mgraphctl.errors import AuthError

    assert gate([]) is None and gate(["User.Read"]) is None
    with pytest.raises(AuthError) as excinfo:
        gate(["Mail.ReadWrite"])
    assert excinfo.value.code == "MISSING_SCOPE" and excinfo.value.exit_code == 3


def test_limit_option_rejects_zero():
    import typer
    from typer.testing import CliRunner

    from mgraphctl.cli import LimitOpt

    probe = typer.Typer()

    @probe.command()
    def run(limit: LimitOpt = None) -> None:
        typer.echo(str(limit))

    runner = CliRunner()
    assert runner.invoke(probe, ["--limit", "0"], catch_exceptions=False).exit_code == 2
    ok = runner.invoke(probe, ["--limit", "3"], catch_exceptions=False)
    assert ok.exit_code == 0 and ok.stdout.strip() == "3"


def test_debug_short_option_counts(invoke, graph):
    graph.get(f"{GRAPH}/v1.0/me").mock(return_value=httpx.Response(200, json={"id": "1"}))
    r = invoke("-d", "me", "--json")
    assert r.exit_code == 0, r.stderr
    assert "DEBUG GET https://graph.microsoft.com/v1.0/me" in r.stderr
    # The help text promises `-dd`; at level 2 the response body is logged too.
    r2 = invoke("-dd", "me", "--json")
    assert r2.exit_code == 0, r2.stderr
    assert 'DEBUG body: {"id":"1"}' in r2.stderr
