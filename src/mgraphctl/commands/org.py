"""Manager, direct reports and the management chain (spec §8.6)."""

from typing import Annotated

import typer

from mgraphctl.cli import (
    AllFlag,
    JsonFlag,
    LimitOpt,
    gate,
    graph_command,
    make_noun_app,
    page_bounds,
)
from mgraphctl.errors import GraphError
from mgraphctl.graph import org
from mgraphctl.http import GraphClient
from mgraphctl.render import Column, ListResult, ObjectResult, TextResult

app = make_noun_app("Manager, direct reports, management chain.")

MANAGER_FIELDS = [
    ("Name", "displayName"),
    ("UPN", "userPrincipalName"),
    ("Mail", "mail"),
    ("Title", "jobTitle"),
    ("Dept", "department"),
    ("User id", "id"),
]


def _chain_line(level: int, person: dict) -> str:
    upn = person.get("userPrincipalName") or ""
    title = person.get("jobTitle")
    suffix = f" — {title}" if title else ""
    return f"{level}: {person.get('displayName')} <{upn}>{suffix}"


@app.command("manager")
@graph_command(scopes=["User.Read"])
def manager(
    client: GraphClient,
    upn: Annotated[str | None, typer.Argument(metavar="UPN")] = None,
    json_: JsonFlag = False,
):
    """Show a user's manager (self by default)."""
    if upn is not None:
        gate(["User.Read.All"])
    return ObjectResult(obj=org.manager(client, upn), fields=list(MANAGER_FIELDS))


@app.command("reports")
@graph_command(scopes=["User.Read"])
def reports(
    client: GraphClient,
    upn: Annotated[str | None, typer.Argument(metavar="UPN")] = None,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List a user's direct reports (self by default)."""
    if upn is not None:
        gate(["User.Read.All"])
    limit, all_ = page_bounds(limit, all_, default=20)
    page = org.reports(client, upn, limit=limit, all_=all_)
    return ListResult(
        items=page.items,
        page=page,
        hit_cap=org.CAP if all_ else None,
        columns=[
            Column("id", "id"),
            Column("name", "displayName"),
            Column("upn", "userPrincipalName"),
            Column("mail", "mail"),
            Column("title", "jobTitle"),
            Column("department", "department"),
        ],
    )


@app.command("chain")
@graph_command(scopes=["User.Read"])
def chain(
    client: GraphClient,
    upn: Annotated[str | None, typer.Argument(metavar="UPN")] = None,
    max_: Annotated[int, typer.Option("--max", min=1, help="Maximum levels to climb.")] = 10,
    json_: JsonFlag = False,
):
    """Show the management chain from the user upward (self by default)."""
    try:
        levels = org.chain_expand(client, upn, max_levels=max_)
    except GraphError as exc:
        if exc.status not in (400, 403):
            raise
        gate(["User.Read.All"])
        levels = org.chain_iterative(client, upn, max_levels=max_)
    text = "\n".join(_chain_line(i, person) for i, person in enumerate(levels))
    return TextResult(
        text=text,
        json_obj={"items": levels, "count": len(levels), "truncated": False},
    )
