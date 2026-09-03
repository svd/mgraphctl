"""Teams presence commands (spec §8.9)."""

from typing import Annotated

import typer

from mgraphctl.cli import DryRunFlag, JsonFlag, gate, graph_command, make_noun_app
from mgraphctl.graph import presence as presence_api
from mgraphctl.graph import users
from mgraphctl.http import GraphClient
from mgraphctl.render import (
    Column,
    DryRunResult,
    ListResult,
    ObjectResult,
    WriteResult,
    dig,
    parse_duration,
)

OTHERS_SCOPES = ["Presence.Read.All"]
STATES = ", ".join(presence_api.PRESENCE_PAIRS)

app = make_noun_app("Teams presence.")


@app.command("get")
@graph_command(scopes=["Presence.Read"])
def get(
    client: GraphClient,
    user: Annotated[
        list[str] | None,
        typer.Argument(metavar="[USER...]", help="UPNs or user ids; omit for yourself."),
    ] = None,
    json_: JsonFlag = False,
):
    """Show your presence, or that of the given users."""
    if not user:
        return ObjectResult(
            obj=presence_api.get_presence(client),
            fields=[
                ("Availability", "availability"),
                ("Activity", "activity"),
                ("Status", lambda p: dig(p, "statusMessage.message.content")),
                ("User id", "id"),
            ],
        )
    gate(OTHERS_SCOPES)  # Reading anyone else needs the on-demand scope (spec §4.4).
    people = [users.get_user(client, ref, select="id,displayName") for ref in user]
    names = {p["id"]: p.get("displayName") for p in people}
    return ListResult(
        items=presence_api.get_presences(client, [p["id"] for p in people]),
        empty_text="No presence information.",
        columns=[
            Column("id", "id"),
            Column("name", lambda p: names.get(p.get("id"), "")),
            Column("availability", "availability"),
            Column("activity", "activity"),
        ],
    )


@app.command("set")
@graph_command(scopes=["Presence.ReadWrite"])
def set_(
    client: GraphClient,
    state: Annotated[str, typer.Argument(metavar="STATE", help=f"One of {STATES}.")],
    expiration: Annotated[
        str, typer.Option("--expiration", help="How long it lasts (30m, 2h, PT1H).")
    ] = "1h",
    message: Annotated[
        str | None, typer.Option("--message", help="Status message to show alongside it.")
    ] = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Set your preferred presence."""
    availability, _ = presence_api.resolve_pair(state)
    plan = presence_api.plan_set(
        client,
        presence_api.my_oid(),
        state,
        expiration=parse_duration(expiration),
        message=message,
    )
    if dry_run:
        return DryRunResult(plan)
    for step in plan:
        client.execute(step)
    return WriteResult(obj=None, message=f"Presence set to {availability}.")


@app.command("clear")
@graph_command(scopes=["Presence.ReadWrite"])
def clear(client: GraphClient, dry_run: DryRunFlag = False, json_: JsonFlag = False):
    """Clear your preferred presence, handing it back to Teams."""
    plan = presence_api.plan_clear(client, presence_api.my_oid())
    if dry_run:
        return DryRunResult(plan)
    client.execute(plan[0])
    return WriteResult(obj=None, message="Preferred presence cleared.")
