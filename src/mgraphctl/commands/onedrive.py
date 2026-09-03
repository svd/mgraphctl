"""OneDrive files: browse, search, up/download, organise (spec §8.11).

Every verb targets the signed-in user's own drive unless `--drive DRIVE_ID` names another one
(`shared-with-me`, `recent` and `link` are always the caller's own drive/shares, so they have no
`--drive` option). Item and folder metadata operations delegate to `mgraphctl.graph.files`.
"""

from pathlib import Path
from typing import Annotated, Literal

import typer

from mgraphctl.cli import (
    AllFlag,
    DryRunFlag,
    JsonFlag,
    LimitOpt,
    graph_command,
    make_noun_app,
    page_bounds,
)
from mgraphctl.graph import files, onedrive
from mgraphctl.http import GraphClient
from mgraphctl.render import (
    Column,
    DryRunResult,
    FileResult,
    ListResult,
    ObjectResult,
    WriteResult,
    dig,
    fmt_dt,
    fmt_size,
    note,
    parse_dt,
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
        items=page.items,
        truncated=page.truncated,
        supports_all=False,
        columns=files.item_columns(client.tz),
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


# --------------------------------------------------------------------------- writes


@app.command("upload")
@graph_command(scopes=["Files.ReadWrite"])
def upload(
    client: GraphClient,
    file: Annotated[
        Path,
        typer.Argument(metavar="FILE", help="Local file to upload.", exists=True, dir_okay=False),
    ],
    drive: DriveOpt = None,
    dest: Annotated[
        str | None,
        typer.Option(
            "--dest", help="Destination path (default: /<basename>; trailing / = folder)."
        ),
    ] = None,
    conflict: Annotated[
        Literal["rename", "replace", "fail"], typer.Option("--conflict", help="On a name clash.")
    ] = "replace",
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Upload a local file (simple PUT under 4 MiB, an upload session above it)."""
    base = onedrive.base_for(drive)
    if dry_run:
        return DryRunResult(files.plan_upload(client, base, file, dest, conflict))
    item = files.run_upload(client, base, file, dest, conflict)
    return WriteResult(obj=item, message=f"Uploaded {file.name}.")


@app.command("mkdir")
@graph_command(scopes=["Files.ReadWrite"])
def mkdir(
    client: GraphClient,
    path: Annotated[str, typer.Argument(metavar="PATH")],
    drive: DriveOpt = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Create a folder."""
    base = onedrive.base_for(drive)
    if dry_run:
        return DryRunResult(files.plan_mkdir(client, base, path))
    item = files.run_mkdir(client, base, path)
    return WriteResult(obj=item, message=f"Created {item.get('name', path)}.")


@app.command("move")
@graph_command(scopes=["Files.ReadWrite"])
def move(
    client: GraphClient,
    ref: RefArg,
    to: Annotated[str, typer.Option("--to", help="Destination folder path, or 'id:ID'.")] = ...,
    drive: DriveOpt = None,
    name: Annotated[str | None, typer.Option("--name", help="Rename while moving.")] = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Move (and optionally rename) a file or folder."""
    base = onedrive.base_for(drive)
    if dry_run:
        return DryRunResult(files.plan_move(client, base, ref, to, name))
    item = files.run_move(client, base, ref, to, name)
    return WriteResult(obj=item, message=f"Moved {ref} to {to}.")


@app.command("rename")
@graph_command(scopes=["Files.ReadWrite"])
def rename(
    client: GraphClient,
    ref: RefArg,
    name: Annotated[str, typer.Argument(metavar="NAME")],
    drive: DriveOpt = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Rename a file or folder."""
    base = onedrive.base_for(drive)
    if dry_run:
        return DryRunResult(files.plan_rename(client, base, ref, name))
    item = files.run_rename(client, base, ref, name)
    return WriteResult(obj=item, message=f"Renamed to {name}.")


@app.command("delete")
@graph_command(scopes=["Files.ReadWrite"])
def delete(
    client: GraphClient,
    ref: RefArg,
    drive: DriveOpt = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Delete a file or folder (moves it to the recycle bin)."""
    base = onedrive.base_for(drive)
    if dry_run:
        return DryRunResult(files.plan_delete(client, base, ref))
    item_id = files.resolve_item_id(client, base, ref)
    files.run_delete(client, base, ref)
    return WriteResult(obj={"status": "deleted", "id": item_id}, message=f"Deleted {item_id}.")


@app.command("share")
@graph_command(scopes=["Files.ReadWrite"])
def share(
    client: GraphClient,
    ref: RefArg,
    drive: DriveOpt = None,
    link_type: Annotated[
        Literal["view", "edit"], typer.Option("--type", help="Kind of link to create.")
    ] = "view",
    scope: Annotated[
        Literal["organization", "anonymous"], typer.Option("--scope", help="Who can use it.")
    ] = "organization",
    expires: Annotated[
        str | None, typer.Option("--expires", help="When the link stops working.")
    ] = None,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Create a sharing link."""
    base = onedrive.base_for(drive)
    expires_dt = parse_dt(expires, client.tz) if expires else None
    if dry_run:
        return DryRunResult(
            files.plan_share(
                client, base, ref, link_type=link_type, scope=scope, expires=expires_dt
            )
        )
    link = files.run_share(client, base, ref, link_type=link_type, scope=scope, expires=expires_dt)
    return WriteResult(obj=link, message=dig(link, "link.webUrl") or "")


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
    return ListResult(
        items=page.items, truncated=page.truncated, supports_all=False, columns=columns
    )


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
        items=page.items,
        truncated=page.truncated,
        supports_all=False,
        columns=files.item_columns(client.tz),
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
