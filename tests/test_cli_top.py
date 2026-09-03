"""login/logout/status/claims/me/version (spec §4.2, §4.3, §4.6, §8.1)."""

import base64
import json
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from helpers import GRAPH, covers, mock_graph
from mgraphctl import auth, config
from mgraphctl.errors import AuthError

WARSAW = ZoneInfo("Europe/Warsaw")


def jwt(claims: dict) -> str:
    def enc(payload: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")

    return f"{enc({'alg': 'none', 'typ': 'JWT'})}.{enc(claims)}."


def default_token(upn: str = "ada@example.com") -> str:
    return auth.synthetic_token(config.msal_scopes(config.DEFAULT_SCOPES), upn=upn)


def cache_path() -> str:
    return str(config.settings().token_cache)


@covers("me")
def test_me_json_and_text(invoke, graph):
    routes = mock_graph(graph, "top/me")
    r = invoke("me", "--json")
    assert r.exit_code == 0 and json.loads(r.stdout)["userPrincipalName"] == "ada@example.com"
    assert routes[0].calls.last.request.url.query.decode() == (
        "$select=id%2CdisplayName%2CuserPrincipalName%2Cmail%2CjobTitle%2Cdepartment"
        "%2CofficeLocation%2CbusinessPhones%2CmobilePhone%2CpreferredLanguage"
    )
    r = invoke("me")
    assert r.exit_code == 0 and "Name    : Ada Example" in r.stdout
    assert "UPN     : ada@example.com" in r.stdout


@covers("me")
def test_me_photo_saves_file(invoke, graph, tmp_path):
    mock_graph(graph, "top/me_photo")
    dest = tmp_path / "p.png"
    r = invoke("me", "--photo", str(dest))
    assert r.exit_code == 0, r.stderr
    assert dest.read_bytes().startswith(b"\x89PNG")
    assert r.stdout == f"Downloaded photo (50 B) to {dest}\n"
    r = invoke("me", "--photo", str(dest), "--json")
    doc = json.loads(r.stdout)
    assert doc == {"path": str(dest), "bytes": 50, "contentType": "image/png"}


@covers("me")
def test_me_photo_404_exit_4(invoke, graph, tmp_path):
    graph.get(f"{GRAPH}/v1.0/me/photo/$value").mock(
        return_value=httpx.Response(404, json={"error": {"code": "ImageNotFound", "message": "x"}})
    )
    r = invoke("me", "--photo", str(tmp_path / "p.png"))
    assert r.exit_code == 4 and r.stdout == ""
    assert r.stderr.startswith("error[ImageNotFound]: x\n")


@covers("status")
def test_status_logged_in(invoke, monkeypatch):
    token = default_token()
    monkeypatch.setattr(auth, "acquire_silent", lambda **kw: {"access_token": token})
    monkeypatch.setattr(auth, "account_upn", lambda: "ada@example.com")
    r = invoke("status")
    assert r.exit_code == 0, r.stderr
    expires = datetime.fromtimestamp(auth.decode_jwt(token)["exp"], WARSAW).isoformat(
        timespec="seconds"
    )
    assert r.stdout == (
        "Logged in as: ada@example.com\n"
        f"Token expires: {expires}\n"
        "Scopes: default (23)\n"
        f"Cache: {cache_path()}\n"
    )


@covers("status")
def test_status_json_logged_in(invoke, monkeypatch):
    token = default_token()
    monkeypatch.setattr(auth, "acquire_silent", lambda **kw: {"access_token": token})
    monkeypatch.setattr(auth, "account_upn", lambda: "ada@example.com")
    r = invoke("status", "--json")
    doc = json.loads(r.stdout)
    assert r.exit_code == 0 and doc["loggedIn"] is True
    assert doc["account"] == "ada@example.com" and doc["scopeSet"] == "default"
    assert doc["scopes"] == config.DEFAULT_SCOPES and doc["cache"] == cache_path()
    assert doc["expiresAt"].startswith(str(datetime.now(WARSAW).year))


@covers("status")
def test_status_logged_out_json_still_on_stdout(invoke, monkeypatch):
    def boom(**kw):
        raise AuthError("NOT_LOGGED_IN", "no cached sign-in")

    monkeypatch.setattr(auth, "acquire_silent", boom)
    r = invoke("status", "--json")
    assert r.exit_code == 3
    assert json.loads(r.stdout) == {
        "loggedIn": False,
        "account": None,
        "expiresAt": None,
        "scopeSet": "default",
        "scopes": config.DEFAULT_SCOPES,
        "cache": cache_path(),
    }
    assert r.stderr.startswith("error[NOT_LOGGED_IN]: no cached sign-in")


@covers("status")
@pytest.mark.real_auth
def test_status_fixture_mode(invoke, monkeypatch, tmp_path):
    monkeypatch.setenv("MGRAPHCTL_FIXTURE_DIR", str(tmp_path))
    r = invoke("status")
    assert r.exit_code == 0, r.stderr
    assert r.stdout.startswith("Logged in as: fixture-user@example.com\n")
    assert "Scopes: default (23)\n" in r.stdout


@covers("claims")
def test_claims_sections_and_json(invoke, monkeypatch):
    now = int(time.time())
    payload = {
        "upn": "ada@example.com",
        "oid": "00000000-0000-0000-0000-00000000000a",
        "tid": "00000000-0000-0000-0000-00000000000b",
        "iat": now,
        "exp": now + 3600,
        "deviceid": "00000000-0000-0000-0000-00000000000d",
        "amr": ["pwd", "mfa"],
        "scp": "User.Read Mail.Read Calendars.Read",
    }
    monkeypatch.setattr(auth, "cached_access_token", lambda: jwt(payload))
    r = invoke("claims")
    assert r.exit_code == 0, r.stderr
    for header in ("IDENTITY", "DEVICE", "AUTH METHODS", "SCOPES"):
        assert header in r.stdout
    assert "expires in" in r.stdout and "pwd, mfa" in r.stdout
    lines = r.stdout.splitlines()
    scopes = [ln.strip() for ln in lines[lines.index("SCOPES") + 1 :] if ln.strip()]
    assert scopes == ["Calendars.Read", "Mail.Read", "User.Read"]
    r = invoke("claims", "--json")
    assert json.loads(r.stdout) == payload


@covers("claims")
def test_claims_without_token_exit_3(invoke, monkeypatch):
    monkeypatch.setattr(auth, "cached_access_token", lambda: None)
    r = invoke("claims")
    assert r.exit_code == 3 and r.stdout == ""
    assert r.stderr.startswith("error[NOT_LOGGED_IN]: no cached token")


@covers("login")
def test_login_already_logged_in(invoke, monkeypatch):
    monkeypatch.setattr(auth, "acquire_silent", lambda **kw: {"access_token": default_token()})
    monkeypatch.setattr(auth, "account_upn", lambda: "ada@example.com")

    def never(*a, **kw):
        raise AssertionError("login must not run interactively when the scopes are already held")

    monkeypatch.setattr(auth, "login_interactive", never)
    r = invoke("login")
    assert r.exit_code == 0, r.stderr
    assert r.stdout == (
        "Already logged in as: ada@example.com\n"
        "Use --force to re-authenticate, --scopes extended to add permissions.\n"
    )


@pytest.fixture
def interactive(monkeypatch):
    """Record the arguments `login` hands to msal, and route `GET /me` afterwards."""
    calls: list[tuple[list[str], bool]] = []

    def record(scopes, *, force):
        calls.append((list(scopes), force))
        return {"access_token": default_token()}

    monkeypatch.setattr(auth, "login_interactive", record)
    return calls


def route_login_me(graph):
    return graph.get(f"{GRAPH}/v1.0/me").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "00000000-0000-0000-0000-00000000000a",
                "displayName": "Ada Example",
                "userPrincipalName": "ada@example.com",
            },
        )
    )


