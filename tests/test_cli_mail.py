"""CLI tests for the mail noun (spec §8.2)."""

import json

import httpx
import pytest

from helpers import GRAPH, covers, graph_error, mock_graph

LIST_SELECT = (
    "id,subject,from,toRecipients,ccRecipients,receivedDateTime,isRead,hasAttachments,"
    "importance,bodyPreview,conversationId,webLink,inferenceClassification"
)
READ_SELECT = LIST_SELECT + ",body,uniqueBody,replyTo"
INBOX = f"{GRAPH}/v1.0/me/mailFolders/inbox/messages"
FOLDERS = f"{GRAPH}/v1.0/me/mailFolders"
MSG = f"{GRAPH}/v1.0/me/messages/AAMk-msg-0001"


def message(**over) -> dict:
    """A list-shaped message; `over` replaces fields."""
    base = {
        "id": "AAMk-msg-0001",
        "subject": "Sprint review",
        "isRead": False,
        "hasAttachments": True,
        "importance": "high",
        "receivedDateTime": "2026-08-31T08:15:00Z",
        "from": {"emailAddress": {"name": "Ada Example", "address": "ada@example.com"}},
    }
    return {**base, **over}


# --------------------------------------------------------------------------- mail list


@covers("mail list")
def test_mail_list_json(invoke, graph):
    routes = mock_graph(graph, "mail/list")
    result = invoke("mail", "list", "--json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert set(doc) == {"items", "count", "truncated"}
    assert doc["count"] == 2 and doc["items"][0]["id"] == "AAMk-msg-0001"
    assert doc["truncated"] is False
    req = routes[0].calls.last.request
    assert req.headers["Prefer"] == 'outlook.timezone="Europe/Warsaw"'
    assert req.headers["Authorization"].startswith("Bearer ")
    assert result.stderr == ""


@covers("mail list")
def test_mail_list_text(invoke, graph):
    mock_graph(graph, "mail/list")
    result = invoke("mail", "list")
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["id", "received", "flags", "from", "subject"]
    assert "AAMk-msg-0001" in lines[1] and "2026-08-31T10:15+02:00" in lines[1]
    assert "*A!" in lines[1] and "Ada Example <ada@example.com>" in lines[1]
    assert "AAMk-msg-0002" in lines[2]


@covers("mail list")
def test_mail_list_search_mode_and_unread_client_side(invoke, graph):
    route = graph.get(INBOX).mock(
        return_value=httpx.Response(
            200,
            json={"value": [message(), message(id="AAMk-msg-0002", isRead=True)]},
        )
    )
    result = invoke(
        "mail",
        "list",
        "--search",
        "budget",
        "--from",
        "ada@example.com",
        "--after",
        "2026-08-01",
        "--unread",
        "--json",
    )
    assert result.exit_code == 0, result.stderr
    params = route.calls.last.request.url.params
    assert params["$search"] == '"budget AND from:ada@example.com AND received>=2026-08-01"'
    assert params["$top"] == "25" and params["$select"] == LIST_SELECT
    assert "$orderby" not in params and "$filter" not in params
    doc = json.loads(result.stdout)
    assert [m["id"] for m in doc["items"]] == ["AAMk-msg-0001"]


@covers("mail list")
def test_mail_list_filter_mode_dates_and_unread(invoke, graph):
    route = graph.get(INBOX).mock(return_value=httpx.Response(200, json={"value": []}))
    result = invoke("mail", "list", "--after", "2026-08-01", "--before", "2026-08-31", "--unread")
    assert result.exit_code == 0, result.stderr
    params = route.calls.last.request.url.params
    assert params["$filter"] == (
        "receivedDateTime ge 2026-08-01T00:00:00+02:00 "
        "and receivedDateTime le 2026-08-31T23:59:59+02:00 "
        "and isRead eq false"
    )
    assert params["$orderby"] == "receivedDateTime desc" and params["$top"] == "50"
    assert result.stdout == "No results.\n"


@covers("mail list")
def test_mail_list_folder_all_uses_me_messages(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/me/messages").mock(
        return_value=httpx.Response(200, json={"value": [message()]})
    )
    result = invoke("mail", "list", "--folder", "all", "--json")
    assert result.exit_code == 0, result.stderr
    assert route.called and json.loads(result.stdout)["count"] == 1


@covers("mail list")
def test_mail_list_folder_by_name_resolves_child(invoke, graph):
    routes = mock_graph(graph, "mail/folders_resolve")
    result = invoke("mail", "list", "--folder", "Projects", "--json")
    assert result.exit_code == 0, result.stderr
    assert [r.call_count for r in routes] == [1, 1, 1]
    assert json.loads(result.stdout)["items"][0]["id"] == "AAMk-msg-0009"


@covers("mail list")
def test_mail_list_folder_ambiguous_exit_2(invoke, graph):
    graph.get(FOLDERS).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {"id": "AAMk-folder-0001", "displayName": "Projects", "childFolderCount": 0},
                    {"id": "AAMk-folder-0002", "displayName": "projects", "childFolderCount": 0},
                ]
            },
        )
    )
    result = invoke("mail", "list", "--folder", "Projects")
    assert result.exit_code == 2 and result.stdout == ""
    assert result.stderr.startswith("error[AMBIGUOUS]: mail folder 'Projects' matches 2 items\n")
    assert "  candidate: AAMk-folder-0001  Projects\n" in result.stderr


