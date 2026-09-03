"""Graph operations for SharePoint sites, drives and lists (spec §8.12, §6.6).

Pure: client + params in, Graph dicts / PageResult / Plan out. Drive browsing, download and
upload reuse `graph.files` with a site-drive `base` (`/sites/{id}/drive` or `/drives/{id}`);
this module owns site/drive/list resolution and the SharePoint-only `url` and `search` verbs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from mgraphctl import odata, resolve
from mgraphctl.errors import AuthError, GraphError, NotFoundError
from mgraphctl.graph import files
from mgraphctl.http import DownloadResult, GraphClient, PageResult, SearchResult

SITE_SELECT = "id,displayName,name,webUrl,description"
SITES_FOLLOWED_SELECT = "id,displayName,webUrl"
DRIVE_SELECT = "id,name,webUrl,driveType"
LIST_SELECT = "id,displayName,webUrl,list"

SEARCH_SIZE, SEARCH_CAP = 25, 200
ITEMS_PAGE, ITEMS_CAP = 200, 500
PREFER_NONINDEXED = "HonorNonIndexedQueriesWarningMayFailRandomly"

_SITE_KINDS = ("sites", "teams", "personal")
_VIEWER_SEGMENT_RE = re.compile(r"^:[A-Za-z]:$")


@dataclass(frozen=True)
class Resolution:
    site_id: str | None
    drive_id: str | None
    path: str
    item: dict


def _site_id_segment(site_id: str) -> str:
    """A site id in a URL path: commas kept literal, like `odata.site_ref`'s composite form."""
    return quote(site_id, safe=",")


def _site_path(site_id: str, *rest: str) -> str:
    tail = "/".join(quote(s, safe="") for s in rest)
    base = f"/sites/{_site_id_segment(site_id)}"
    return f"{base}/{tail}" if tail else base


# --------------------------------------------------------------------------- sites


def list_sites(client: GraphClient, *, search: str | None, limit: int) -> PageResult:
    """Followed sites by default; `--search` or an empty followed list falls back to `/sites`."""
    if not search:
        payload = client.get("/me/followedSites", params={"$select": SITES_FOLLOWED_SELECT}) or {}
        items = payload.get("value") or []
        if items:
            return PageResult(items=items[:limit], truncated=len(items) > limit, pages=1)
        search = "*"
    payload = client.get("/sites", params={"search": search, "$top": limit}) or {}
    items = payload.get("value") or []
    return PageResult(items=items[:limit], truncated=len(items) > limit, pages=1)


def resolve_site(client: GraphClient, value: str) -> dict:
    """A URL / `host:/a/b` / composite id / `id:`-forced id via `odata.site_ref`, else a name."""
    bare, _ = resolve.split_id_prefix(value)
    if resolve.looks_like_id(value, "site"):
        return client.get(odata.site_ref(bare), params={"$select": SITE_SELECT})
    payload = client.get("/sites", params={"search": value}) or {}
    items = payload.get("value") or []
    return resolve.pick_unique(items, "displayName", value, what="site")


# --------------------------------------------------------------------------- drives


def list_drives(client: GraphClient, site_id: str) -> list[dict]:
    payload = client.get(_site_path(site_id, "drives"), params={"$select": DRIVE_SELECT}) or {}
    return payload.get("value") or []


def resolve_drive(client: GraphClient, site_id: str, value: str) -> str:
    """A `b!` drive id, else a `name` among the site's drives."""
    if resolve.looks_like_id(value, "drive"):
        bare, _ = resolve.split_id_prefix(value)
        return bare
    drives = list_drives(client, site_id)
    return resolve.pick_unique(drives, "name", value, what="drive")["id"]


def drive_base(site_id: str, drive_id: str | None = None) -> str:
    """`/sites/{id}/drive` (the site's default drive) or `/drives/{id}` (a named drive)."""
    if drive_id is None:
        return _site_path(site_id, "drive")
    return odata.p("drives", drive_id)


# --------------------------------------------------------------------------- search


def search_site_drive(
    client: GraphClient, site_id: str, q: str, *, limit: int, all_: bool = False
) -> PageResult:
    base = drive_base(site_id)
    path = f"{base}/root/search(q='{odata.odata_str(q)}')"
    return client.paginate(
        path,
        params={"$select": files.ITEM_SELECT},
        limit=limit,
        all_=all_,
        cap=SEARCH_CAP,
        page_size=SEARCH_SIZE,
    )


def search_all(client: GraphClient, q: str, *, limit: int, all_: bool = False) -> SearchResult:
    bound = SEARCH_CAP if all_ else min(limit, SEARCH_CAP)
    return client.search(["driveItem"], q, size=SEARCH_SIZE, limit=bound)


# --------------------------------------------------------------------------- url resolution


def _is_personal_url(url: str) -> bool:
    return "/personal/" in urlsplit(url).path


def _url_segments(url: str) -> tuple[str, list[str]]:
    """The host and decoded path segments, with a leading `/:x:/r/` viewer prefix skipped."""
    parsed = urlsplit(url)
    segments = [unquote(s) for s in parsed.path.split("/") if s]
    while segments and (_VIEWER_SEGMENT_RE.match(segments[0]) or segments[0].lower() == "r"):
        segments.pop(0)
    return parsed.netloc, segments


def _rel_path(item: dict) -> str:
    """The item's drive-relative path, from `parentReference.path` plus its name."""
    raw = (item.get("parentReference") or {}).get("path") or ""
    _, _, after_colon = raw.partition(":")
    name = item.get("name") or ""
    return f"{after_colon}/{name}" if after_colon else f"/{name}"


