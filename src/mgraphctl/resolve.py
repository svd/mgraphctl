"""Generic name-versus-id resolution machinery (spec §6.6). No Graph calls live here."""

from __future__ import annotations

import re
from collections.abc import Callable

from mgraphctl.errors import AmbiguousError, NotFoundError

GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

WELL_KNOWN_FOLDERS = frozenset(
    [
        "inbox",
        "drafts",
        "sentitems",
        "deleteditems",
        "junkemail",
        "archive",
        "outbox",
        "clutter",
        "conversationhistory",
        "msgfolderroot",
    ]
)

_DRIVE_ITEM_RE = re.compile(r"[A-Za-z0-9!]{20,}")
_PLANNER_RE = re.compile(r"[A-Za-z0-9_-]{28}")
_ONENOTE_PREFIX_RE = re.compile(r"^\d-")

# An opaque Outlook id is long and unbroken; a folder or calendar people typed has spaces.
_OPAQUE_MIN = 40


def split_id_prefix(value: str) -> tuple[str, bool]:
    """Strip an explicit `id:` prefix: `("x", True)` for `"id:x"`, else `(value, False)`."""
    if value.startswith("id:"):
        return value[3:], True
    return value, False


def _is_opaque(value: str) -> bool:
    return len(value) >= _OPAQUE_MIN and " " not in value


def looks_like_id(value: str, kind: str) -> bool:
    """Whether `value` is already an id of `kind`, rather than a name to look up (§6.6)."""
    bare, forced = split_id_prefix(value)
    match kind:
        case "guid" | "team" | "group":
            return bool(GUID_RE.match(value))
        case "mail_folder":
            return value.lower() in WELL_KNOWN_FOLDERS or _is_opaque(value)
        case "channel" | "chat":
            return value.startswith("19:")
        case "user":
            return bool(GUID_RE.match(value)) or "@" in value or value == "me"
        case "site":
            return value.startswith(("https://", "http://")) or ":/" in value or "," in value
        case "drive":
            return value.startswith("b!")
        case "drive_item":
            return forced or (bool(_DRIVE_ITEM_RE.fullmatch(bare)) and "." not in bare)
        case "onenote":
            return "!" in value or bool(_ONENOTE_PREFIX_RE.match(value))
        case "planner":
            return bool(_PLANNER_RE.fullmatch(value))
        case "todo_list":
            return value.startswith(("AQMk", "AAMk")) or len(value) >= _OPAQUE_MIN
        case "calendar":
            return _is_opaque(value)
        case _:
            raise ValueError(f"unknown id kind {kind!r}")


def _value_of(candidate: dict, key: str | Callable[[dict], str | None]) -> str | None:
    return key(candidate) if callable(key) else candidate.get(key)


def pick_unique(
    candidates: list[dict],
    key: str | Callable[[dict], str | None],
    needle: str,
    *,
    what: str,
) -> dict:
    """The one candidate whose `key` equals `needle`, compared case-insensitively (§6.6)."""
    folded = needle.casefold()
    matches = [c for c in candidates if (_value_of(c, key) or "").casefold() == folded]
    if not matches:
        raise NotFoundError("NOT_FOUND", f"{what} {needle!r} not found")
    if len(matches) > 1:
        raise AmbiguousError(
            "AMBIGUOUS",
            f"{what} {needle!r} matches {len(matches)} items",
            candidates=[(c.get("id", ""), _value_of(c, key) or "") for c in matches],
        )
    return matches[0]
