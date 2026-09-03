"""Graph operations for Teams and channels (spec §8.7).

Pure: client and parameters in, Graph dicts, a `PageResult` or a `Plan` out.
"""

from __future__ import annotations

from mgraphctl import odata, resolve
from mgraphctl.html import to_markdown
from mgraphctl.http import JSON_HEADERS, GraphClient, PageResult, Plan, PlannedRequest
from mgraphctl.render import Column, fmt_dt, truncate

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
    return PageResult(
        items=[m for m in page.items if _renderable(m)],
        truncated=page.truncated,
        pages=page.pages,
    )


def channel_messages(
    client: GraphClient,
    team_id: str,
    channel_id: str,
    *,
    with_replies: bool,
    limit: int | None,
    all_: bool,
) -> PageResult:
    params = {"$expand": "replies"} if with_replies else None
    page = client.paginate(
        odata.p("teams", team_id, "channels", channel_id, "messages"),
        params=params,
        limit=limit,
        all_=all_,
        cap=CAP_MESSAGES,
        page_size=PAGE_MESSAGES,
    )
    return _keep(page)


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
    return _keep(page)


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
