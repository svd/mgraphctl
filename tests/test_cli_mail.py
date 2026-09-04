"""CLI tests for the mail noun (spec §8.2)."""

import json
from pathlib import Path

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
def test_mail_list_search_mode_refilters_a_bound_with_a_time(invoke, graph):
    """KQL compares dates only, so a bound with a time of day is re-applied client-side."""
    route = graph.get(INBOX).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    message(id="AAMk-early", receivedDateTime="2026-08-31T08:15:00Z"),
                    message(id="AAMk-late", receivedDateTime="2026-08-31T11:00:00Z"),
                ]
            },
        )
    )
    result = invoke("mail", "list", "--search", "budget", "--after", "2026-08-31T12:00", "--json")
    assert result.exit_code == 0, result.stderr
    params = route.calls.last.request.url.params
    assert params["$search"] == '"budget AND received>=2026-08-31"'
    doc = json.loads(result.stdout)
    assert [m["id"] for m in doc["items"]] == ["AAMk-late"]


@covers("mail list")
def test_mail_list_search_mode_refilters_an_upper_bound_with_a_time(invoke, graph):
    graph.get(INBOX).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    message(id="AAMk-early", receivedDateTime="2026-08-31T08:15:00Z"),
                    message(id="AAMk-late", receivedDateTime="2026-08-31T11:00:00Z"),
                ]
            },
        )
    )
    result = invoke("mail", "list", "--search", "budget", "--before", "2026-08-31T12:00", "--json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert [m["id"] for m in doc["items"]] == ["AAMk-early"]


@covers("mail list")
def test_mail_list_search_mode_leaves_a_date_only_bound_unfiltered(invoke, graph):
    """A date-only bound already means what the KQL date means: no client-side pass at all."""
    graph.get(INBOX).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    message(id="AAMk-early", receivedDateTime="2026-08-31T08:15:00Z"),
                    message(id="AAMk-late", receivedDateTime="2026-08-31T11:00:00Z"),
                ]
            },
        )
    )
    result = invoke(
        "mail",
        "list",
        "--search",
        "budget",
        "--after",
        "2026-08-31",
        "--before",
        "2026-08-31",
        "--json",
    )
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert [m["id"] for m in doc["items"]] == ["AAMk-early", "AAMk-late"]


@covers("mail list")
def test_mail_list_search_post_filter_keeps_the_fetch_truncated(invoke, graph):
    """Filtering happens after paging: a short page can still be a truncated one."""
    graph.get(INBOX).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    message(id="AAMk-early", receivedDateTime="2026-08-31T08:15:00Z"),
                    message(id="AAMk-late", receivedDateTime="2026-08-31T11:00:00Z"),
                ],
                "@odata.nextLink": f"{INBOX}?$skip=2",
            },
        )
    )
    result = invoke(
        "mail",
        "list",
        "--search",
        "budget",
        "--after",
        "2026-08-31T12:00",
        "--limit",
        "2",
        "--json",
    )
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["count"] == 1 and doc["truncated"] is True


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


