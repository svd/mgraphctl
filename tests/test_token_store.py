"""The token store: keychain item or 0600 file, and the choice between them."""

import pathlib
import stat
import sys

import pytest

from mgraphctl import config, token_store

pytestmark = pytest.mark.real_auth


def store():
    return token_store.resolve(config.settings())


# --------------------------------------------------------------------------- resolve


def test_file_store_never_imports_keyring(monkeypatch, tmp_path):
    monkeypatch.setenv("MGRAPHCTL_TOKEN_STORE", "file")
    monkeypatch.delitem(sys.modules, "keyring", raising=False)
    s = store()
    assert s.kind == "file" and s.path == tmp_path / "token_cache.json"
    assert s.label == str(tmp_path / "token_cache.json")
    assert "keyring" not in sys.modules


def test_auto_prefers_a_working_backend(fake_keyring, monkeypatch):
    monkeypatch.setenv("MGRAPHCTL_TOKEN_STORE", "auto")
    s = store()
    assert s.kind == "keyring" and s.label == "OS keychain (mgraphctl)"
    assert fake_keyring.calls == [("get_keyring",)]


@pytest.mark.parametrize("module", ["keyring.backends.fail", "keyring.backends.null"])
def test_auto_rejects_fail_and_null_backends(fake_keyring, monkeypatch, module):
    monkeypatch.setenv("MGRAPHCTL_TOKEN_STORE", "auto")
    fake_keyring.backend_module = module
    assert store().kind == "file"


def test_auto_falls_back_when_get_keyring_raises(fake_keyring, monkeypatch):
    monkeypatch.setenv("MGRAPHCTL_TOKEN_STORE", "auto")
    fake_keyring.get_keyring = lambda: (_ for _ in ()).throw(RuntimeError("no dbus"))
    assert store().kind == "file"


def test_explicit_keyring_is_unconditional(fake_keyring):
    fake_keyring.backend_module = "keyring.backends.fail"
    assert store().kind == "keyring"


# --------------------------------------------------------------------------- keyring backend


def test_keyring_round_trip_is_one_item(fake_keyring, tmp_path):
    s = store()
    assert token_store.read(s) is None
    token_store.write(s, '{"a": 1}')
    assert fake_keyring.items == {("mgraphctl", str(tmp_path / "token_cache.json")): '{"a": 1}'}
    assert token_store.read(s) == '{"a": 1}'
    assert token_store.clear(s) is True
    assert fake_keyring.items == {} and token_store.read(s) is None
    assert token_store.clear(s) is False
    assert not (tmp_path / "token_cache.json").exists()


def test_keyring_errors_propagate(fake_keyring):
    s = store()
    fake_keyring.fail_with = fake_keyring.errors.KeyringLocked("denied")
    with pytest.raises(fake_keyring.errors.KeyringLocked):
        token_store.read(s)
    with pytest.raises(fake_keyring.errors.KeyringLocked):
        token_store.write(s, "{}")


def test_keyring_chunks_when_a_limit_applies(fake_keyring, monkeypatch, tmp_path):
    monkeypatch.setattr(token_store, "CHUNK_CHARS", 8)
    s = store()
    account = str(tmp_path / "token_cache.json")
    text = '{"k": "0123456789abcdefghij"}'  # 30 chars -> 4 chunks of 8
    token_store.write(s, text)
    assert fake_keyring.items[("mgraphctl", account)] == "mgraphctl-chunks:4"
    assert [fake_keyring.items[("mgraphctl", f"{account}#{i}")] for i in range(4)] == [
        text[0:8],
        text[8:16],
        text[16:24],
        text[24:],
    ]
    assert token_store.read(s) == text

    token_store.write(s, '{"k": 12}')  # 9 chars -> 2 chunks; the stale #2 and #3 must go
    assert fake_keyring.items == {
        ("mgraphctl", account): "mgraphctl-chunks:2",
        ("mgraphctl", f"{account}#0"): '{"k": 12',
        ("mgraphctl", f"{account}#1"): "}",
    }
    assert token_store.read(s) == '{"k": 12}'

    token_store.write(s, "{}")  # under the limit: back to a single item
    assert fake_keyring.items == {("mgraphctl", account): "{}"}

    token_store.write(s, text)
    assert token_store.clear(s) is True
    assert fake_keyring.items == {}


def test_keyring_missing_chunk_reads_as_empty(fake_keyring, monkeypatch, tmp_path):
    monkeypatch.setattr(token_store, "CHUNK_CHARS", 8)
    s = store()
    token_store.write(s, '{"k": "0123456789abcdefghij"}')
    del fake_keyring.items[("mgraphctl", f"{tmp_path / 'token_cache.json'}#1")]
    assert token_store.read(s) is None


# --------------------------------------------------------------------------- file backend


def test_file_backend_keeps_0600_atomic_semantics(monkeypatch, tmp_path):
    monkeypatch.setenv("MGRAPHCTL_TOKEN_STORE", "file")
    monkeypatch.setenv("MGRAPHCTL_TOKEN_CACHE", str(tmp_path / ".mgraphctl" / "tc.json"))
    s = store()
    path = pathlib.Path(tmp_path / ".mgraphctl" / "tc.json")
    assert token_store.read(s) is None
    token_store.write(s, '{"a": 1}')
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert not list(path.parent.glob("*.tmp"))
    assert token_store.read(s) == '{"a": 1}'
    assert token_store.clear(s) is True and not path.exists()
    assert token_store.clear(s) is False


def test_file_write_raises_oserror_for_the_caller(monkeypatch, tmp_path):
    monkeypatch.setenv("MGRAPHCTL_TOKEN_STORE", "file")
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    monkeypatch.setenv("MGRAPHCTL_TOKEN_CACHE", str(blocker / "sub" / "tc.json"))
    with pytest.raises(OSError):
        token_store.write(store(), "{}")
    assert not list(tmp_path.glob("**/*.tmp"))
