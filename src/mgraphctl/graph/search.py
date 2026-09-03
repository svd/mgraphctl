"""Graph operations for the unified `search` command (spec §8.17).

Pure: client and parameters in, an `http.SearchResult` out. The Search API
(`POST /search/query`) is entered through `GraphClient.search`, which already handles
paging on `moreResultsAvailable`; this module only shapes the query and the results.
"""

from __future__ import annotations

from datetime import datetime

from mgraphctl.errors import UsageError
from mgraphctl.graph.chats import shape_chat_hit
from mgraphctl.http import GraphClient, SearchResult
from mgraphctl.render import (
    Column,
    dig,
    fmt_dt,
    fmt_dtz,
    fmt_person,
    kql_date,
    parse_graph_dt,
    truncate,
)

ENTITY_TYPES = ("message", "event", "driveItem", "site", "list", "chatMessage", "person")

# Scopes per §8.17: declared statically as [] on the command and gated at runtime with
# `gate(SCOPES_BY_TYPE[type])`, because the scope needed depends on `--type`.
SCOPES_BY_TYPE: dict[str, list[str]] = {
    "message": ["Mail.Read"],
    "event": ["Calendars.Read"],
    "driveItem": ["Sites.Read.All"],
    "site": ["Sites.Read.All"],
    "list": ["Sites.Read.All"],
    "chatMessage": ["Chat.Read"],
    "person": ["People.Read"],
}

SEARCH_SIZE, DEFAULT_LIMIT, CAP_SEARCH = 25, 25, 200

# The client-side date-window field for every type but `message` (server-side KQL) and
# `person` (no date field on a person hit) — spec §8.17.
_DATE_PATH: dict[str, str] = {
    "event": "resource.start.dateTime",
    "driveItem": "resource.lastModifiedDateTime",
    "site": "resource.lastModifiedDateTime",
    "list": "resource.lastModifiedDateTime",
    "chatMessage": "resource.createdDateTime",
}


def normalise_entity_type(value: str) -> str:
    """Fold `--type` onto the Graph spelling; anything else is a usage error."""
    for known in ENTITY_TYPES:
        if known.casefold() == value.casefold():
            return known
    raise UsageError("USAGE", f"unknown --type {value!r}; use one of {', '.join(ENTITY_TYPES)}")


def _within(hit: dict, entity_type: str, after: datetime | None, before: datetime | None) -> bool:
    if after is None and before is None:
        return True
    path = _DATE_PATH.get(entity_type)
    if path is None:  # message (filtered server-side) and person (no date field)
        return True
    when = parse_graph_dt(dig(hit, path))
    if when is None:
        return False
    if after is not None and when < after:
        return False
    return before is None or when <= before


def _author(hit: dict) -> str:
    """The display name of whoever last touched a document hit, or its creator."""
    for key in ("lastModifiedBy", "createdBy"):
        name = dig(hit, f"resource.{key}.user.displayName")
        if name:
            return name
    return ""


def _person_email(hit: dict) -> str:
    resource = hit.get("resource") or {}
    scored = resource.get("scoredEmailAddresses") or []
    if scored and scored[0].get("address"):
        return scored[0]["address"]
    emails = resource.get("emailAddresses") or []
    return emails[0].get("address", "") if emails else ""


def columns_for(entity_type: str, tz: str) -> list[Column]:
    """The per-type list columns: id, date, title/subject, from/author, webUrl (spec §8.17)."""
    if entity_type == "message":
        return [
            Column("id", lambda h: dig(h, "resource.id")),
            Column("received", lambda h: fmt_dt(dig(h, "resource.receivedDateTime"), tz)),
            Column("subject", lambda h: truncate(dig(h, "resource.subject"))),
            Column("from", lambda h: fmt_person(dig(h, "resource.from"))),
            Column("webUrl", lambda h: dig(h, "resource.webUrl")),
        ]
    if entity_type == "event":
        return [
            Column("id", lambda h: dig(h, "resource.id")),
            Column("start", lambda h: fmt_dtz(dig(h, "resource.start"), tz)),
            Column("subject", lambda h: truncate(dig(h, "resource.subject"))),
            Column("organizer", lambda h: fmt_person(dig(h, "resource.organizer"))),
            Column("webUrl", lambda h: dig(h, "resource.webUrl")),
        ]
    if entity_type in ("driveItem", "site", "list"):
        return [
            Column("id", lambda h: dig(h, "resource.id")),
            Column("modified", lambda h: fmt_dt(dig(h, "resource.lastModifiedDateTime"), tz)),
            Column("name", lambda h: dig(h, "resource.name") or dig(h, "resource.displayName")),
            Column("author", _author),
            Column("webUrl", lambda h: dig(h, "resource.webUrl")),
        ]
    if entity_type == "chatMessage":
        # Already flattened by `shape_hit` (`shape_chat_hit`): id, created, from, where, summary.
        return [
            Column("id", "id"),
            Column("created", lambda h: fmt_dt(h.get("created"), tz)),
            Column("from", "from"),
            Column("where", "where"),
            Column("summary", lambda h: truncate(h.get("summary"))),
        ]
    if entity_type == "person":
        return [
            Column("id", lambda h: dig(h, "resource.id")),
            Column("name", lambda h: dig(h, "resource.displayName")),
            Column("email", _person_email),
            Column("title", lambda h: dig(h, "resource.jobTitle")),
        ]
    raise UsageError("USAGE", f"unknown --type {entity_type!r}")  # pragma: no cover - CLI validates


def shape_hit(entity_type: str, hit: dict) -> dict:
    """Flatten a `chatMessage` hit the same way `chats search` does (quirk 16); every other
    type is returned as Graph sent it (kept under `resource`, `hitId`, `rank`, `summary`)."""
    if entity_type == "chatMessage":
        return shape_chat_hit(hit)
    return hit


def search(
    client: GraphClient,
    *,
    entity_type: str,
    q: str,
    after: datetime | None,
    before: datetime | None,
    limit: int,
    all_: bool,
    fields: list[str] | None,
    tz: str,
) -> SearchResult:
    """Run one `/search/query` request (paged by `GraphClient.search`) and filter it."""
    terms = [q]
    if entity_type == "message":
        if after is not None:
            terms.append(f"received>={kql_date(after, tz)}")
        if before is not None:
            terms.append(f"received<={kql_date(before, tz)}")
    query_string = " ".join(terms)
    bound = CAP_SEARCH if all_ else limit
    found = client.search([entity_type], query_string, size=SEARCH_SIZE, limit=bound, fields=fields)
    hits = found.hits
    if entity_type != "message":
        hits = [h for h in hits if _within(h, entity_type, after, before)]
    return SearchResult(hits=hits, total=found.total, more=found.more)
