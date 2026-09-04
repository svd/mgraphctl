"""auth.py against a scripted fake msal application (spec §4)."""

import base64
import json
import pathlib
import stat
import time

import msal
import pytest
from msal.oauth2cli.oauth2 import BrowserInteractionTimeoutError

from mgraphctl import auth, config, errors, token_store

pytestmark = pytest.mark.real_auth


def jwt(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'none', 'typ': 'JWT'})}.{enc(claims)}."


def tok(scp: str) -> str:
    return jwt({"scp": scp, "exp": int(time.time()) + 3600, "upn": "ada@example.com"})


ACCOUNT = {
    "home_account_id": "uid.utid",
    "environment": "login.microsoftonline.com",
    "username": "ada@example.com",
}


class FakeApp:
    def __init__(
        self,
        *,
        accounts=(),
        silent=None,
        interactive=None,
        device=None,
        raise_interactive=None,
    ):
        self.accounts = list(accounts)
        self.silent = silent
        self.interactive = interactive
        self.device = device
        self.raise_interactive = raise_interactive
        self.calls = []
        self.token_cache = msal.SerializableTokenCache()

    def get_accounts(self, username=None):
        self.calls.append(("get_accounts",))
        return self.accounts

    def acquire_token_silent(self, scopes, account, force_refresh=False, **kw):
        raise AssertionError(
            "auth must call acquire_token_silent_with_error: the plain variant hides the"
            " error dict, so consent and correlation ids would be lost"
        )

    def acquire_token_silent_with_error(self, scopes, account, force_refresh=False, **kw):
        self.calls.append(("silent", list(scopes), force_refresh))
        return self.silent

    def acquire_token_interactive(self, scopes, **kw):
        self.calls.append(("interactive", list(scopes), kw))
        if self.raise_interactive:
            raise self.raise_interactive
        return self.interactive

    def initiate_device_flow(self, scopes=None, **kw):
        self.calls.append(("device_flow", list(scopes or [])))
        return {
            "user_code": "ABCD1234",
            "device_code": "dc",
            "message": (
                "To sign in, use a web browser to open https://microsoft.com/devicelogin"
                " and enter the code ABCD1234"
            ),
        }

    def acquire_token_by_device_flow(self, flow, **kw):
        self.calls.append(("device", flow["device_code"]))
        return self.device


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MGRAPHCTL_TOKEN_CACHE", str(tmp_path / ".mgraphctl" / "token_cache.json"))
    monkeypatch.delenv("MGRAPHCTL_FIXTURE_DIR", raising=False)
    monkeypatch.delenv("MGRAPHCTL_RECORD", raising=False)
    monkeypatch.delenv("MGRAPHCTL_SCOPES", raising=False)
    holder = {}
    monkeypatch.setattr(auth, "_build_app", lambda s, cache: holder["app"])
    monkeypatch.setattr(auth, "_app", None)
    monkeypatch.setattr(auth, "_cache", None)
    monkeypatch.setattr(auth, "_store", None)
    monkeypatch.setattr(auth, "_migrate_from", None)
    monkeypatch.setattr(auth, "_warned", False)

    def install(app):
        holder["app"] = app
        auth._app = None
        return app

    return install


def test_silent_success_returns_token_without_interaction(fake):
    token = jwt(
        {"scp": "User.Read Mail.Read", "exp": int(time.time()) + 3600, "upn": "ada@example.com"}
    )
    app = fake(FakeApp(accounts=[ACCOUNT], silent={"access_token": token, "expires_in": 3600}))
    assert auth.get_access_token() == token
    assert app.calls[-1] == ("silent", config.msal_scopes(config.DEFAULT_SCOPES), False)
    assert not any(c[0] in ("interactive", "device_flow") for c in app.calls)
    auth.get_access_token(force_refresh=True)
    assert app.calls[-1][2] is True


def test_no_accounts_is_not_logged_in(fake, tmp_path):
    fake(FakeApp())
    with pytest.raises(errors.AuthError) as info:
        auth.get_access_token()
    assert info.value.code == "NOT_LOGGED_IN" and info.value.message == "no cached sign-in"
    assert info.value.hint.endswith("mgraphctl login' in your own terminal (opens a browser)")
    assert info.value.exit_code == 3


