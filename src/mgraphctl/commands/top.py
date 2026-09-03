"""login, logout, status, claims, me and version (spec §4.2, §4.3, §4.6, §8.1)."""

import importlib.metadata
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer

from mgraphctl import __version__, auth, config, errors, render
from mgraphctl.cli import Globals, JsonFlag, graph_command, open_client
from mgraphctl.errors import AuthError
from mgraphctl.graph import users
from mgraphctl.http import GraphClient
from mgraphctl.render import FileResult, ObjectResult, TextResult, WriteResult, fmt_size

LOGIN_SELECT = "id,displayName,userPrincipalName"

ME_FIELDS = [
    ("Name", "displayName"),
    ("UPN", "userPrincipalName"),
    ("Mail", "mail"),
    ("Title", "jobTitle"),
    ("Dept", "department"),
    ("Office", "officeLocation"),
    ("Phones", lambda u: ", ".join(u.get("businessPhones") or [])),
    ("Mobile", "mobilePhone"),
    ("Lang", "preferredLanguage"),
    ("User id", "id"),
]

NO_DEVICE_NOTE = (
    "none (Conditional Access policies that require a compliant device will fail without it)"
)


def _iso_local(epoch: object, tz: str) -> str | None:
    """An `exp`/`iat` epoch rendered in `tz` with seconds, or None."""
    if epoch is None:
        return None
    return datetime.fromtimestamp(int(epoch), ZoneInfo(tz)).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- login / logout


def _already_logged_in(wanted: list[str], name: str, cache: str) -> TextResult | None:
    """The current token, when it already carries every requested scope (spec §4.2)."""
    try:
        result = auth.acquire_silent()
    except AuthError:
        return None
    claims = auth.decode_jwt(result["access_token"])
    held = auth.expand_scopes(claims.get("scp", "").split())
    if any(s not in held for s in config.msal_scopes(wanted)):
        return None
    upn = auth.account_upn() or claims.get("upn") or claims.get("unique_name")
    text = (
        f"Already logged in as: {upn}\n"
        "Use --force to re-authenticate, --scopes extended to add permissions."
    )
    payload = dict(account=upn, scopes=wanted, scopeSet=name, cache=cache, alreadyLoggedIn=True)
    return TextResult(text=text, json_obj=payload)


