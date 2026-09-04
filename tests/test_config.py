from pathlib import Path

import pytest

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


# --------------------------------------------------------------------------- config file


def test_config_path_defaults_under_state_dir(monkeypatch):
    monkeypatch.delenv("MGRAPHCTL_CONFIG", raising=False)
    assert config.config_path() == Path.home() / ".mgraphctl" / "config.toml"
    monkeypatch.setenv("MGRAPHCTL_CONFIG", "~/elsewhere/x.toml")
    assert config.config_path() == Path.home() / "elsewhere" / "x.toml"


def test_missing_config_file_is_empty():
    assert config.load_config_file() == {}


def test_file_values_land_in_settings(config_file):
    config_file(
        'tenant_id = "contoso.example"\nclient_id = "abc"\nscopes = "extended"\n'
        'tz = "Asia/Tokyo"\ntoken_cache = "~/tc.json"\ndebug = 2\nretries = 1\n'
        "timeout_ms = 5000\nretry_base_ms = 50\n"
    )
    s = config.settings()
    assert s.tenant_id == "contoso.example" and s.client_id == "abc"
    assert s.scope_set == "extended" and s.scope_spec == "extended"
    assert s.debug == 2 and s.retries == 1 and s.timeout_ms == 5000 and s.retry_base_ms == 50


def test_file_token_cache_expands_home(config_file, monkeypatch):
    config_file('token_cache = "~/tc.json"\n')
    monkeypatch.delenv("MGRAPHCTL_TOKEN_CACHE")
    assert config.settings().token_cache == Path.home() / "tc.json"


def test_env_beats_file(config_file, monkeypatch):
    config_file('tenant_id = "file.example"\nretries = 9\ntz = "Asia/Tokyo"\n')
    assert config.settings().tz == "Europe/Warsaw"  # conftest's MGRAPHCTL_TZ wins
    monkeypatch.delenv("MGRAPHCTL_TZ")
    assert config.settings().tz == "Asia/Tokyo"
    monkeypatch.setenv("MGRAPHCTL_TENANT_ID", "env.example")
    monkeypatch.setenv("MGRAPHCTL_RETRIES", "2")
    s = config.settings()
    assert s.tenant_id == "env.example" and s.retries == 2


def test_file_junk_ints_fall_back_and_unknown_keys_are_ignored(config_file):
    config_file('retries = "abc"\ntimeout_ms = -5\ndebug = true\nfoo = 1\n')
    s = config.settings()
    assert s.retries == config.RETRIES_DEFAULT and s.timeout_ms == config.TIMEOUT_MS_DEFAULT
    assert s.debug == 1


def test_file_and_record_knobs_are_env_only(config_file):
    config_file('fixture_dir = "/tmp/x"\nrecord = 1\n')
    s = config.settings()
    assert s.fixture_dir is None and s.record is False


def test_invalid_toml_is_a_config_error(config_file):
    from mgraphctl.errors import UsageError

    config_file("retries = [\n")
    with pytest.raises(UsageError) as exc:
        config.settings()
    assert exc.value.code == "CONFIG" and "config.toml" in exc.value.message


def test_effective_settings_reports_sources(config_file, monkeypatch):
    config_file('tenant_id = "file.example"\nfoo = 1\n')
    monkeypatch.setenv("MGRAPHCTL_RETRIES", "2")
    rows = {key: (value, source) for key, value, source in config.effective_settings()}
    assert rows["tenant_id"] == ("file.example", "file")
    assert rows["retries"] == (2, "env")
    assert rows["timeout_ms"] == (config.TIMEOUT_MS_DEFAULT, "default")
    assert set(rows) == set(config.CONFIG_KEYS)
    assert config.unknown_config_keys() == ["foo"]