def test_silent_none_and_invalid_grant_are_not_logged_in(fake):
    app = fake(FakeApp(accounts=[ACCOUNT], silent=None))
    with pytest.raises(errors.AuthError) as info:
        auth.get_access_token()
    assert info.value.code == "NOT_LOGGED_IN"
    app.silent = {
        "error": "invalid_grant",
        "error_description": "AADSTS50173: token revoked\nTrace ID: x",
        "correlation_id": "corr-1",
    }
    with pytest.raises(errors.AuthError) as info:
        auth.get_access_token()
    assert (info.value.code, info.value.message, info.value.correlation_id) == (
        "NOT_LOGGED_IN",
        "AADSTS50173: token revoked",
        "corr-1",
    )


CONSENT_RESULTS = [
    {"error": "consent_required", "error_description": "x"},
    {
        "error": "invalid_grant",
        "error_description": "AADSTS65001: The user or administrator has not consented",
    },
    {"error": "invalid_grant", "error_description": "AADSTS650052: needs approval"},
    {"error": "invalid_grant", "error_description": "Need admin approval"},
]


@pytest.mark.parametrize("result", CONSENT_RESULTS)
def test_consent_required_classification(fake, result):
    fake(FakeApp(accounts=[ACCOUNT], silent=result))
    with pytest.raises(errors.AuthError) as info:
        auth.get_access_token()
    assert info.value.code == "CONSENT_REQUIRED"
    assert (
        info.value.hint == "an admin must grant consent once: "
        "https://login.microsoftonline.com/common/adminconsent?client_id="
        + config.CLIENT_ID_DEFAULT
    )


@pytest.mark.parametrize("result", CONSENT_RESULTS)
def test_classify_msal_error_marks_consent_during_login_too(fake, result):
    fake(FakeApp(accounts=[ACCOUNT]))
    assert auth.classify_msal_error(result, during_login=True).code == "CONSENT_REQUIRED"


def test_login_interactive_uses_select_account_and_login_on_force(fake, capsys):
    app = fake(FakeApp(interactive={"access_token": tok("User.Read")}))
    result = auth.login_interactive(config.DEFAULT_SCOPES, force=False)
    assert result["access_token"] == app.interactive["access_token"]
    _, scopes, kw = app.calls[-1]
    assert scopes == config.msal_scopes(config.DEFAULT_SCOPES)
    assert kw["prompt"] == "select_account" and kw["port"] is None and kw["timeout"] == 300
    assert callable(kw["auth_uri_callback"])
    kw["auth_uri_callback"]("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?a=1")
    err = capsys.readouterr().err
    assert "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?a=1" in err

    auth.login_interactive(config.DEFAULT_SCOPES, force=True)
    assert app.calls[-1][2]["prompt"] == "login"


def test_login_interactive_timeout(fake):
    fake(FakeApp(raise_interactive=BrowserInteractionTimeoutError("x")))
    with pytest.raises(errors.AuthError) as info:
        auth.login_interactive(config.DEFAULT_SCOPES, force=False)
    assert info.value.code == "LOGIN_TIMEOUT" and info.value.exit_code == 3
    assert "login" in info.value.hint


def test_login_interactive_error_dict_uses_login_force_hint(fake):
    fake(FakeApp(interactive={"error": "access_denied", "error_description": "user cancelled"}))
    with pytest.raises(errors.AuthError) as info:
        auth.login_interactive(config.DEFAULT_SCOPES, force=False)
    assert info.value.code == "NOT_LOGGED_IN" and info.value.message == "user cancelled"
    assert "login --force" in info.value.hint


def test_login_device_code_prints_message_to_stderr(fake, capsys):
    app = fake(FakeApp(device={"access_token": tok("User.Read")}))
    result = auth.login_device_code(config.DEFAULT_SCOPES)
    assert result == app.device
    assert ("device", "dc") in app.calls
    assert "ABCD1234" in capsys.readouterr().err