@covers("login")
def test_login_force_runs_interactive_then_get_me(invoke, graph, interactive, monkeypatch):
    route = route_login_me(graph)
    r = invoke("login", "--force")
    assert r.exit_code == 0, r.stderr
    assert interactive == [(config.msal_scopes(config.DEFAULT_SCOPES), True)]
    assert route.calls.last.request.url.query.decode() == (
        "$select=id%2CdisplayName%2CuserPrincipalName"
    )
    assert r.stdout == (
        "Logged in as: Ada Example <ada@example.com>\n"
        "Scopes: default (23)\n"
        f"Cache: {cache_path()}\n"
    )
    r = invoke("login", "--force", "--json")
    assert json.loads(r.stdout) == {
        "account": "ada@example.com",
        "displayName": "Ada Example",
        "userId": "00000000-0000-0000-0000-00000000000a",
        "scopes": config.DEFAULT_SCOPES,
        "scopeSet": "default",
        "cache": cache_path(),
    }


@covers("login")
def test_login_scopes_extended_when_missing_from_token(invoke, graph, interactive, monkeypatch):
    monkeypatch.setattr(auth, "acquire_silent", lambda **kw: {"access_token": default_token()})
    monkeypatch.setattr(auth, "account_upn", lambda: "ada@example.com")
    route_login_me(graph)
    r = invoke("login", "--scopes", "extended")
    assert r.exit_code == 0, r.stderr
    assert interactive == [(config.msal_scopes(config.EXTENDED_SCOPES), False)]
    assert "Scopes: extended (33)\n" in r.stdout


