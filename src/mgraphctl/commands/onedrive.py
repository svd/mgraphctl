"""OneDrive files: browse, search, up/download, organise (spec §8.11).

Every verb targets the signed-in user's own drive unless `--drive DRIVE_ID` names another one
(`shared-with-me`, `recent` and `link` are always the caller's own drive/shares, so they have no
`--drive` option). Item and folder metadata operations delegate to `mgraphctl.graph.files`.
"""

from pathlib import Path
from typing import Annotated

import typer

from mgraphctl.cli import AllFlag, JsonFlag, LimitOpt, graph_command, make_noun_app, page_bounds
from mgraphctl.graph import files, onedrive
from mgraphctl.http import GraphClient
from mgraphctl.render import (
    Column,
    FileResult,
    ListResult,
    ObjectResult,
    dig,
    fmt_dt,
    fmt_size,
    note,
)

app = make_noun_app("OneDrive files.")

DriveOpt = Annotated[str | None, typer.Option("--drive", help="Target another drive by id.")]
RefArg = Annotated[str, typer.Argument(metavar="ID|PATH", help="Item id, 'id:ID', or a path.")]

SHARED_WITH_ME_NOTE = (
    "note: /me/drive/sharedWithMe is deprecated by Microsoft and returns nothing after "
    "November 2026"
)


def _item_fields(tz: str) -> list[tuple[str, object]]:
    """`Label : value` fields for `get`/`link` (an `ObjectResult` view of one drive item)."""
    return [
        ("Name", "name"),
        ("Id", "id"),
        ("Type", lambda i: "folder" if "folder" in i else "file"),
        ("Size", lambda i: fmt_size(i.get("size"))),
        ("Modified", lambda i: fmt_dt(i.get("lastModifiedDateTime"), tz)),
        ("Web URL", "webUrl"),
        ("Parent", lambda i: dig(i, "parentReference.path")),
    ]


# --------------------------------------------------------------------------- browsing


@app.command("ls")
@graph_command(scopes=["Files.Read"])
def ls(
    client: GraphClient,
    path: Annotated[str | None, typer.Argument(metavar="PATH")] = None,
    drive: DriveOpt = None,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List the files and folders in a drive (default: the drive root)."""
    limit, all_ = page_bounds(limit, all_, default=50)
    base = onedrive.base_for(drive)
    page = files.list_children(client, base, path, limit=limit, all_=all_)
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=files.CAP_LS if all_ else None,
        columns=files.item_columns(client.tz),
    )


@app.command("search")
@graph_command(scopes=["Files.Read"])
def search(
    client: GraphClient,
    q: Annotated[str, typer.Argument(metavar="Q")],
    drive: DriveOpt = None,
    shared: Annotated[
        bool, typer.Option("--shared", help="Search everything shared with you too.")
    ] = False,
    limit: LimitOpt = None,
    json_: JsonFlag = False,
):
    """Search files and folders by name or content."""
    base = onedrive.base_for(drive)
    bound = limit if limit is not None else 50
    page = files.search_items(client, base, q, limit=bound, shared=shared)
    return ListResult(
        items=page.items, truncated=page.truncated, columns=files.item_columns(client.tz)
    )


@app.command("get")
@graph_command(scopes=["Files.Read"])
def get(
    client: GraphClient,
    ref: RefArg,
    drive: DriveOpt = None,
    json_: JsonFlag = False,
):
    """Show one file or folder's metadata."""
    base = onedrive.base_for(drive)
    item = files.get_item(client, base, ref)
    return ObjectResult(obj=item, fields=_item_fields(client.tz))


@app.command("download")
@graph_command(scopes=["Files.Read"])
def download(
    client: GraphClient,
    ref: RefArg,
    drive: DriveOpt = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Destination file (default: the item name).")
    ] = None,
    json_: JsonFlag = False,
):
    """Download a file's contents."""
    base = onedrive.base_for(drive)
    item, got = files.download_item(client, base, ref, output)
    return FileResult(
        path=got.path,
        bytes=got.bytes,
        meta=dict(contentType=got.content_type),
        message=f"Downloaded {item['name']} ({fmt_size(got.bytes)}) to {got.path}",
    )


# --------------------------------------------------------------------------- own-drive listings


@app.command("shared-with-me")
@graph_command(scopes=["Files.Read.All|Sites.Read.All"])
def shared_with_me(
    client: GraphClient,
    limit: LimitOpt = None,
    json_: JsonFlag = False,
):
    """List items other people have shared with you."""
    note(SHARED_WITH_ME_NOTE)
    bound = limit if limit is not None else 50
    page = onedrive.shared_with_me(client, limit=bound)
    tz = client.tz
    columns = [
        Column("id", "id"),
        Column("name", "name"),
        Column("size", lambda i: fmt_size(i.get("size"))),
        Column("modified", lambda i: fmt_dt(i.get("lastModifiedDateTime"), tz)),
        Column("sharedDriveId", lambda i: dig(i, "remoteItem.parentReference.driveId") or ""),
        Column("sharedItemId", lambda i: dig(i, "remoteItem.id") or ""),
    ]
    return ListResult(items=page.items, truncated=page.truncated, columns=columns)


@app.command("recent")
@graph_command(scopes=["Files.Read"])
def recent(
    client: GraphClient,
    limit: LimitOpt = None,
    json_: JsonFlag = False,
):
    """List recently used files."""
    bound = limit if limit is not None else 20
    page = onedrive.recent(client, limit=bound)
    return ListResult(
        items=page.items, truncated=page.truncated, columns=files.item_columns(client.tz)
    )


@app.command("link")
@graph_command(scopes=["Files.Read"])
def link(
    client: GraphClient,
    url: Annotated[
        str, typer.Argument(metavar="URL", help="A OneDrive or SharePoint sharing link.")
    ],
    download: Annotated[
        bool, typer.Option("--download", help="Download the item's content.")
    ] = False,
    output: Annotated[
        Path | None, typer.Option("--output", help="Destination file for --download.")
    ] = None,
    json_: JsonFlag = False,
):
    """Resolve a sharing link to the item it points at."""
    if download:
        item, got = files.download_shared_item(client, url, output)
        return FileResult(
            path=got.path,
            bytes=got.bytes,
            meta=dict(contentType=got.content_type),
            message=f"Downloaded {item['name']} ({fmt_size(got.bytes)}) to {got.path}",
        )
    item = files.get_shared_item(client, url)
    return ObjectResult(obj=item, fields=_item_fields(client.tz))