def test_scopes_sent_exclude_offline_access(fake, tmp_path, capsys):
    token = tok("User.Read")
    app = fake(
        FakeApp(
            accounts=[ACCOUNT],
            silent={"access_token": token},
            interactive={"access_token": token},
            device={"access_token": token},
        )
    )
    auth.get_access_token()
    auth.login_interactive(config.DEFAULT_SCOPES, force=False)
    auth.login_device_code(config.DEFAULT_SCOPES)
    sent = [part for call in app.calls for part in call if isinstance(part, list)]
    assert sent, "expected the fake to have recorded scope lists"
    assert all("offline_access" not in scopes for scopes in sent)
    capsys.readouterr()


def test_cache_saved_0600_atomically(fake, monkeypatch, tmp_path, caplog):
    cache = msal.SerializableTokenCache()
    cache.deserialize(json.dumps({"AccessToken": {}, "Account": {}}))
    path = tmp_path / ".mgraphctl" / "token_cache.json"

    auth._cache = cache
    cache.has_state_changed = False
    auth.save_cache()
    assert not path.exists()

    cache.has_state_changed = True
    auth.save_cache()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert not list(path.parent.glob("*.tmp"))
    assert path.read_text() == cache.serialize()

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    monkeypatch.setenv("MGRAPHCTL_TOKEN_CACHE", str(blocker / "sub" / "token_cache.json"))
    cache.has_state_changed = True
    with caplog.at_level("DEBUG", logger="mgraphctl.auth"):
        auth.save_cache()
    assert any("could not save the token cache" in r.message for r in caplog.records)
    # A failed write must stay pending so the next save retries it.
    assert cache.has_state_changed is True


def test_cache_save_uses_a_unique_temp_file(fake, monkeypatch, tmp_path):
    cache = msal.SerializableTokenCache()
    cache.deserialize(json.dumps({"AccessToken": {}, "Account": {}}))
    auth._cache = cache
    path = tmp_path / ".mgraphctl" / "token_cache.json"
    path.parent.mkdir(parents=True)

    seen = []
    real_mkstemp = token_store.tempfile.mkstemp

    def spy(**kw):
        fd, name = real_mkstemp(**kw)
        seen.append(name)
        return fd, name

    monkeypatch.setattr(token_store.tempfile, "mkstemp", spy)
    for _ in range(2):
        cache.has_state_changed = True
        auth.save_cache()
    assert len(set(seen)) == 2, "each save must use its own temp file"
    assert all(pathlib.Path(name).parent == path.parent for name in seen)
    assert not list(path.parent.glob("*.tmp"))
    assert path.read_text() == cache.serialize()


def test_logout_removes_cache_only(fake, tmp_path):
    state = tmp_path / ".mgraphctl"
    state.mkdir()
    cache_file = state / "token_cache.json"
    cache_file.write_text("{}")

    assert auth.logout() == (token_store.Store("file", cache_file), True)
    assert not cache_file.exists()
    assert auth.logout() == (token_store.Store("file", cache_file), False)


def test_decode_jwt_and_synthetic_token():
    claims = auth.decode_jwt(auth.synthetic_token(["User.Read", "Mail.Read"]))
    assert claims["upn"] == "fixture-user@example.com"
    assert claims["unique_name"] == "fixture-user@example.com"
    assert claims["oid"] == "00000000-0000-0000-0000-000000000001"
    assert claims["tid"] == "00000000-0000-0000-0000-000000000002"
    assert claims["scp"] == "User.Read Mail.Read"
    assert abs(claims["exp"] - (time.time() + 3600)) < 5
    assert auth.decode_jwt("not-a-jwt") == {}


def test_fixture_mode_bypasses_msal(fake, monkeypatch, tmp_path):
    def explode(s, cache):
        raise AssertionError("fixture mode must not build an msal application")

    monkeypatch.setattr(auth, "_build_app", explode)
    monkeypatch.setattr(auth, "DECLARED_SCOPES", {"Bookings.Read.All"})
    monkeypatch.setenv("MGRAPHCTL_FIXTURE_DIR", str(tmp_path / "fixtures"))
    held = set(auth.decode_jwt(auth.get_access_token())["scp"].split())
    expected = config.msal_scopes(
        config.DEFAULT_SCOPES + config.EXTENDED_EXTRA + config.ON_DEMAND_SCOPES
    )
    assert set(expected) <= held
    assert "Bookings.Read.All" in held
    assert "offline_access" not in held
    assert auth.account_upn() == "fixture-user@example.com"
    assert set(auth.decode_jwt(auth.cached_access_token())["scp"].split()) == held


