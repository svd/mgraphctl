"""Graph operations for Teams chats and direct messages (spec §8.8).

Pure: client and parameters in, Graph dicts, a `PageResult` or a `Plan` out.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from urllib.parse import unquote

from mgraphctl import config, odata, resolve
from mgraphctl.errors import NotFoundError, UsageError
from mgraphctl.graph import teams, users
from mgraphctl.http import (
    JSON_HEADERS,
    GraphClient,
    PageResult,
    Plan,
    PlannedRequest,
    SearchResult,
    filter_page,
    with_routing,
)
from mgraphctl.render import dig, parse_graph_dt, to_iso_offset

CHAT_SELECT = "id,topic,chatType,lastUpdatedDateTime,viewpoint,webUrl"
CHAT_EXPAND = "members,lastMessagePreview"
CHAT_ORDER = "lastMessagePreview/createdDateTime desc"
CHAT_TYPES = ("oneOnOne", "group", "meeting")
DM_SELECT = "id,displayName"
MEMBER_TYPE = "#microsoft.graph.aadUserConversationMember"
# The plan a `--dry-run` prints cannot know which chat will be created (spec §6.4).
ME_PLACEHOLDER = "{me}"
CHAT_ID_PLACEHOLDER = "{chatId}"
GROUP_TITLE_NAMES = 3

PAGE_CHATS, CAP_CHATS = 50, 200
CAP_CHAT_MEMBERS = 999
PAGE_MESSAGES, CAP_MESSAGES = 50, 200
# The only chat-message property Graph filters on with both `gt` and `lt`, and only when
# `$orderby` names it too — otherwise the `$filter` is silently ignored (spec §8.8).
MESSAGE_WINDOW_FIELD = "lastModifiedDateTime"
CAP_ONE_ON_ONE = 500
SEARCH_SIZE, CAP_SEARCH = 25, 200
HOSTED_NAME_PREFIX = "teams_hosted_"
HOSTED_ID_IN_NAME = 8
# Every request carries the access token, so a URL taken from a message body is only ever
# followed when it is a Graph hosted-contents address on our own base (spec §5.1, §10 quirk 21).
_HOSTED_TAIL = r"/messages/[^/]+/hostedContents/([^/?]+)/\$value(?:\?.*)?$"
_CHAT_HOSTED_RE = re.compile(r"^/chats/[^/]+" + _HOSTED_TAIL)
_CHANNEL_HOSTED_RE = re.compile(r"^/teams/[^/]+/channels/[^/]+" + _HOSTED_TAIL)
# The magic bytes the Teams hosted contents actually carry (spec §8.8 `hosted-content`).
_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"%PDF", "pdf"),
)


def normalise_chat_type(value: str | None) -> str | None:
    """Fold `--type` onto the Graph spelling; anything else is a usage error."""
    if value is None:
        return None
    for known in CHAT_TYPES:
        if known.casefold() == value.casefold():
            return known
    raise UsageError("USAGE", f"unknown chat type {value!r}; use one of {', '.join(CHAT_TYPES)}")


def last_message_at(chat: dict) -> datetime | None:
    """When the chat's last message preview was written, which is the order `/me/chats` is in."""
    return parse_graph_dt(dig(chat, "lastMessagePreview.createdDateTime"))


def _quiet_since(since: datetime | None) -> Callable[[dict], bool] | None:
    """Page no further once a chat's last message predates `since`.

    A chat with no readable preview timestamp is not the end of the feed — it says nothing
    about where the boundary is — so it neither stops the fetch nor, in `_active_since`, gets
    dropped from it. The two rules are deliberately the same: an undatable chat is kept.
    """
    if since is None:
        return None

    def past_it(chat: dict) -> bool:
        created = last_message_at(chat)
        return created is not None and created < since

    return past_it


def _active_since(since: datetime) -> Callable[[dict], bool]:
    """Keep the chats whose last message is at or after `since`, and the undatable ones."""

    def keep(chat: dict) -> bool:
        created = last_message_at(chat)
        return created is None or created >= since

    return keep


