"""CLI tests for the sharepoint noun (spec §8.12, §6.6)."""

import json

import httpx
import pytest

from helpers import GRAPH, covers, graph_error, mock_graph
from mgraphctl import odata
from mgraphctl.graph import files, sharepoint

V1 = f"{GRAPH}/v1.0"
SITE_ID = (
    "contoso.example,11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222"
)
LIST_ID = "44444444-4444-4444-4444-444444444444"


def test_sharepoint_group_help(invoke):
    r = invoke("sharepoint")
    assert r.exit_code == 0 and "Usage:" in r.stdout


@covers("sharepoint sites")
def test_sharepoint_sites_followed_then_search_fallback(invoke, graph):
    routes = mock_graph(graph, "sharepoint/sites")
    r = invoke("sharepoint", "sites", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert set(doc) == {"items", "count", "truncated"}
    assert (
        doc["count"] == 1 and doc["items"][0]["displayName"] == "Eng" and doc["truncated"] is False
    )
    assert routes[0].called and routes[1].called and not routes[2].called

    r2 = invoke("sharepoint", "sites", "--search", "x")
    assert r2.exit_code == 0, r2.stderr
    assert routes[2].called
    lines = r2.stdout.splitlines()
    assert lines[0].split() == ["id", "name", "webUrl"]
    assert "Xray" in r2.stdout


@covers("sharepoint site")
def test_sharepoint_site_forms(invoke, graph):
    routes = mock_graph(graph, "sharepoint/site")
    for ref, idx in (
        ("https://contoso.example/sites/Eng/Shared%20Documents/a.docx", 0),
        ("contoso.example:/sites/Eng", 0),
        ("https://contoso.example/", 1),
        (SITE_ID, 2),
        ("Eng", 3),
    ):
        r = invoke("sharepoint", "site", ref, "--json")
        assert r.exit_code == 0, (ref, r.stderr)
        assert routes[idx].called and json.loads(r.stdout)["displayName"] == "Eng"
    assert (
        routes[0].calls[0].request.url.params["$select"] == "id,displayName,name,webUrl,description"
    )


@covers("sharepoint site")
def test_sharepoint_site_ambiguous_exit_2(invoke, graph):
    graph.get(f"{V1}/sites", params__eq={"search": "Eng"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [{"id": "s1", "displayName": "Eng"}, {"id": "s2", "displayName": "Eng"}]
            },
        )
    )
    r = invoke("sharepoint", "site", "Eng")
    assert r.exit_code == 2
    assert r.stderr.startswith("error[AMBIGUOUS]:")


@covers("sharepoint site")
@pytest.mark.parametrize(
    "status,code,exit_code",
    [(404, "ErrorItemNotFound", 4), (403, "ErrorAccessDenied", 3), (400, "BadRequest", 1)],
)
def test_sharepoint_site_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.get(f"{V1}/sites/contoso.example").mock(return_value=graph_error(status, code))
    r = invoke("sharepoint", "site", "https://contoso.example/")
    assert r.exit_code == exit_code
    assert r.stdout == ""
    assert r.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("sharepoint site")
def test_sharepoint_site_401_after_refresh(invoke, graph):
    route = graph.get(f"{V1}/sites/contoso.example").mock(
        return_value=graph_error(401, "InvalidAuthenticationToken")
    )
    r = invoke("sharepoint", "site", "https://contoso.example/")
    assert r.exit_code == 3 and route.call_count == 2
    assert r.stderr.startswith("error[UNAUTHORIZED]:") and "login --force" in r.stderr