def test_expand_scopes_implication_table():
    assert {"Mail.Read", "Mail.ReadBasic"} <= auth.expand_scopes(["Mail.ReadWrite"])
    assert "ChatMessage.Send" in auth.expand_scopes(["Chat.ReadWrite"])
    assert "User.ReadBasic.All" in auth.expand_scopes(["User.Read.All"])
    assert auth.expand_scopes([]) == set()


def test_require_scopes_any_of_and_missing():
    auth.require_scopes(tok("Group.Read.All"), ["Team.ReadBasic.All|Group.Read.All"])
    auth.require_scopes(tok("Mail.ReadWrite"), ["Mail.Read"])
    auth.require_scopes(tok("Mail.Read"), [])

    with pytest.raises(errors.AuthError) as info:
        auth.require_scopes(tok("Mail.Read"), ["Mail.ReadWrite"])
    assert info.value.code == "MISSING_SCOPE" and info.value.exit_code == 3
    assert (
        info.value.message == "this command needs Mail.ReadWrite; the current token has Mail.Read"
    )
    assert "login --scopes extended" in info.value.hint

    with pytest.raises(errors.AuthError) as info:
        auth.require_scopes(tok("User.Read"), ["OnlineMeetingRecording.Read.All"])
    assert "login --scope OnlineMeetingRecording.Read.All" in info.value.hint
    assert info.value.message.endswith("the current token has none")

    with pytest.raises(errors.AuthError) as info:
        auth.require_scopes(tok("User.Read"), ["Team.ReadBasic.All|Group.Read.All"])
    assert info.value.message.startswith(
        "this command needs Team.ReadBasic.All or Group.Read.All; "
    )


def test_cached_access_token_reads_msal_cache_without_network(fake):
    token = tok("User.Read")
    cache = msal.SerializableTokenCache()
    cache.deserialize(
        json.dumps(
            {
                "AccessToken": {
                    "k1": {
                        "credential_type": "AccessToken",
                        "secret": token,
                        "home_account_id": "uid.utid",
                        "environment": "login.microsoftonline.com",
                        "client_id": config.CLIENT_ID_DEFAULT,
                        "realm": "utid",
                        "target": "User.Read",
                        "cached_at": "1",
                        "expires_on": str(int(time.time()) + 100),
                        "extended_expires_on": "1",
                    }
                },
                "Account": {},
            }
        )
    )
    app = fake(FakeApp(accounts=[ACCOUNT]))
    app.token_cache = cache
    assert auth.cached_access_token() == token
    assert not any(c[0] == "silent" for c in app.calls)

    app.accounts = []
    assert auth.cached_access_token() is None


def test_my_oid_needs_an_oid_claim(monkeypatch):
    monkeypatch.setattr(auth, "cached_access_token", lambda: jwt({"oid": "u-ada"}))
    assert auth.my_oid() == "u-ada"

    for absent in (tok("User.Read"), None):  # a token without the claim, and no token at all
        monkeypatch.setattr(auth, "cached_access_token", lambda absent=absent: absent)
        with pytest.raises(errors.AuthError) as info:
            auth.my_oid()
        assert info.value.code == "NOT_LOGGED_IN" and info.value.exit_code == 3
        assert info.value.message == "the cached token carries no oid claim"
        assert info.value.hint == errors.HINTS["NOT_LOGGED_IN"]


def test_account_upn(fake):
    app = fake(FakeApp(accounts=[ACCOUNT]))
    assert auth.account_upn() == "ada@example.com"
    app.accounts = []
    assert auth.account_upn() is None


# --------------------------------------------------------------------------- keychain store


def seed_cache() -> tuple[msal.SerializableTokenCache, str]:
    cache = msal.SerializableTokenCache()
    cache.deserialize(json.dumps({"AccessToken": {}, "Account": {"k": {"username": "ada"}}}))
    return cache, cache.serialize()


def test_load_cache_reads_the_keyring_item(fake, fake_keyring, tmp_path):
    _, text = seed_cache()
    path = tmp_path / ".mgraphctl" / "token_cache.json"
    fake_keyring.items[("mgraphctl", str(path))] = text
    fake(FakeApp())
    auth.app()
    assert json.loads(auth._cache.serialize()) == json.loads(text)
    assert auth.store_info().kind == "keyring" and not path.exists()


