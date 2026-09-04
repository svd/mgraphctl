"""Fixtures shared by every CLI test (spec §11)."""

import sys
import types

import pytest
import respx
from typer.testing import CliRunner

from mgraphctl import auth, config

# A registered-looking client id: the CLI refuses to talk to Entra with the placeholder default.
TEST_CLIENT_ID = "11111111-1111-1111-1111-111111111111"

ALL_SCOPES = [
    s
    for s in dict.fromkeys(config.DEFAULT_SCOPES + config.EXTENDED_EXTRA + config.ON_DEMAND_SCOPES)
    if s not in config.RESERVED_SCOPES
]


@pytest.fixture(autouse=True)
def fake_auth(request, monkeypatch, tmp_path):
    monkeypatch.setenv("MGRAPHCTL_TZ", "Europe/Warsaw")
    monkeypatch.setenv("MGRAPHCTL_CLIENT_ID", TEST_CLIENT_ID)
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("MGRAPHCTL_FIXTURE_DIR", raising=False)
    monkeypatch.delenv("MGRAPHCTL_RECORD", raising=False)
    monkeypatch.delenv("MGRAPHCTL_DEBUG", raising=False)
    monkeypatch.delenv("MGRAPHCTL_SCOPES", raising=False)
    monkeypatch.setenv("MGRAPHCTL_TOKEN_CACHE", str(tmp_path / "token_cache.json"))
    # The suite must never touch the developer's keychain; keyring tests opt in explicitly.
    monkeypatch.setenv("MGRAPHCTL_TOKEN_STORE", "file")
    # Point at a file that does not exist yet: the developer's own ~/.mgraphctl/config.toml
    # must never leak into the suite.
    monkeypatch.setenv("MGRAPHCTL_CONFIG", str(tmp_path / "config.toml"))
    if request.node.get_closest_marker("real_auth"):
        return
    marker = request.node.get_closest_marker("scopes")
    scopes = list(marker.args[0]) if marker else sorted(set(ALL_SCOPES) | auth.DECLARED_SCOPES)
    token = auth.synthetic_token(scopes)
    monkeypatch.setattr(auth, "get_access_token", lambda force_refresh=False: token)
    monkeypatch.setattr(auth, "cached_access_token", lambda: token)
    monkeypatch.setattr(auth, "save_cache", lambda: None)


class FakeKeyring(types.ModuleType):
    """An in-memory stand-in for the `keyring` package, installed into `sys.modules`.

    `items` maps `(service, username)` to the stored text. `backend_module` is what
    `type(get_keyring()).__module__` reports; `fail_with` makes every call raise it.
    """

    def __init__(self):
        super().__init__("keyring")
        self.items: dict[tuple[str, str], str] = {}
        self.backend_module = "keyring.backends.macOS"
        self.fail_with: Exception | None = None
        self.calls: list[tuple] = []
        errors = types.ModuleType("keyring.errors")

        class KeyringError(Exception):
            pass

        class PasswordDeleteError(KeyringError):
            pass

        class PasswordSetError(KeyringError):
            pass

        class KeyringLocked(KeyringError):
            pass

        errors.KeyringError = KeyringError
        errors.PasswordDeleteError = PasswordDeleteError
        errors.PasswordSetError = PasswordSetError
        errors.KeyringLocked = KeyringLocked
        self.errors = errors

    def _check(self, *call):
        self.calls.append(call)
        if self.fail_with is not None:
            raise self.fail_with

    def get_keyring(self):
        self.calls.append(("get_keyring",))
        return type("Backend", (), {"__module__": self.backend_module})()

    def get_password(self, service, username):
        self._check("get", service, username)
        return self.items.get((service, username))

    def set_password(self, service, username, value):
        self._check("set", service, username)
        self.items[(service, username)] = value

    def delete_password(self, service, username):
        self._check("delete", service, username)
        if (service, username) not in self.items:
            raise self.errors.PasswordDeleteError(f"{service}/{username} not found")
        del self.items[(service, username)]


@pytest.fixture
def fake_keyring(monkeypatch):
    """Replace the `keyring` package for the test and select the keyring store."""
    fake = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setitem(sys.modules, "keyring.errors", fake.errors)
    monkeypatch.setenv("MGRAPHCTL_TOKEN_STORE", "keyring")
    return fake


@pytest.fixture
def config_file(tmp_path):
    """Write TOML text to the config path the autouse fixture selected."""

    def _write(text: str):
        path = tmp_path / "config.toml"
        path.write_text(text)
        return path

    return _write


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
