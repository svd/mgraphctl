"""Fixtures shared by every CLI test (spec §11)."""

import pytest
import respx
from typer.testing import CliRunner

from mgraphctl import auth, config

ALL_SCOPES = [
    s
    for s in dict.fromkeys(config.DEFAULT_SCOPES + config.EXTENDED_EXTRA + config.ON_DEMAND_SCOPES)
    if s not in config.RESERVED_SCOPES
]


@pytest.fixture(autouse=True)
def fake_auth(request, monkeypatch, tmp_path):
    monkeypatch.setenv("MGRAPHCTL_TZ", "Europe/Warsaw")
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("MGRAPHCTL_FIXTURE_DIR", raising=False)
    monkeypatch.delenv("MGRAPHCTL_RECORD", raising=False)
    monkeypatch.delenv("MGRAPHCTL_DEBUG", raising=False)
    monkeypatch.delenv("MGRAPHCTL_SCOPES", raising=False)
    monkeypatch.setenv("MGRAPHCTL_TOKEN_CACHE", str(tmp_path / "token_cache.json"))
    if request.node.get_closest_marker("real_auth"):
        return
    marker = request.node.get_closest_marker("scopes")
    scopes = list(marker.args[0]) if marker else sorted(set(ALL_SCOPES) | auth.DECLARED_SCOPES)
    token = auth.synthetic_token(scopes)
    monkeypatch.setattr(auth, "get_access_token", lambda force_refresh=False: token)
    monkeypatch.setattr(auth, "cached_access_token", lambda: token)
    monkeypatch.setattr(auth, "save_cache", lambda: None)


@pytest.fixture
def graph():
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture(scope="session")
def app():
    from mgraphctl.cli import build_app

    return build_app()


@pytest.fixture
def invoke(app):
    runner = CliRunner()

    def _invoke(*args: str, input: str | None = None):
        return runner.invoke(app, list(args), input=input, catch_exceptions=False)

    return _invoke