def test_save_cache_writes_the_keyring_not_the_file(fake, fake_keyring, tmp_path):
    fake(FakeApp())
    auth.app()
    cache, _ = seed_cache()
    auth._cache = cache
    cache.has_state_changed = True
    auth.save_cache()
    path = tmp_path / ".mgraphctl" / "token_cache.json"
    assert fake_keyring.items == {("mgraphctl", str(path)): cache.serialize()}
    assert not path.exists() and cache.has_state_changed is False


def test_first_load_imports_the_file_then_deletes_it_after_saving(fake, fake_keyring, tmp_path):
    _, text = seed_cache()
    path = tmp_path / ".mgraphctl" / "token_cache.json"
    path.parent.mkdir()
    path.write_text(text)
    fake(FakeApp())
    auth.app()
    # serialize() would clear the flag, so the content is checked through the save below.
    assert auth._cache.has_state_changed is True
    assert path.exists(), "the file goes only once the keychain holds the cache"
    auth.save_cache()
    assert fake_keyring.items == {("mgraphctl", str(path)): text}
    assert not path.exists()


def test_import_keeps_the_file_when_the_keyring_write_fails(fake, fake_keyring, tmp_path, capsys):
    _, text = seed_cache()
    path = tmp_path / ".mgraphctl" / "token_cache.json"
    path.parent.mkdir()
    path.write_text(text)
    fake(FakeApp())
    auth.app()
    fake_keyring.fail_with = fake_keyring.errors.PasswordSetError("locked")
    auth.save_cache()
    assert path.read_text() == text and fake_keyring.items == {}
    assert auth.store_info().kind == "file"
    err = capsys.readouterr().err
    assert err.count("warning:") == 1 and "keyring" in err and str(path) in err


def test_keyring_read_failure_falls_back_to_the_file_once(fake, fake_keyring, tmp_path, capsys):
    fake_keyring.fail_with = fake_keyring.errors.KeyringLocked("denied")
    fake(FakeApp())
    auth.app()
    assert auth.store_info().kind == "file"
    cache, _ = seed_cache()
    auth._cache = cache
    for _ in range(2):
        cache.has_state_changed = True
        auth.save_cache()
    path = tmp_path / ".mgraphctl" / "token_cache.json"
    assert path.read_text() == cache.serialize()
    assert capsys.readouterr().err.count("warning:") == 1


def test_chunked_keyring_cache_round_trips(fake, fake_keyring, monkeypatch, tmp_path):
    monkeypatch.setattr(token_store, "CHUNK_CHARS", 16)
    fake(FakeApp())
    auth.app()
    cache, text = seed_cache()
    auth._cache = cache
    cache.has_state_changed = True
    auth.save_cache()
    account = str(tmp_path / ".mgraphctl" / "token_cache.json")
    assert fake_keyring.items[("mgraphctl", account)].startswith("mgraphctl-chunks:")
    auth._app = auth._cache = auth._store = None
    auth.app()
    assert json.loads(auth._cache.serialize()) == json.loads(text)


def test_logout_clears_the_keyring_item_and_the_file(fake, fake_keyring, tmp_path):
    path = tmp_path / ".mgraphctl" / "token_cache.json"
    path.parent.mkdir()
    path.write_text("{}")
    fake_keyring.items[("mgraphctl", str(path))] = "{}"
    assert auth.logout() == (token_store.Store("keyring", path), True)
    assert fake_keyring.items == {} and not path.exists()
    assert auth.logout() == (token_store.Store("keyring", path), False)


def test_auto_without_a_backend_uses_the_file_silently(fake, fake_keyring, monkeypatch, capsys):
    monkeypatch.setenv("MGRAPHCTL_TOKEN_STORE", "auto")
    fake_keyring.backend_module = "keyring.backends.fail"
    fake(FakeApp())
    auth.app()
    cache, _ = seed_cache()
    auth._cache = cache
    cache.has_state_changed = True
    auth.save_cache()
    assert auth.store_info().kind == "file"
    assert config.settings().token_cache.read_text() == cache.serialize()
    assert capsys.readouterr().err == ""