@covers("sharepoint drives")
def test_sharepoint_drives(invoke, graph):
    routes = mock_graph(graph, "sharepoint/drives")
    r = invoke("sharepoint", "drives", SITE_ID, "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 1 and doc["items"][0]["id"] == "b!drive1"
    assert routes[0].called and routes[1].called


@covers("sharepoint ls")
def test_sharepoint_ls_site_drive_and_named_drive(invoke, graph):
    routes = mock_graph(graph, "sharepoint/ls")
    r = invoke("sharepoint", "ls", SITE_ID, "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["items"][0]["id"] == "item-1"
    assert routes[0].called and routes[1].called

    r2 = invoke("sharepoint", "ls", SITE_ID, "Sub", "--drive", "Documents")
    assert r2.exit_code == 0, r2.stderr
    assert routes[2].called and routes[3].called
    assert "item-2" in r2.stdout


@covers("sharepoint ls")
def test_sharepoint_ls_limit_zero_is_usage_error(invoke):
    assert invoke("sharepoint", "ls", SITE_ID, "--limit", "0").exit_code == 2


@covers("sharepoint search")
def test_sharepoint_search_site_and_global(invoke, graph):
    routes = mock_graph(graph, "sharepoint/search")
    r = invoke("sharepoint", "search", "x", "--site", SITE_ID, "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["items"][0]["id"] == "s1"
    assert routes[0].called and routes[1].called

    r2 = invoke("sharepoint", "search", "x", "--json")
    assert r2.exit_code == 0, r2.stderr
    doc2 = json.loads(r2.stdout)
    assert doc2["items"][0]["id"] == "g1"
    assert routes[2].called
    body = json.loads(routes[2].calls.last.request.content)
    assert body["requests"][0] == {
        "entityTypes": ["driveItem"],
        "query": {"queryString": "x"},
        "from": 0,
        "size": 25,
    }


@covers("sharepoint download")
def test_sharepoint_download_uses_site_drive(invoke, graph, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    routes = mock_graph(graph, "sharepoint/download")
    r = invoke("sharepoint", "download", SITE_ID, "AAAAAAAAAAAAAAAAAAAAAAAA")
    assert r.exit_code == 0, r.stderr
    assert routes[0].called and routes[1].called and routes[2].called
    assert (tmp_path / "Report.pdf").read_bytes() == b"hello world"
    assert "Downloaded Report.pdf" in r.stdout


@covers("sharepoint lists")
def test_sharepoint_lists_hides_hidden(invoke, graph):
    routes = mock_graph(graph, "sharepoint/lists")
    r = invoke("sharepoint", "lists", SITE_ID, "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 1 and doc["items"][0]["displayName"] == "Documents"
    assert routes[0].called and routes[1].called
    assert routes[1].calls.last.request.url.params["$select"] == "id,displayName,webUrl,list"


@covers("sharepoint items")
def test_sharepoint_items_fields_filter_and_prefer(invoke, graph):
    routes = mock_graph(graph, "sharepoint/items")
    r = invoke("sharepoint", "items", SITE_ID, LIST_ID, "--fields", "Title,Status")
    assert r.exit_code == 0, r.stderr
    assert routes[0].called and routes[1].called and routes[2].called
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["Title", "Status"]
    assert "Task A" in r.stdout and "Task B" in r.stdout

    r2 = invoke(
        "sharepoint",
        "items",
        SITE_ID,
        LIST_ID,
        "--fields",
        "Title,Status",
        "--filter",
        "fields/Status eq 'Open'",
        "--json",
    )
    assert r2.exit_code == 0, r2.stderr
    doc = json.loads(r2.stdout)
    assert doc["count"] == 1 and doc["items"][0]["fields"]["Title"] == "Task A"
    assert routes[3].called
    assert (
        routes[3].calls.last.request.headers["Prefer"]
        == "HonorNonIndexedQueriesWarningMayFailRandomly"
    )


# --------------------------------------------------------------------------- url


@covers("sharepoint url")
def test_sharepoint_url_share_link_first(invoke, graph, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    url_ = "https://contoso.example/sites/Eng/Shared%20Documents/a.docx"
    share_id = odata.share_id(url_)
    item = {
        "id": "item-1",
        "name": "a.docx",
        "parentReference": {
            "siteId": SITE_ID,
            "driveId": "b!drive1",
            "path": "/drives/b!drive1/root:/Folder",
        },
    }
    meta_route = graph.get(
        f"{V1}/shares/{share_id}/driveItem", params__eq={"$select": files.ITEM_SELECT}
    ).mock(return_value=httpx.Response(200, json=item))

    r = invoke("sharepoint", "url", url_, "--info", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["resolution"] == {"siteId": SITE_ID, "driveId": "b!drive1", "path": "/Folder/a.docx"}
    assert doc["item"]["id"] == "item-1"
    assert meta_route.called

    content_route = graph.get(f"{V1}/shares/{share_id}/driveItem/content").mock(
        return_value=httpx.Response(
            200, content=b"data", headers={"Content-Type": "application/pdf"}
        )
    )
    r2 = invoke("sharepoint", "url", url_)
    assert r2.exit_code == 0, r2.stderr
    assert content_route.called
    assert (tmp_path / "a.docx").read_bytes() == b"data"


@covers("sharepoint url")
def test_sharepoint_url_node_algorithm_fallback(invoke, graph, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    url_ = "https://contoso.example/:w:/r/sites/Eng/Shared%20Documents/Folder/a.docx?web=1"
    share_id = odata.share_id(url_)
    graph.get(f"{V1}/shares/{share_id}/driveItem").mock(
        return_value=graph_error(403, "AccessDenied")
    )
    site_route = graph.get(
        f"{V1}/sites/contoso.example:/sites/Eng", params__eq={"$select": sharepoint.SITE_SELECT}
    ).mock(return_value=httpx.Response(200, json={"id": SITE_ID, "displayName": "Eng"}))
    drives_route = graph.get(
        f"{V1}/sites/{SITE_ID}/drives", params__eq={"$select": sharepoint.DRIVE_SELECT}
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "b!root",
                        "name": "Site Pages",
                        "webUrl": "https://contoso.example/sites/Eng",
                        "driveType": "documentLibrary",
                    },
                    {
                        "id": "b!docs",
                        "name": "Documents",
                        "webUrl": "https://contoso.example/sites/Eng/Shared Documents",
                        "driveType": "documentLibrary",
                    },
                ]
            },
        )
    )
    item_route = graph.get(
        f"{V1}/drives/b!docs/root:/Folder/a.docx", params__eq={"$select": files.ITEM_SELECT}
    ).mock(return_value=httpx.Response(200, json={"id": "item-2", "name": "a.docx"}))
    content_route = graph.get(f"{V1}/drives/b!docs/root:/Folder/a.docx:/content").mock(
        return_value=httpx.Response(
            200, content=b"payload", headers={"Content-Type": "application/octet-stream"}
        )
    )

    r = invoke("sharepoint", "url", url_)
    assert r.exit_code == 0, r.stderr
    assert site_route.called and drives_route.called and item_route.called and content_route.called
    assert (tmp_path / "a.docx").read_bytes() == b"payload"


@covers("sharepoint url")
def test_sharepoint_url_fallback_without_first_segment(invoke, graph, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    url_ = "https://contoso.example/sites/Eng/Folder/a.docx"
    share_id = odata.share_id(url_)
    graph.get(f"{V1}/shares/{share_id}/driveItem").mock(
        return_value=graph_error(404, "ItemNotFound")
    )
    graph.get(
        f"{V1}/sites/contoso.example:/sites/Eng", params__eq={"$select": sharepoint.SITE_SELECT}
    ).mock(return_value=httpx.Response(200, json={"id": SITE_ID, "displayName": "Eng"}))
    graph.get(f"{V1}/sites/{SITE_ID}/drives", params__eq={"$select": sharepoint.DRIVE_SELECT}).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "b!x",
                        "name": "Pages",
                        "webUrl": "https://contoso.example/sites/Eng",
                        "driveType": "documentLibrary",
                    }
                ]
            },
        )
    )
    drive_attempt = graph.get(
        f"{V1}/drives/b!x/root:/Folder/a.docx", params__eq={"$select": files.ITEM_SELECT}
    ).mock(return_value=graph_error(404, "ItemNotFound"))
    with_first = graph.get(
        f"{V1}/sites/{SITE_ID}/drive/root:/Folder/a.docx", params__eq={"$select": files.ITEM_SELECT}
    ).mock(return_value=graph_error(404, "ItemNotFound"))
    without_first = graph.get(
        f"{V1}/sites/{SITE_ID}/drive/root:/a.docx", params__eq={"$select": files.ITEM_SELECT}
    ).mock(return_value=httpx.Response(200, json={"id": "item-3", "name": "a.docx"}))
    content_route = graph.get(f"{V1}/sites/{SITE_ID}/drive/root:/a.docx:/content").mock(
        return_value=httpx.Response(
            200, content=b"final", headers={"Content-Type": "application/octet-stream"}
        )
    )

    r = invoke("sharepoint", "url", url_)
    assert r.exit_code == 0, r.stderr
    assert (
        drive_attempt.called and with_first.called and without_first.called and content_route.called
    )
    assert (tmp_path / "a.docx").read_bytes() == b"final"