def list_chats(
    client: GraphClient,
    *,
    chat_type: str | None,
    since: datetime | None = None,
    limit: int | None,
    all_: bool,
) -> PageResult:
    """The signed-in user's chats, most recently active first.

    `$orderby=lastMessagePreview/createdDateTime desc` already puts the feed in that order, so
    `since` needs no server-side filter: paging stops at the first chat whose last message
    predates it, and the chats past that boundary are dropped here.
    """
    params: dict[str, object] = {
        "$expand": CHAT_EXPAND,
        "$orderby": CHAT_ORDER,
        "$select": CHAT_SELECT,
    }
    if chat_type:
        params["$filter"] = f"chatType eq '{odata.odata_str(chat_type)}'"
    page = client.paginate(
        "/me/chats",
        params=params,
        limit=limit,
        all_=all_,
        cap=CAP_CHATS,
        page_size=PAGE_CHATS,
        stop=_quiet_since(since),
    )
    if since is None:
        return page
    return filter_page(page, _active_since(since))


def chat_title(chat: dict, my_oid: str | None) -> str:
    """The other person for a 1:1 chat, else the topic, else the first few member names."""
    others = [m for m in (chat.get("members") or []) if (m.get("userId") or "") != my_oid]
    names = [m["displayName"] for m in others if m.get("displayName")]
    if chat.get("chatType") == "oneOnOne":
        return names[0] if names else (chat.get("topic") or "")
    return chat.get("topic") or ", ".join(names[:GROUP_TITLE_NAMES])


def is_unread(chat: dict) -> bool:
    """Whether the last message preview is newer than what the viewpoint says was read."""
    created = parse_graph_dt(dig(chat, "lastMessagePreview.createdDateTime"))
    if created is None:
        return False
    read = parse_graph_dt(dig(chat, "viewpoint.lastMessageReadDateTime"))
    return read is None or read < created


def get_chat(client: GraphClient, chat_id: str) -> dict:
    return client.get(odata.p("chats", chat_id), params={"$expand": "members"})


def list_chat_members(client: GraphClient, chat_id: str) -> PageResult:
    return client.paginate(
        odata.p("chats", chat_id, "members"),
        limit=None,
        all_=True,
        cap=CAP_CHAT_MEMBERS,
        page_size=None,
    )


def chat_messages(
    client: GraphClient,
    chat_id: str,
    *,
    after: datetime | None,
    before: datetime | None,
    limit: int | None,
    all_: bool,
) -> PageResult:
    """Messages in one chat, newest first, optionally narrowed to a time window.

    Graph filters chat messages on `lastModifiedDateTime` (`gt` and `lt`); `createdDateTime`
    takes only `lt`, and either way the filter is *ignored* unless `$orderby` names the same
    property. So a window switches both to `lastModifiedDateTime`; without one the order stays
    `createdDateTime desc`, which is the order a thread reads in.
    """
    params: dict[str, object] = {"$orderby": "createdDateTime desc"}
    bounds: list[str] = []
    if after is not None:
        bounds.append(f"{MESSAGE_WINDOW_FIELD} gt {to_iso_offset(after)}")
    if before is not None:
        bounds.append(f"{MESSAGE_WINDOW_FIELD} lt {to_iso_offset(before)}")
    if bounds:
        params["$orderby"] = f"{MESSAGE_WINDOW_FIELD} desc"
        params["$filter"] = " and ".join(bounds)
    page = client.paginate(
        odata.p("chats", chat_id, "messages"),
        params=params,
        limit=limit,
        all_=all_,
        cap=CAP_MESSAGES,
        page_size=PAGE_MESSAGES,
    )
    return with_routing(page, chatId=chat_id)


def message_body(body: str, html: bool) -> dict:
    """Plain text goes out as `contentType: "text"`, so nothing needs escaping (§10 quirk 9)."""
    return {"body": {"contentType": "html" if html else "text", "content": body}}


def plan_chat_send(client: GraphClient, chat_id: str, *, body: str, html: bool) -> Plan:
    url = client.url(odata.p("chats", chat_id, "messages"))
    return [PlannedRequest("POST", url, dict(JSON_HEADERS), message_body(body, html))]


def find_one_on_one(client: GraphClient, user_id: str) -> dict | None:
    """The existing 1:1 chat with `user_id`, found by paging every 1:1 chat (§10 quirk 10)."""
    page = client.paginate(
        "/me/chats",
        params={"$filter": "chatType eq 'oneOnOne'", "$expand": "members"},
        limit=None,
        all_=True,
        cap=CAP_ONE_ON_ONE,
        page_size=PAGE_CHATS,
    )
    for chat in page.items:
        if any((m.get("userId") or "") == user_id for m in chat.get("members") or []):
            return chat
    return None


