"""Teams chat commands (spec §8.8)."""

from pathlib import Path
from typing import Annotated

import typer

from mgraphctl import auth
from mgraphctl.cli import (
    AllFlag,
    DryRunFlag,
    JsonFlag,
    LimitOpt,
    gate,
    graph_command,
    make_noun_app,
    page_bounds,
    read_body,
)
from mgraphctl.graph import chats, teams, users
from mgraphctl.http import GraphClient
from mgraphctl.render import (
    Column,
    DryRunResult,
    FileResult,
    ListResult,
    ObjectResult,
    WriteResult,
    fmt_dt,
    fmt_size,
    parse_dt,
    truncate,
)

CREATE_SCOPES = ["Chat.Create"]
CHANNEL_SCOPES = ["ChannelMessage.Read.All"]

ChatArg = Annotated[str, typer.Argument(metavar="CHAT", help="Chat id (19:…) or a UPN.")]
BodyOpt = Annotated[str | None, typer.Option("--body", help="Message text.")]
BodyFileOpt = Annotated[
    str | None, typer.Option("--body-file", help="File holding the text, or - for stdin.")
]
HtmlFlag = Annotated[bool, typer.Option("--html", help="Send the body as HTML.")]

app = make_noun_app("Teams chats and direct messages.")


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
    oid = auth.my_oid()
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
    oid = auth.my_oid()
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
    text = read_body(body, body_file)
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
    text = read_body(body, body_file)
    if dry_run:
        # Both branches are shown; looking the chat up would be a request (spec §8.8).
        return DryRunResult(chats.plan_dm(client, user, None, body=text, html=html))
    who = users.get_user(client, user, select=chats.DM_SELECT)
    sent = chats.run_dm(
        client,
        who,
        body=text,
        html=html,
        my_oid=auth.my_oid(),
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
    plan = chats.plan_create_chat(
        client, member_ids=member or [], topic=topic, my_oid=auth.my_oid()
    )
    if dry_run:
        return DryRunResult(plan)
    created = client.execute(plan[0]) or {}
    return WriteResult(obj=created, message=f"Created chat {created.get('id')}.")


@app.command("search")
@graph_command(scopes=["Chat.Read"])
def search(
    client: GraphClient,
    q: Annotated[str, typer.Argument(metavar="Q", help="What to look for.")],
    after: Annotated[
        str | None, typer.Option("--after", metavar="DT", help="Only hits after this time.")
    ] = None,
    before: Annotated[
        str | None, typer.Option("--before", metavar="DT", help="Only hits before this time.")
    ] = None,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """Search your chat and channel messages. Hits carry a snippet, not the whole body."""
    limit, all_ = page_bounds(limit, all_, default=25)
    tz = client.tz
    found = chats.search_chat_messages(
        client,
        q,
        after=parse_dt(after, tz) if after else None,
        before=parse_dt(before, tz, end_of_day=True) if before else None,
        limit=chats.CAP_SEARCH if all_ else limit,
    )
    return ListResult(
        items=[chats.shape_chat_hit(hit) for hit in found.hits],
        truncated=found.more,
        hit_cap=chats.CAP_SEARCH if all_ else None,
        empty_text="No messages found.",
        columns=[
            Column("id", "id"),
            Column("created", lambda h: fmt_dt(h.get("created"), tz)),
            Column("from", "from"),
            Column("where", "where"),
            Column("summary", lambda h: truncate(h.get("summary"))),
        ],
    )


@app.command("hosted-content")
@graph_command(scopes=["Chat.Read"])
def hosted_content(
    client: GraphClient,
    chat: Annotated[
        str, typer.Argument(metavar="CHAT|URL", help="Chat id, or a full hostedContents URL.")
    ],
    msg_id: Annotated[str | None, typer.Argument(metavar="[MSGID]", help="Message id.")] = None,
    hc_id: Annotated[
        str | None, typer.Argument(metavar="[HCID]", help="Hosted content id.")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Where to write it; default is sniffed.")
    ] = None,
    json_: JsonFlag = False,
):
    """Download an image or file hosted inside a Teams message."""
    target, hosted_id, is_channel = chats.hosted_content_target(chat, msg_id, hc_id)
    if is_channel:
        gate(CHANNEL_SCOPES)  # A channel URL reads channel messages, not chats (spec §8.8).
    # The name's extension comes from the bytes, so they are read before the file is opened.
    data = client.request("GET", target, expect="bytes") or b""
    dest = output or Path(chats.hosted_content_name(hosted_id, data))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return FileResult(
        path=dest,
        bytes=len(data),
        meta={},
        message=f"Downloaded {dest.name} ({fmt_size(len(data))}) to {dest}",
    )
