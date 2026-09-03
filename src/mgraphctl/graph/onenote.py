"""Graph operations for OneNote notebooks, sections and pages (spec §8.13).

Pure: client and parameters in, Graph dicts / PageResult / Plan out.
"""

from __future__ import annotations

from html import escape as escape_html

from mgraphctl.errors import GraphError
from mgraphctl.html import text_to_html
from mgraphctl.http import GraphClient, PageResult, Plan, PlannedRequest
from mgraphctl.odata import p
from mgraphctl.resolve import looks_like_id, pick_unique, split_id_prefix

NOTEBOOK_SELECT = "id,displayName,lastModifiedDateTime,links"
SECTION_SELECT = "id,displayName,lastModifiedDateTime,parentNotebook"
PAGE_SELECT = "id,title,lastModifiedDateTime,links"
SEARCH_SELECT = "id,title,createdDateTime,parentSection"
HTML_CONTENT = {"Content-Type": "text/html"}

PAGE_TOP = 100
CAP_LIST = 500


def list_notebooks(client: GraphClient, *, limit: int, all_: bool = False) -> PageResult:
    return client.paginate(
        "/me/onenote/notebooks",
        params={"$select": NOTEBOOK_SELECT},
        limit=limit,
        all_=all_,
        cap=CAP_LIST,
        page_size=PAGE_TOP,
    )


def resolve_notebook(client: GraphClient, value: str) -> str:
    """A notebook id, or the id of the notebook whose `displayName` matches `value` (§6.6)."""
    bare, forced = split_id_prefix(value)
    if looks_like_id(value, "onenote"):
        return bare
    payload = client.get("/me/onenote/notebooks", params={"$top": PAGE_TOP}) or {}
    match = pick_unique(payload.get("value") or [], "displayName", value, what="notebook")
    return match["id"]


def list_sections(
    client: GraphClient, notebook_id: str | None, *, limit: int, all_: bool = False
) -> PageResult:
    path = (
        "/me/onenote/sections"
        if notebook_id is None
        else p("me", "onenote", "notebooks", notebook_id, "sections")
    )
    return client.paginate(
        path,
        params={"$select": SECTION_SELECT},
        limit=limit,
        all_=all_,
        cap=CAP_LIST,
        page_size=PAGE_TOP,
    )


def resolve_section(client: GraphClient, value: str) -> str:
    """A section id, or the id of the section whose `displayName` matches `value` (§6.6)."""
    bare, forced = split_id_prefix(value)
    if looks_like_id(value, "onenote"):
        return bare
    payload = client.get("/me/onenote/sections", params={"$top": PAGE_TOP}) or {}
    match = pick_unique(payload.get("value") or [], "displayName", value, what="section")
    return match["id"]


def list_pages(client: GraphClient, section_id: str, *, limit: int, all_: bool) -> PageResult:
    path = p("me", "onenote", "sections", section_id, "pages")
    return client.paginate(
        path,
        params={"$select": PAGE_SELECT, "$orderby": "lastModifiedDateTime desc"},
        limit=limit,
        all_=all_,
        cap=CAP_LIST,
        page_size=PAGE_TOP,
    )


def resolve_page(client: GraphClient, value: str) -> str:
    """A page id, or the id of the page whose `title` matches `value` (§6.6)."""
    bare, forced = split_id_prefix(value)
    if looks_like_id(value, "onenote"):
        return bare
    payload = client.get("/me/onenote/pages", params={"$top": PAGE_TOP}) or {}
    match = pick_unique(payload.get("value") or [], "title", value, what="page")
    return match["id"]


def get_page(client: GraphClient, page_id: str) -> tuple[dict, str]:
    """A page's metadata and its HTML content (two Graph calls; §8.13 `read`)."""
    meta = client.get(p("me", "onenote", "pages", page_id), params={"$select": PAGE_SELECT})
    content = client.get(
        p("me", "onenote", "pages", page_id, "content"),
        params={"includeIDs": True},
        expect="text",
    )
    return meta, content


def plan_create_page(
    client: GraphClient, section_id: str, *, title: str, body: str, html: bool
) -> Plan:
    """`POST .../pages` with an HTML string body.

    Title is always escaped; body is escaped and paragraph-wrapped unless `html` (quirk 14).
    """
    content = body if html else text_to_html(body)
    page_html = (
        f"<!DOCTYPE html><html><head><title>{escape_html(title)}</title></head>"
        f"<body>{content}</body></html>"
    )
    url = client.url(p("me", "onenote", "sections", section_id, "pages"))
    return [PlannedRequest("POST", url, dict(HTML_CONTENT), page_html)]


def search_pages(client: GraphClient, q: str, *, limit: int) -> PageResult:
    """`$search` over page titles/content; Graph only supports this for consumer notebooks."""
    try:
        return client.paginate(
            "/me/onenote/pages",
            params={"$search": q, "$select": SEARCH_SELECT},
            limit=limit,
            all_=False,
            cap=CAP_LIST,
            page_size=PAGE_TOP,
        )
    except GraphError as exc:
        if exc.status in (400, 501):
            exc.hint = f"search {q} --type driveItem"
        raise