def resolve_chat(client: GraphClient, value: str) -> str:
    """A `19:` id as-is, or the 1:1 chat with a UPN (§6.6)."""
    bare, _ = resolve.split_id_prefix(value)
    if resolve.looks_like_id(value, "chat"):
        return bare
    if "@" not in value:
        raise UsageError("USAGE", f"{value!r} is not a chat id or a UPN; chat ids start with '19:'")
    user = users.get_user(client, value, select=DM_SELECT)
    chat = find_one_on_one(client, user["id"])
    if chat is None:
        raise NotFoundError("NOT_FOUND", f"no 1:1 chat with {value!r}")
    return chat["id"]


def _bind(client: GraphClient, user_ref: str) -> dict:
    # The reference sits inside an OData string literal, so an apostrophe has to be doubled.
    return {
        "@odata.type": MEMBER_TYPE,
        "roles": ["owner"],
        "user@odata.bind": client.url(f"/users('{odata.odata_str(user_ref)}')"),
    }


def create_chat_body(
    client: GraphClient, *, member_ids: list[str], topic: str | None, my_oid: str
) -> dict:
    """A `POST /chats` body: one member and no topic makes a 1:1 chat, anything else a group."""
    one_on_one = len(member_ids) == 1 and not topic
    body: dict[str, object] = {"chatType": "oneOnOne" if one_on_one else "group"}
    if topic and not one_on_one:
        body["topic"] = topic
    body["members"] = [_bind(client, my_oid), *(_bind(client, ref) for ref in member_ids)]
    return body


def plan_create_chat(
    client: GraphClient, *, member_ids: list[str], topic: str | None, my_oid: str
) -> Plan:
    if not member_ids:
        raise UsageError("USAGE", "give at least one --members UPN")
    body = create_chat_body(client, member_ids=member_ids, topic=topic, my_oid=my_oid)
    return [PlannedRequest("POST", client.url("/chats"), dict(JSON_HEADERS), body)]


def plan_dm(
    client: GraphClient, user: dict | str, existing_chat: dict | None, *, body: str, html: bool
) -> Plan:
    """Both possible steps of a DM. `user` may be the raw reference and `existing_chat` None."""
    user_ref = user["id"] if isinstance(user, dict) else user
    steps: Plan = []
    if existing_chat is None:
        steps.append(
            PlannedRequest(
                "POST",
                client.url("/chats"),
                dict(JSON_HEADERS),
                create_chat_body(client, member_ids=[user_ref], topic=None, my_oid=ME_PLACEHOLDER),
                note="only when no 1:1 chat exists",
            )
        )
        send_url = client.url(f"/chats/{CHAT_ID_PLACEHOLDER}/messages")
    else:
        send_url = client.url(odata.p("chats", existing_chat["id"], "messages"))
    steps.append(PlannedRequest("POST", send_url, dict(JSON_HEADERS), message_body(body, html)))
    return steps


def run_dm(
    client: GraphClient,
    user: dict,
    *,
    body: str,
    html: bool,
    my_oid: str,
    can_create: Callable[[], None],
) -> dict:
    """Send to the existing 1:1 chat, creating one first when there is none."""
    chat = find_one_on_one(client, user["id"])
    if chat is None:
        can_create()  # Chat.Create is only needed on this branch (spec §4.4).
        plan = plan_create_chat(client, member_ids=[user["id"]], topic=None, my_oid=my_oid)
        chat = client.execute(plan[0]) or {}
    sent = dict(client.execute(plan_chat_send(client, chat["id"], body=body, html=html)[0]) or {})
    sent.setdefault("chatId", chat["id"])
    return sent


def _within(hit: dict, after: datetime | None, before: datetime | None) -> bool:
    if after is None and before is None:
        return True
    created = parse_graph_dt(dig(hit, "resource.createdDateTime"))
    if created is None:
        return False
    if after is not None and created < after:
        return False
    return before is None or created <= before


