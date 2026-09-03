"""Graph operations for Teams chats and direct messages (spec §8.8).

Pure: client and parameters in, Graph dicts, a `PageResult` or a `Plan` out.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime

from mgraphctl import odata, resolve
from mgraphctl.errors import NotFoundError, UsageError
from mgraphctl.graph import users
from mgraphctl.http import GraphClient, PageResult, Plan, PlannedRequest
from mgraphctl.render import dig, to_iso_offset

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
PAGE_MESSAGES, CAP_MESSAGES = 50, 200
CAP_ONE_ON_ONE = 500
JSON = {"Content-Type": "application/json"}

_FRACTIONAL_RE = re.compile(r"(\.\d{6})\d+")


def _instant(value: str | None) -> datetime | None:
    """A Graph UTC timestamp as an aware datetime, or None when it is absent or unparsable."""
    if not value:
        return None
    text = _FRACTIONAL_RE.sub(r"\1", value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def normalise_chat_type(value: str | None) -> str | None:
    """Fold `--type` onto the Graph spelling; anything else is a usage error."""
    if value is None:
        return None
    for known in CHAT_TYPES:
        if known.casefold() == value.casefold():
            return known
    raise UsageError("USAGE", f"unknown chat type {value!r}; use one of {', '.join(CHAT_TYPES)}")


def list_chats(
    client: GraphClient, *, chat_type: str | None, limit: int | None, all_: bool
) -> PageResult:
    params: dict[str, object] = {
        "$expand": CHAT_EXPAND,
        "$orderby": CHAT_ORDER,
        "$select": CHAT_SELECT,
    }
    if chat_type:
        params["$filter"] = f"chatType eq '{odata.odata_str(chat_type)}'"
    return client.paginate(
        "/me/chats",
        params=params,
        limit=limit,
        all_=all_,
        cap=CAP_CHATS,
        page_size=PAGE_CHATS,
    )


def chat_title(chat: dict, my_oid: str | None) -> str:
    """The other person for a 1:1 chat, else the topic, else the first few member names."""
    others = [m for m in (chat.get("members") or []) if (m.get("userId") or "") != my_oid]
    names = [m["displayName"] for m in others if m.get("displayName")]
    if chat.get("chatType") == "oneOnOne":
        return names[0] if names else (chat.get("topic") or "")
    return chat.get("topic") or ", ".join(names[:GROUP_TITLE_NAMES])


def is_unread(chat: dict) -> bool:
    """Whether the last message preview is newer than what the viewpoint says was read."""
    created = _instant(dig(chat, "lastMessagePreview.createdDateTime"))
    if created is None:
        return False
    read = _instant(dig(chat, "viewpoint.lastMessageReadDateTime"))
    return read is None or read < created


def get_chat(client: GraphClient, chat_id: str) -> dict:
    return client.get(odata.p("chats", chat_id), params={"$expand": "members"})


def list_chat_members(client: GraphClient, chat_id: str) -> PageResult:
    return client.paginate(
        odata.p("chats", chat_id, "members"),
        limit=None,
        all_=True,
        cap=CAP_CHATS,
        page_size=None,
    )


def chat_messages(
    client: GraphClient, chat_id: str, *, after: datetime | None, limit: int | None, all_: bool
) -> PageResult:
    params: dict[str, object] = {"$orderby": "createdDateTime desc"}
    if after is not None:
        params["$filter"] = f"createdDateTime gt {to_iso_offset(after)}"
    return client.paginate(
        odata.p("chats", chat_id, "messages"),
        params=params,
        limit=limit,
        all_=all_,
        cap=CAP_MESSAGES,
        page_size=PAGE_MESSAGES,
    )


def message_body(body: str, html: bool) -> dict:
    """Plain text goes out as `contentType: "text"`, so nothing needs escaping (§10 quirk 9)."""
    return {"body": {"contentType": "html" if html else "text", "content": body}}


def plan_chat_send(client: GraphClient, chat_id: str, *, body: str, html: bool) -> Plan:
    url = client.url(odata.p("chats", chat_id, "messages"))
    return [PlannedRequest("POST", url, dict(JSON), message_body(body, html))]


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
    return {
        "@odata.type": MEMBER_TYPE,
        "roles": ["owner"],
        "user@odata.bind": client.url(f"/users('{user_ref}')"),
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
    return [PlannedRequest("POST", client.url("/chats"), dict(JSON), body)]


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
                dict(JSON),
                create_chat_body(client, member_ids=[user_ref], topic=None, my_oid=ME_PLACEHOLDER),
                note="only when no 1:1 chat exists",
            )
        )
        send_url = client.url(f"/chats/{CHAT_ID_PLACEHOLDER}/messages")
    else:
        send_url = client.url(odata.p("chats", existing_chat["id"], "messages"))
    steps.append(PlannedRequest("POST", send_url, dict(JSON), message_body(body, html)))
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