@covers("sharepoint url")
def test_sharepoint_url_personal_hint(invoke, graph):
    url_ = "https://contoso-my.example/personal/alice_contoso_example/Documents/a.docx"
    share_id = odata.share_id(url_)
    graph.get(f"{V1}/shares/{share_id}/driveItem").mock(
        return_value=graph_error(403, "AccessDenied")
    )
    r = invoke("sharepoint", "url", url_)
    assert r.exit_code == 3
    assert r.stderr.startswith("error[FORBIDDEN]:")
    assert "owner" in r.stderr and "share" in r.stderr


# --------------------------------------------------------------------------- upload


@covers("sharepoint upload")
def test_sharepoint_upload_site_drive(invoke, graph, tmp_path):
    site_route = graph.get(
        f"{V1}/sites/{SITE_ID}", params__eq={"$select": sharepoint.SITE_SELECT}
    ).mock(return_value=httpx.Response(200, json={"id": SITE_ID, "displayName": "Eng"}))

    small = tmp_path / "a.txt"
    small.write_bytes(b"hello")
    put_route = graph.put(
        f"{V1}/sites/{SITE_ID}/drive/root:/Docs/a.txt:/content",
        params__eq={"@microsoft.graph.conflictBehavior": "replace"},
    ).mock(
        return_value=httpx.Response(
            201, json={"id": "up-1", "webUrl": "https://contoso.example/Docs/a.txt"}
        )
    )
    r = invoke("sharepoint", "upload", SITE_ID, str(small), "--dest", "Docs/a.txt", "--json")
    assert r.exit_code == 0, r.stderr
    assert site_route.called and put_route.called
    assert json.loads(r.stdout)["id"] == "up-1"

    big = tmp_path / "b.bin"
    big.write_bytes(b"y" * (5 * 1024 * 1024))
    create_route = graph.post(
        f"{V1}/sites/{SITE_ID}/drive/root:/Docs/b.bin:/createUploadSession"
    ).mock(
        return_value=httpx.Response(200, json={"uploadUrl": "https://upload.example.com/session-1"})
    )
    chunk_route = graph.put("https://upload.example.com/session-1").mock(
        return_value=httpx.Response(201, json={"id": "up-2"})
    )
    r2 = invoke(
        "sharepoint",
        "upload",
        SITE_ID,
        str(big),
        "--dest",
        "Docs/b.bin",
        "--conflict",
        "rename",
        "--json",
    )
    assert r2.exit_code == 0, r2.stderr
    assert create_route.called and chunk_route.called
    assert json.loads(r2.stdout)["id"] == "up-2"


