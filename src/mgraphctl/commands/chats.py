"""Teams chat commands (spec §8.8)."""

from typing import Annotated

import typer

from mgraphctl import auth, errors
from mgraphctl.cli import (
    AllFlag,
    DryRunFlag,
    JsonFlag,
    LimitOpt,
    gate,
    graph_command,
    make_noun_app,
    page_bounds,
)
from mgraphctl.errors import AuthError
from mgraphctl.graph import chats, teams, users
from mgraphctl.http import GraphClient
from mgraphctl.render import (
    Column,
    DryRunResult,
    ListResult,
    ObjectResult,
    WriteResult,
    fmt_dt,
    parse_dt,
    truncate,
)

CREATE_SCOPES = ["Chat.Create"]

ChatArg = Annotated[str, typer.Argument(metavar="CHAT", help="Chat id (19:…) or a UPN.")]
BodyOpt = Annotated[str | None, typer.Option("--body", help="Message text.")]
BodyFileOpt = Annotated[
    str | None, typer.Option("--body-file", help="File holding the text, or - for stdin.")
]
HtmlFlag = Annotated[bool, typer.Option("--html", help="Send the body as HTML.")]

app = make_noun_app("Teams chats and direct messages.")


def my_oid() -> str:
    """The signed-in user's object id, read from the cached token (spec §8.9, no `/me` call)."""
    oid = auth.decode_jwt(auth.cached_access_token() or "").get("oid")
    if not oid:
        raise AuthError(
            "NOT_LOGGED_IN",
            "the cached token carries no oid claim",
            hint=errors.HINTS["NOT_LOGGED_IN"],
        )
    return oid


@app.command("list")
@graph_command(scopes=["Chat.Read"])
def list_(
    client: GraphClient,
    unread: Annotated[bool, typer.Option("--unread", help="Only chats with unread mail.")] = False,
    chat_type: Annotated[
        str | None, typer.Option("--type", help="oneOnOne, group or meeting.")
    ] = None,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List your chats, most recently active first."""
    limit, all_ = page_bounds(limit, all_, default=20)
    page = chats.list_chats(
        client, chat_type=chats.normalise_chat_type(chat_type), limit=limit, all_=all_
    )
    items = [c for c in page.items if chats.is_unread(c)] if unread else page.items
    oid = my_oid()
    tz = client.tz
    return ListResult(
        items=items,
        truncated=page.truncated,
        hit_cap=chats.CAP_CHATS if all_ else None,
        empty_text="No chats.",
        columns=[
            Column("id", "id"),
            Column("flags", lambda c: "*" if chats.is_unread(c) else ""),
            Column("type", "chatType"),
            Column("updated", lambda c: fmt_dt(c.get("lastUpdatedDateTime"), tz)),
            Column("title", lambda c: truncate(chats.chat_title(c, oid))),
        ],
    )


@app.command("get")
@graph_command(scopes=["Chat.Read"])
def get(client: GraphClient, chat: ChatArg, json_: JsonFlag = False):
    """Show one chat."""
    chat_id = chats.resolve_chat(client, chat)
    oid = my_oid()
    tz = client.tz
    return ObjectResult(
        obj=chats.get_chat(client, chat_id),
        fields=[
            ("Title", lambda c: chats.chat_title(c, oid)),
            ("Type", "chatType"),
            ("Updated", lambda c: fmt_dt(c.get("lastUpdatedDateTime"), tz)),
            ("Web URL", "webUrl"),
            ("Chat id", "id"),
        ],
    )


@app.command("members")
@graph_command(scopes=["Chat.Read"])
def members(client: GraphClient, chat: ChatArg, json_: JsonFlag = False):
    """List a chat's members."""
    chat_id = chats.resolve_chat(client, chat)
    page = chats.list_chat_members(client, chat_id)
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        empty_text="No members.",
        columns=[
            Column("id", "id"),
            Column("name", "displayName"),
            Column("email", "email"),
            Column("userId", "userId"),
        ],
    )


@app.command("messages")
@graph_command(scopes=["Chat.Read"])
def messages(
    client: GraphClient,
    chat: ChatArg,
    after: Annotated[
        str | None, typer.Option("--after", metavar="DT", help="Only messages after this time.")
    ] = None,
    full: Annotated[
        bool, typer.Option("--full", help="Print whole bodies, not 300 chars.")
    ] = False,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List chat messages, oldest first in text mode."""
    limit, all_ = page_bounds(limit, all_, default=20)
    since = parse_dt(after, client.tz) if after else None
    chat_id = chats.resolve_chat(client, chat)
    page = chats.chat_messages(client, chat_id, after=since, limit=limit, all_=all_)
    # JSON keeps the Graph order (newest first); text reads better oldest first (§10 quirk 17).
    # A chat message is the same Graph resource as a channel message, rendered by `graph.teams`.
    return ListResult(
        items=page.items if json_ else list(reversed(page.items)),
        truncated=page.truncated,
        hit_cap=chats.CAP_MESSAGES if all_ else None,
        empty_text="No messages.",
        columns=teams.message_columns(client.tz, full),
    )


@app.command("send")
@graph_command(scopes=["ChatMessage.Send"])
def send(
    client: GraphClient,
    chat: ChatArg,
    body: BodyOpt = None,
    body_file: BodyFileOpt = None,
    html: HtmlFlag = False,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Send a message to a chat."""
    text = teams.read_body(body, body_file)
    chat_id = chats.resolve_chat(client, chat)
    plan = chats.plan_chat_send(client, chat_id, body=text, html=html)
    if dry_run:
        return DryRunResult(plan)
    return WriteResult(obj=client.execute(plan[0]), message="Sent.")


@app.command("dm")
@graph_command(scopes=["Chat.Read", "ChatMessage.Send"])
def dm(
    client: GraphClient,
    user: Annotated[str, typer.Argument(metavar="USER", help="UPN, user id, or 'me'.")],
    body: BodyOpt = None,
    body_file: BodyFileOpt = None,
    html: HtmlFlag = False,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Send a direct message, creating the 1:1 chat when there is none yet."""
    text = teams.read_body(body, body_file)
    if dry_run:
        # Both branches are shown; looking the chat up would be a request (spec §8.8).
        return DryRunResult(chats.plan_dm(client, user, None, body=text, html=html))
    who = users.get_user(client, user, select=chats.DM_SELECT)
    sent = chats.run_dm(
        client,
        who,
        body=text,
        html=html,
        my_oid=my_oid(),
        can_create=lambda: gate(CREATE_SCOPES),
    )
    return WriteResult(obj=sent, message="Sent.")


@app.command("create")
@graph_command(scopes=CREATE_SCOPES)
def create(
    client: GraphClient,
    member: Annotated[
        list[str] | None,
        typer.Option("--members", help="UPN or user id to add (repeatable, at least one)."),
    ] = None,
    topic: Annotated[str | None, typer.Option("--topic", help="Group chat topic.")] = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Create a chat with the given members."""
    plan = chats.plan_create_chat(client, member_ids=member or [], topic=topic, my_oid=my_oid())
    if dry_run:
        return DryRunResult(plan)
    created = client.execute(plan[0]) or {}
    return WriteResult(obj=created, message=f"Created chat {created.get('id')}.")
