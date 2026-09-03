"""CLI tests for the onedrive noun (spec §8.11)."""

import json

import httpx
import pytest

from helpers import GRAPH, covers, graph_error, mock_graph
from mgraphctl import odata

SHARE_URL = "https://contoso.example/:x:/s/team/Ab12CdEf34"


# --------------------------------------------------------------------------- ls / search / get


@covers("onedrive ls")
def test_onedrive_ls_root_and_path(invoke, graph):
    routes = mock_graph(graph, "onedrive/ls")
    r = invoke("onedrive", "ls", "--json")
    assert r.exit_code == 0, r.stderr
    assert dict(routes[0].calls.last.request.url.params) == {
        "$top": "200",
        "$orderby": "name",
        "$select": "id,name,size,lastModifiedDateTime,file,folder,webUrl,parentReference",
    }
    assert json.loads(r.stdout)["count"] == 2
    r = invoke("onedrive", "ls", "Docs Q3")
    assert routes[1].called and r.stdout.splitlines()[0].split() == [
        "type",
        "id",
        "size",
        "modified",
        "name",
    ]
    assert r.stdout.splitlines()[1].split()[:2] == ["d", "01ABCDEFGHIJKLMNOPQRSTUV"]


@covers("onedrive ls")
def test_onedrive_ls_drive_option(invoke, graph):
    # base_for() runs the drive id through odata.p(), so "!" is percent-encoded like any other
    # path segment (matching item_ref()'s own handling of ids elsewhere in graph/files.py).
    route = graph.get(f"{GRAPH}/v1.0{odata.p('drives', 'b!abc')}/root/children").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    r = invoke("onedrive", "ls", "--drive", "b!abc")
    assert r.exit_code == 0, r.stderr
    assert route.called


@covers("onedrive ls")
def test_onedrive_ls_limit_zero_is_usage_error(invoke):
    assert invoke("onedrive", "ls", "--limit", "0").exit_code == 2


@covers("onedrive search")
def test_onedrive_search_own_and_shared(invoke, graph):
    routes = mock_graph(graph, "onedrive/search")
    r = invoke("onedrive", "search", "quarter", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["count"] == 1
    assert dict(routes[0].calls.last.request.url.params) == {
        "$select": "id,name,size,lastModifiedDateTime,file,folder,webUrl,parentReference",
        "$top": "200",
    }
    r = invoke("onedrive", "search", "quarter", "--shared")
    assert r.exit_code == 0, r.stderr
    assert routes[1].called


@covers("onedrive get")
def test_onedrive_get_by_id_and_path(invoke, graph):
    routes = mock_graph(graph, "onedrive/get")
    r = invoke("onedrive", "get", "01ABCDEFGHIJKLMNOPQRSTUV", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["name"] == "report.pdf"
    assert routes[0].called
    r = invoke("onedrive", "get", "Docs/report.pdf")
    assert r.exit_code == 0, r.stderr
    assert "report.pdf" in r.stdout and routes[1].called


@covers("onedrive get")
@pytest.mark.parametrize(
    "status,code,exit_code",
    [(404, "ErrorItemNotFound", 4), (403, "ErrorAccessDenied", 3), (400, "BadRequest", 1)],
)
def test_onedrive_get_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.get(f"{GRAPH}/v1.0/me/drive/items/01BADBADBADBADBADBADBAD").mock(
        return_value=graph_error(status, code)
    )
    r = invoke("onedrive", "get", "01BADBADBADBADBADBADBAD")
    assert r.exit_code == exit_code
    assert r.stdout == ""
    assert r.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("onedrive get")
def test_onedrive_get_401_after_refresh(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/me/drive/items/01BADBADBADBADBADBADBAD").mock(
        return_value=graph_error(401, "InvalidAuthenticationToken")
    )
    r = invoke("onedrive", "get", "01BADBADBADBADBADBADBAD")
    assert r.exit_code == 3 and route.call_count == 2
    assert r.stderr.startswith("error[UNAUTHORIZED]:") and "login --force" in r.stderr


# --------------------------------------------------------------------------- download


@covers("onedrive download")
def test_onedrive_download_default_name_and_output(invoke, graph, tmp_path, monkeypatch):
    mock_graph(graph, "onedrive/download")
    graph.get("https://files.contoso.example/blob", params__contains={"tempauth": "abc"}).mock(
        return_value=httpx.Response(
            200, content=b"Hello Graph!", headers={"Content-Type": "application/pdf"}
        )
    )
    monkeypatch.chdir(tmp_path)
    r = invoke("onedrive", "download", "01ABCDEFGHIJKLMNOPQRSTUV")
    assert r.exit_code == 0, r.stderr
    # No --output: the item's own name, relative to the current directory (files.download_item's
    # default `dest`).
    assert r.stdout == "Downloaded report.pdf (12 B) to report.pdf\n"
    assert (tmp_path / "report.pdf").read_bytes() == b"Hello Graph!"

    out = tmp_path / "out" / "r.pdf"
    r2 = invoke("onedrive", "download", "01ABCDEFGHIJKLMNOPQRSTUV", "--output", str(out), "--json")
    assert r2.exit_code == 0, r2.stderr
    doc = json.loads(r2.stdout)
    assert set(doc) == {"path", "bytes", "contentType"}
    assert doc["bytes"] == 12 and doc["path"] == str(out)
    assert out.read_bytes() == b"Hello Graph!"


# ----------------------------------------------------------------- shared-with-me/recent/link


@covers("onedrive shared-with-me")
def test_onedrive_shared_with_me_note(invoke, graph):
    mock_graph(graph, "onedrive/shared_with_me")
    r = invoke("onedrive", "shared-with-me")
    assert r.exit_code == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "name", "size", "modified", "sharedDriveId", "sharedItemId"]
    assert "b!remoteDrive0001" in lines[1] and "01REMOTE00000000000001" in lines[1]
    assert "November 2026" in r.stderr

    r2 = invoke("onedrive", "shared-with-me", "--json")
    doc = json.loads(r2.stdout)
    assert doc["items"][0]["remoteItem"]["parentReference"]["driveId"] == "b!remoteDrive0001"
    assert doc["items"][0]["remoteItem"]["id"] == "01REMOTE00000000000001"


@covers("onedrive recent")
def test_onedrive_recent(invoke, graph):
    mock_graph(graph, "onedrive/recent")
    r = invoke("onedrive", "recent", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 1 and doc["items"][0]["name"] == "Notes.docx"


@covers("onedrive link")
def test_onedrive_link_info_and_download(invoke, graph, tmp_path):
    share_path = f"/v1.0/shares/{odata.share_id(SHARE_URL)}/driveItem"
    info_route = graph.get(GRAPH + share_path).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "01LINK00000000000000001",
                "name": "Deck.pptx",
                "size": 12,
                "lastModifiedDateTime": "2026-08-25T00:00:00Z",
                "webUrl": SHARE_URL,
            },
        )
    )
    r = invoke("onedrive", "link", SHARE_URL)
    assert r.exit_code == 0, r.stderr
    assert "Deck.pptx" in r.stdout
    assert info_route.called

    graph.get(GRAPH + share_path + "/content").mock(
        return_value=httpx.Response(
            200, content=b"pptx-bytes!!", headers={"Content-Type": "application/x"}
        )
    )
    out = tmp_path / "deck.pptx"
    r2 = invoke("onedrive", "link", SHARE_URL, "--download", "--output", str(out))
    assert r2.exit_code == 0, r2.stderr
    assert out.read_bytes() == b"pptx-bytes!!"
    assert r2.stdout == f"Downloaded Deck.pptx (12 B) to {out}\n"
