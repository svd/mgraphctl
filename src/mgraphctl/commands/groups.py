"""Microsoft 365 groups (spec §8.16)."""

from typing import Annotated

import typer

from mgraphctl.cli import AllFlag, JsonFlag, LimitOpt, graph_command, make_noun_app, page_bounds
from mgraphctl.graph import groups
from mgraphctl.http import GraphClient
from mgraphctl.render import Column, ListResult

app = make_noun_app("Microsoft 365 groups.")


@app.command("list")
@graph_command(scopes=["User.Read"])
def list_(
    client: GraphClient,
    unified: Annotated[bool, typer.Option("--unified", help="Only Microsoft 365 groups.")] = False,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List the groups the signed-in user belongs to."""
    limit, all_ = page_bounds(limit, all_, default=20)
    page = groups.list_groups(client, unified=unified, limit=limit, all_=all_)
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=groups.CAP if all_ else None,
        columns=[
            Column("id", "id"),
            Column("name", "displayName"),
            Column("mail", "mail"),
            Column("types", "groupTypes"),
            Column("description", "description"),
        ],
    )


@app.command("members")
@graph_command(scopes=["Group.Read.All"])
def members(
    client: GraphClient,
    group: Annotated[str, typer.Argument(metavar="GROUP")],
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List a group's members, by group name or id."""
    limit, all_ = page_bounds(limit, all_, default=20)
    resolved = groups.resolve_group(client, group)
    page = groups.list_members(client, resolved["id"], limit=limit, all_=all_)
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=groups.CAP if all_ else None,
        columns=[
            Column("id", "id"),
            Column("name", "displayName"),
            Column("upn", "userPrincipalName"),
            Column("mail", "mail"),
            Column("title", "jobTitle"),
        ],
    )
