"""CLI tests for the `mcp` noun (MCP spec §8)."""

import json
from pathlib import Path

import pytest

from helpers import covers
from mgraphctl.mcp import discover


@covers("mcp tools")
def test_mcp_tools_lists_the_default_capabilities(invoke):
    result = invoke("mcp", "tools", "--json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    capabilities = {item["capability"] for item in doc["items"]}
    assert capabilities == set(discover.DEFAULT)
    names = {item["name"] for item in doc["items"]}
    assert "mail_list" in names and "me" in names


@covers("mcp tools")
def test_mcp_tools_is_read_only_until_allow_write(invoke):
    read_only = json.loads(invoke("mcp", "tools", "--json").stdout)["items"]
    assert not any(item["write"] for item in read_only)
    with_writes = json.loads(invoke("mcp", "tools", "--allow-write", "--json").stdout)["items"]
    assert any(item["write"] for item in with_writes)
    assert len(with_writes) > len(read_only)


@covers("mcp tools")
def test_mcp_tools_narrows_to_the_named_capabilities(invoke):
    doc = json.loads(invoke("mcp", "tools", "--capabilities", "mail", "--json").stdout)
    assert {item["capability"] for item in doc["items"]} == {"mail"}
    # Naming a group is how the operator keeps the client's context bounded.
    everything = json.loads(invoke("mcp", "tools", "--capabilities", "all", "--json").stdout)
    assert everything["count"] > doc["count"]


@covers("mcp tools")
def test_mcp_tools_rejects_an_unknown_capability(invoke):
    result = invoke("mcp", "tools", "--capabilities", "maildrop")
    assert result.exit_code == 2
    assert "maildrop" in result.stderr


@covers("mcp tools")
def test_mcp_tools_prints_a_table_without_json(invoke):
    result = invoke("mcp", "tools", "--capabilities", "core")
    assert result.exit_code == 0, result.stderr
    assert "Tool" in result.stdout and "me" in result.stdout


@covers("mcp serve")
def test_mcp_serve_rejects_an_unknown_transport(invoke):
    result = invoke("mcp", "serve", "--transport", "carrier-pigeon")
    assert result.exit_code == 2
    assert "stdio" in result.stderr


@covers("mcp serve")
@pytest.mark.parametrize("host", ["0.0.0.0", "10.0.0.5"])
def test_mcp_serve_refuses_to_bind_off_loopback(invoke, host):
    """One identity, no way to tell callers apart: a reachable port is the user's mailbox."""
    result = invoke("mcp", "serve", "--transport", "http", "--host", host)
    assert result.exit_code == 2
    assert "loopback" in result.stderr


SHIM = Path(__file__).resolve().parents[1] / "mgraphctl"


def shim_argv(tmp_path, *args: str) -> list[str]:
    """The `uv run` line the shim would exec, with a stub `uv` standing in for the real one."""
    import os
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    stub = bin_dir / "uv"
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    stub.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "UV_PROJECT_ENVIRONMENT": str(tmp_path / "venv"),
    }
    done = subprocess.run(
        ["bash", str(SHIM), *args], capture_output=True, text=True, env=env, check=True
    )
    return done.stdout.split()


@covers("mcp serve")
def test_the_shim_asks_for_the_mcp_extra_only_for_the_mcp_noun(tmp_path):
    """`--no-dev` hides the SDK, so without this the plugin's own `mcp serve` cannot start."""
    assert "--extra" not in shim_argv(tmp_path / "a", "mail", "list")
    argv = shim_argv(tmp_path / "b", "mcp", "serve")
    assert argv[argv.index("--extra") + 1] == "mcp"
    # The extra is an option to `uv run`, so it has to precede the command being run.
    assert argv.index("--extra") < argv.index("mgraphctl")
    # Root flags come before the noun, and `--tz` takes a value that must not be read as one.
    assert "--extra" in shim_argv(tmp_path / "c", "-dd", "mcp", "serve")
    assert "--extra" in shim_argv(tmp_path / "d", "--tz", "UTC", "mcp", "tools")
    assert "--extra" not in shim_argv(tmp_path / "e", "--tz", "mcp", "mail", "list")
    assert "--extra" not in shim_argv(tmp_path / "f", "--version")


def _capture_settings(monkeypatch):
    """Start `mcp serve` far enough to build its settings, then stop before it blocks."""
    from mgraphctl.commands import mcp_cmd
    from mgraphctl.mcp import server

    # `serve` moves the process into its output directory; register the undo.
    monkeypatch.chdir(Path.cwd())
    captured = {}
    real_build = server.build

    def build(settings, app=None):
        captured["settings"] = settings
        return real_build(settings, app)

    async def no_serve(built):
        return None

    monkeypatch.setattr(server, "build", build)
    monkeypatch.setattr(mcp_cmd, "_serve_stdio", no_serve)
    return captured


@covers("mcp serve")
def test_mcp_serve_carries_the_root_flags_into_every_tool_call(invoke, monkeypatch, tmp_path):
    """`-dd` has to reach the client the server opens, or request logging is silently dead."""
    captured = _capture_settings(monkeypatch)
    result = invoke("-dd", "--tz", "Europe/Warsaw", "mcp", "serve", "--output-dir", str(tmp_path))
    assert result.exit_code == 0, result.stderr
    assert captured["settings"].env.debug == 2
    assert captured["settings"].env.tz == "Europe/Warsaw"


@covers("mcp serve")
def test_mcp_serve_falls_back_to_the_config_when_no_flag_is_given(invoke, monkeypatch, tmp_path):
    """The root callback folds config into `Globals`, so the env var still reaches the server."""
    monkeypatch.setenv("MGRAPHCTL_DEBUG", "1")
    captured = _capture_settings(monkeypatch)
    assert invoke("mcp", "serve", "--output-dir", str(tmp_path)).exit_code == 0
    assert captured["settings"].env.debug == 1


@covers("mcp serve")
def test_mcp_serve_says_how_to_install_the_extra_when_it_is_missing(invoke, monkeypatch):
    """The SDK is an optional dependency; without it the verb must say what to install."""
    import sys

    import mgraphctl.mcp

    for name in list(sys.modules):
        if name == "mcp" or name.startswith(("mcp.", "mgraphctl.mcp.server")):
            monkeypatch.delitem(sys.modules, name)
    # `from mgraphctl.mcp import server` would find the attribute a previous import left on the
    # package and never re-import, so the attribute has to go as well.
    monkeypatch.delattr(mgraphctl.mcp, "server", raising=False)
    # A None entry makes `import mcp...` raise ImportError, as an uninstalled package would.
    monkeypatch.setitem(sys.modules, "mcp", None)
    result = invoke("mcp", "serve")
    assert result.exit_code == 2
    assert "mgraphctl[mcp]" in result.stderr
