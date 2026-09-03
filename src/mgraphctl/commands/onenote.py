"""OneNote notebooks, sections and pages (spec §8.13)."""

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
    read_body,
)
from mgraphctl.graph import onenote
from mgraphctl.html import to_markdown
from mgraphctl.http import GraphClient
from mgraphctl.render import (
    Column,
    DryRunResult,
    FileResult,
    ListResult,
    TextResult,
    WriteResult,
    fmt_dt,
    fmt_size,
    truncate,
)

DEFAULT_LIMIT = 50

app = make_noun_app("OneNote notebooks and pages.")


@app.command("notebooks")
@graph_command(scopes=["Notes.Read"])
def notebooks(
    client: GraphClient,
    limit: LimitOpt = None,
    json_: JsonFlag = False,
):
    """List OneNote notebooks."""
    bound = limit if limit is not None else DEFAULT_LIMIT
    page = onenote.list_notebooks(client, limit=bound)
    tz = client.tz
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        supports_all=False,
        columns=[
            Column("id", "id"),
            Column("name", "displayName"),
            Column("modified", lambda n: fmt_dt(n.get("lastModifiedDateTime"), tz)),
        ],
    )


@app.command("sections")
@graph_command(scopes=["Notes.Read"])
def sections(
    client: GraphClient,
    notebook: Annotated[str | None, typer.Argument(metavar="NOTEBOOK")] = None,
    limit: LimitOpt = None,
    json_: JsonFlag = False,
):
    """List OneNote sections, across all notebooks or within one."""
    bound = limit if limit is not None else DEFAULT_LIMIT
    notebook_id = onenote.resolve_notebook(client, notebook) if notebook is not None else None
    page = onenote.list_sections(client, notebook_id, limit=bound)
    tz = client.tz
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        supports_all=False,
        columns=[
            Column("id", "id"),
            Column("name", "displayName"),
            Column("modified", lambda s: fmt_dt(s.get("lastModifiedDateTime"), tz)),
        ],
    )


@app.command("pages")
@graph_command(scopes=["Notes.Read"])
def pages(
    client: GraphClient,
    section: Annotated[str, typer.Argument(metavar="SECTION")],
    limit: LimitOpt = None,
    all_: AllFlag = False,
    json_: JsonFlag = False,
):
    """List the pages in a section."""
    bound, all_pages = page_bounds(limit, all_, default=DEFAULT_LIMIT)
    section_id = onenote.resolve_section(client, section)
    page = onenote.list_pages(client, section_id, limit=bound, all_=all_pages)
    tz = client.tz
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        hit_cap=onenote.CAP_LIST if all_pages else None,
        columns=[
            Column("id", "id"),
            Column("modified", lambda pg: fmt_dt(pg.get("lastModifiedDateTime"), tz)),
            Column("title", lambda pg: truncate(pg.get("title"))),
        ],
    )


@app.command("read")
@graph_command(scopes=["Notes.Read"])
def read(
    client: GraphClient,
    page: Annotated[str, typer.Argument(metavar="PAGE")],
    html_: Annotated[bool, typer.Option("--html", help="Print the page's raw HTML.")] = False,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write to this file instead of stdout.")
    ] = None,
    json_: JsonFlag = False,
):
    """Read a OneNote page as Markdown (or raw HTML with --html)."""
    page_id = onenote.resolve_page(client, page)
    meta, html_body = onenote.get_page(client, page_id)
    markdown = to_markdown(html_body, mode="onenote")
    doc = {
        "id": meta.get("id"),
        "title": meta.get("title"),
        "html": html_body,
        "markdown": markdown,
    }
    if output is not None:
        content = html_body if html_ else markdown
        output.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        output.write_bytes(data)
        return FileResult(
            path=output,
            bytes=len(data),
            meta=dict(id=doc["id"], title=doc["title"]),
            message=f"Wrote {fmt_size(len(data))} to {output}",
        )
    if html_:
        return TextResult(text=html_body, json_obj=doc)
    return TextResult(text=markdown, json_obj=doc)


@app.command("create")
@graph_command(scopes=["Notes.ReadWrite"])
def create(
    client: GraphClient,
    section: Annotated[str, typer.Option("--section", help="Section name or id.")],
    title: Annotated[str, typer.Option("--title", help="Page title.")],
    body: Annotated[str | None, typer.Option("--body", help="Page body text.")] = None,
    body_file: Annotated[
        str | None, typer.Option("--body-file", help="File, or - for stdin.")
    ] = None,
    html_: Annotated[
        bool, typer.Option("--html", help="Treat --body/--body-file as raw HTML, unescaped.")
    ] = False,
    dry_run: DryRunFlag = False,
    json_: JsonFlag = False,
):
    """Create a page in a OneNote section."""
    text = read_body(body, body_file)
    section_id = onenote.resolve_section(client, section)
    plan = onenote.plan_create_page(client, section_id, title=title, body=text, html=html_)
    if dry_run:
        return DryRunResult(plan)
    obj = client.execute(plan[0])
    return WriteResult(obj=obj, message=f"Created page {title!r}.")


@app.command("search")
@graph_command(scopes=["Notes.Read"])
def search(
    client: GraphClient,
    q: Annotated[str, typer.Argument(metavar="Q")],
    limit: LimitOpt = None,
    json_: JsonFlag = False,
):
    """Search OneNote page titles and content (Graph supports this for consumer notebooks only)."""
    bound = limit if limit is not None else DEFAULT_LIMIT
    page = onenote.search_pages(client, q, limit=bound)
    tz = client.tz
    return ListResult(
        items=page.items,
        truncated=page.truncated,
        supports_all=False,
        columns=[
            Column("id", "id"),
            Column("created", lambda pg: fmt_dt(pg.get("createdDateTime"), tz)),
            Column("title", lambda pg: truncate(pg.get("title"))),
        ],
    )
