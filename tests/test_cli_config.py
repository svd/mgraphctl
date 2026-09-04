"""`config path|show|init`, `--config`, and the file's effect on the root callback and `login`."""

import json
import stat

import httpx
from test_cli_top import default_token

from helpers import GRAPH, covers
from mgraphctl import auth, config


def _me_route(graph):
    return graph.get(f"{GRAPH}/v1.0/me").mock(
        return_value=httpx.Response(
            200, json={"id": "1", "displayName": "Ada", "userPrincipalName": "ada@example.com"}
        )
    )


# --------------------------------------------------------------------------- config path


@covers("config path")
def test_config_path_text_and_json(invoke, tmp_path, config_file):
    expected = str(tmp_path / "config.toml")
    r = invoke("config", "path")
    assert r.exit_code == 0 and r.stdout == expected + "\n"
    assert json.loads(invoke("config", "path", "--json").stdout) == {
        "path": expected,
        "exists": False,
    }
    config_file("")
    assert json.loads(invoke("config", "path", "--json").stdout)["exists"] is True


def test_config_flag_beats_env(invoke, tmp_path, monkeypatch):
    other = tmp_path / "other.toml"
    r = invoke("--config", str(other), "config", "path")
    assert r.stdout == f"{other}\n"


# --------------------------------------------------------------------------- config show


@covers("config show")
def test_config_show_lists_every_key_with_its_source(invoke, config_file, monkeypatch):
    config_file('tenant_id = "contoso.example"\nretries = 7\nbogus = 1\n')
    monkeypatch.setenv("MGRAPHCTL_RETRIES", "2")
    r = invoke("config", "show")
    assert r.exit_code == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == f"Config file: {config.config_path()}"
    assert any(line.split() == ["tenant_id", "contoso.example", "file"] for line in lines)
    assert any(line.split() == ["retries", "2", "env"] for line in lines)
    assert any(line.split() == ["timeout_ms", "60000", "default"] for line in lines)
    assert any(line.split() == ["tz", "Europe/Warsaw", "env"] for line in lines)
    assert lines[-1] == "Unknown keys ignored: bogus"

    out = json.loads(invoke("config", "show", "--json").stdout)
    assert out["path"] == str(config.config_path())
    assert out["settings"]["tenant_id"] == "contoso.example" and out["settings"]["retries"] == 2
    assert out["sources"]["tenant_id"] == "file" and out["sources"]["retries"] == "env"
    assert out["unknownKeys"] == ["bogus"]
    assert set(out["settings"]) == set(config.CONFIG_KEYS)


def test_config_show_flags_win_for_tz_and_debug(invoke, config_file, monkeypatch):
    config_file('tz = "Asia/Tokyo"\ndebug = 1\n')
    monkeypatch.delenv("MGRAPHCTL_TZ")
    out = json.loads(invoke("--tz", "Europe/Paris", "-dd", "config", "show", "--json").stdout)
    assert out["settings"]["tz"] == "Europe/Paris" and out["sources"]["tz"] == "flag"
    assert out["settings"]["debug"] == 2 and out["sources"]["debug"] == "flag"
    out = json.loads(invoke("config", "show", "--json").stdout)
    assert out["settings"]["tz"] == "Asia/Tokyo" and out["sources"]["tz"] == "file"
    assert out["settings"]["debug"] == 1 and out["sources"]["debug"] == "file"


def test_invalid_toml_fails_every_command(invoke, config_file):
    config_file("retries = [\n")
    r = invoke("me")
    assert r.exit_code == 2 and r.stderr.startswith("error[CONFIG]: ")
    assert "config.toml" in r.stderr and "hint:" in r.stderr


# --------------------------------------------------------------------------- config init


@covers("config init")
def test_config_init_writes_template_once(invoke, tmp_path):
    path = tmp_path / "nested" / "config.toml"
    r = invoke("--config", str(path), "config", "init")
    assert r.exit_code == 0, r.stderr
    assert r.stdout == f"Wrote {path}\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    text = path.read_text()
    assert text == config.CONFIG_TEMPLATE
    # The template is valid TOML that names every key, all commented out.
    assert config.load_config_file(path) == {}
    assert all(f"# {key}" in text for key in config.CONFIG_KEYS)

    r = invoke("--config", str(path), "config", "init")
    assert r.exit_code == 2 and r.stderr.startswith("error[USAGE]: ")
    assert "--force" in r.stderr and path.read_text() == text

    path.write_text("retries = 1\n")
    r = invoke("--config", str(path), "config", "init", "--force", "--json")
    assert r.exit_code == 0
    assert json.loads(r.stdout) == {"path": str(path), "overwritten": True}
    assert path.read_text() == config.CONFIG_TEMPLATE