def _pick_drive(drives: list[dict], segments: list[str]) -> tuple[dict | None, list[str]]:
    """The drive whose `webUrl` is the deepest prefix of `segments`, and the remaining path."""
    best: dict | None = None
    best_len = -1
    for d in drives:
        web = d.get("webUrl") or ""
        web_segments = [unquote(s) for s in urlsplit(web).path.split("/") if s]
        n = len(web_segments)
        if 0 < n <= len(segments) and n > best_len:
            folded = [s.casefold() for s in segments[:n]]
            if folded == [s.casefold() for s in web_segments]:
                best, best_len = d, n
    if best is None:
        return None, segments[2:]
    return best, segments[best_len:]


def _resolve_via_site(client: GraphClient, url: str) -> tuple[Resolution, str]:
    """Node's fallback algorithm: parse the site from the URL, then locate the item."""
    host, segments = _url_segments(url)
    if len(segments) < 2 or segments[0] not in _SITE_KINDS:
        raise NotFoundError("NOT_FOUND", f"cannot parse a SharePoint site from {url!r}")
    kind, name = segments[0], segments[1]
    site_path = f"/sites/{quote(host, safe='')}:/{quote(kind, safe='')}/{quote(name, safe='')}"
    site = client.get(site_path, params={"$select": SITE_SELECT})
    site_id = site["id"]
    drive, drive_rel = _pick_drive(list_drives(client, site_id), segments)
    rest = segments[2:]
    last_exc: GraphError | None = None
    if drive is not None:
        rel = "/".join(quote(s, safe="") for s in drive_rel)
        path = f"/drives/{drive['id']}/root:/{rel}" if rel else f"/drives/{drive['id']}/root"
        try:
            item = client.get(path, params={"$select": files.ITEM_SELECT})
            resolution = Resolution(site_id, drive["id"], "/" + "/".join(drive_rel), item)
            content = f"{path}:/content" if rel else f"{path}/content"
            return resolution, content
        except GraphError as exc:
            if exc.status != 404:
                raise
            last_exc = exc
    base = _site_path(site_id, "drive")
    for candidate in (rest, rest[1:]):
        if not candidate:
            continue
        rel = "/".join(quote(s, safe="") for s in candidate)
        path = f"{base}/root:/{rel}"
        try:
            item = client.get(path, params={"$select": files.ITEM_SELECT})
            resolution = Resolution(site_id, None, "/" + "/".join(candidate), item)
            return resolution, f"{path}:/content"
        except GraphError as exc:
            last_exc = exc
            if exc.status != 404:
                raise
            continue
    raise last_exc or NotFoundError("NOT_FOUND", f"could not resolve {url!r} to a SharePoint item")


def _resolve(client: GraphClient, url: str) -> tuple[Resolution, str]:
    share_path = f"/shares/{odata.share_id(url)}/driveItem"
    try:
        item = client.get(share_path, params={"$select": files.ITEM_SELECT})
    except GraphError as exc:
        if not (400 <= exc.status < 500):
            raise
        if exc.status == 403 and _is_personal_url(url):
            raise AuthError(
                "FORBIDDEN",
                f"cannot resolve {url!r}: this is a personal OneDrive link",
                hint="ask the owner to share the file and use that share link instead",
            ) from exc
        return _resolve_via_site(client, url)
    pr = item.get("parentReference") or {}
    resolution = Resolution(pr.get("siteId"), pr.get("driveId"), _rel_path(item), item)
    return resolution, f"{share_path}/content"


def resolve_url(client: GraphClient, url: str) -> Resolution:
    resolution, _content_path = _resolve(client, url)
    return resolution


def download_url(
    client: GraphClient, url: str, dest: Path | None
) -> tuple[Resolution, DownloadResult]:
    resolution, content_path = _resolve(client, url)
    name = resolution.item.get("name") or url.rsplit("/", 1)[-1].split("?", 1)[0]
    result = client.download(content_path, dest or Path(name))
    return resolution, result


# --------------------------------------------------------------------------- lists / items


def list_lists(client: GraphClient, site_id: str) -> list[dict]:
    """Every list, with hidden system lists dropped (`list.hidden`); document libraries kept."""
    payload = client.get(_site_path(site_id, "lists"), params={"$select": LIST_SELECT}) or {}
    items = payload.get("value") or []
    return [i for i in items if not (i.get("list") or {}).get("hidden")]


def resolve_list(client: GraphClient, site_id: str, value: str) -> dict:
    if resolve.looks_like_id(value, "guid"):
        bare, _ = resolve.split_id_prefix(value)
        return client.get(_site_path(site_id, "lists", bare), params={"$select": LIST_SELECT})
    return resolve.pick_unique(list_lists(client, site_id), "displayName", value, what="list")


def list_items(
    client: GraphClient,
    site_id: str,
    list_id: str,
    *,
    fields: list[str] | None,
    filter_: str | None,
    limit: int | None,
    all_: bool,
) -> PageResult:
    expand = f"fields($select={','.join(fields)})" if fields else "fields"
    params: dict[str, object] = {"$expand": expand}
    headers = None
    if filter_:
        params["$filter"] = filter_
        headers = {"Prefer": PREFER_NONINDEXED}
    path = _site_path(site_id, "lists", list_id, "items")
    return client.paginate(
        path,
        params=params,
        headers=headers,
        limit=limit,
        all_=all_,
        cap=ITEMS_CAP,
        page_size=ITEMS_PAGE,
    )
