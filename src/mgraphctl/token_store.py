"""Where the msal token cache lives: an OS keychain item via `keyring`, or the 0600 file.

The store holds one opaque string, `msal.SerializableTokenCache.serialize()`, and never parses
it. Keyring calls let every exception through; `auth` decides whether to fall back to the file.
Keychain writes are last-writer-wins, the same as the file's `os.replace`; no lock is taken.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mgraphctl import config

log = logging.getLogger("mgraphctl.token_store")

SERVICE = "mgraphctl"
KEYRING_LABEL = f"OS keychain ({SERVICE})"
# The Windows Credential Locker caps one secret at 2560 UTF-16 bytes and keyring does not split
# for us; macOS and Secret Service take the whole cache in one item. None means "never split".
CHUNK_CHARS: int | None = 1000 if sys.platform == "win32" else None
_CHUNKED = "mgraphctl-chunks:"


@dataclass(frozen=True)
class Store:
    kind: str  # "keyring" or "file"
    # The file backend's path. For the keyring it is the item's account name, so two cache
    # paths stay two sign-ins, and the file an earlier version left behind to import.
    path: Path

    @property
    def account(self) -> str:
        return str(self.path)

    @property
    def label(self) -> str:
        """What `login`/`status`/`logout` print after `Cache:`."""
        return KEYRING_LABEL if self.kind == "keyring" else str(self.path)


def resolve(s: config.Settings) -> Store:
    """The store `token_store` selects; `auto` asks keyring whether a real backend exists."""
    if s.token_store == "file":
        return Store("file", s.token_cache)
    if s.token_store == "keyring" or keyring_usable():
        return Store("keyring", s.token_cache)
    return Store("file", s.token_cache)


def keyring_usable() -> bool:
    """Whether keyring has a real backend. Never touches the keychain itself."""
    try:
        import keyring

        backend = keyring.get_keyring()
    except Exception as exc:
        log.debug("keyring unavailable: %s", exc)
        return False
    module = type(backend).__module__ or ""
    log.debug("keyring backend: %s.%s", module, type(backend).__name__)
    # `fail` is the placeholder when no store exists; `null` is what `keyring disable` leaves,
    # and it discards writes without an error.
    return "fail" not in module and "null" not in module


def read(store: Store) -> str | None:
    return _read_keyring(store.account) if store.kind == "keyring" else read_file(store.path)


def write(store: Store, text: str) -> None:
    if store.kind == "keyring":
        _write_keyring(store.account, text)
    else:
        write_file(store.path, text)


def clear(store: Store) -> bool:
    """Remove the stored cache; True when there was one."""
    return _clear_keyring(store.account) if store.kind == "keyring" else clear_file(store.path)


# --------------------------------------------------------------------------- file backend


def read_file(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError as exc:
        log.debug("could not read the token cache %s: %s", path, exc)
        return None


def write_file(path: Path, text: str) -> None:
    """Atomic 0600 write into a 0700 directory. Raises OSError."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # A directory we do not own cannot be chmod-ed, but the 0600 file still goes in it.
    with contextlib.suppress(OSError):
        path.parent.chmod(0o700)
    # A unique temp file in the same directory: two concurrent invocations must not write
    # through one another's half-finished file before os.replace lands.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    try:
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, text.encode())
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    path.chmod(0o600)


def clear_file(path: Path) -> bool:
    if not path.exists():
        return False
    path.unlink()
    return True


# --------------------------------------------------------------------------- keyring backend


def _chunk_account(account: str, i: int) -> str:
    return f"{account}#{i}"


def _read_keyring(account: str) -> str | None:
    import keyring

    head = keyring.get_password(SERVICE, account)
    if head is None or not head.startswith(_CHUNKED):
        return head
    parts = []
    for i in range(int(head[len(_CHUNKED) :])):
        part = keyring.get_password(SERVICE, _chunk_account(account, i))
        if part is None:
            log.debug("token cache chunk %d is missing from the keychain", i)
            return None
        parts.append(part)
    return "".join(parts)


def _write_keyring(account: str, text: str) -> None:
    import keyring

    limit = CHUNK_CHARS
    if limit is None or len(text) <= limit:
        keyring.set_password(SERVICE, account, text)
        stale_from = 0
    else:
        pieces = [text[i : i + limit] for i in range(0, len(text), limit)]
        for i, piece in enumerate(pieces):
            keyring.set_password(SERVICE, _chunk_account(account, i), piece)
        # The head goes last: a reader sees either the previous complete set or this one.
        keyring.set_password(SERVICE, account, f"{_CHUNKED}{len(pieces)}")
        stale_from = len(pieces)
    _delete_chunks_from(account, stale_from)


def _delete_chunks_from(account: str, start: int) -> None:
    """Drop chunk items from `start` up, left behind by a longer earlier write."""
    import keyring

    i = start
    while keyring.get_password(SERVICE, _chunk_account(account, i)) is not None:
        _delete_item(_chunk_account(account, i))
        i += 1


def _delete_item(account: str) -> None:
    import keyring
    from keyring.errors import PasswordDeleteError

    with contextlib.suppress(PasswordDeleteError):
        keyring.delete_password(SERVICE, account)


def _clear_keyring(account: str) -> bool:
    import keyring

    head = keyring.get_password(SERVICE, account)
    if head is None:
        return False
    if head.startswith(_CHUNKED):
        _delete_chunks_from(account, 0)
    _delete_item(account)
    return True