def login(
    ctx: typer.Context,
    scopes: Annotated[
        str,
        typer.Option(
            "--scopes",
            envvar="MGRAPHCTL_SCOPES",
            help="default, extended, or a space/comma-separated scope list.",
        ),
    ] = "",
    scope: Annotated[
        list[str] | None,
        typer.Option("--scope", help="Ask for one extra scope on demand (repeatable)."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Sign in again even when a token is cached.")
    ] = False,
    device_code: Annotated[
        bool, typer.Option("--device-code", help="Use the device code flow (no browser).")
    ] = False,
    json_: JsonFlag = False,
) -> None:
    """Sign in and cache the token. The only command that may open a browser."""
    g: Globals = ctx.find_root().obj
    name, wanted = config.resolve_scopes(scopes or None, scope or [])
    cache = str(config.settings().token_cache)
    if not force:
        already = _already_logged_in(wanted, name, cache)
        if already is not None:
            render.emit(already, json_mode=json_)
            return
    sent = config.msal_scopes(wanted)
    if device_code:
        auth.login_device_code(sent)
    else:
        auth.login_interactive(sent, force=force)
    with open_client(g, []) as client:
        me_obj = client.get("/me", params={"$select": LOGIN_SELECT})
    account = me_obj.get("userPrincipalName")
    display = me_obj.get("displayName")
    text = f"Logged in as: {display} <{account}>\nScopes: {name} ({len(wanted)})\nCache: {cache}"
    payload = dict(
        account=account,
        displayName=display,
        userId=me_obj.get("id"),
        scopes=wanted,
        scopeSet=name,
        cache=cache,
    )
    render.emit(TextResult(text=text, json_obj=payload), json_mode=json_)


def logout(json_: JsonFlag = False) -> None:
    """Delete the cached sign-in."""
    path = auth.logout()
    message = f"Logged out. Cache removed: {path}" if path else "No cached credentials found."
    payload = dict(loggedOut=path is not None, cache=str(path) if path else None)
    render.emit(WriteResult(obj=payload, message=message), json_mode=json_)


# --------------------------------------------------------------------------- status / claims


def status(ctx: typer.Context, json_: JsonFlag = False) -> None:
    """Report whether a cached sign-in is usable, and until when (spec §4.6)."""
    g: Globals = ctx.find_root().obj
    s = config.settings()
    cache = str(s.token_cache)
    try:
        result = auth.acquire_silent()
    except AuthError:
        # JSON callers parse stdout without checking the exit code first (spec §4.6).
        if json_:
            out = dict(
                loggedIn=False,
                account=None,
                expiresAt=None,
                scopeSet=s.scope_set,
                scopes=s.scopes,
                cache=cache,
            )
            render.emit(TextResult(text="", json_obj=out), json_mode=True)
        raise
    claims = auth.decode_jwt(result["access_token"])
    account = auth.account_upn() or claims.get("upn") or claims.get("unique_name")
    expires = _iso_local(claims.get("exp"), g.tz)
    text = (
        f"Logged in as: {account}\n"
        f"Token expires: {expires}\n"
        f"Scopes: {s.scope_set} ({len(s.scopes)})\n"
        f"Cache: {cache}"
    )
    payload = dict(
        loggedIn=True,
        account=account,
        expiresAt=expires,
        scopeSet=s.scope_set,
        scopes=s.scopes,
        cache=cache,
    )
    render.emit(TextResult(text=text, json_obj=payload), json_mode=json_)


def _expiry_note(exp: object) -> str:
    if exp is None:
        return ""
    remaining = int(exp) - int(time.time())
    return "EXPIRED" if remaining <= 0 else f"expires in {remaining // 60}m"


def _section(title: str, rows: list[tuple[str, str]]) -> list[str]:
    width = max((len(label) for label, _ in rows), default=0)
    body = [f"  {label:<{width}} : {value}" for label, value in rows]
    return [title] + body


def _claims_text(payload: dict, tz: str) -> str:
    """The IDENTITY / DEVICE / AUTH METHODS / SCOPES report of spec §4.6."""
    exp = payload.get("exp")
    expires = _iso_local(exp, tz) or "N/A"
    note = _expiry_note(exp)
    identity = [
        ("UPN", str(payload.get("upn") or payload.get("unique_name") or "N/A")),
        ("Object id", str(payload.get("oid") or "N/A")),
        ("Tenant id", str(payload.get("tid") or "N/A")),
        ("Issued", _iso_local(payload.get("iat"), tz) or "N/A"),
        ("Expires", f"{expires} ({note})" if note else expires),
    ]
    device = [
        ("Device id", str(payload.get("deviceid") or NO_DEVICE_NOTE)),
        ("Join type", str(payload.get("join_type") or "N/A")),
    ]
    amr = payload.get("amr") or []
    methods = ", ".join(str(a) for a in amr) if amr else "N/A"
    lines = _section("IDENTITY", identity) + [""]
    lines += _section("DEVICE", device) + [""]
    lines += ["AUTH METHODS", f"  {methods}", ""]
    lines += ["SCOPES"] + [f"  {s}" for s in sorted(payload.get("scp", "").split())]
    return "\n".join(lines)


def claims(ctx: typer.Context, json_: JsonFlag = False) -> None:
    """Decode the cached access token locally. No network call (spec §4.6)."""
    g: Globals = ctx.find_root().obj
    token = auth.cached_access_token()
    if not token:
        raise AuthError("NOT_LOGGED_IN", "no cached token", hint=errors.HINTS["NOT_LOGGED_IN"])
    payload = auth.decode_jwt(token)
    render.emit(TextResult(text=_claims_text(payload, g.tz), json_obj=payload), json_mode=json_)


# --------------------------------------------------------------------------- me / version


@graph_command(scopes=["User.Read"])
def me(
    client: GraphClient,
    photo: Annotated[
        Path | None, typer.Option("--photo", help="Save the profile photo to this file.")
    ] = None,
    json_: JsonFlag = False,
):
    """Show the signed-in user's profile, or save their photo."""
    if photo is not None:
        got = client.download("/me/photo/$value", photo)
        return FileResult(
            path=got.path,
            bytes=got.bytes,
            meta=dict(contentType=got.content_type),
            message=f"Downloaded photo ({fmt_size(got.bytes)}) to {got.path}",
        )
    return ObjectResult(obj=users.get_me(client), fields=list(ME_FIELDS))


def version(json_: JsonFlag = False) -> None:
    """Show the versions of mgraphctl and the libraries it runs on."""
    python_version = platform.python_version()
    msal_version = importlib.metadata.version("msal")
    httpx_version = importlib.metadata.version("httpx")
    text = (
        f"mgraphctl {__version__} (python {python_version},"
        f" msal {msal_version}, httpx {httpx_version})"
    )
    payload = dict(
        version=__version__, python=python_version, msal=msal_version, httpx=httpx_version
    )
    render.emit(TextResult(text=text, json_obj=payload), json_mode=json_)


def register(root: typer.Typer) -> None:
    """Attach the top-level verbs to the root app."""
    root.command("login")(login)
    root.command("logout")(logout)
    root.command("status")(status)
    root.command("claims")(claims)
    root.command("me")(me)
    root.command("version")(version)