@covers("mail folders")
def test_mail_folders_reports_the_cap(invoke, graph):
    items = [
        {
            "id": f"AAMk-folder-{n:04d}",
            "displayName": f"Folder {n}",
            "childFolderCount": 0,
            "unreadItemCount": 0,
            "totalItemCount": 0,
        }
        for n in range(500)
    ]
    graph.get(FOLDERS).mock(
        return_value=httpx.Response(
            200, json={"value": items, "@odata.nextLink": f"{FOLDERS}?$skiptoken=page-2"}
        )
    )
    r = invoke("mail", "folders", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 500 and doc["truncated"] is True
    assert r.stderr == ""  # notes are a text-mode diagnostic
    r = invoke("mail", "folders")
    assert r.exit_code == 0 and r.stderr == "(hit the 500-item cap — narrow the query)\n"


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


# --------------------------------------------------------------------------- mail send


@covers("mail send")
def test_mail_send_absent_attachment_is_a_usage_error(invoke, graph, tmp_path):
    r = invoke(
        "mail",
        "send",
        "--to",
        "ada@example.com",
        "--subject",
        "Hi",
        "--body",
        "x",
        "--attach",
        str(tmp_path / "gone.txt"),
    )
    assert r.exit_code == 2 and graph.calls.call_count == 0


@covers("mail send")
def test_mail_send_inline_path(invoke, graph, tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    route = graph.post(f"{GRAPH}/v1.0/me/sendMail").mock(return_value=httpx.Response(202))
    r = invoke(
        "mail",
        "send",
        "--to",
        "ada@example.com,bob@example.com",
        "--cc",
        "eve@example.com",
        "--subject",
        "Hi",
        "--body",
        "Body",
        "--attach",
        str(f),
        "--importance",
        "high",
        "--json",
    )
    assert r.exit_code == 0 and json.loads(r.stdout) == {"status": "sent"}
    body = json.loads(route.calls.last.request.content)
    msg = body["message"]
    assert body["saveToSentItems"] is True and msg["subject"] == "Hi"
    assert msg["importance"] == "high"
    assert msg["body"] == {"contentType": "Text", "content": "Body"}
    assert [r["emailAddress"]["address"] for r in msg["toRecipients"]] == [
        "ada@example.com",
        "bob@example.com",
    ]
    assert [r["emailAddress"]["address"] for r in msg["ccRecipients"]] == ["eve@example.com"]
    assert msg["attachments"] == [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "a.txt",
            "contentType": "text/plain",
            "contentBytes": "aGVsbG8=",
        }
    ]


@covers("mail send")
def test_mail_send_inline_dry_run_hides_file_bytes(invoke, graph, tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    r = invoke(
        "mail",
        "send",
        "--to",
        "ada@example.com",
        "--subject",
        "Hi",
        "--body",
        "Body",
        "--attach",
        str(f),
        "--dry-run",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["dryRun"] is True and len(doc["requests"]) == 1
    step = doc["requests"][0]
    assert step["url"] == f"{GRAPH}/v1.0/me/sendMail" and "inline path" in step["note"]
    assert step["body"]["message"]["attachments"][0]["contentBytes"] == {
        "$file": str(f),
        "bytes": 5,
        "contentType": "text/plain",
    }
    assert graph.calls.call_count == 0


@covers("mail send")
def test_mail_send_draft_path_dry_run_names_steps(invoke, graph, tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"\0" * 3_000_000)
    r = invoke(
        "mail",
        "send",
        "--to",
        "ada@example.com",
        "--subject",
        "Big",
        "--body",
        "x",
        "--attach",
        str(big),
        "--dry-run",
        "--json",
    )
    doc = json.loads(r.stdout)
    assert [s["method"] for s in doc["requests"]] == ["POST", "POST", "POST"]
    assert doc["requests"][0]["url"] == f"{GRAPH}/v1.0/me/messages"
    assert "draft path" in doc["requests"][0]["note"]
    assert doc["requests"][1]["url"] == f"{GRAPH}/v1.0/me/messages/{{draftId}}/attachments"
    assert doc["requests"][1]["body"]["contentBytes"] == {
        "$file": str(big),
        "bytes": 3_000_000,
        "contentType": "application/octet-stream",
    }
    assert doc["requests"][2]["url"] == f"{GRAPH}/v1.0/me/messages/{{draftId}}/send"
    assert graph.calls.call_count == 0


@covers("mail send")
def test_mail_send_draft_path_large_attachment_upload_session(invoke, graph, tmp_path):
    huge = tmp_path / "huge.bin"
    huge.write_bytes(b"\1" * 4_000_000)
    graph.post(f"{GRAPH}/v1.0/me/messages").mock(
        return_value=httpx.Response(201, json={"id": "AAMk-draft-1"})
    )
    graph.post(f"{GRAPH}/v1.0/me/messages/AAMk-draft-1/attachments/createUploadSession").mock(
        return_value=httpx.Response(
            201,
            json={
                "uploadUrl": "https://upload.example.com/session?tok=1",
                "nextExpectedRanges": ["0-"],
            },
        )
    )
    put = graph.put("https://upload.example.com/session").mock(
        side_effect=[
            httpx.Response(200, json={"nextExpectedRanges": ["3932160-"]}),
            httpx.Response(
                201,
                headers={
                    "Location": "https://graph.microsoft.com/v1.0/me/messages/AAMk-draft-1"
                    "/attachments/x"
                },
            ),
        ]
    )
    send = graph.post(f"{GRAPH}/v1.0/me/messages/AAMk-draft-1/send").mock(
        return_value=httpx.Response(202)
    )
    r = invoke(
        "mail",
        "send",
        "--to",
        "ada@example.com",
        "--subject",
        "Huge",
        "--body",
        "x",
        "--attach",
        str(huge),
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout) == {"status": "sent", "draftId": "AAMk-draft-1"}
    assert [c.request.headers["Content-Range"] for c in put.calls] == [
        "bytes 0-3932159/4000000",
        "bytes 3932160-3999999/4000000",
    ]
    assert "Authorization" not in put.calls[0].request.headers and send.called


@covers("mail send")
@pytest.mark.scopes(["Mail.Send", "Mail.Read"])
def test_mail_send_draft_path_needs_mail_readwrite(invoke, graph, tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"\0" * 3_000_000)
    r = invoke(
        "mail",
        "send",
        "--to",
        "ada@example.com",
        "--subject",
        "Big",
        "--body",
        "x",
        "--attach",
        str(big),
    )
    assert r.exit_code == 3 and "needs Mail.ReadWrite" in r.stderr
    assert graph.calls.call_count == 0


@covers("mail send")
def test_mail_send_requires_to_and_body(invoke, graph, tmp_path):
    r = invoke("mail", "send", "--subject", "Hi", "--body", "Body")
    assert r.exit_code == 2 and r.stderr.startswith("error[USAGE]: --to is required")
    r = invoke("mail", "send", "--to", "ada@example.com", "--subject", "Hi")
    assert r.exit_code == 2 and "exactly one of --body or --body-file" in r.stderr
    f = tmp_path / "b.txt"
    f.write_text("From a file")
    r = invoke(
        "mail",
        "send",
        "--to",
        "ada@example.com",
        "--body",
        "x",
        "--body-file",
        str(f),
        "--dry-run",
    )
    assert r.exit_code == 2 and "exactly one of --body or --body-file" in r.stderr
    route = graph.post(f"{GRAPH}/v1.0/me/sendMail").mock(return_value=httpx.Response(202))
    r = invoke("mail", "send", "--to", "ada@example.com", "--body-file", "-", input="From stdin")
    assert r.exit_code == 0, r.stderr
    body = json.loads(route.calls.last.request.content)
    assert body["message"]["body"]["content"] == "From stdin"
    assert graph.calls.call_count == 1


@covers("mail send")
def test_mail_send_html_and_no_save(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/sendMail").mock(return_value=httpx.Response(202))
    r = invoke(
        "mail",
        "send",
        "--to",
        "ada@example.com",
        "--subject",
        "Hi",
        "--body",
        "<p>Hi</p>",
        "--html",
        "--no-save-to-sent",
    )
    assert r.exit_code == 0 and r.stdout == "Sent.\n"
    body = json.loads(route.calls.last.request.content)
    assert body["message"]["body"] == {"contentType": "HTML", "content": "<p>Hi</p>"}
    assert body["saveToSentItems"] is False


@covers("mail send")
def test_mail_send_default_subject_no_subject(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/sendMail").mock(return_value=httpx.Response(202))
    assert invoke("mail", "send", "--to", "ada@example.com", "--body", "x").exit_code == 0
    body = json.loads(route.calls.last.request.content)
    assert body["message"]["subject"] == "(no subject)"
    assert body["message"]["importance"] == "normal"


@covers("mail send")
def test_mail_send_attachment_over_150mb_exit_2(invoke, graph, tmp_path, monkeypatch):
    big = tmp_path / "huge.iso"
    big.write_bytes(b"x")
    real_stat = Path.stat

    class Stat:
        st_size = 157_286_401

    monkeypatch.setattr(
        Path, "stat", lambda self, **kw: Stat() if self == big else real_stat(self, **kw)
    )
    r = invoke("mail", "send", "--to", "ada@example.com", "--body", "x", "--attach", str(big))
    assert r.exit_code == 2 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[USAGE]: huge.iso is 157286401 bytes")


@covers("mail send")
def test_mail_send_no_save_to_sent_rejected_on_the_draft_path(invoke, graph, tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"\0" * 3_000_000)
    for extra in (["--dry-run"], []):
        r = invoke(
            "mail",
            "send",
            "--to",
            "ada@example.com",
            "--body",
            "x",
            "--attach",
            str(big),
            "--no-save-to-sent",
            *extra,
        )
        assert r.exit_code == 2 and r.stdout == ""
        assert r.stderr.startswith(
            "error[USAGE]: --no-save-to-sent is not supported with attachments over the inline "
            "limit (Graph keeps a Sent Items copy on the draft path)"
        )
    assert graph.calls.call_count == 0


@covers("mail send")
def test_mail_send_bad_importance_exit_2(invoke, graph):
    r = invoke("mail", "send", "--to", "ada@example.com", "--body", "x", "--importance", "urgent")
    assert r.exit_code == 2 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[USAGE]: --importance must be one of")


# --------------------------------------------------------------------------- reply / forward


@covers("mail reply")
def test_mail_reply_dry_run(invoke, graph):
    result = invoke("mail", "reply", "AAMk-msg-0001", "--body", "Thanks", "--dry-run", "--json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["dryRun"] is True
    assert doc["requests"] == [
        {
            "method": "POST",
            "url": f"{GRAPH}/v1.0/me/messages/AAMk-msg-0001/reply",
            "headers": {"Content-Type": "application/json"},
            "body": {"comment": "Thanks"},
        }
    ]
    assert graph.calls.call_count == 0


@covers("mail reply")
def test_mail_reply_dry_run_text(invoke, graph):
    result = invoke("mail", "reply", "AAMk-msg-0001", "--body", "Thanks", "--dry-run")
    assert result.stdout.startswith(
        f"DRY RUN — nothing sent\n1. POST {GRAPH}/v1.0/me/messages/AAMk-msg-0001/reply\n"
    )
    assert graph.calls.call_count == 0


@covers("mail reply")
def test_mail_reply_sends(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/messages/AAMk-msg-0001/reply").mock(
        return_value=httpx.Response(202)
    )
    result = invoke("mail", "reply", "AAMk-msg-0001", "--body", "Thanks", "--json")
    assert result.exit_code == 0 and json.loads(result.stdout) == {"status": "sent"}
    assert json.loads(route.calls.last.request.content) == {"comment": "Thanks"}


@covers("mail reply")
def test_mail_reply_all_html_and_extra_recipients(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/messages/AAMk-msg-0001/replyAll").mock(
        return_value=httpx.Response(202)
    )
    result = invoke(
        "mail",
        "reply",
        "AAMk-msg-0001",
        "--body",
        "<p>Ack</p>",
        "--html",
        "--reply-all",
        "--to",
        "eve@example.com",
    )
    assert result.exit_code == 0, result.stderr
    body = json.loads(route.calls.last.request.content)
    assert body["message"]["body"] == {"contentType": "HTML", "content": "<p>Ack</p>"}
    assert body["message"]["toRecipients"] == [{"emailAddress": {"address": "eve@example.com"}}]
    assert "comment" not in body


@covers("mail forward")
def test_mail_forward(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/messages/AAMk-msg-0001/forward").mock(
        return_value=httpx.Response(202)
    )
    result = invoke(
        "mail",
        "forward",
        "AAMk-msg-0001",
        "--to",
        "eve@example.com,bob@example.com",
        "--body",
        "FYI",
        "--json",
    )
    assert result.exit_code == 0 and json.loads(result.stdout) == {"status": "sent"}
    assert json.loads(route.calls.last.request.content) == {
        "toRecipients": [
            {"emailAddress": {"address": "eve@example.com"}},
            {"emailAddress": {"address": "bob@example.com"}},
        ],
        "comment": "FYI",
    }


@covers("mail forward")
def test_mail_forward_dry_run_and_requires_to(invoke, graph):
    result = invoke("mail", "forward", "AAMk-msg-0001", "--to", "eve@example.com", "--dry-run")
    assert result.exit_code == 0, result.stderr
    assert f"1. POST {GRAPH}/v1.0/me/messages/AAMk-msg-0001/forward" in result.stdout
    assert graph.calls.call_count == 0
    result = invoke("mail", "forward", "AAMk-msg-0001", "--body", "FYI")
    assert result.exit_code == 2 and result.stderr.startswith("error[USAGE]: --to is required")


# --------------------------------------------------------------------------- drafts write


@covers("mail drafts create")
def test_mail_drafts_create_returns_draft(invoke, graph, tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    draft = {"id": "AAMk-draft-0003", "subject": "Hi", "isDraft": True}
    route = graph.post(f"{GRAPH}/v1.0/me/messages").mock(
        return_value=httpx.Response(201, json=draft)
    )
    result = invoke(
        "mail",
        "drafts",
        "create",
        "--to",
        "ada@example.com",
        "--subject",
        "Hi",
        "--body",
        "Body",
        "--attach",
        str(f),
        "--json",
    )
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == draft
    body = json.loads(route.calls.last.request.content)
    assert body["subject"] == "Hi" and body["toRecipients"]
    assert body["body"] == {"contentType": "Text", "content": "Body"}
    assert body["attachments"][0]["contentBytes"] == "aGVsbG8="
    assert "saveToSentItems" not in body


@covers("mail drafts create")
def test_mail_drafts_create_dry_run(invoke, graph):
    result = invoke(
        "mail", "drafts", "create", "--to", "ada@example.com", "--body", "x", "--dry-run", "--json"
    )
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert [s["url"] for s in doc["requests"]] == [f"{GRAPH}/v1.0/me/messages"]
    assert graph.calls.call_count == 0


@covers("mail drafts send")
def test_mail_drafts_send(invoke, graph):
    route = graph.post(f"{GRAPH}/v1.0/me/messages/AAMk-draft-0003/send").mock(
        return_value=httpx.Response(202)
    )
    result = invoke("mail", "drafts", "send", "AAMk-draft-0003", "--json")
    assert result.exit_code == 0 and json.loads(result.stdout) == {"status": "sent"}
    assert route.called and route.calls.last.request.content == b""


@covers("mail drafts send")
def test_mail_drafts_send_dry_run(invoke, graph):
    result = invoke("mail", "drafts", "send", "AAMk-draft-0003", "--dry-run", "--json")
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["requests"] == [
        {
            "method": "POST",
            "url": f"{GRAPH}/v1.0/me/messages/AAMk-draft-0003/send",
            "headers": {},
            "body": None,
        }
    ]
    assert graph.calls.call_count == 0


# --------------------------------------------------------------------------- mail mark


@covers("mail mark")
def test_mail_mark_single_patch_and_list_envelope(invoke, graph):
    updated = message(isRead=True, categories=["Red"], importance="low")
    route = graph.patch(MSG).mock(return_value=httpx.Response(200, json=updated))
    r = invoke(
        "mail",
        "mark",
        "AAMk-msg-0001",
        "--read",
        "--flag",
        "--category",
        "Red",
        "--importance",
        "low",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    assert json.loads(route.calls.last.request.content) == {
        "isRead": True,
        "flag": {"flagStatus": "flagged"},
        "categories": ["Red"],
        "importance": "low",
    }
    assert json.loads(r.stdout) == {"items": [updated], "count": 1, "truncated": False}


@covers("mail mark")
def test_mail_mark_many_uses_batch(invoke, graph):
    ids = ["AAMk-msg-0001", "AAMk-msg-0002", "AAMk-msg-0003"]
    route = graph.post(f"{GRAPH}/v1.0/$batch").mock(
        return_value=httpx.Response(
            200,
            json={
                "responses": [
                    {
                        "id": str(n),
                        "status": 200,
                        "headers": {},
                        "body": message(id=mid, isRead=True),
                    }
                    for n, mid in enumerate(ids, 1)
                ]
            },
        )
    )
    r = invoke("mail", "mark", *ids, "--unflag", "--json")
    assert r.exit_code == 0, r.stderr
    assert [m["id"] for m in json.loads(r.stdout)["items"]] == ids
    assert route.call_count == 1
    requests = json.loads(route.calls.last.request.content)["requests"]
    assert [s["method"] for s in requests] == ["PATCH", "PATCH", "PATCH"]
    assert [s["url"] for s in requests] == [f"/me/messages/{mid}" for mid in ids]
    assert requests[0]["headers"]["Content-Type"] == "application/json"
    assert requests[0]["body"] == {"flag": {"flagStatus": "notFlagged"}}


@covers("mail mark")
def test_mail_mark_batch_sub_error_exit_4(invoke, graph):
    graph.post(f"{GRAPH}/v1.0/$batch").mock(
        return_value=httpx.Response(
            200,
            json={
                "responses": [
                    {"id": "1", "status": 200, "headers": {}, "body": message()},
                    {
                        "id": "2",
                        "status": 404,
                        "headers": {},
                        "body": {
                            "error": {
                                "code": "ErrorItemNotFound",
                                "message": "The specified object was not found.",
                                "innerError": {"request-id": "req-0001"},
                            }
                        },
                    },
                ]
            },
        )
    )
    r = invoke("mail", "mark", "AAMk-msg-0001", "AAMk-msg-9999", "--read")
    assert r.exit_code == 4 and r.stdout == ""
    assert r.stderr.startswith("error[ErrorItemNotFound]: The specified object was not found.\n")


@covers("mail mark")
def test_mail_mark_conflicting_flags_exit_2(invoke, graph):
    r = invoke("mail", "mark", "AAMk-msg-0001", "--read", "--unread")
    assert r.exit_code == 2 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[USAGE]: --read and --unread are mutually exclusive")
    r = invoke("mail", "mark", "AAMk-msg-0001", "--flag", "--unflag")
    assert r.exit_code == 2 and "at most one of" in r.stderr
    r = invoke("mail", "mark", "AAMk-msg-0001", "--category", "Red", "--clear-categories")
    assert r.exit_code == 2 and "--category and --clear-categories" in r.stderr
    r = invoke("mail", "mark", "AAMk-msg-0001")
    assert r.exit_code == 2 and "nothing to change" in r.stderr
    assert graph.calls.call_count == 0


@covers("mail mark")
def test_mail_mark_dry_run(invoke, graph):
    r = invoke(
        "mail", "mark", "AAMk-msg-0001", "AAMk-msg-0002", "--flag-complete", "--dry-run", "--json"
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert [s["method"] for s in doc["requests"]] == ["PATCH", "PATCH"]
    assert doc["requests"][0]["url"] == MSG
    assert doc["requests"][0]["body"] == {"flag": {"flagStatus": "complete"}}
    assert "$batch" in doc["requests"][0]["note"]
    assert graph.calls.call_count == 0


@covers("mail mark")
@pytest.mark.scopes(["User.Read", "Mail.Read"])
def test_mail_mark_missing_scope(invoke, graph):
    r = invoke("mail", "mark", "AAMk-msg-0001", "--read")
    assert r.exit_code == 3 and graph.calls.call_count == 0
    assert r.stderr.startswith(
        "error[MISSING_SCOPE]: this command needs Mail.ReadWrite; the current token has Mail.Read\n"
    )
    assert "login --scopes extended" in r.stderr


# --------------------------------------------------------------------------- move / delete


@covers("mail move")
def test_mail_move_returns_new_message(invoke, graph):
    moved = message(id="AAMk-msg-0099")
    route = graph.post(f"{MSG}/move").mock(return_value=httpx.Response(201, json=moved))
    r = invoke("mail", "move", "AAMk-msg-0001", "--folder", "Archive")
    assert r.exit_code == 0, r.stderr
    assert json.loads(route.calls.last.request.content) == {"destinationId": "archive"}
    assert r.stdout == "Moved to Archive; new id: AAMk-msg-0099\n"
    r = invoke("mail", "move", "AAMk-msg-0001", "--folder", "Archive", "--json")
    assert json.loads(r.stdout) == moved


@covers("mail move")
def test_mail_move_by_folder_name_resolves(invoke, graph):
    mock_graph(graph, "mail/folders_resolve")
    route = graph.post(f"{MSG}/move").mock(
        return_value=httpx.Response(201, json=message(id="AAMk-msg-0098"))
    )
    r = invoke("mail", "move", "AAMk-msg-0001", "--folder", "Projects", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(route.calls.last.request.content) == {"destinationId": "AAMk-folder-0003"}


@covers("mail move")
def test_mail_move_dry_run(invoke, graph):
    r = invoke("mail", "move", "AAMk-msg-0001", "--folder", "archive", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["requests"] == [
        {
            "method": "POST",
            "url": f"{MSG}/move",
            "headers": {"Content-Type": "application/json"},
            "body": {"destinationId": "archive"},
        }
    ]
    assert graph.calls.call_count == 0


@covers("mail move")
def test_mail_move_dry_run_resolves_a_folder_name(invoke, graph):
    routes = mock_graph(graph, "mail/folders_resolve")
    move = graph.post(f"{MSG}/move").mock(return_value=httpx.Response(201, json=message()))
    r = invoke("mail", "move", "AAMk-msg-0001", "--folder", "Projects", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    # Resolution is a read, so a dry run still performs it; only the write is withheld.
    assert [routes[0].call_count, routes[1].call_count] == [1, 1]
    assert not move.called and graph.calls.call_count == 2
    assert json.loads(r.stdout)["requests"] == [
        {
            "method": "POST",
            "url": f"{MSG}/move",
            "headers": {"Content-Type": "application/json"},
            "body": {"destinationId": "AAMk-folder-0003"},
        }
    ]


@covers("mail delete")
def test_mail_delete(invoke, graph):
    route = graph.delete(MSG).mock(return_value=httpx.Response(204))
    r = invoke("mail", "delete", "AAMk-msg-0001", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout) == {"status": "deleted", "id": "AAMk-msg-0001"}
    assert route.called


@covers("mail delete")
def test_mail_delete_dry_run(invoke, graph):
    r = invoke("mail", "delete", "AAMk-msg-0001", "--dry-run")
    assert r.exit_code == 0, r.stderr
    assert r.stdout == f"DRY RUN — nothing sent\n1. DELETE {MSG}\n"
    r = invoke("mail", "delete", "AAMk-msg-0001", "--dry-run", "--json")
    assert json.loads(r.stdout)["requests"] == [
        {"method": "DELETE", "url": MSG, "headers": {}, "body": None}
    ]
    assert graph.calls.call_count == 0


# --------------------------------------------------------------------------- rules / categories


@covers("mail rules list")
def test_mail_rules_list(invoke, graph):
    mock_graph(graph, "mail/rules")
    r = invoke("mail", "rules", "list")
    assert r.exit_code == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "sequence", "enabled", "name", "actions"]
    assert lines[1].startswith("AQAAAJ-rule-0001")
    assert "moveToFolder, markAsRead, stopProcessingRules" in lines[1]
    assert "yes" in lines[1] and "no" in lines[2]


@covers("mail categories")
def test_mail_categories(invoke, graph):
    mock_graph(graph, "mail/categories")
    r = invoke("mail", "categories", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 2 and doc["items"][0]["displayName"] == "Red category"
    r = invoke("mail", "categories")
    lines = r.stdout.splitlines()
    assert lines[0].split() == ["id", "name", "color"]
    assert lines[1].split() == [
        "00000000-0000-0000-0000-0000000000c1",
        "Red",
        "category",
        "preset0",
    ]


# --------------------------------------------------------------------------- help


def test_mail_group_help(invoke):
    result = invoke("mail")
    assert result.exit_code == 0 and "Usage:" in result.stdout
    assert "list" in result.stdout and "read" in result.stdout
    for group in ("drafts", "rules"):
        result = invoke("mail", group)
        assert result.exit_code == 0 and "Usage:" in result.stdout
