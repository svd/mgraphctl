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


def test_retry_and_timeout_knobs_default_and_parse(monkeypatch):
    s = config.settings()
    assert s.retries == config.RETRIES_DEFAULT and s.max_attempts == 5
    assert s.timeout_ms == config.TIMEOUT_MS_DEFAULT
    assert s.retry_base_ms == config.RETRY_BASE_MS_DEFAULT

    monkeypatch.setenv("MGRAPHCTL_RETRIES", "0")
    monkeypatch.setenv("MGRAPHCTL_TIMEOUT_MS", "5000")
    monkeypatch.setenv("MGRAPHCTL_RETRY_BASE_MS", "50")
    s = config.settings()
    assert s.retries == 0 and s.max_attempts == 1
    assert s.timeout_ms == 5000 and s.retry_base_ms == 50


def test_retry_and_timeout_knobs_fall_back_on_junk(monkeypatch):
    """An unusable value takes the default rather than crashing a data command."""
    for bad in ("", "  ", "abc", "-1", "1.5", "1e3"):
        monkeypatch.setenv("MGRAPHCTL_RETRIES", bad)
        monkeypatch.setenv("MGRAPHCTL_TIMEOUT_MS", bad)
        monkeypatch.setenv("MGRAPHCTL_RETRY_BASE_MS", bad)
        s = config.settings()
        assert s.retries == config.RETRIES_DEFAULT, bad
        assert s.timeout_ms == config.TIMEOUT_MS_DEFAULT, bad
        assert s.retry_base_ms == config.RETRY_BASE_MS_DEFAULT, bad


def test_shim_path_points_at_scripts_dir():
    assert config.shim_path().endswith("/mgraphctl")
