"""Shared drive-item operations for OneDrive and SharePoint (spec §8.11, §8.12).

Pure: client + params in, Graph dicts / PageResult / Plan out. `base` is one of `/me/drive`,
`/drives/{id}` or `/sites/{id}/drive`, already encoded by the caller.
"""

from __future__ import annotations

from datetime import datetime
from math import ceil
from mimetypes import guess_type
from pathlib import Path
from typing import Any

from mgraphctl import config, odata, resolve
from mgraphctl.errors import UsageError
from mgraphctl.http import DownloadResult, GraphClient, PageResult, Plan, PlannedRequest
from mgraphctl.render import Column, fmt_dt, fmt_size, to_iso_offset

ITEM_SELECT = "id,name,size,lastModifiedDateTime,file,folder,webUrl,parentReference"
PAGE_LS, CAP_LS = 200, 1000
JSON = {"Content-Type": "application/json"}
CONFLICT_BEHAVIORS = frozenset({"rename", "replace", "fail"})


def item_ref(base: str, ref: str) -> str:
    """`{base}/items/{id}` for an id (or `id:`-forced value), else `{base}/root:/{path}`."""
    value, forced = resolve.split_id_prefix(ref)
    if resolve.looks_like_id(ref, "drive_item"):
        return f"{base}/items" + odata.p(value)
    return f"{base}/root:/{odata.drive_path(value.lstrip('/'))}"


def children_path(base: str, path: str | None) -> str:
    if not path:
        return f"{base}/root/children"
    return f"{base}/root:/{odata.drive_path(path.lstrip('/'))}:/children"


def list_children(
    client: GraphClient, base: str, path: str | None, *, limit: int | None, all_: bool
) -> PageResult:
    return client.paginate(
        children_path(base, path),
        params={"$select": ITEM_SELECT, "$orderby": "name"},
        limit=limit,
        all_=all_,
        cap=CAP_LS,
        page_size=PAGE_LS,
    )


def search_items(
    client: GraphClient, base: str, q: str, *, limit: int | None, shared: bool = False
) -> PageResult:
    prefix = base if shared else f"{base}/root"
    path = f"{prefix}/search(q='{odata.odata_str(q)}')"
    return client.paginate(
        path,
        params={"$select": ITEM_SELECT},
        limit=limit,
        all_=False,
        cap=CAP_LS,
        page_size=PAGE_LS,
    )


def get_item(client: GraphClient, base: str, ref: str) -> dict:
    return client.get(item_ref(base, ref), params={"$select": ITEM_SELECT})


def resolve_item_id(client: GraphClient, base: str, ref: str) -> str:
    value, forced = resolve.split_id_prefix(ref)
    if resolve.looks_like_id(ref, "drive_item"):
        return value
    return get_item(client, base, ref)["id"]


def _action_path(base: str, ref: str, action: str) -> str:
    """`item_ref(...)` plus an action segment, colon-fenced correctly for each ref form.

    An id-form ref (`{base}/items/{id}`) takes the action as a plain path segment
    (`/items/{id}/action`); a path-form ref (`{base}/root:/{path}`) needs the path's closing
    colon before the action segment (`root:/{path}:/action`) or Graph 400s.
    """
    sep = "/" if resolve.looks_like_id(ref, "drive_item") else ":/"
    return item_ref(base, ref) + sep + action


def download_item(
    client: GraphClient, base: str, ref: str, dest: Path | None
) -> tuple[dict, DownloadResult]:
    item = get_item(client, base, ref)
    result = client.download(_action_path(base, ref, "content"), dest or Path(item["name"]))
    return item, result


def _dest(file: Path, dest: str | None) -> str:
    """`--dest` resolution (spec §8.11 `upload`): default `/<basename>`; trailing `/` = folder."""
    if dest is None:
        return f"/{file.name}"
    if dest.endswith("/"):
        return f"{dest}{file.name}"
    return dest


def plan_upload(
    client: GraphClient, base: str, file: Path, dest: str | None, conflict: str
) -> Plan:
    if conflict not in CONFLICT_BEHAVIORS:
        raise UsageError(
            "USAGE",
            f"--conflict must be one of {', '.join(sorted(CONFLICT_BEHAVIORS))} (got {conflict!r})",
        )
    dest_path = _dest(file, dest)
    encoded = odata.drive_path(dest_path.lstrip("/"))
    size = file.stat().st_size
    if size < config.DRIVE_SIMPLE_UPLOAD:
        url = client.url(
            f"{base}/root:/{encoded}:/content?@microsoft.graph.conflictBehavior={conflict}"
        )
        content_type = guess_type(file.name)[0] or "application/octet-stream"
        return [PlannedRequest("PUT", url, {"Content-Type": content_type}, None, file=file)]
    url = client.url(f"{base}/root:/{encoded}:/createUploadSession")
    name = dest_path.rsplit("/", 1)[-1]
    body = {"item": {"@microsoft.graph.conflictBehavior": conflict, "name": name}}
    note = f"upload {size} bytes in {ceil(size / config.CHUNK_DRIVE)} chunks"
    return [
        PlannedRequest(
            "POST", url, dict(JSON), body, file=file, chunk_size=config.CHUNK_DRIVE, note=note
        )
    ]


