"""Shared drive-item operations for OneDrive and SharePoint (spec §8.11, §8.12)."""

from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from mgraphctl import odata
from mgraphctl.graph import files
from mgraphctl.http import GraphClient, PlannedRequest
from mgraphctl.render import fmt_dt, fmt_size

V1 = "https://graph.microsoft.com/v1.0"


@pytest.fixture
def client():
    c = GraphClient(lambda force: "tok", tz="Europe/Warsaw")
    yield c
    c.close()


def test_children_path_forms():
    assert files.children_path("/me/drive", None) == "/me/drive/root/children"
    assert (
        files.children_path("/drives/b!x", "Docs/Q3 plan")
        == "/drives/b!x/root:/Docs/Q3%20plan:/children"
    )


def test_item_ref_forms():
    base = "/me/drive"
    assert (
        files.item_ref(base, "01ABCDEFGHIJKLMNOPQRSTUV") == base + "/items/01ABCDEFGHIJKLMNOPQRSTUV"
    )
    assert files.item_ref(base, "id:abc") == base + "/items/abc"
    assert files.item_ref(base, "/Docs/a.txt") == base + "/root:/Docs/a.txt"
    assert files.item_ref(base, "Docs/a.txt") == base + "/root:/Docs/a.txt"


@respx.mock
def test_list_children_query(client):
    route = respx.get(f"{V1}/me/drive/root/children").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "1", "name": "a"}]})
    )
    page = files.list_children(client, "/me/drive", None, limit=50, all_=False)
    assert [i["id"] for i in page.items] == ["1"]
    params = httpx.QueryParams(route.calls[0].request.url.query)
    assert dict(params) == {"$select": files.ITEM_SELECT, "$orderby": "name", "$top": "200"}

    nested = respx.get(f"{V1}/drives/b!x/root:/Docs:/children").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    files.list_children(client, "/drives/b!x", "Docs", limit=50, all_=False)
    assert nested.called


@respx.mock
def test_search_items_own_and_shared(client):
    own = respx.get(f"{V1}/me/drive/root/search(q='O''Brien')").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "1"}]})
    )
    page = files.search_items(client, "/me/drive", "O'Brien", limit=50)
    assert own.called and [i["id"] for i in page.items] == ["1"]

    shared = respx.get(f"{V1}/me/drive/search(q='x')").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "2"}]})
    )
    page2 = files.search_items(client, "/me/drive", "x", limit=50, shared=True)
    assert shared.called and [i["id"] for i in page2.items] == ["2"]


@respx.mock
def test_get_item_by_path_and_id(client):
    id_route = respx.get(f"{V1}/me/drive/items/01ABCDEFGHIJKLMNOPQRSTUV").mock(
        return_value=httpx.Response(200, json={"id": "01ABCDEFGHIJKLMNOPQRSTUV", "name": "a.txt"})
    )
    item = files.get_item(client, "/me/drive", "01ABCDEFGHIJKLMNOPQRSTUV")
    assert item["name"] == "a.txt"
    assert httpx.QueryParams(id_route.calls[0].request.url.query)["$select"] == files.ITEM_SELECT

    path_route = respx.get(f"{V1}/me/drive/root:/Docs/a.txt").mock(
        return_value=httpx.Response(200, json={"id": "x1", "name": "a.txt"})
    )
    item2 = files.get_item(client, "/me/drive", "Docs/a.txt")
    assert item2["id"] == "x1"
    assert httpx.QueryParams(path_route.calls[0].request.url.query)["$select"] == files.ITEM_SELECT


def test_resolve_item_id_forced_and_id_like(client):
    assert files.resolve_item_id(client, "/me/drive", "id:xyz") == "xyz"
    assert (
        files.resolve_item_id(client, "/me/drive", "01ABCDEFGHIJKLMNOPQRSTUV")
        == "01ABCDEFGHIJKLMNOPQRSTUV"
    )


@respx.mock
def test_resolve_item_id_by_path_fetches_item(client):
    respx.get(f"{V1}/me/drive/root:/Docs/a.txt").mock(
        return_value=httpx.Response(200, json={"id": "resolved-1", "name": "a.txt"})
    )
    assert files.resolve_item_id(client, "/me/drive", "Docs/a.txt") == "resolved-1"


