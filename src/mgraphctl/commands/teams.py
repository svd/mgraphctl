"""Teams and channel commands (spec §8.7)."""

from typing import Annotated

import typer

from mgraphctl.cli import (
    AllFlag,
    DryRunFlag,
    JsonFlag,
    LimitOpt,
    graph_command,
    make_noun_app,
    page_bounds,
    read_body,
)
from mgraphctl.errors import UsageError
from mgraphctl.graph import teams
from mgraphctl.http import GraphClient
from mgraphctl.render import Column, DryRunResult, ListResult, ObjectResult, WriteResult, truncate

READ_TEAM = ["Team.ReadBasic.All|Group.Read.All"]
READ_CHANNEL = ["Channel.ReadBasic.All|Group.Read.All"]

TeamArg = Annotated[str, typer.Argument(metavar="TEAM", help="Team GUID or display name.")]
ChannelArg = Annotated[
    str, typer.Argument(metavar="CHANNEL", help="Channel id (19:…) or display name.")
]

TEAM_FIELDS = [
    ("Name", "displayName"),
    ("Description", "description"),
    ("Visibility", "visibility"),
    ("Web URL", "webUrl"),
    ("Team id", "id"),
]

CHANNEL_FIELDS = [
    ("Name", "displayName"),
    ("Description", "description"),
    ("Membership", "membershipType"),
    ("Web URL", "webUrl"),
    ("Channel id", "id"),
]

app = make_noun_app("Teams and channels.")
channel = make_noun_app("Channels within a team.")
app.add_typer(channel, name="channel")


@app.command("list")
@graph_command(scopes=READ_TEAM)
def list_(client: GraphClient, json_: JsonFlag = False):
    """List the teams you belong to."""
    page = teams.list_teams(client)
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=teams.CAP_TEAMS,
        empty_text="No teams.",
        columns=[
            Column("id", "id"),
            Column("name", "displayName"),
            Column("description", lambda t: truncate(t.get("description"))),
        ],
    )


@app.command("get")
@graph_command(scopes=READ_TEAM)
def get(client: GraphClient, team: TeamArg, json_: JsonFlag = False):
    """Show one team."""
    team_id = teams.resolve_team(client, team)["id"]
    return ObjectResult(obj=teams.get_team(client, team_id), fields=list(TEAM_FIELDS))


@app.command("members")
@graph_command(scopes=["TeamMember.Read.All"])
def members(
    client: GraphClient,
    team: TeamArg,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List a team's members."""
    limit, all_ = page_bounds(limit, all_, default=100)
    team_id = teams.resolve_team(client, team)["id"]
    page = teams.list_members(client, team_id, limit=limit, all_=all_)
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=teams.CAP_MEMBERS if all_ else None,
        empty_text="No members.",
        columns=[
            Column("id", "id"),
            Column("name", "displayName"),
            Column("email", "email"),
            Column("roles", "roles"),
        ],
    )


@app.command("channels")
@graph_command(scopes=READ_CHANNEL)
def channels(client: GraphClient, team: TeamArg, json_: JsonFlag = False):
    """List a team's channels."""
    team_id = teams.resolve_team(client, team)["id"]
    page = teams.list_channels(client, team_id)
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=teams.CAP_CHANNELS,
        empty_text="No channels.",
        columns=[
            Column("id", "id"),
            Column("name", "displayName"),
            Column("membership", "membershipType"),
            Column("description", lambda c: truncate(c.get("description"))),
        ],
    )


@channel.command("get")
@graph_command(scopes=READ_CHANNEL)
def channel_get(client: GraphClient, team: TeamArg, chan: ChannelArg, json_: JsonFlag = False):
    """Show one channel."""
    team_id = teams.resolve_team(client, team)["id"]
    channel_id = teams.resolve_channel(client, team_id, chan)["id"]
    return ObjectResult(
        obj=teams.get_channel(client, team_id, channel_id), fields=list(CHANNEL_FIELDS)
    )


@channel.command("messages")
@graph_command(scopes=["ChannelMessage.Read.All"])
def channel_messages(
    client: GraphClient,
    team: TeamArg,
    chan: ChannelArg,
    full: Annotated[
        bool, typer.Option("--full", help="Print whole bodies, not 300 chars.")
    ] = False,
    with_replies: Annotated[
        bool, typer.Option("--with-replies", help="Expand each message's replies.")
    ] = False,
    replies: Annotated[
        str | None,
        typer.Option("--replies", metavar="MSGID", help="List the replies to one message."),
    ] = None,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List channel messages, oldest first in text mode."""
    if replies is not None and with_replies:
        raise UsageError("USAGE", "--replies and --with-replies are mutually exclusive")
    limit, all_ = page_bounds(limit, all_, default=20)
    team_id = teams.resolve_team(client, team)["id"]
    channel_id = teams.resolve_channel(client, team_id, chan)["id"]
    if replies is not None:
        page = teams.channel_replies(client, team_id, channel_id, replies, limit=limit, all_=all_)
    else:
        page = teams.channel_messages(
            client, team_id, channel_id, with_replies=with_replies, limit=limit, all_=all_
        )
    # JSON keeps the Graph order (newest first); text reads better oldest first (§10 quirk 17).
    return ListResult(
        items=page.items if json_ else list(reversed(page.items)),
        truncated=page.truncated,
        hit_cap=teams.CAP_MESSAGES if all_ else None,
        empty_text="No messages.",
        columns=teams.message_columns(client.tz, full),
    )


@channel.command("send")
@graph_command(scopes=["ChannelMessage.Send"])
def channel_send(
    client: GraphClient,
    team: TeamArg,
    chan: ChannelArg,
    body: Annotated[str | None, typer.Option("--body", help="Message text.")] = None,
    body_file: Annotated[
        str | None, typer.Option("--body-file", help="File holding the text, or - for stdin.")
    ] = None,
    html: Annotated[bool, typer.Option("--html", help="Send the body as HTML.")] = False,
    subject: Annotated[str | None, typer.Option("--subject", help="Message subject.")] = None,
    reply_to: Annotated[
        str | None, typer.Option("--reply-to", metavar="MSGID", help="Reply in this thread.")
    ] = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Post a message to a channel."""
    text = read_body(body, body_file)
    team_id = teams.resolve_team(client, team)["id"]
    channel_id = teams.resolve_channel(client, team_id, chan)["id"]
    plan = teams.plan_channel_send(
        client, team_id, channel_id, body=text, html=html, subject=subject, reply_to=reply_to
    )
    if dry_run:
        return DryRunResult(plan)
    return WriteResult(obj=client.execute(plan[0]), message="Sent.")