def search_chat_messages(
    client: GraphClient,
    q: str,
    *,
    after: datetime | None,
    before: datetime | None,
    limit: int,
) -> SearchResult:
    """Search chat and channel messages. The Search API has no date filter, so we apply one."""
    found = client.search(["chatMessage"], q, size=SEARCH_SIZE, limit=limit)
    hits = [h for h in found.hits if _within(h, after, before)]
    return SearchResult(
        hits=hits,
        total=found.total,
        more=found.more,
        fetched=len(found.hits),
        cap=limit,
        query={"entityTypes": "chatMessage", "query": q},
    )


def shape_chat_hit(hit: dict) -> dict:
    """Flatten one `chatMessage` search hit, naming the chat or channel it came from (quirk 16).

    `where` is the text column, a single readable string. The same routing also comes out as
    `kind`/`chatId`/`teamId`/`channelId` so a JSON consumer can follow a hit into
    `chats messages` or `teams channel messages` without parsing that string back apart —
    which is the point of the windowed channel fetch.
    """
    resource = hit.get("resource") or {}
    chat_id = resource.get("chatId")
    identity = resource.get("channelIdentity") or {}
    team_id = identity.get("teamId")
    channel_id = identity.get("channelId")
    if chat_id:
        kind, where = "chat", f"chat:{chat_id}"
    elif team_id and channel_id:
        kind, where = "channel", f"channel:{team_id}/{channel_id}"
    else:
        # A hit whose routing Graph did not supply: say so rather than emit "channel:None/None".
        kind, where = "unknown", ""
    return {
        "id": resource.get("id") or hit.get("hitId"),
        "created": resource.get("createdDateTime"),
        "from": teams.message_sender(resource),
        "kind": kind,
        "chatId": chat_id if kind == "chat" else None,
        "teamId": team_id if kind == "channel" else None,
        "channelId": channel_id if kind == "channel" else None,
        "where": where,
        # The Search API returns a snippet, never the body (spec §8.8 `search`).
        "summary": " ".join((hit.get("summary") or "").split()),
        "webUrl": resource.get("webUrl"),
    }


def hosted_content_path(chat_id: str, msg_id: str, hc_id: str) -> str:
    return odata.p("chats", chat_id, "messages", msg_id, "hostedContents", hc_id) + "/$value"


def _graph_path(url: str) -> str | None:
    """The path of a URL on our own Graph base, or None when it is anywhere else."""
    for base in (config.GRAPH_V1, config.GRAPH_BETA):
        if url.startswith(base + "/"):
            return url[len(base) :]
    return None


def _verbatim_url(url: str) -> tuple[str, str, bool]:
    """Validate a hosted-contents URL before it is sent with the bearer token attached."""
    path = _graph_path(url)
    if path is None:
        raise UsageError(
            "USAGE",
            "a hosted content URL must be on "
            f"{config.GRAPH_V1} or {config.GRAPH_BETA}; refusing to send the access token "
            "to another host",
        )
    chat = _CHAT_HOSTED_RE.match(path)
    if chat:
        return url, unquote(chat.group(1)), False
    channel = _CHANNEL_HOSTED_RE.match(path)
    if channel:
        return url, unquote(channel.group(1)), True
    raise UsageError(
        "USAGE",
        "that URL is not a /chats/… or /teams/… messages/hostedContents/<id>/$value address",
    )


def hosted_content_target(ref: str, msg_id: str | None, hc_id: str | None) -> tuple[str, str, bool]:
    """`(path or URL, hosted content id, is a channel message)` for either argument form."""
    if ref.startswith(("https://", "http://")):
        if msg_id is not None or hc_id is not None:
            raise UsageError("USAGE", "give CHAT MSGID HCID, or one hostedContents URL")
        return _verbatim_url(ref)
    if msg_id is None or hc_id is None:
        raise UsageError("USAGE", "give CHAT MSGID HCID, or one hostedContents URL")
    return hosted_content_path(ref, msg_id, hc_id), hc_id, False


def sniff_extension(data: bytes) -> str:
    """The file extension the bytes themselves imply; `bin` when nothing matches."""
    for magic, extension in _MAGIC:
        if data.startswith(magic):
            return extension
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if b"<svg" in data[:512].lower():
        return "svg"
    return "bin"


def hosted_content_name(hc_id: str, data: bytes) -> str:
    return f"{HOSTED_NAME_PREFIX}{hc_id[:HOSTED_ID_IN_NAME]}.{sniff_extension(data)}"
