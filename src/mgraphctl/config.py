"""Configuration (env vars over `~/.mgraphctl/config.toml`), paths, scope sets and shared constants
(spec §3, §4.1, §4.4)."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # tomllib is stdlib from 3.11; on 3.10 the same parser ships as tomli
    import tomli as tomllib

from mgraphctl import __version__

CLIENT_ID_DEFAULT = "00000000-0000-0000-0000-000000000000"
CONFIG_FILE_NAME = "config.toml"
# Every key the file may set: the env var name without `MGRAPHCTL_`, lower-cased. The test-only
# knobs (fixture_dir, record) are deliberately absent.
CONFIG_KEYS: tuple[str, ...] = (
    "client_id",
    "tenant_id",
    "scopes",
    "tz",
    "token_cache",
    "token_store",
    "debug",
    "retries",
    "timeout_ms",
    "retry_base_ms",
)
# Where the msal cache lives: the OS keychain, the 0600 file, or whichever of the two works.
TOKEN_STORE_VALUES = ("auto", "keyring", "file")
TOKEN_STORE_DEFAULT = "auto"
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

# What `config init` writes: every key present, commented out, at its default.
CONFIG_TEMPLATE = """\
# mgraphctl configuration. Every key is optional; environment variables (MGRAPHCTL_<KEY>) and
# command-line flags override it. Uncomment a line to set it.

# client_id     = "00000000-0000-0000-0000-000000000000"   # Entra application (public client)
# tenant_id     = "common"                                 # authority tenant
# scopes        = "default"                                # default, extended, or a scope list
# tz            = "Europe/Warsaw"                          # IANA zone; default: detected
# token_cache   = "~/.mgraphctl/token_cache.json"
# token_store   = "auto"                                   # auto, keyring, or file
# debug         = 0                                        # 1 = --debug, 2 = -dd
# retries       = 4                                        # after the first attempt; 0 disables
# timeout_ms    = 60000
# retry_base_ms = 1000
"""

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


def state_dir() -> Path:
    return Path.home() / ".mgraphctl"


def config_path() -> Path:
    """`MGRAPHCTL_CONFIG`, else `~/.mgraphctl/config.toml`."""
    raw = os.environ.get("MGRAPHCTL_CONFIG")
    return Path(raw).expanduser() if raw else state_dir() / CONFIG_FILE_NAME


def load_config_file(path: Path | None = None) -> dict[str, Any]:
    """The file's top-level table; `{}` when it does not exist. Invalid TOML is a CONFIG error."""
    path = path or config_path()
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:
        from mgraphctl.errors import UsageError  # errors imports config; keep this lazy

        raise UsageError(
            "CONFIG", f"{path}: {exc}", hint="fix the file, or point MGRAPHCTL_CONFIG elsewhere"
        ) from None


INT_CONFIG_KEYS = frozenset({"debug", "retries", "timeout_ms", "retry_base_ms"})


def parse_config_value(key: str, text: str) -> str | int:
    """`text` as the value `key` takes in the file, or a USAGE error saying why it cannot."""
    from mgraphctl.errors import UsageError  # errors imports config; keep this lazy

    if key not in CONFIG_KEYS:
        raise UsageError(
            "USAGE", f"unknown config key {key!r}", hint=f"one of: {', '.join(CONFIG_KEYS)}"
        )
    if key in INT_CONFIG_KEYS:
        if not text.strip().isdigit():
            raise UsageError("USAGE", f"{key} must be a non-negative integer, not {text!r}")
        return int(text)
    if key == "token_store":
        value = text.strip().lower()
        if value not in TOKEN_STORE_VALUES:
            raise UsageError(
                "USAGE",
                f"token_store must be one of {', '.join(TOKEN_STORE_VALUES)}, not {text!r}",
            )
        return value
    return text


def format_toml_value(value: str | int) -> str:
    if isinstance(value, int):
        return str(value)
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


_KEY_LINE = re.compile(r"^(\s*#\s*)?(?P<key>[A-Za-z0-9_-]+)\s*=")


def upsert_config_line(text: str, key: str, value: str | int | None) -> str:
    """The file text with `key = value` in place of its first (possibly commented-out) line.

    `None` comments the active line out instead. A key with no line is appended (or, for
    `None`, left alone). Comments and every other line survive untouched.
    """
    lines = text.splitlines()
    done = False
    for i, line in enumerate(lines):
        m = _KEY_LINE.match(line)
        if not m or m.group("key") != key:
            continue
        active = m.group(1) is None
        if value is None:
            if active:
                lines[i] = f"# {line.strip()}"
                done = True
                break
            continue  # keep looking for an active one before uncommenting this one
        lines[i] = f"{key} = {format_toml_value(value)}"
        done = True
        break
    if not done and value is not None:
        lines.append(f"{key} = {format_toml_value(value)}")
    return "\n".join(lines) + ("\n" if lines else "")