@respx.mock
def test_download_item_uses_content_and_item_name(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    respx.get(f"{V1}/me/drive/items/x").mock(
        return_value=httpx.Response(200, json={"id": "x", "name": "report.pdf"})
    )
    respx.get(f"{V1}/me/drive/items/x/content").mock(
        return_value=httpx.Response(302, headers={"Location": "https://files.example.com/blob"})
    )
    respx.get("https://files.example.com/blob").mock(
        return_value=httpx.Response(
            200, content=b"data", headers={"Content-Type": "application/pdf"}
        )
    )
    item, result = files.download_item(client, "/me/drive", "id:x", None)
    assert item["name"] == "report.pdf"
    assert result.path == Path("report.pdf")
    assert result.path.read_bytes() == b"data"


@respx.mock
def test_download_item_path_form_colon_fences_content(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    respx.get(f"{V1}/me/drive/root:/Docs/report.pdf").mock(
        return_value=httpx.Response(200, json={"id": "y", "name": "report.pdf"})
    )
    content_route = respx.get(f"{V1}/me/drive/root:/Docs/report.pdf:/content").mock(
        return_value=httpx.Response(
            200, content=b"data", headers={"Content-Type": "application/pdf"}
        )
    )
    item, result = files.download_item(client, "/me/drive", "Docs/report.pdf", None)
    assert item["name"] == "report.pdf"
    assert content_route.called
    assert result.path == Path("report.pdf")


def test_plan_upload_small_put(client, tmp_path):
    file = tmp_path / "f.bin"
    file.write_bytes(b"x" * (3 * 1024 * 1024))
    plan = files.plan_upload(client, "/me/drive", file, "Docs/f.bin", "replace")
    assert len(plan) == 1
    step = plan[0]
    assert step.method == "PUT"
    assert (
        step.url
        == f"{V1}/me/drive/root:/Docs/f.bin:/content?@microsoft.graph.conflictBehavior=replace"
    )
    assert step.headers["Content-Type"] == "application/octet-stream"
    assert step.file == file
    assert step.chunk_size is None


def test_plan_upload_large_session(client, tmp_path):
    file = tmp_path / "f.bin"
    file.write_bytes(b"x" * (5 * 1024 * 1024))
    plan = files.plan_upload(client, "/me/drive", file, "Docs/f.bin", "rename")
    assert len(plan) == 1
    step = plan[0]
    assert step.method == "POST"
    assert step.url == f"{V1}/me/drive/root:/Docs/f.bin:/createUploadSession"
    assert step.body == {"item": {"@microsoft.graph.conflictBehavior": "rename", "name": "f.bin"}}
    assert step.chunk_size == 10_485_760
    assert step.file == file


def test_plan_upload_rejects_bad_conflict(client, tmp_path):
    file = tmp_path / "f.bin"
    file.write_bytes(b"x")
    from mgraphctl.errors import UsageError

    with pytest.raises(UsageError):
        files.plan_upload(client, "/me/drive", file, "f.bin", "clobber")


def test_dest_rules(tmp_path):
    file = tmp_path / "report.pdf"
    file.write_bytes(b"x")
    assert files._dest(file, None) == "/report.pdf"
    assert files._dest(file, "Docs/") == "Docs/report.pdf"
    assert files._dest(file, "Docs/new.bin") == "Docs/new.bin"


@respx.mock
def test_run_upload_small_and_large(client, tmp_path):
    small = tmp_path / "s.bin"
    small.write_bytes(b"x" * 100)
    put_route = respx.put(
        f"{V1}/me/drive/root:/s.bin:/content",
        params__eq={"@microsoft.graph.conflictBehavior": "replace"},
    ).mock(return_value=httpx.Response(201, json={"id": "item-small"}))
    result = files.run_upload(client, "/me/drive", small, None, "replace")
    assert result == {"id": "item-small"}
    assert put_route.calls[0].request.content == small.read_bytes()

    big = tmp_path / "b.bin"
    big.write_bytes(b"y" * (5 * 1024 * 1024))
    create = respx.post(f"{V1}/me/drive/root:/b.bin:/createUploadSession").mock(
        return_value=httpx.Response(200, json={"uploadUrl": "https://upload.example.com/s1"})
    )
    chunks = respx.put("https://upload.example.com/s1").mock(
        return_value=httpx.Response(201, json={"id": "item-big"})
    )
    result2 = files.run_upload(client, "/me/drive", big, None, "rename")
    assert result2 == {"id": "item-big"}
    assert create.called and chunks.called


def test_mkdir_plan(client):
    plan = files.plan_mkdir(client, "/me/drive", "Docs/New")
    assert plan == [
        PlannedRequest(
            "POST",
            f"{V1}/me/drive/root:/Docs:/children",
            {"Content-Type": "application/json"},
            {"name": "New", "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
        )
    ]
    root_plan = files.plan_mkdir(client, "/me/drive", "New")
    assert root_plan == [
        PlannedRequest(
            "POST",
            f"{V1}/me/drive/root/children",
            {"Content-Type": "application/json"},
            {"name": "New", "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
        )
    ]


@respx.mock
def test_run_mkdir(client):
    route = respx.post(f"{V1}/me/drive/root/children").mock(
        return_value=httpx.Response(201, json={"id": "new-1", "name": "New"})
    )
    result = files.run_mkdir(client, "/me/drive", "New")
    assert result == {"id": "new-1", "name": "New"}
    assert route.called


@respx.mock
def test_move_resolves_folder(client):
    folder_route = respx.get(f"{V1}/me/drive/root:/Archive").mock(
        return_value=httpx.Response(200, json={"id": "fid", "name": "Archive"})
    )
    plan = files.plan_move(client, "/me/drive", "id:x", "Archive", "n")
    assert folder_route.called
    assert plan == [
        PlannedRequest(
            "PATCH",
            f"{V1}/me/drive/items/x",
            {"Content-Type": "application/json"},
            {"parentReference": {"id": "fid"}, "name": "n"},
        )
    ]

    plan2 = files.plan_move(client, "/me/drive", "id:x", "id:fid", None)
    assert folder_route.call_count == 1
    assert plan2 == [
        PlannedRequest(
            "PATCH",
            f"{V1}/me/drive/items/x",
            {"Content-Type": "application/json"},
            {"parentReference": {"id": "fid"}},
        )
    ]


def test_rename_delete_share_plans(client):
    rename_plan = files.plan_rename(client, "/me/drive", "id:x", "new-name.txt")
    assert rename_plan == [
        PlannedRequest(
            "PATCH",
            f"{V1}/me/drive/items/x",
            {"Content-Type": "application/json"},
            {"name": "new-name.txt"},
        )
    ]

    delete_plan = files.plan_delete(client, "/me/drive", "id:x")
    assert delete_plan == [
        PlannedRequest("DELETE", f"{V1}/me/drive/items/x", {}, None, expect="none")
    ]

    share_plan = files.plan_share(
        client, "/me/drive", "id:x", link_type="view", scope="organization", expires=None
    )
    assert share_plan == [
        PlannedRequest(
            "POST",
            f"{V1}/me/drive/items/x/createLink",
            {"Content-Type": "application/json"},
            {"type": "view", "scope": "organization"},
        )
    ]

    expires = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    share_plan2 = files.plan_share(
        client, "/me/drive", "id:x", link_type="edit", scope="anonymous", expires=expires
    )
    assert share_plan2[0].body == {
        "type": "edit",
        "scope": "anonymous",
        "expirationDateTime": "2026-12-31T23:59:59+00:00",
    }

    path_share_plan = files.plan_share(
        client, "/me/drive", "Docs/report.pdf", link_type="view", scope="organization", expires=None
    )
    assert path_share_plan[0].url == f"{V1}/me/drive/root:/Docs/report.pdf:/createLink"


@respx.mock
def test_run_rename_delete_share(client):
    rename_route = respx.patch(f"{V1}/me/drive/items/x").mock(
        return_value=httpx.Response(200, json={"id": "x", "name": "new-name.txt"})
    )
    assert files.run_rename(client, "/me/drive", "id:x", "new-name.txt") == {
        "id": "x",
        "name": "new-name.txt",
    }
    assert rename_route.called

    delete_route = respx.delete(f"{V1}/me/drive/items/x").mock(return_value=httpx.Response(204))
    assert files.run_delete(client, "/me/drive", "id:x") is None
    assert delete_route.called

    share_route = respx.post(f"{V1}/me/drive/items/x/createLink").mock(
        return_value=httpx.Response(201, json={"link": {"webUrl": "https://x/link"}})
    )
    result = files.run_share(
        client, "/me/drive", "id:x", link_type="view", scope="organization", expires=None
    )
    assert result == {"link": {"webUrl": "https://x/link"}}
    assert share_route.called

    path_share_route = respx.post(f"{V1}/me/drive/root:/Docs/report.pdf:/createLink").mock(
        return_value=httpx.Response(201, json={"link": {"webUrl": "https://x/link2"}})
    )
    path_result = files.run_share(
        client, "/me/drive", "Docs/report.pdf", link_type="view", scope="organization", expires=None
    )
    assert path_result == {"link": {"webUrl": "https://x/link2"}}
    assert path_share_route.called


@respx.mock
def test_shared_item_by_link(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    url = "https://contoso.example/sites/team/Shared%20Documents/report.pdf"
    share_id = odata.share_id(url)
    respx.get(f"{V1}/shares/{share_id}/driveItem").mock(
        return_value=httpx.Response(200, json={"id": "sh1", "name": "report.pdf"})
    )
    item = files.get_shared_item(client, url)
    assert item["id"] == "sh1"

    respx.get(f"{V1}/shares/{share_id}/driveItem/content").mock(
        return_value=httpx.Response(
            200, content=b"data", headers={"Content-Type": "application/pdf"}
        )
    )
    item2, result = files.download_shared_item(client, url, None)
    assert item2["id"] == "sh1"
    assert result.path == Path("report.pdf")
    assert result.path.read_bytes() == b"data"


def test_item_columns_render():
    cols = files.item_columns("Europe/Warsaw")
    assert [c.header for c in cols] == ["type", "id", "size", "modified", "name"]
    folder_item = {"id": "f1", "name": "Docs", "folder": {"childCount": 2}}
    file_item = {
        "id": "i1",
        "name": "a.txt",
        "size": 2048,
        "lastModifiedDateTime": "2026-08-31T08:15:00Z",
    }

    def render(item):
        return {c.header: (c.path(item) if callable(c.path) else item.get(c.path)) for c in cols}

    folder_values = render(folder_item)
    assert folder_values["type"] == "d" and folder_values["name"] == "Docs"

    file_values = render(file_item)
    assert file_values["type"] == "f"
    assert file_values["size"] == fmt_size(2048)
    assert file_values["modified"] == fmt_dt("2026-08-31T08:15:00Z", "Europe/Warsaw")
