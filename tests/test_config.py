from pathlib import Path

from mgraphctl import config


def test_scope_sets_have_spec_sizes():
    assert len(config.DEFAULT_SCOPES) == 23 and "offline_access" in config.DEFAULT_SCOPES
    assert len(config.EXTENDED_EXTRA) == 10 and len(config.EXTENDED_SCOPES) == 33


def test_msal_scopes_strips_reserved():
    assert "offline_access" not in config.msal_scopes(config.DEFAULT_SCOPES)


def test_resolve_scopes():
    assert config.resolve_scopes(None) == ("default", config.DEFAULT_SCOPES)
    assert config.resolve_scopes("extended") == ("extended", config.EXTENDED_SCOPES)
    name, scopes = config.resolve_scopes("User.Read, Mail.Read Files.Read")
    assert (name, scopes) == ("custom", ["User.Read", "Mail.Read", "Files.Read"])
    name, scopes = config.resolve_scopes("default", extra=["User.Read.All"])
    assert name == "custom" and scopes[-1] == "User.Read.All" and scopes.count("User.Read") == 1


def test_settings_reads_env_each_call(monkeypatch, tmp_path):
    monkeypatch.setenv("MGRAPHCTL_TENANT_ID", "contoso.example")
    monkeypatch.setenv("MGRAPHCTL_TOKEN_CACHE", str(tmp_path / "c.json"))
    monkeypatch.setenv("MGRAPHCTL_DEBUG", "1")
    s = config.settings()
    assert s.authority == "https://login.microsoftonline.com/contoso.example"
    assert (
        s.client_id == config.CLIENT_ID_DEFAULT
        and s.token_cache == tmp_path / "c.json"
        and s.debug == 1
    )
    assert s.state_dir == Path.home() / ".mgraphctl" and s.fixture_dir is None
    monkeypatch.setenv("MGRAPHCTL_FIXTURE_DIR", str(tmp_path))
    monkeypatch.setenv("MGRAPHCTL_RECORD", "1")
    assert config.settings().fixture_dir == tmp_path and config.settings().record is True


def test_shim_path_points_at_scripts_dir():
    assert config.shim_path().endswith("/mgraphctl")
