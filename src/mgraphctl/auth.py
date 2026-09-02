"""msal sign-in, token cache and the local scope gate (spec §4)."""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

import msal
from msal.oauth2cli.oauth2 import BrowserInteractionTimeoutError

from mgraphctl import config, errors
from mgraphctl.errors import AuthError

log = logging.getLogger("mgraphctl.auth")

# Filled by cli.graph_command at decoration time: every scope any command declares.
DECLARED_SCOPES: set[str] = set()

# Error-description fragments that mean "an admin has to consent" rather than "sign in again".
CONSENT_MARKERS = ("AADSTS65001", "AADSTS650052", "Need admin approval")

FIXTURE_UPN = "fixture-user@example.com"
FIXTURE_OID = "00000000-0000-0000-0000-000000000001"
FIXTURE_TID = "00000000-0000-0000-0000-000000000002"

LOGIN_TIMEOUT_SECONDS = 300

_app: msal.PublicClientApplication | None = None
_cache: msal.SerializableTokenCache | None = None


# --------------------------------------------------------------------------- app and cache


def _build_app(
    s: config.Settings, cache: msal.SerializableTokenCache
) -> msal.PublicClientApplication:
    return msal.PublicClientApplication(s.client_id, authority=s.authority, token_cache=cache)


def app() -> msal.PublicClientApplication:
    """The process-wide msal application, built on first use."""
    global _app, _cache
    if _app is None:
        s = config.settings()
        _cache = load_cache(s.token_cache)
        _app = _build_app(s, _cache)
    return _app


def load_cache(path: Path) -> msal.SerializableTokenCache:
    """Read the msal cache from `path`; an absent or unreadable file yields an empty cache."""
    cache = msal.SerializableTokenCache()
    try:
        cache.deserialize(path.read_text())
    except (OSError, ValueError) as exc:
        log.debug("could not load the token cache %s: %s", path, exc)
    return cache


def save_cache() -> None:
    """Write the cache back when msal changed it. Never raises: it runs in a `finally`."""
    cache = _cache
    if cache is None or not cache.has_state_changed:
        return
    path = config.settings().token_cache
    tmp: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        # A unique temp file in the same directory: two concurrent invocations must not
        # write through one another's half-finished file before os.replace lands.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, cache.serialize().encode())
        finally:
            os.close(fd)
        os.replace(tmp, path)
        tmp = None
        path.chmod(0o600)
    except OSError as exc:
        log.debug("could not save the token cache: %s", exc)
        # serialize() already cleared the flag; set it again so the next save retries.
        cache.has_state_changed = True
        if tmp is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp)


def logout() -> Path | None:
    """Delete our token cache. Returns the path, or None."""
    global _app, _cache
    _app = None
    _cache = None
    path = config.settings().token_cache
    if not path.exists():
        return None
    path.unlink()
    return path


# --------------------------------------------------------------------------- token acquisition


def _replay_mode(s: config.Settings) -> bool:
    return s.fixture_dir is not None and not s.record


def _all_scopes() -> list[str]:
    """Every scope this build knows about, in spec order, minus the reserved ones."""
    seen: dict[str, None] = dict.fromkeys(
        config.DEFAULT_SCOPES + config.EXTENDED_EXTRA + config.ON_DEMAND_SCOPES
    )
    seen.update(dict.fromkeys(sorted(DECLARED_SCOPES)))
    return [s for s in seen if s not in config.RESERVED_SCOPES]


def acquire_silent(*, force_refresh: bool = False) -> dict:
    """Get a token without any user interaction. Raises AuthError when that is impossible."""
    s = config.settings()
    if _replay_mode(s):
        log.debug("token source: fixture")
        return {"access_token": synthetic_token(_all_scopes())}
    a = app()
    accounts = a.get_accounts()
    if not accounts:
        raise AuthError("NOT_LOGGED_IN", "no cached sign-in", hint=errors.HINTS["NOT_LOGGED_IN"])
    # ...with_error, not acquire_token_silent: the plain variant collapses every refresh
    # failure into None, which would make the CONSENT_REQUIRED branch unreachable (spec §4.2).
    result = a.acquire_token_silent_with_error(
        config.msal_scopes(s.scopes), account=accounts[0], force_refresh=force_refresh
    )
    if not result or "error" in result:
        raise classify_msal_error(result, during_login=False)
    log.debug("token source: %s", "refresh" if force_refresh else "cache")
    return result


def get_access_token(force_refresh: bool = False) -> str:
    """The token provider handed to GraphClient. Never prompts."""
    return acquire_silent(force_refresh=force_refresh)["access_token"]


def cached_access_token() -> str | None:
    """The newest cached access token for the signed-in account, without any network call."""
    s = config.settings()
    if _replay_mode(s):
        return synthetic_token(_all_scopes())
    a = app()
    accounts = a.get_accounts()
    if not accounts:
        return None
    entries = list(
        a.token_cache.search(
            msal.TokenCache.CredentialType.ACCESS_TOKEN,
            query={"home_account_id": accounts[0]["home_account_id"]},
        )
    )
    if not entries:
        return None
    newest = max(entries, key=lambda e: int(e.get("expires_on") or 0))
    return newest.get("secret")


