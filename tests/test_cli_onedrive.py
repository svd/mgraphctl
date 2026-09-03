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


# --------------------------------------------------------------------------- upload


@covers("onedrive upload")
def test_onedrive_upload_small_put(invoke, graph, tmp_path):
    src = tmp_path / "a.txt"
    src.write_bytes(b"hello world!")
    route = graph.put(
        f"{GRAPH}/v1.0/me/drive/root:/Docs/a.txt:/content",
        params__eq={"@microsoft.graph.conflictBehavior": "replace"},
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "01UPLOAD0000000000000001", "name": "a.txt", "size": 12}
        )
    )
    r = invoke("onedrive", "upload", str(src), "--dest", "Docs/a.txt", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["name"] == "a.txt"
    req = route.calls.last.request
    assert req.content == b"hello world!"
    assert req.headers["Content-Type"] == "text/plain"


@covers("onedrive upload")
def test_onedrive_upload_large_session(invoke, graph, tmp_path):
    size = 5 * 1024 * 1024
    src = tmp_path / "big.bin"
    src.write_bytes(b"\x00" * size)
    create_route = graph.post(f"{GRAPH}/v1.0/me/drive/root:/big.bin:/createUploadSession").mock(
        return_value=httpx.Response(
            200, json={"uploadUrl": "https://upload.contoso.example/session1"}
        )
    )
    chunk_route = graph.put("https://upload.contoso.example/session1").mock(
        return_value=httpx.Response(
            201, json={"id": "01BIGFILE00000000000001", "name": "big.bin", "size": size}
        )
    )
    r = invoke("onedrive", "upload", str(src), "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["id"] == "01BIGFILE00000000000001"
    body = json.loads(create_route.calls.last.request.content)
    assert body == {"item": {"@microsoft.graph.conflictBehavior": "replace", "name": "big.bin"}}
    assert chunk_route.calls.last.request.headers["Content-Range"] == f"bytes 0-{size - 1}/{size}"
    assert chunk_route.call_count == 1


@covers("onedrive upload")
def test_onedrive_upload_dest_folder_and_conflict(invoke, graph, tmp_path):
    src = tmp_path / "notes.md"
    src.write_bytes(b"# notes")
    route = graph.put(
        f"{GRAPH}/v1.0/me/drive/root:/Docs/notes.md:/content",
        params__eq={"@microsoft.graph.conflictBehavior": "fail"},
    ).mock(
        return_value=httpx.Response(
            200, json={"id": "01NOTES00000000000000001", "name": "notes.md"}
        )
    )
    r = invoke("onedrive", "upload", str(src), "--dest", "Docs/", "--conflict", "fail", "--json")
    assert r.exit_code == 0, r.stderr
    assert route.called
    assert json.loads(r.stdout)["name"] == "notes.md"


@covers("onedrive upload")
def test_onedrive_upload_dry_run(invoke, graph, tmp_path):
    size = 5 * 1024 * 1024
    src = tmp_path / "big2.bin"
    src.write_bytes(b"\x00" * size)
    r = invoke("onedrive", "upload", str(src), "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["dryRun"] is True
    step = doc["requests"][0]
    assert step["method"] == "POST"
    assert step["url"].endswith("/me/drive/root:/big2.bin:/createUploadSession")
    assert step["body"]["createUploadSession"] == {
        "item": {"@microsoft.graph.conflictBehavior": "replace", "name": "big2.bin"}
    }
    assert step["body"]["upload"] == {
        "$file": str(src),
        "bytes": size,
        "contentType": "application/octet-stream",
    }
    assert step["body"]["chunkSize"] == 10485760
    assert graph.calls.call_count == 0


@covers("onedrive upload")
def test_onedrive_upload_absent_file_is_a_usage_error(invoke, graph, tmp_path):
    r = invoke("onedrive", "upload", str(tmp_path / "gone.txt"))
    assert r.exit_code == 2 and graph.calls.call_count == 0


@covers("onedrive upload")
@pytest.mark.scopes(["Files.Read"])
def test_onedrive_upload_missing_scope(invoke, graph, tmp_path):
    src = tmp_path / "a.txt"
    src.write_bytes(b"hi")
    r = invoke("onedrive", "upload", str(src))
    assert r.exit_code == 3 and graph.calls.call_count == 0
    assert r.stderr.startswith(
        "error[MISSING_SCOPE]: this command needs Files.ReadWrite; "
        "the current token has Files.Read\n"
    )


# ------------------------------------------------------------------- mkdir/move/rename/delete


@covers("onedrive mkdir")
def test_onedrive_mkdir(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/drive/root:/Docs:/children").mock(
        return_value=httpx.Response(
            201, json={"id": "01MKDIR000000000000001", "name": "Q4", "folder": {"childCount": 0}}
        )
    )
    r = invoke("onedrive", "mkdir", "Docs/Q4", "--json")
    assert r.exit_code == 0, r.stderr
    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "Q4", "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
    assert json.loads(r.stdout)["name"] == "Q4"


@covers("onedrive mkdir")
def test_onedrive_mkdir_dry_run(invoke, graph):
    r = invoke("onedrive", "mkdir", "Docs/Q4", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["requests"][0]["body"] == {
        "name": "Q4",
        "folder": {},
        "@microsoft.graph.conflictBehavior": "fail",
    }
    assert graph.calls.call_count == 0


@covers("onedrive move")
def test_onedrive_move_by_path_and_id(invoke, graph):
    route1 = graph.patch(f"{GRAPH}/v1.0/me/drive/items/01MOVE000000000000000001").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "01MOVE000000000000000001",
                "name": "a.txt",
                "parentReference": {"id": "01FOLDERTARGET00000000001"},
            },
        )
    )
    r = invoke(
        "onedrive",
        "move",
        "01MOVE000000000000000001",
        "--to",
        "id:01FOLDERTARGET00000000001",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    assert json.loads(route1.calls.last.request.content) == {
        "parentReference": {"id": "01FOLDERTARGET00000000001"}
    }

    folder_route = graph.get(f"{GRAPH}/v1.0/me/drive/root:/Archive").mock(
        return_value=httpx.Response(
            200, json={"id": "01ARCHIVE0000000000000001", "name": "Archive"}
        )
    )
    move_route = graph.patch(f"{GRAPH}/v1.0/me/drive/root:/Docs/a.txt").mock(
        return_value=httpx.Response(
            200, json={"id": "01MOVE000000000000000001", "name": "renamed.txt"}
        )
    )
    r2 = invoke(
        "onedrive", "move", "Docs/a.txt", "--to", "Archive", "--name", "renamed.txt", "--json"
    )
    assert r2.exit_code == 0, r2.stderr
    assert folder_route.called and move_route.called
    assert json.loads(move_route.calls.last.request.content) == {
        "parentReference": {"id": "01ARCHIVE0000000000000001"},
        "name": "renamed.txt",
    }


@covers("onedrive move")
def test_onedrive_move_dry_run(invoke, graph):
    r = invoke(
        "onedrive",
        "move",
        "01MOVE000000000000000001",
        "--to",
        "id:01FOLDERTARGET00000000001",
        "--dry-run",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["requests"][0]["body"] == {"parentReference": {"id": "01FOLDERTARGET00000000001"}}
    assert graph.calls.call_count == 0


@covers("onedrive rename")
def test_onedrive_rename(invoke, graph):
    route = graph.patch(f"{GRAPH}/v1.0/me/drive/items/01RENAME0000000000000001").mock(
        return_value=httpx.Response(
            200, json={"id": "01RENAME0000000000000001", "name": "final.txt"}
        )
    )
    r = invoke("onedrive", "rename", "01RENAME0000000000000001", "final.txt", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(route.calls.last.request.content) == {"name": "final.txt"}
    assert json.loads(r.stdout)["name"] == "final.txt"


@covers("onedrive rename")
def test_onedrive_rename_dry_run(invoke, graph):
    r = invoke("onedrive", "rename", "01RENAME0000000000000001", "final.txt", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["requests"][0]["body"] == {"name": "final.txt"}
    assert graph.calls.call_count == 0


@covers("onedrive delete")
def test_onedrive_delete(invoke, graph):
    route = graph.delete(f"{GRAPH}/v1.0/me/drive/items/01DELETE0000000000000001").mock(
        return_value=httpx.Response(204)
    )
    r = invoke("onedrive", "delete", "01DELETE0000000000000001", "--json")
    assert r.exit_code == 0, r.stderr
    assert route.called
    assert json.loads(r.stdout) == {"status": "deleted", "id": "01DELETE0000000000000001"}


@covers("onedrive delete")
def test_onedrive_delete_dry_run(invoke, graph):
    r = invoke("onedrive", "delete", "01DELETE0000000000000001", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["requests"] == [
        {
            "method": "DELETE",
            "url": f"{GRAPH}/v1.0/me/drive/items/01DELETE0000000000000001",
            "headers": {},
            "body": None,
        }
    ]
    assert graph.calls.call_count == 0


# --------------------------------------------------------------------------- share


@covers("onedrive share")
def test_onedrive_share_prints_web_url(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/drive/items/01SHARE0000000000000001/createLink").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "perm1",
                "roles": ["write"],
                "link": {
                    "type": "edit",
                    "scope": "anonymous",
                    "webUrl": "https://contoso.example/share/xyz",
                },
            },
        )
    )
    r = invoke(
        "onedrive",
        "share",
        "01SHARE0000000000000001",
        "--type",
        "edit",
        "--scope",
        "anonymous",
        "--expires",
        "2026-12-31T23:59:59",
    )
    assert r.exit_code == 0, r.stderr
    assert r.stdout == "https://contoso.example/share/xyz\n"
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "type": "edit",
        "scope": "anonymous",
        "expirationDateTime": "2026-12-31T23:59:59+01:00",
    }


@covers("onedrive share")
def test_onedrive_share_dry_run(invoke, graph):
    r = invoke(
        "onedrive",
        "share",
        "01SHARE0000000000000001",
        "--type",
        "edit",
        "--scope",
        "anonymous",
        "--expires",
        "2026-12-31T23:59:59",
        "--dry-run",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["requests"][0]["body"] == {
        "type": "edit",
        "scope": "anonymous",
        "expirationDateTime": "2026-12-31T23:59:59+01:00",
    }
    assert graph.calls.call_count == 0


@covers("onedrive share")
def test_onedrive_share_forbidden(invoke, graph):
    graph.post(f"{GRAPH}/v1.0/me/drive/items/01SHARE0000000000000001/createLink").mock(
        return_value=graph_error(403, "accessDenied", message="policy blocks anonymous links")
    )
    r = invoke("onedrive", "share", "01SHARE0000000000000001", "--scope", "anonymous")
    assert r.exit_code == 3
    assert r.stderr.startswith("error[accessDenied]: policy blocks anonymous links\n")
    assert "hint:" in r.stderr


# --------------------------------------------------------------------------- misc


def test_onedrive_group_help(invoke):
    r = invoke("onedrive")
    assert r.exit_code == 0 and "Usage:" in r.stdout