@covers("login")
def test_login_scope_on_demand_appended(invoke, graph, interactive, monkeypatch):
    monkeypatch.setattr(auth, "acquire_silent", lambda **kw: {"access_token": default_token()})
    monkeypatch.setattr(auth, "account_upn", lambda: "ada@example.com")
    route_login_me(graph)
    r = invoke("login", "--scope", "User.Read.All")
    assert r.exit_code == 0, r.stderr
    assert "User.Read.All" in interactive[0][0]
    assert "Scopes: custom (24)\n" in r.stdout


@covers("login")
def test_login_device_code(invoke, graph, monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        auth,
        "login_device_code",
        lambda scopes: (calls.append(list(scopes)), {"access_token": default_token()})[1],
    )
    route_login_me(graph)
    r = invoke("login", "--device-code", "--force")
    assert r.exit_code == 0, r.stderr
    assert calls == [config.msal_scopes(config.DEFAULT_SCOPES)]


@covers("login")
def test_login_not_logged_in_goes_interactive(invoke, graph, interactive, monkeypatch):
    def boom(**kw):
        raise AuthError("NOT_LOGGED_IN", "no cached sign-in")

    monkeypatch.setattr(auth, "acquire_silent", boom)
    route_login_me(graph)
    r = invoke("login")
    assert r.exit_code == 0, r.stderr
    assert interactive == [(config.msal_scopes(config.DEFAULT_SCOPES), False)]


@covers("login")
def test_login_timeout_exit_3(invoke, monkeypatch):
    def boom(**kw):
        raise AuthError("NOT_LOGGED_IN", "no cached sign-in")

    def timeout(scopes, *, force):
        raise AuthError("LOGIN_TIMEOUT", "the browser sign-in did not complete within 300 s")

    monkeypatch.setattr(auth, "acquire_silent", boom)
    monkeypatch.setattr(auth, "login_interactive", timeout)
    r = invoke("login")
    assert r.exit_code == 3 and r.stdout == ""
    assert r.stderr.startswith("error[LOGIN_TIMEOUT]:")


@covers("logout")
def test_logout_messages(invoke, monkeypatch, tmp_path):
    path = tmp_path / "token_cache.json"
    monkeypatch.setattr(auth, "logout", lambda: path)
    r = invoke("logout")
    assert r.exit_code == 0 and r.stdout == f"Logged out. Cache removed: {path}\n"
    monkeypatch.setattr(auth, "logout", lambda: None)
    r = invoke("logout")
    assert r.exit_code == 0 and r.stdout == "No cached credentials found.\n"
    r = invoke("logout", "--json")
    assert json.loads(r.stdout) == {"loggedOut": False, "cache": None}


@covers("version")
def test_version_command(invoke):
    r = invoke("version")
    assert r.exit_code == 0
    assert re.fullmatch(
        r"mgraphctl 0\.1\.0 \(python 3\.1[123]\.\d+, msal \S+, httpx \S+\)", r.stdout.strip()
    )
    doc = json.loads(invoke("version", "--json").stdout)
    assert set(doc) == {"version", "python", "msal", "httpx"} and doc["version"] == "0.1.0"


@covers("me")
@pytest.mark.real_auth
def test_me_replays_committed_corpus(invoke, monkeypatch):
    corpus = Path(__file__).parent / "fixtures" / "replay"
    monkeypatch.setenv("MGRAPHCTL_FIXTURE_DIR", str(corpus))
    r = invoke("me", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["userPrincipalName"] == "fixture-user@example.com"