def account_upn() -> str | None:
    s = config.settings()
    if _replay_mode(s):
        return FIXTURE_UPN
    accounts = app().get_accounts()
    return accounts[0].get("username") if accounts else None


# --------------------------------------------------------------------------- interactive sign-in


def _print_auth_uri(uri: str) -> None:
    sys.stderr.write(f"If no browser opened, visit this URL to sign in:\n{uri}\n")
    sys.stderr.flush()


def login_interactive(scopes: list[str], *, force: bool) -> dict:
    """Sign in through the system browser on a loopback redirect. Only `login` calls this."""
    try:
        result = app().acquire_token_interactive(
            config.msal_scopes(scopes),
            prompt="login" if force else "select_account",
            port=None,
            timeout=LOGIN_TIMEOUT_SECONDS,
            auth_uri_callback=_print_auth_uri,
        )
    except BrowserInteractionTimeoutError as exc:
        raise AuthError(
            "LOGIN_TIMEOUT",
            f"the browser sign-in did not complete within {LOGIN_TIMEOUT_SECONDS} s",
            hint=f"run '{config.shim_path()} login' again and finish the sign-in in the browser",
        ) from exc
    if not result or "error" in result:
        raise classify_msal_error(result, during_login=True)
    log.debug("token source: interactive")
    return result


def login_device_code(scopes: list[str]) -> dict:
    """Sign in with the device code flow, for hosts with no browser. Only `login` calls this."""
    a = app()
    flow = a.initiate_device_flow(scopes=config.msal_scopes(scopes))
    if "user_code" not in flow:
        raise classify_msal_error(flow, during_login=True)
    sys.stderr.write(f"{flow.get('message', '')}\n")
    sys.stderr.flush()
    result = a.acquire_token_by_device_flow(flow)
    if not result or "error" in result:
        raise classify_msal_error(result, during_login=True)
    log.debug("token source: device code")
    return result


# --------------------------------------------------------------------------- claims and scopes


def _b64url(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_jwt(token: str) -> dict:
    """The JWT payload, unverified. An undecodable token yields an empty dict."""
    parts = token.split(".") if token else []
    if len(parts) < 2:
        return {}
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError) as exc:
        log.debug("could not decode the access token: %s", exc)
        return {}
    return claims if isinstance(claims, dict) else {}


def synthetic_token(scopes: Iterable[str], *, upn: str = FIXTURE_UPN, ttl: int = 3600) -> str:
    """An unsigned JWT for fixture replay and tests. Never accepted by Graph."""
    now = int(time.time())
    claims = {
        "upn": upn,
        "unique_name": upn,
        "oid": FIXTURE_OID,
        "tid": FIXTURE_TID,
        "scp": " ".join(scopes),
        "iat": now,
        "exp": now + ttl,
    }
    return f"{_b64url({'alg': 'none', 'typ': 'JWT'})}.{_b64url(claims)}."


def expand_scopes(held: Iterable[str]) -> set[str]:
    """Held scopes plus everything they imply (spec §4.4)."""
    scopes = set(held)
    for scope in list(scopes):
        scopes.update(config.SCOPE_IMPLIES.get(scope, ()))
    return scopes


def require_scopes(token: str, declared: list[str]) -> None:
    """The local gate: raise MISSING_SCOPE before any request. `"A|B"` means any-of."""
    if not declared:
        return
    held = expand_scopes(decode_jwt(token).get("scp", "").split())
    for entry in declared:
        options = entry.split("|")
        if any(option in held for option in options):
            continue
        wanted = options[0]
        family = wanted.split(".")[0]
        closest = max((h for h in held if h.split(".")[0] == family), key=len, default=None)
        if wanted in config.ON_DEMAND_SCOPES:
            hint = f"run '{config.shim_path()} login --scope {wanted}' in your own terminal"
        else:
            hint = errors.HINTS["MISSING_SCOPE"]
        raise AuthError(
            "MISSING_SCOPE",
            f"this command needs {' or '.join(options)}; the current token has {closest or 'none'}",
            hint=hint,
        )


# --------------------------------------------------------------------------- error classification


def admin_consent_url() -> str:
    s = config.settings()
    token = cached_access_token()
    tenant = (decode_jwt(token).get("tid") if token else None) or s.tenant_id
    return f"https://{config.TOKEN_HOST}/{tenant}/adminconsent?client_id={s.client_id}"


def classify_msal_error(result: dict | None, *, during_login: bool) -> AuthError:
    """Turn an msal failure into CONSENT_REQUIRED or NOT_LOGGED_IN (spec §4.5)."""
    result = result or {}
    desc = result.get("error_description") or ""
    first = desc.splitlines()[0] if desc else (result.get("error") or "no cached sign-in")
    if result.get("error") == "consent_required" or any(m in desc for m in CONSENT_MARKERS):
        return AuthError(
            "CONSENT_REQUIRED",
            first,
            hint=f"an admin must grant consent once: {admin_consent_url()}",
            correlation_id=result.get("correlation_id"),
        )
    hint = errors.HINTS["UNAUTHORIZED"] if during_login else errors.HINTS["NOT_LOGGED_IN"]
    return AuthError("NOT_LOGGED_IN", first, hint=hint, correlation_id=result.get("correlation_id"))