def unknown_config_keys(path: Path | None = None) -> list[str]:
    return sorted(k for k in load_config_file(path) if k not in CONFIG_KEYS)


def _token_store(raw: str | None) -> str:
    """`auto`, `keyring` or `file`; anything else is a CONFIG error, like invalid TOML."""
    value = (raw or "").strip().lower()
    if not value:
        return TOKEN_STORE_DEFAULT
    if value in TOKEN_STORE_VALUES:
        return value
    from mgraphctl.errors import UsageError  # errors imports config; keep this lazy

    raise UsageError(
        "CONFIG",
        f"token_store must be one of {', '.join(TOKEN_STORE_VALUES)}, not {raw!r}",
        hint=f"fix MGRAPHCTL_TOKEN_STORE or the token_store line in {config_path()}",
    )


def _debug_level(raw: str | None) -> int:
    text = (raw or "").strip().lower()
    if text.isdigit():
        return int(text)
    return 1 if text in {"true", "yes", "on"} else 0


@dataclass(frozen=True)
class Settings:
    client_id: str
    tenant_id: str
    authority: str
    # The raw `scopes` spec from env or file, or None; `login` reuses it.
    scope_spec: str | None
    scope_set: str
    scopes: list[str]
    token_cache: Path
    # "keyring" or "file", or "auto" for keyring-when-it-works; token_store.resolve decides.
    token_store: str
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


def _raw_values() -> dict[str, tuple[str | None, str]]:
    """Each config key's raw text and where it came from: env beats file beats nothing."""
    env = os.environ
    file = load_config_file()
    out: dict[str, tuple[str | None, str]] = {}
    for key in CONFIG_KEYS:
        env_value = env.get(f"MGRAPHCTL_{key.upper()}")
        if env_value:
            out[key] = (env_value, "env")
        elif key in file:
            value = file[key]
            # TOML `true` for debug reads like the env var's "true"; everything else is str().
            out[key] = ("1" if value is True else "0" if value is False else str(value), "file")
        else:
            out[key] = (None, "default")
    return out


def settings() -> Settings:
    """Read configuration from `os.environ` and the config file. Never cached — call fresh."""
    env = os.environ
    raw = {key: value for key, (value, _) in _raw_values().items()}
    tenant = raw["tenant_id"] or "common"
    scope_set, scopes = resolve_scopes(raw["scopes"])
    fixture_dir = env.get("MGRAPHCTL_FIXTURE_DIR")
    return Settings(
        client_id=raw["client_id"] or CLIENT_ID_DEFAULT,
        tenant_id=tenant,
        authority=f"https://{TOKEN_HOST}/{tenant}",
        scope_spec=raw["scopes"],
        scope_set=scope_set,
        scopes=scopes,
        token_cache=Path(raw["token_cache"] or state_dir() / "token_cache.json").expanduser(),
        token_store=_token_store(raw["token_store"]),
        state_dir=state_dir(),
        tz=raw["tz"] or None,
        debug=_debug_level(raw["debug"]),
        fixture_dir=Path(fixture_dir).expanduser() if fixture_dir else None,
        record=(env.get("MGRAPHCTL_RECORD") or "") == "1",
        retries=_positive_int(raw["retries"], RETRIES_DEFAULT),
        timeout_ms=_positive_int(raw["timeout_ms"], TIMEOUT_MS_DEFAULT),
        retry_base_ms=_positive_int(raw["retry_base_ms"], RETRY_BASE_MS_DEFAULT),
    )


def effective_settings() -> list[tuple[str, Any, str]]:
    """`(key, parsed value, source)` per config key, for `config show`."""
    s = settings()
    sources = {key: source for key, (_, source) in _raw_values().items()}
    values: dict[str, Any] = {
        "client_id": s.client_id,
        "tenant_id": s.tenant_id,
        "scopes": s.scope_spec or "default",
        "tz": s.tz,
        "token_cache": str(s.token_cache),
        "token_store": s.token_store,
        "debug": s.debug,
        "retries": s.retries,
        "timeout_ms": s.timeout_ms,
        "retry_base_ms": s.retry_base_ms,
    }
    return [(key, values[key], sources[key]) for key in CONFIG_KEYS]


def shim_path() -> str:
    """Path to the bash shim next to this project, or the bare name when it isn't there."""
    candidate = Path(__file__).resolve().parents[2] / "mgraphctl"
    return str(candidate) if candidate.exists() else "mgraphctl"


def user_agent() -> str:
    return f"mgraphctl/{__version__}"
