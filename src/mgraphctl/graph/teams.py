"""Graph operations for Teams and channels (spec §8.7).

Pure: client and parameters in, Graph dicts, a `PageResult` or a `Plan` out.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from mgraphctl import odata, resolve
from mgraphctl.html import to_markdown
from mgraphctl.http import (
    JSON_HEADERS,
    GraphClient,
    PageResult,
    Plan,
    PlannedRequest,
    filter_page,
    with_routing,
)
from mgraphctl.render import Column, fmt_dt, parse_graph_dt, truncate

CHANNEL_SELECT = "id,displayName,description,membershipType"
# The Teams endpoints reject a `$top` above 50.
PAGE_MEMBERS, CAP_MEMBERS = 50, 999
PAGE_MESSAGES, CAP_MESSAGES = 50, 200
CAP_TEAMS = CAP_CHANNELS = 999
BODY_CAP = 300


def list_teams(client: GraphClient) -> PageResult:
    """Every team the signed-in user joined. `/me/joinedTeams` takes no OData parameters."""
    return client.paginate("/me/joinedTeams", limit=None, all_=True, cap=CAP_TEAMS, page_size=None)


def resolve_team(client: GraphClient, value: str) -> dict:
    """A GUID (or `id:`-forced value) as-is, else the team of that display name (§6.6)."""
    bare, _ = resolve.split_id_prefix(value)
    if resolve.looks_like_id(value, "team"):
        return {"id": bare}
    return resolve.pick_unique(list_teams(client).items, "displayName", value, what="team")


def resolve_channel(client: GraphClient, team_id: str, value: str) -> dict:
    """A `19:` id (or `id:`-forced value) as-is, else the channel of that display name (§6.6)."""
    bare, _ = resolve.split_id_prefix(value)
    if resolve.looks_like_id(value, "channel"):
        return {"id": bare}
    channels = list_channels(client, team_id).items
    return resolve.pick_unique(channels, "displayName", value, what="channel")


def get_team(client: GraphClient, team_id: str) -> dict:
    return client.get(odata.p("teams", team_id))


def list_members(client: GraphClient, team_id: str, *, limit: int | None, all_: bool) -> PageResult:
    return client.paginate(
        odata.p("teams", team_id, "members"),
        limit=limit,
        all_=all_,
        cap=CAP_MEMBERS,
        page_size=PAGE_MEMBERS,
    )


def list_channels(client: GraphClient, team_id: str) -> PageResult:
    return client.paginate(
        odata.p("teams", team_id, "channels"),
        params={"$select": CHANNEL_SELECT},
        limit=None,
        all_=True,
        cap=CAP_CHANNELS,
        page_size=None,
    )


def get_channel(client: GraphClient, team_id: str, channel_id: str) -> dict:
    return client.get(odata.p("teams", team_id, "channels", channel_id))


def _renderable(message: dict) -> bool:
    """Tombstones and forward-compatible kinds carry no body worth showing (spec §8.7)."""
    if message.get("deletedDateTime"):
        return False
    return message.get("messageType") != "unknownFutureValue"


def _keep(page: PageResult) -> PageResult:
    return filter_page(page, _renderable)


def chain_modified(message: dict) -> datetime | None:
    """When the message's whole reply chain was last touched, which is how Graph orders it.

    Graph sorts channel messages "by the last modified date of the entire reply chain", so a
    root message's own `lastModifiedDateTime` is not the key the feed is in order of. With
    `--with-replies` the replies are in hand and the real key can be computed; without them
    the root's own timestamp is the best available approximation.
    """
    stamps = [
        parse_graph_dt(m.get("lastModifiedDateTime") or m.get("createdDateTime"))
        for m in [message, *(message.get("replies") or [])]
    ]
    known = [s for s in stamps if s is not None]
    return max(known) if known else None


def _window_filter(
    after: datetime | None, before: datetime | None
) -> Callable[[dict], bool] | None:
    """Keep the messages whose reply chain was last touched inside the window."""
    if after is None and before is None:
        return None

    def keep(message: dict) -> bool:
        stamp = chain_modified(message)
        if stamp is None:  # undatable: keep it rather than silently drop a message
            return True
        if after is not None and stamp <= after:
            return False
        return before is None or stamp < before

    return keep


def _before_window(after: datetime | None) -> Callable[[dict], bool] | None:
    """Page no further once a message's chain was last touched at or before `after`."""
    if after is None:
        return None

    def past_it(message: dict) -> bool:
        stamp = chain_modified(message)
        return stamp is not None and stamp <= after

    return past_it


