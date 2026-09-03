"""Unified search across Microsoft 365 (spec §8.17). Registered as a top-level command."""

from typing import Annotated

import typer

from mgraphctl.cli import AllFlag, JsonFlag, LimitOpt, gate, graph_command, page_bounds
from mgraphctl.graph import search as search_ops
from mgraphctl.http import GraphClient
from mgraphctl.render import ListResult, parse_dt


def _split_fields(value: str | None) -> list[str] | None:
    if value is None:
        return None
    fields = [f.strip() for f in value.split(",") if f.strip()]
    return fields or None


@graph_command(scopes=[])  # the scope depends on --type; gated at runtime below (spec §8.17)
def command(
    client: GraphClient,
    q: Annotated[str, typer.Argument(metavar="Q", help="What to search for.")],
    type_: Annotated[
        str,
        typer.Option(
            "--type", help="message, event, driveItem, site, list, chatMessage, or person."
        ),
    ] = "message",
    after: Annotated[
        str | None, typer.Option("--after", metavar="DT", help="Only hits after this time.")
    ] = None,
    before: Annotated[
        str | None, typer.Option("--before", metavar="DT", help="Only hits before this time.")
    ] = None,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    fields: Annotated[
        str | None, typer.Option("--fields", help="Comma-separated Graph fields to fetch.")
    ] = None,
    json_: JsonFlag = False,
):
    """Search mail, calendar, files, sites, chats or people with the Microsoft Search API."""
    entity_type = search_ops.normalise_entity_type(type_)
    gate(search_ops.SCOPES_BY_TYPE[entity_type])
    limit, all_ = page_bounds(limit, all_, default=search_ops.DEFAULT_LIMIT)
    tz = client.tz
    found = search_ops.search(
        client,
        entity_type=entity_type,
        q=q,
        after=parse_dt(after, tz) if after else None,
        before=parse_dt(before, tz, end_of_day=True) if before else None,
        limit=limit,
        all_=all_,
        fields=_split_fields(fields),
        tz=tz,
    )
    return ListResult(
        items=[search_ops.shape_hit(entity_type, hit) for hit in found.hits],
        truncated=found.more,
        hit_cap=search_ops.CAP_SEARCH if all_ else None,
        empty_text="No results.",
        columns=search_ops.columns_for(entity_type, tz),
    )