@covers("mail list")
def test_mail_list_folder_missing_exit_4(invoke, graph):
    graph.get(FOLDERS).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [{"id": "AAMk-folder-0001", "displayName": "Inbox", "childFolderCount": 0}]
            },
        )
    )
    result = invoke("mail", "list", "--folder", "Nope")
    assert result.exit_code == 4 and result.stdout == ""
    assert result.stderr.startswith("error[NOT_FOUND]: mail folder 'Nope' not found\n")


@covers("mail list")
def test_mail_list_select_override(invoke, graph):
    route = graph.get(INBOX).mock(return_value=httpx.Response(200, json={"value": []}))
    assert invoke("mail", "list", "--select", "id,subject").exit_code == 0
    assert route.calls.last.request.url.params["$select"] == "id,subject"


@covers("mail list")
def test_mail_list_all_hits_cap_note(invoke, graph):
    pages = []

    def page(request: httpx.Request) -> httpx.Response:
        n = len(pages)
        pages.append(n)
        items = [message(id=f"AAMk-msg-{n * 50 + i:04d}") for i in range(50)]
        return httpx.Response(200, json={"value": items, "@odata.nextLink": str(request.url)})

    graph.get(INBOX).mock(side_effect=page)
    result = invoke("mail", "list", "--all", "--json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["count"] == 500 and doc["truncated"] is True
    assert len(pages) == 10
    result = invoke("mail", "list", "--all")
    assert result.stderr == "(hit the 500-item cap — narrow the query)\n"


@covers("mail list")
def test_mail_list_limit_zero_is_usage_error(invoke, graph):
    assert invoke("mail", "list", "--limit", "0").exit_code == 2
    assert graph.calls.call_count == 0


@covers("mail list")
def test_mail_list_all_and_limit_conflict(invoke, graph):
    result = invoke("mail", "list", "--all", "--limit", "5")
    assert result.exit_code == 2 and graph.calls.call_count == 0
    assert result.stderr.startswith("error[USAGE]: --all and --limit are mutually exclusive")


# --------------------------------------------------------------------------- mail read


def read_response(body: str, content_type: str = "text", **over) -> httpx.Response:
    obj = message(body={"contentType": content_type, "content": body}, **over)
    return httpx.Response(200, json=obj)


@covers("mail read")
def test_mail_read_text_body_prefers_text_and_truncates(invoke, graph):
    body = "".join(str(i % 10) for i in range(5000))
    route = graph.get(MSG).mock(return_value=read_response(body))
    result = invoke("mail", "read", "AAMk-msg-0001")
    assert result.exit_code == 0, result.stderr
    request = route.calls.last.request
    assert request.url.params["$select"] == READ_SELECT
    assert 'outlook.body-content-type="text"' in request.headers["Prefer"]
    assert 'outlook.timezone="Europe/Warsaw"' in request.headers["Prefer"]
    assert result.stdout.startswith("Subject  : Sprint review\n")
    assert "From     : Ada Example <ada@example.com>\n" in result.stdout
    assert "Received : 2026-08-31T10:15+02:00\n" in result.stdout
    assert result.stdout.rstrip("\n").endswith(body[:4000])
    assert body[:4001] not in result.stdout
    assert result.stderr == "(body truncated to 4000 chars; use --full)\n"

    result = invoke("mail", "read", "AAMk-msg-0001", "--full")
    assert result.exit_code == 0 and result.stdout.rstrip("\n").endswith(body)
    assert result.stderr == ""


@covers("mail read")
def test_mail_read_html_flag_and_markdown_fallback(invoke, graph):
    html = "<html><body><h1>Plan</h1><p>Ship <b>it</b>.</p></body></html>"
    route = graph.get(MSG).mock(return_value=read_response(html, "html"))
    result = invoke("mail", "read", "AAMk-msg-0001", "--html")
    assert result.exit_code == 0, result.stderr
    assert "Prefer" in route.calls.last.request.headers
    assert 'outlook.body-content-type="text"' not in route.calls.last.request.headers["Prefer"]
    assert html in result.stdout

    result = invoke("mail", "read", "AAMk-msg-0001")
    assert result.exit_code == 0
    assert "# Plan" in result.stdout and "Ship **it**." in result.stdout
    assert "<h1>" not in result.stdout


@covers("mail read")
def test_mail_read_headers(invoke, graph):
    headers = [
        {"name": "Received", "value": "from mail.example.com"},
        {"name": "Message-ID", "value": "<msg-0001@example.com>"},
    ]
    route = graph.get(MSG).mock(return_value=read_response("Body.", internetMessageHeaders=headers))
    result = invoke("mail", "read", "AAMk-msg-0001", "--headers")
    assert result.exit_code == 0, result.stderr
    select = route.calls.last.request.url.params["$select"]
    assert select == READ_SELECT + ",internetMessageHeaders"
    assert "Headers\n" in result.stdout
    assert "  Message-ID: <msg-0001@example.com>" in result.stdout


@covers("mail read")
def test_mail_read_output_writes_full_body(invoke, graph, tmp_path):
    body = "line\n" * 1000
    graph.get(MSG).mock(return_value=read_response(body))
    dest = tmp_path / "body.txt"
    result = invoke("mail", "read", "AAMk-msg-0001", "--output", str(dest))
    assert result.exit_code == 0, result.stderr
    assert dest.read_text() == body
    assert result.stdout == f"Wrote {len(body)} chars to {dest}\n"
    assert result.stderr == ""


@covers("mail read")
def test_mail_read_save_attachments(invoke, graph, tmp_path):
    mock_graph(graph, "mail/read_attachments")
    out = tmp_path / "att"
    result = invoke("mail", "read", "AAMk-msg-0001", "--save-attachments", str(out))
    assert result.exit_code == 0, result.stderr
    assert (out / "plan.docx").read_bytes() == b"hello world!"
    assert result.stderr == ("skipped Forwarded note: itemAttachment cannot be downloaded\n")
    assert "Deck attached." in result.stdout


@covers("mail read")
def test_mail_read_json_is_raw_object(invoke, graph):
    graph.get(MSG).mock(return_value=read_response("Body."))
    result = invoke("mail", "read", "AAMk-msg-0001", "--json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["id"] == "AAMk-msg-0001"
    assert doc["body"] == {"contentType": "text", "content": "Body."}


@covers("mail read")
@pytest.mark.parametrize(
    "status,code,exit_code",
    [(404, "ErrorItemNotFound", 4), (403, "ErrorAccessDenied", 3), (400, "BadRequest", 1)],
)
def test_mail_read_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.get(MSG).mock(return_value=graph_error(status, code))
    result = invoke("mail", "read", "AAMk-msg-0001")
    assert result.exit_code == exit_code and result.stdout == ""
    assert result.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("mail read")
def test_mail_read_401_after_refresh(invoke, graph):
    route = graph.get(MSG).mock(return_value=graph_error(401, "InvalidAuthenticationToken"))
    result = invoke("mail", "read", "AAMk-msg-0001")
    assert result.exit_code == 3 and route.call_count == 2
    assert result.stderr.startswith("error[UNAUTHORIZED]:") and "login --force" in result.stderr


@covers("mail read")
@pytest.mark.scopes(["User.Read"])
def test_mail_read_missing_scope(invoke, graph):
    result = invoke("mail", "read", "AAMk-msg-0001")
    assert result.exit_code == 3 and graph.calls.call_count == 0
    assert result.stderr.startswith("error[MISSING_SCOPE]: this command needs Mail.Read;")


# --------------------------------------------------------------------------- mail attachments


@covers("mail attachments")
def test_mail_attachments_list_and_download(invoke, graph, tmp_path):
    routes = mock_graph(graph, "mail/read_attachments")
    result = invoke("mail", "attachments", "AAMk-msg-0001")
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["id", "type", "name", "size", "inline"]
    assert lines[1].split() == ["AAMk-att-0001", "file", "plan.docx", "12", "B", "no"]
    assert routes[1].calls.last.request.url.params["$select"] == "id,name,contentType,size,isInline"

    dest = tmp_path / "f"
    result = invoke(
        "mail", "attachments", "AAMk-msg-0001", "--download", "AAMk-att-0001", "--output", str(dest)
    )
    assert result.exit_code == 0, result.stderr
    assert dest.read_bytes() == b"hello world!"
    assert result.stdout == f"Downloaded plan.docx (12 B) to {dest}\n"


@covers("mail attachments")
def test_mail_attachments_download_item_attachment_exit_1(invoke, graph, tmp_path):
    mock_graph(graph, "mail/read_attachments")
    result = invoke(
        "mail",
        "attachments",
        "AAMk-msg-0001",
        "--download",
        "AAMk-att-0002",
        "--output",
        str(tmp_path / "f"),
    )
    assert result.exit_code == 1 and result.stdout == ""
    assert result.stderr.startswith(
        "error[ATTACHMENT_NOT_A_FILE]: itemAttachment 'Forwarded note' cannot be downloaded"
    )


@covers("mail attachments")
def test_mail_attachments_all_output_dir(invoke, graph, tmp_path):
    mock_graph(graph, "mail/read_attachments")
    out = tmp_path / "all"
    result = invoke(
        "mail",
        "attachments",
        "AAMk-msg-0001",
        "--all-attachments",
        "--output-dir",
        str(out),
        "--json",
    )
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["count"] == 1
    assert doc["items"][0] == {
        "id": "AAMk-att-0001",
        "name": "plan.docx",
        "bytes": 12,
        "path": str(out / "plan.docx"),
    }
    assert (out / "plan.docx").read_bytes() == b"hello world!"
    assert result.stderr == "skipped Forwarded note: itemAttachment cannot be downloaded\n"


# --------------------------------------------------------------------------- mail folders


@covers("mail folders")
def test_mail_folders_tree_depth_and_hidden(invoke, graph):
    routes = mock_graph(graph, "mail/folders")
    result = invoke("mail", "folders", "--json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["count"] == 3
    assert [f["displayName"] for f in doc["items"]] == ["Inbox", "Archive", "Sent Items"]
    assert [c["displayName"] for c in doc["items"][0]["children"]] == ["Projects"]
    # depth 2 stops there: Projects has children but they are not fetched.
    assert doc["items"][0]["children"][0]["children"] == []
    assert [r.call_count for r in routes] == [1, 1, 1]

    result = invoke("mail", "folders")
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["name", "unread", "total", "id"]
    assert lines[1].startswith("Inbox") and lines[2].startswith("  Projects")
    assert "AAMk-folder-0003" in lines[2]

    result = invoke("mail", "folders", "--depth", "1", "--json")
    assert result.exit_code == 0, result.stderr
    # The text run above spent one call on each route; --depth 1 fetches no childFolders at all.
    assert [r.call_count for r in routes] == [3, 2, 2]
    assert json.loads(result.stdout)["items"][0]["children"] == []

    hidden = graph.get(FOLDERS, params__contains={"includeHiddenFolders": "true"}).mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    assert invoke("mail", "folders", "--hidden", "--depth", "1").exit_code == 0
    assert hidden.called


# --------------------------------------------------------------------------- mail drafts list


@covers("mail drafts list")
def test_mail_drafts_list(invoke, graph):
    routes = mock_graph(graph, "mail/drafts_list")
    result = invoke("mail", "drafts", "list")
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["id", "to", "subject"]
    assert lines[1].startswith("AAMk-draft-0001")
    assert "Ada Example <ada@example.com>" in lines[1]
    assert routes[0].calls.last.request.headers["Prefer"] == 'outlook.timezone="Europe/Warsaw"'


@covers("mail drafts list")
def test_mail_drafts_list_json_limit(invoke, graph):
    mock_graph(graph, "mail/drafts_list")
    result = invoke("mail", "drafts", "list", "--limit", "1", "--json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["count"] == 1 and doc["truncated"] is True
    assert result.stderr == ""  # notes are a text-mode diagnostic
    result = invoke("mail", "drafts", "list", "--limit", "1")
    assert result.stderr == "(more results available — rerun with --all)\n"


# --------------------------------------------------------------------------- help


def test_mail_group_help(invoke):
    result = invoke("mail")
    assert result.exit_code == 0 and "Usage:" in result.stdout
    assert "list" in result.stdout and "read" in result.stdout
    result = invoke("mail", "drafts")
    assert result.exit_code == 0 and "Usage:" in result.stdout