# --------------------------------------------------------------------------- effects


def test_file_tz_reaches_prefer_header(invoke, graph, config_file, monkeypatch):
    config_file('tz = "Asia/Tokyo"\n')
    monkeypatch.delenv("MGRAPHCTL_TZ")
    route = _me_route(graph)
    r = invoke("api", "GET", "/me", "--outlook-tz")
    assert r.exit_code == 0, r.stderr
    assert route.calls.last.request.headers["Prefer"] == 'outlook.timezone="Asia/Tokyo"'


def test_file_debug_turns_on_request_logging(invoke, graph, config_file):
    config_file("debug = 1\n")
    _me_route(graph)
    r = invoke("api", "GET", "/me")
    assert r.exit_code == 0 and "GET " in r.stderr


def test_login_uses_file_scopes(invoke, graph, config_file, monkeypatch):
    config_file('scopes = "extended"\n')
    monkeypatch.setattr(auth, "acquire_silent", lambda **kw: {"access_token": default_token()})
    monkeypatch.setattr(auth, "account_upn", lambda: "ada@example.com")
    calls = []
    monkeypatch.setattr(
        auth,
        "login_interactive",
        lambda scopes, *, force: (calls.append(list(scopes)), {"access_token": default_token()})[1],
    )
    _me_route(graph)
    r = invoke("login")
    assert r.exit_code == 0, r.stderr
    assert calls == [config.msal_scopes(config.EXTENDED_SCOPES)]
    assert "Scopes: extended (33)\n" in r.stdout
    r = invoke("login", "--scopes", "default")
    assert "Already logged in" in r.stdout  # the flag still wins over the file


# --------------------------------------------------------------------------- config set / unset


@covers("config set")
def test_config_set_creates_file_and_reads_back(invoke, tmp_path):
    path = tmp_path / "config.toml"
    r = invoke("config", "set", "tenant_id", "contoso.example")
    assert r.exit_code == 0, r.stderr
    assert r.stdout == f'Set tenant_id = "contoso.example" in {path}\n'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert config.load_config_file(path) == {"tenant_id": "contoso.example"}
    r = invoke("config", "set", "retries", "2", "--json")
    assert json.loads(r.stdout) == {"path": str(path), "key": "retries", "value": 2}
    assert config.load_config_file(path) == {"tenant_id": "contoso.example", "retries": 2}


def test_config_set_replaces_in_place_and_keeps_comments(invoke, tmp_path):
    path = tmp_path / "config.toml"
    invoke("config", "init")
    invoke("config", "set", "tz", "Asia/Tokyo")
    invoke("config", "set", "retries", "0")
    invoke("config", "set", "tz", "Europe/Paris")
    text = path.read_text()
    assert text.startswith("# mgraphctl configuration.")  # the header comment survived
    assert text.count("tz ") == 1 and '\ntz = "Europe/Paris"' in text
    assert "\nretries = 0" in text and "# timeout_ms" in text
    assert config.load_config_file(path) == {"tz": "Europe/Paris", "retries": 0}


def test_config_set_validates(invoke, tmp_path, config_file):
    r = invoke("config", "set", "bogus", "1")
    assert r.exit_code == 2 and "unknown config key 'bogus'" in r.stderr
    assert "tenant_id" in r.stderr  # the valid keys are listed
    r = invoke("config", "set", "retries", "abc")
    assert r.exit_code == 2 and "retries must be a non-negative integer" in r.stderr
    r = invoke("config", "set", "tz", "Mars/Olympus")
    assert r.exit_code == 2 and "unknown time zone" in r.stderr
    assert not (tmp_path / "config.toml").exists()
    config_file("retries = [\n")
    r = invoke("config", "set", "retries", "1")
    assert r.exit_code == 2 and r.stderr.startswith("error[CONFIG]")


@covers("config unset")
def test_config_unset_comments_the_line_out(invoke, tmp_path, config_file):
    path = tmp_path / "config.toml"
    config_file('tenant_id = "a"\nretries = 2\n')
    r = invoke("config", "unset", "retries")
    assert r.exit_code == 0 and r.stdout == f"Unset retries in {path}\n"
    assert path.read_text() == 'tenant_id = "a"\n# retries = 2\n'
    assert config.load_config_file(path) == {"tenant_id": "a"}
    r = invoke("config", "unset", "retries", "--json")
    assert json.loads(r.stdout) == {"path": str(path), "key": "retries", "removed": False}
    assert invoke("config", "unset", "bogus").exit_code == 2
