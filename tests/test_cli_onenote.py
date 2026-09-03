"""CLI tests for the onenote noun (spec §8.13)."""

import json

import httpx
import pytest

from helpers import GRAPH, covers, graph_error, mock_graph


@covers("onenote notebooks")
def test_onenote_notebooks(invoke, graph):
    routes = mock_graph(graph, "onenote/notebooks")
    r = invoke("onenote", "notebooks", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert set(doc) == {"items", "count", "truncated"}
    assert doc["count"] == 2 and doc["items"][0]["id"] == "0-notebook0001!1"
    assert doc["truncated"] is False
    assert routes[0].calls.last.request.headers["Authorization"].startswith("Bearer ")


@covers("onenote notebooks")
def test_onenote_notebooks_text(invoke, graph):
    mock_graph(graph, "onenote/notebooks")
    r = invoke("onenote", "notebooks")
    assert r.exit_code == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "name", "modified"]
    assert "Work" in lines[1]


@covers("onenote sections")
def test_onenote_sections_all_and_by_notebook_name(invoke, graph):
    routes = mock_graph(graph, "onenote/sections")
    r = invoke("onenote", "sections", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 2 and doc["items"][0]["id"] == "0-section0001!1"

    r2 = invoke("onenote", "sections", "Work", "--json")
    assert r2.exit_code == 0, r2.stderr
    doc2 = json.loads(r2.stdout)
    assert doc2["count"] == 1 and doc2["items"][0]["id"] == "0-section0001!1"
    last = routes[2].calls.last.request
    assert last.url.path == "/v1.0/me/onenote/notebooks/0-notebook0001!1/sections"


@covers("onenote pages")
def test_onenote_pages_by_section_name(invoke, graph):
    routes = mock_graph(graph, "onenote/pages")
    r = invoke("onenote", "pages", "Meeting Notes", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 2 and doc["items"][0]["id"] == "1-page0001!1"
    last = routes[1].calls.last.request
    assert last.url.path == "/v1.0/me/onenote/sections/0-section0001!1/pages"


@covers("onenote pages")
def test_onenote_pages_limit_zero_is_usage_error(invoke):
    r = invoke("onenote", "pages", "0-section0001!1", "--limit", "0")
    assert r.exit_code == 2


@covers("onenote read")
def test_onenote_read_markdown_and_json(invoke, graph):
    routes = mock_graph(graph, "onenote/read")
    r = invoke("onenote", "read", "1-abc!12")
    assert r.exit_code == 0, r.stderr
    assert routes[1].calls.last.request.url.query.decode() == "includeIDs=true"
    assert "# Meeting notes" in r.stdout and "- action one" in r.stdout
    doc = json.loads(invoke("onenote", "read", "1-abc!12", "--json").stdout)
    assert set(doc) == {"id", "title", "html", "markdown"} and doc["html"].startswith("<html")
    assert invoke("onenote", "read", "1-abc!12", "--html").stdout.startswith("<html")


@covers("onenote read")
def test_onenote_read_by_title_resolves(invoke, graph):
    routes = mock_graph(graph, "onenote/read_by_title")
    r = invoke("onenote", "read", "Weekly Sync")
    assert r.exit_code == 0, r.stderr
    assert routes[0].calls.last.request.url.path == "/v1.0/me/onenote/pages"
    assert "# Weekly Sync" in r.stdout


@covers("onenote read")
def test_onenote_read_output_writes_markdown(invoke, graph, tmp_path):
    mock_graph(graph, "onenote/read")
    dest = tmp_path / "notes.md"
    r = invoke("onenote", "read", "1-abc!12", "--output", str(dest))
    assert r.exit_code == 0, r.stderr
    text = dest.read_text()
    assert "# Meeting notes" in text and "- action one" in text
    assert "Wrote" in r.stdout and str(dest) in r.stdout


@covers("onenote read")
@pytest.mark.parametrize(
    "status,code,exit_code",
    [(404, "ErrorItemNotFound", 4), (403, "ErrorAccessDenied", 3), (400, "BadRequest", 1)],
)
def test_onenote_read_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.get(f"{GRAPH}/v1.0/me/onenote/pages/1-abc%2112").mock(
        return_value=graph_error(status, code)
    )
    r = invoke("onenote", "read", "1-abc!12")
    assert r.exit_code == exit_code
    assert r.stdout == ""
    assert r.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("onenote read")
def test_onenote_read_401_after_refresh(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/me/onenote/pages/1-abc%2112").mock(
        return_value=graph_error(401, "InvalidAuthenticationToken")
    )
    r = invoke("onenote", "read", "1-abc!12")
    assert r.exit_code == 3 and route.call_count == 2
    assert r.stderr.startswith("error[UNAUTHORIZED]:") and "login --force" in r.stderr


@covers("onenote create")
def test_onenote_create_escapes_unless_html(invoke, graph):
    url = f"{GRAPH}/v1.0/me/onenote/sections/0-section0001%211/pages"
    route = graph.post(url).mock(
        side_effect=[
            httpx.Response(201, json={"id": "1-page0099!1", "title": "Q3 <plan>"}),
            httpx.Response(201, json={"id": "1-page0100!1", "title": "Raw"}),
        ]
    )
    r = invoke(
        "onenote",
        "create",
        "--section",
        "0-section0001!1",
        "--title",
        "Q3 <plan>",
        "--body",
        "a <b>",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    first = route.calls[0].request
    assert first.headers["Content-Type"] == "text/html"
    body = first.content.decode()
    assert "<title>Q3 &lt;plan&gt;</title>" in body
    assert "<p>a &lt;b&gt;</p>" in body

    r2 = invoke(
        "onenote",
        "create",
        "--section",
        "0-section0001!1",
        "--title",
        "Raw",
        "--body",
        "<p>raw html</p>",
        "--html",
        "--json",
    )
    assert r2.exit_code == 0, r2.stderr
    second_body = route.calls[1].request.content.decode()
    assert "<body><p>raw html</p></body>" in second_body


@covers("onenote create")
def test_onenote_create_dry_run(invoke, graph):
    r = invoke(
        "onenote",
        "create",
        "--section",
        "0-section0001!1",
        "--title",
        "Q3 <plan>",
        "--body",
        "a <b>",
        "--dry-run",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["dryRun"] is True
    step = doc["requests"][0]
    assert step["method"] == "POST"
    assert step["url"] == f"{GRAPH}/v1.0/me/onenote/sections/0-section0001%211/pages"
    assert step["headers"] == {"Content-Type": "text/html"}
    assert step["body"] == (
        "<!DOCTYPE html><html><head><title>Q3 &lt;plan&gt;</title></head>"
        "<body><p>a &lt;b&gt;</p></body></html>"
    )
    assert graph.calls.call_count == 0


@covers("onenote create")
@pytest.mark.scopes(["Notes.Read"])
def test_onenote_create_missing_scope(invoke, graph):
    r = invoke(
        "onenote",
        "create",
        "--section",
        "0-section0001!1",
        "--title",
        "T",
        "--body",
        "b",
    )
    assert r.exit_code == 3 and graph.calls.call_count == 0
    assert r.stderr.startswith(
        "error[MISSING_SCOPE]: this command needs Notes.ReadWrite; "
        "the current token has Notes.Read\n"
    )
    assert "login --scopes extended" in r.stderr


@covers("onenote search")
def test_onenote_search(invoke, graph):
    routes = mock_graph(graph, "onenote/search")
    r = invoke("onenote", "search", "budget", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 1 and doc["items"][0]["id"] == "1-page0050!1"
    assert routes[0].calls.last.request.url.params["$search"] == "budget"


@covers("onenote search")
def test_onenote_search_passthrough_hint(invoke, graph):
    graph.get(f"{GRAPH}/v1.0/me/onenote/pages").mock(
        return_value=graph_error(400, "BadRequest", "search not supported for work accounts")
    )
    r = invoke("onenote", "search", "budget")
    assert r.exit_code == 1
    assert r.stdout == ""
    assert r.stderr.startswith("error[BadRequest]: search not supported for work accounts\n")
    assert "search budget --type driveItem" in r.stderr


def test_onenote_group_help(invoke):
    r = invoke("onenote")
    assert r.exit_code == 0 and "Usage:" in r.stdout
