"""SharePoint sites, drives, browsing, lists and items (spec §8.12)."""

from pathlib import Path
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
)
from mgraphctl.graph import files, sharepoint
from mgraphctl.http import GraphClient
from mgraphctl.render import (
    Column,
    DryRunResult,
    FileResult,
    ListResult,
    ObjectResult,
    WriteResult,
    fmt_size,
)

app = make_noun_app("SharePoint sites, drives and lists.")

SITE_FIELDS = [
    ("Name", "displayName"),
    ("Site name", "name"),
    ("Web URL", "webUrl"),
    ("Description", "description"),
    ("Id", "id"),
]
SITE_LIST_COLUMNS = [Column("id", "id"), Column("name", "displayName"), Column("webUrl", "webUrl")]
DRIVE_COLUMNS = [
    Column("id", "id"),
    Column("name", "name"),
    Column("type", "driveType"),
    Column("webUrl", "webUrl"),
]
LIST_COLUMNS = [Column("id", "id"), Column("name", "displayName"), Column("webUrl", "webUrl")]

DriveOpt = Annotated[str | None, typer.Option("--drive", help="Drive name or id.")]


def _open_drive(client: GraphClient, site: str, drive: str | None) -> tuple[str, str]:
    """Resolve `SITE` (and `--drive`, if given) to `(site_id, base)`."""
    site_obj = sharepoint.resolve_site(client, site)
    site_id = site_obj["id"]
    drive_id = sharepoint.resolve_drive(client, site_id, drive) if drive else None
    return site_id, sharepoint.drive_base(site_id, drive_id)


def _item_columns(items: list[dict], fields: list[str] | None) -> list[Column]:
    """One column per requested `--fields` entry, else per field seen on the items (first 8)."""
    if fields:
        keys = fields[:8]
    else:
        keys = []
        for item in items:
            for key in item.get("fields") or {}:
                if key not in keys:
                    keys.append(key)
            if len(keys) >= 8:
                break
        keys = keys[:8]
    return [
        Column(key, (lambda k: lambda it: (it.get("fields") or {}).get(k))(key)) for key in keys
    ]


@app.command("sites")
@graph_command(scopes=["Sites.Read.All"])
def sites(
    client: GraphClient,
    search: Annotated[
        str | None, typer.Option("--search", help="Search text (default '*').")
    ] = None,
    limit: LimitOpt = None,
    json_: JsonFlag = False,
):
    """List followed sites, or search all sites."""
    page = sharepoint.list_sites(client, search=search, limit=limit if limit is not None else 20)
    return ListResult(items=page.items, truncated=page.truncated, columns=SITE_LIST_COLUMNS)


@app.command("site")
@graph_command(scopes=["Sites.Read.All"])
def site(
    client: GraphClient, ref: Annotated[str, typer.Argument(metavar="REF")], json_: JsonFlag = False
):
    """Show one site, resolved by URL, `host:/a/b`, composite id, or name."""
    return ObjectResult(obj=sharepoint.resolve_site(client, ref), fields=list(SITE_FIELDS))


@app.command("drives")
@graph_command(scopes=["Sites.Read.All"])
def drives(
    client: GraphClient,
    site: Annotated[str, typer.Argument(metavar="SITE")],
    json_: JsonFlag = False,
):
    """List a site's document libraries (drives)."""
    site_obj = sharepoint.resolve_site(client, site)
    items = sharepoint.list_drives(client, site_obj["id"])
    return ListResult(items=items, columns=DRIVE_COLUMNS)