@covers("sharepoint upload")
def test_sharepoint_upload_dry_run(invoke, graph, tmp_path):
    site_route = graph.get(
        f"{V1}/sites/{SITE_ID}", params__eq={"$select": sharepoint.SITE_SELECT}
    ).mock(return_value=httpx.Response(200, json={"id": SITE_ID, "displayName": "Eng"}))
    small = tmp_path / "a.txt"
    small.write_bytes(b"hello")
    put_route = graph.put(f"{V1}/sites/{SITE_ID}/drive/root:/Docs/a.txt:/content").mock(
        return_value=httpx.Response(201, json={"id": "up-1"})
    )

    r = invoke(
        "sharepoint", "upload", SITE_ID, str(small), "--dest", "Docs/a.txt", "--dry-run", "--json"
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["dryRun"] is True
    upload_url = f"{V1}/sites/{SITE_ID}/drive/root:/Docs/a.txt:/content"
    assert doc["requests"] == [
        {
            "method": "PUT",
            "url": f"{upload_url}?@microsoft.graph.conflictBehavior=replace",
            "headers": {"Content-Type": "text/plain"},
            "body": {"$file": str(small), "bytes": 5, "contentType": "text/plain"},
        }
    ]
    # Resolving SITE to a dict needs a real lookup, but the write itself never happens.
    assert site_route.called
    assert not put_route.called


@covers("sharepoint upload")
@pytest.mark.scopes(["Sites.Read.All"])
def test_sharepoint_upload_missing_scope(invoke, graph, tmp_path):
    small = tmp_path / "a.txt"
    small.write_bytes(b"hello")
    r = invoke("sharepoint", "upload", SITE_ID, str(small))
    assert r.exit_code == 3 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[MISSING_SCOPE]:")
    assert "login --scopes extended" in r.stderr