def channel_messages(
    client: GraphClient,
    team_id: str,
    channel_id: str,
    *,
    with_replies: bool,
    after: datetime | None = None,
    before: datetime | None = None,
    limit: int | None,
    all_: bool,
) -> PageResult:
    """Channel messages, newest-modified first, optionally narrowed to a time window.

    The window is applied here rather than as a `$filter`: Graph documents `$top` and
    `$expand` as the only query parameters this endpoint supports (v1.0 and beta alike), so a
    `$filter` would be rejected or — worse — ignored, and an ignored one would dress an
    unfiltered page up as a window. Since the feed is ordered newest-first, paging can still
    stop at the far edge of the window instead of walking to the cap.
    """
    params = {"$expand": "replies"} if with_replies else None
    keep = _window_filter(after, before)
    page = client.paginate(
        odata.p("teams", team_id, "channels", channel_id, "messages"),
        params=params,
        limit=limit,
        all_=all_,
        cap=CAP_MESSAGES,
        page_size=PAGE_MESSAGES,
        stop=_before_window(after),
    )
    page = with_routing(_keep(page), teamId=team_id, channelId=channel_id)
    return page if keep is None else filter_page(page, keep)


def channel_replies(
    client: GraphClient,
    team_id: str,
    channel_id: str,
    msg_id: str,
    *,
    limit: int | None,
    all_: bool,
) -> PageResult:
    page = client.paginate(
        odata.p("teams", team_id, "channels", channel_id, "messages", msg_id, "replies"),
        limit=limit,
        all_=all_,
        cap=CAP_MESSAGES,
        page_size=PAGE_MESSAGES,
    )
    return with_routing(_keep(page), teamId=team_id, channelId=channel_id)


def message_sender(message: dict) -> str:
    """The display name behind a message's `from`, whichever identity kind carries it."""
    identity = message.get("from") or {}
    for kind in ("user", "application", "device"):
        name = (identity.get(kind) or {}).get("displayName")
        if name:
            return name
    return ""


def render_message_body(m: dict, full: bool) -> str:
    """One line of body text: HTML through Markdown, capped at 300 chars unless `full`."""
    body = m.get("body") or {}
    content = body.get("content") or ""
    if (body.get("contentType") or "").lower() == "html":
        content = to_markdown(content, mode="teams")
    single_line = " ".join(content.split())
    return single_line if full else truncate(single_line, BODY_CAP)


def message_columns(tz: str, full: bool) -> list[Column]:
    return [
        Column("created", lambda m: fmt_dt(m.get("createdDateTime"), tz)),
        Column("id", "id"),
        Column("from", message_sender),
        Column("body", lambda m: render_message_body(m, full)),
    ]


def plan_channel_send(
    client: GraphClient,
    team_id: str,
    channel_id: str,
    *,
    body: str,
    html: bool,
    subject: str | None,
    reply_to: str | None,
) -> Plan:
    """One POST. Plain text goes out as `contentType: "text"`, so nothing needs escaping."""
    segments = ["teams", team_id, "channels", channel_id, "messages"]
    if reply_to is not None:
        segments += [reply_to, "replies"]
    payload: dict[str, object] = {}
    if subject is not None:
        payload["subject"] = subject
    payload["body"] = {"contentType": "html" if html else "text", "content": body}
    return [PlannedRequest("POST", client.url(odata.p(*segments)), dict(JSON_HEADERS), payload)]