@app.command("ls")
@graph_command(scopes=["Sites.Read.All"])
def ls(
    client: GraphClient,
    site: Annotated[str, typer.Argument(metavar="SITE")],
    path: Annotated[str | None, typer.Argument(metavar="PATH")] = None,
    drive: DriveOpt = None,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List the children of a folder in the site drive (default: root)."""
    limit_, all_val = page_bounds(limit, all_, default=50)
    _site_id, base = _open_drive(client, site, drive)
    page = files.list_children(client, base, path, limit=limit_, all_=all_val)
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=files.CAP_LS if all_val else None,
        columns=files.item_columns(client.tz),
    )


@app.command("search")
@graph_command(scopes=["Sites.Read.All"])
def search(
    client: GraphClient,
    q: Annotated[str, typer.Argument(metavar="Q")],
    site: Annotated[
        str | None, typer.Option("--site", help="Search within one site's drive.")
    ] = None,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """Search a site's drive, or every site (Search API) when `--site` is not given."""
    limit_, all_val = page_bounds(limit, all_, default=25)
    if site:
        site_obj = sharepoint.resolve_site(client, site)
        page = sharepoint.search_site_drive(client, site_obj["id"], q, limit=limit_, all_=all_val)
        items, truncated = page.items, page.truncated
    else:
        result = sharepoint.search_all(client, q, limit=limit_, all_=all_val)
        items = [hit.get("resource") or {} for hit in result.hits]
        truncated = result.more
    return ListResult(
        items=items,
        truncated=truncated,
        hit_cap=sharepoint.SEARCH_CAP if all_val else None,
        columns=files.item_columns(client.tz),
    )


@app.command("download")
@graph_command(scopes=["Sites.Read.All"])
def download(
    client: GraphClient,
    site: Annotated[str, typer.Argument(metavar="SITE")],
    item: Annotated[str, typer.Argument(metavar="ITEM_OR_PATH")],
    output: Annotated[Path | None, typer.Option("--output", help="Destination file.")] = None,
    drive: DriveOpt = None,
    json_: JsonFlag = False,
):
    """Download a file from the site drive (fixes the Node quirk of using the wrong drive)."""
    _site_id, base = _open_drive(client, site, drive)
    graph_item, result = files.download_item(client, base, item, output)
    return FileResult(
        path=result.path,
        bytes=result.bytes,
        meta=dict(contentType=result.content_type, id=graph_item.get("id")),
        message=f"Downloaded {graph_item.get('name')} ({fmt_size(result.bytes)}) to {result.path}",
    )


@app.command("upload")
@graph_command(scopes=["Sites.ReadWrite.All"])
def upload(
    client: GraphClient,
    site: Annotated[str, typer.Argument(metavar="SITE")],
    file: Annotated[Path, typer.Argument(metavar="FILE", exists=True, dir_okay=False)],
    dest: Annotated[
        str | None, typer.Option("--dest", help="Destination path (default: /basename).")
    ] = None,
    drive: DriveOpt = None,
    conflict: Annotated[
        str, typer.Option("--conflict", help="rename, replace, or fail.")
    ] = "replace",
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Upload a file to the site drive."""
    _site_id, base = _open_drive(client, site, drive)
    plan = files.plan_upload(client, base, file, dest, conflict)
    if dry_run:
        return DryRunResult(plan)
    obj = files.run_upload(client, base, file, dest, conflict)
    return WriteResult(obj=obj, message=f"Uploaded {file.name} to {obj.get('webUrl') or base}.")


@app.command("url")
@graph_command(scopes=["Sites.Read.All"])
def url(
    client: GraphClient,
    url: Annotated[str, typer.Argument(metavar="URL")],
    output: Annotated[Path | None, typer.Option("--output", help="Destination file.")] = None,
    info: Annotated[
        bool, typer.Option("--info", help="Resolve and print, without downloading.")
    ] = False,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Resolve a SharePoint web URL to a drive item, and download it."""
    if info or dry_run:
        resolution = sharepoint.resolve_url(client, url)
        obj = {
            "resolution": {
                "siteId": resolution.site_id,
                "driveId": resolution.drive_id,
                "path": resolution.path,
            },
            "item": resolution.item,
        }
        fields = [
            ("siteId", "resolution.siteId"),
            ("driveId", "resolution.driveId"),
            ("path", "resolution.path"),
            ("item", "item.id"),
        ]
        return ObjectResult(obj=obj, fields=fields)
    _resolution, result = sharepoint.download_url(client, url, output)
    return FileResult(
        path=result.path,
        bytes=result.bytes,
        meta=dict(contentType=result.content_type),
        message=f"Downloaded {result.path.name} ({fmt_size(result.bytes)}) to {result.path}",
    )


@app.command("lists")
@graph_command(scopes=["Sites.Read.All"])
def lists_(
    client: GraphClient,
    site: Annotated[str, typer.Argument(metavar="SITE")],
    json_: JsonFlag = False,
):
    """List a site's lists and document libraries (system lists hidden)."""
    site_obj = sharepoint.resolve_site(client, site)
    items = sharepoint.list_lists(client, site_obj["id"])
    return ListResult(items=items, columns=LIST_COLUMNS)


@app.command("items")
@graph_command(scopes=["Sites.Read.All"])
def items_(
    client: GraphClient,
    site: Annotated[str, typer.Argument(metavar="SITE")],
    list_: Annotated[str, typer.Argument(metavar="LIST")],
    fields: Annotated[
        str | None, typer.Option("--fields", help="Comma-separated field names.")
    ] = None,
    filter_: Annotated[
        str | None, typer.Option("--filter", help="OData filter on fields/*.")
    ] = None,
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List a SharePoint list's items, with their column values."""
    limit_, all_val = page_bounds(limit, all_, default=50)
    site_obj = sharepoint.resolve_site(client, site)
    site_id = site_obj["id"]
    list_obj = sharepoint.resolve_list(client, site_id, list_)
    field_list = [f.strip() for f in fields.split(",")] if fields else None
    page = sharepoint.list_items(
        client,
        site_id,
        list_obj["id"],
        fields=field_list,
        filter_=filter_,
        limit=limit_,
        all_=all_val,
    )
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=sharepoint.ITEMS_CAP if all_val else None,
        columns=_item_columns(page.items, field_list),
    )