def _run(client: GraphClient, plan: Plan) -> Any:
    """Execute every step of `plan` in order, returning the last step's result."""
    result: Any = None
    for step in plan:
        result = client.execute(step)
    return result


def run_upload(client: GraphClient, base: str, file: Path, dest: str | None, conflict: str) -> dict:
    return _run(client, plan_upload(client, base, file, dest, conflict))


def plan_mkdir(client: GraphClient, base: str, path: str) -> Plan:
    clean = path.strip("/")
    if "/" in clean:
        parent, name = clean.rsplit("/", 1)
        url = client.url(f"{base}/root:/{odata.drive_path(parent)}:/children")
    else:
        name = clean
        url = client.url(f"{base}/root/children")
    body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
    return [PlannedRequest("POST", url, dict(JSON), body)]


def run_mkdir(client: GraphClient, base: str, path: str) -> dict:
    return _run(client, plan_mkdir(client, base, path))


def _resolve_folder_id(client: GraphClient, base: str, to: str) -> str:
    value, forced = resolve.split_id_prefix(to)
    if forced:
        return value
    return get_item(client, base, to)["id"]


def plan_move(client: GraphClient, base: str, ref: str, to: str, name: str | None) -> Plan:
    folder_id = _resolve_folder_id(client, base, to)
    body: dict[str, Any] = {"parentReference": {"id": folder_id}}
    if name is not None:
        body["name"] = name
    url = client.url(item_ref(base, ref))
    return [PlannedRequest("PATCH", url, dict(JSON), body)]


def run_move(client: GraphClient, base: str, ref: str, to: str, name: str | None) -> dict:
    return _run(client, plan_move(client, base, ref, to, name))


def plan_rename(client: GraphClient, base: str, ref: str, name: str) -> Plan:
    url = client.url(item_ref(base, ref))
    return [PlannedRequest("PATCH", url, dict(JSON), {"name": name})]


def run_rename(client: GraphClient, base: str, ref: str, name: str) -> dict:
    return _run(client, plan_rename(client, base, ref, name))


def plan_delete(client: GraphClient, base: str, ref: str) -> Plan:
    url = client.url(item_ref(base, ref))
    return [PlannedRequest("DELETE", url, {}, None, expect="none")]


def run_delete(client: GraphClient, base: str, ref: str) -> dict | None:
    return _run(client, plan_delete(client, base, ref))


def plan_share(
    client: GraphClient,
    base: str,
    ref: str,
    *,
    link_type: str,
    scope: str,
    expires: datetime | None,
) -> Plan:
    body: dict[str, Any] = {"type": link_type, "scope": scope}
    if expires is not None:
        body["expirationDateTime"] = to_iso_offset(expires)
    url = client.url(_action_path(base, ref, "createLink"))
    return [PlannedRequest("POST", url, dict(JSON), body)]


def run_share(
    client: GraphClient,
    base: str,
    ref: str,
    *,
    link_type: str,
    scope: str,
    expires: datetime | None,
) -> dict:
    return _run(
        client, plan_share(client, base, ref, link_type=link_type, scope=scope, expires=expires)
    )


def get_shared_item(client: GraphClient, url: str) -> dict:
    return client.get(f"/shares/{odata.share_id(url)}/driveItem")


def download_shared_item(
    client: GraphClient, url: str, dest: Path | None
) -> tuple[dict, DownloadResult]:
    item = get_shared_item(client, url)
    result = client.download(
        f"/shares/{odata.share_id(url)}/driveItem/content", dest or Path(item["name"])
    )
    return item, result


def item_columns(tz: str) -> list[Column]:
    return [
        Column("type", lambda i: "d" if "folder" in i else "f"),
        Column("id", "id"),
        Column("size", lambda i: fmt_size(i.get("size"))),
        Column("modified", lambda i: fmt_dt(i.get("lastModifiedDateTime"), tz)),
        Column("name", "name"),
    ]
