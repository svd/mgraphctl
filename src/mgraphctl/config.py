"""Environment configuration, paths, scope sets and shared constants (spec §3, §4.1, §4.4)."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from mgraphctl import __version__

CLIENT_ID_DEFAULT = "00000000-0000-0000-0000-000000000000"
GRAPH_V1 = "https://graph.microsoft.com/v1.0"
GRAPH_BETA = "https://graph.microsoft.com/beta"
TOKEN_HOST = "login.microsoftonline.com"

# Node's 23 default scopes, verbatim and in order (spec §4.1).
DEFAULT_SCOPES: list[str] = [
    "User.Read",
    "Mail.Read",
    "Mail.Send",
    "Calendars.Read",
    "Calendars.ReadWrite",
    "Files.Read",
    "Files.ReadWrite",
    "Sites.Read.All",
    "Sites.ReadWrite.All",
    "Chat.Read",
    "Chat.ReadWrite",
    "ChannelMessage.Read.All",
    "ChannelMessage.Send",
    "OnlineMeetingTranscript.Read.All",
    "OnlineMeetings.Read",
    "People.Read",
    "Contacts.Read",
    "offline_access",
    "Notes.Read",
    "Notes.ReadWrite",
    "OnlineMeetingAiInsight.Read.All",
    "Tasks.ReadWrite",
    "Group.Read.All",
]

# The 10 extra scopes of the "extended" set, in order (spec §4.1).
EXTENDED_EXTRA: list[str] = [
    "Mail.ReadWrite",
    "MailboxSettings.ReadWrite",
    "Presence.Read",
    "Presence.ReadWrite",
    "User.ReadBasic.All",
    "Calendars.Read.Shared",
    "Chat.Create",
    "Team.ReadBasic.All",
    "Channel.ReadBasic.All",
    "TeamMember.Read.All",
]

EXTENDED_SCOPES: list[str] = DEFAULT_SCOPES + EXTENDED_EXTRA

ON_DEMAND_SCOPES = ["OnlineMeetingRecording.Read.All", "User.Read.All", "Presence.Read.All"]

RESERVED_SCOPES = frozenset({"openid", "profile", "offline_access"})

# Scope implication table (spec §4.4): a held "implier" scope also satisfies each "implied" scope.
SCOPE_IMPLIES: dict[str, tuple[str, ...]] = {
    "Mail.ReadWrite": ("Mail.Read", "Mail.ReadBasic"),
    "Calendars.ReadWrite": ("Calendars.Read", "Calendars.ReadBasic"),
    "Files.ReadWrite": ("Files.Read",),
    "Files.ReadWrite.All": ("Files.Read.All",),
    "Sites.ReadWrite.All": ("Sites.Read.All",),
    "Chat.ReadWrite": ("Chat.Read", "Chat.ReadBasic", "ChatMessage.Send"),
    "Tasks.ReadWrite": ("Tasks.Read",),
    "Notes.ReadWrite": ("Notes.Read",),
    "Contacts.ReadWrite": ("Contacts.Read",),
    "Presence.ReadWrite": ("Presence.Read",),
    "MailboxSettings.ReadWrite": ("MailboxSettings.Read",),
    "TeamMember.ReadWrite.All": ("TeamMember.Read.All",),
    "Group.ReadWrite.All": ("Group.Read.All",),
    "User.Read.All": ("User.ReadBasic.All",),
}

CHUNK_DRIVE = 10_485_760
CHUNK_OUTLOOK = 3_932_160
MAIL_INLINE_TOTAL = 2_621_440
MAIL_SMALL_ATTACHMENT = 3_145_728
DRIVE_SIMPLE_UPLOAD = 4_194_304

RETRY_STATUSES = frozenset({429, 503, 504})
# Retries after the first attempt (`MGRAPHCTL_RETRIES`) on RETRY_STATUSES and connection
# failures; 0 disables them. The one 401 re-authentication is not a retry and is not counted.
RETRIES_DEFAULT = 4
RETRY_AFTER_CAP = 300
TIMEOUT_MS_DEFAULT = 60_000
RETRY_BASE_MS_DEFAULT = 1_000
# Uploads and downloads move whole files, so they get a multiple of the configured timeout.
LONG_TIMEOUT_FACTOR = 5
CONNECT_TIMEOUT = 10.0
BACKOFF_CAP = 30.0


def _positive_int(raw: str | None, default: int) -> int:
    """An env var as a non-negative int; anything unusable falls back to `default`."""
    if raw is None:
        return default
    text = raw.strip()
    if not text.isdigit():  # rejects "", "-1", "abc" and "1.5" alike
        return default
    return int(text)


@dataclass(frozen=True)
class Settings:
    client_id: str
    tenant_id: str
    authority: str
    scope_set: str
    scopes: list[str]
    token_cache: Path
    state_dir: Path
    tz: str | None
    debug: int
    fixture_dir: Path | None
    record: bool
    # Retries after the first attempt; 0 disables retrying entirely.
    retries: int
    timeout_ms: int
    retry_base_ms: int

    @property
    def max_attempts(self) -> int:
        return self.retries + 1


def resolve_scopes(spec: str | None, extra: Iterable[str] = ()) -> tuple[str, list[str]]:
    """Resolve a scope spec ("default"|"extended"|a space/comma list|None) plus extras."""
    spec = (spec or "default").strip()
    if spec == "default":
        name, scopes = "default", list(DEFAULT_SCOPES)
    elif spec == "extended":
        name, scopes = "extended", list(EXTENDED_SCOPES)
    else:
        name, scopes = "custom", [s for s in re.split(r"[\s,]+", spec) if s]
    for s in extra:
        if s not in scopes:
            scopes.append(s)
            name = "custom"
    return name, scopes


def msal_scopes(scopes: Iterable[str]) -> list[str]:
    """Drop the reserved scopes msal adds itself, preserving order."""
    return [s for s in scopes if s not in RESERVED_SCOPES]


def settings() -> Settings:
    """Read configuration from `os.environ`. Never cached — call fresh each time."""
    env = os.environ
    tenant = env.get("MGRAPHCTL_TENANT_ID") or "common"
    scope_set, scopes = resolve_scopes(env.get("MGRAPHCTL_SCOPES"))
    state_dir = Path.home() / ".mgraphctl"
    debug_raw = (env.get("MGRAPHCTL_DEBUG") or "").strip().lower()
    debug = (
        int(debug_raw) if debug_raw.isdigit() else (1 if debug_raw in {"true", "yes", "on"} else 0)
    )
    fixture_dir = env.get("MGRAPHCTL_FIXTURE_DIR")
    return Settings(
        client_id=env.get("MGRAPHCTL_CLIENT_ID") or CLIENT_ID_DEFAULT,
        tenant_id=tenant,
        authority=f"https://{TOKEN_HOST}/{tenant}",
        scope_set=scope_set,
        scopes=scopes,
        token_cache=Path(
            env.get("MGRAPHCTL_TOKEN_CACHE") or state_dir / "token_cache.json"
        ).expanduser(),
        state_dir=state_dir,
        tz=env.get("MGRAPHCTL_TZ") or None,
        debug=debug,
        fixture_dir=Path(fixture_dir).expanduser() if fixture_dir else None,
        record=(env.get("MGRAPHCTL_RECORD") or "") == "1",
        retries=_positive_int(env.get("MGRAPHCTL_RETRIES"), RETRIES_DEFAULT),
        timeout_ms=_positive_int(env.get("MGRAPHCTL_TIMEOUT_MS"), TIMEOUT_MS_DEFAULT),
        retry_base_ms=_positive_int(env.get("MGRAPHCTL_RETRY_BASE_MS"), RETRY_BASE_MS_DEFAULT),
    )


def shim_path() -> str:
    """Path to the bash shim next to this project, or the bare name when it isn't there."""
    candidate = Path(__file__).resolve().parents[2] / "mgraphctl"
    return str(candidate) if candidate.exists() else "mgraphctl"


def user_agent() -> str:
    return f"mgraphctl/{__version__}"
