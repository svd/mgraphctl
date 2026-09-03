"""CLI tests for the todo noun (spec §8.15)."""

import json

import httpx
import pytest

from helpers import covers, graph_error, mock_graph

GRAPH = "https://graph.microsoft.com"


@covers("todo lists")
def test_todo_lists_wellknown(invoke, graph):
    routes = mock_graph(graph, "todo/lists")
    r = invoke("todo", "lists", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 2
    assert routes[0].calls.last.request.url.params["$top"] == "100"

    text = invoke("todo", "lists").stdout
    assert text.splitlines()[0].split() == ["id", "wellknown", "name"]
    assert "defaultList" in text and "Groceries" in text


@covers("todo tasks")
def test_todo_tasks_filter_and_list_resolution(invoke, graph):
    routes = mock_graph(graph, "todo/tasks")
    r = invoke("todo", "tasks", "Groceries", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 1 and doc["items"][0]["id"] == "task-0001"
    req = routes[1].calls.last.request
    assert req.headers["Prefer"] == 'outlook.timezone="Europe/Warsaw"'

    all_doc = json.loads(
        invoke("todo", "tasks", "Groceries", "--include-completed", "--json").stdout
    )
    assert all_doc["count"] == 2

    default_doc = json.loads(invoke("todo", "tasks", "defaultList", "--json").stdout)
    assert default_doc["count"] == 1 and default_doc["items"][0]["id"] == "task-0010"

    text = invoke("todo", "tasks", "Groceries").stdout
    assert text.splitlines()[0].split() == ["id", "status", "importance", "due", "title"]


@covers("todo tasks")
def test_todo_tasks_limit_zero_is_usage_error(invoke):
    assert invoke("todo", "tasks", "Groceries", "--limit", "0").exit_code == 2


@covers("todo tasks")
def test_todo_tasks_all_hits_cap_note(invoke, graph):
    pages = []

    def page(request: httpx.Request) -> httpx.Response:
        n = len(pages)
        pages.append(n)
        items = [
            {
                "id": f"task-{n * 100 + i:04d}",
                "status": "notStarted",
                "importance": "normal",
                "dueDateTime": None,
                "title": "Task",
            }
            for i in range(100)
        ]
        return httpx.Response(200, json={"value": items, "@odata.nextLink": str(request.url)})

    graph.get(f"{GRAPH}/v1.0/me/todo/lists/list-0002/tasks").mock(side_effect=page)
    result = invoke("todo", "tasks", "id:list-0002", "--all", "--json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["count"] == 500 and doc["truncated"] is True
    assert len(pages) == 5
    result = invoke("todo", "tasks", "id:list-0002", "--all")
    assert result.stderr == "(hit the 500-item cap — narrow the query)\n"


@covers("todo tasks")
def test_todo_tasks_limit_reports_rerun_with_all(invoke, graph):
    graph.get(f"{GRAPH}/v1.0/me/todo/lists/list-0002/tasks").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "task-0001",
                        "status": "notStarted",
                        "importance": "high",
                        "dueDateTime": None,
                        "title": "Buy milk",
                    },
                    {
                        "id": "task-0002",
                        "status": "notStarted",
                        "importance": "low",
                        "dueDateTime": None,
                        "title": "Buy bread",
                    },
                ]
            },
        )
    )
    result = invoke("todo", "tasks", "id:list-0002", "--limit", "1", "--json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["count"] == 1 and doc["truncated"] is True
    assert result.stderr == ""  # notes are a text-mode diagnostic
    result = invoke("todo", "tasks", "id:list-0002", "--limit", "1")
    assert result.stderr == "(more results available — rerun with --all)\n"


@covers("todo task")
def test_todo_task_expand(invoke, graph):
    routes = mock_graph(graph, "todo/task")
    r = invoke("todo", "task", "Groceries", "task-0001", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["id"] == "task-0001" and "checklistItems" in doc
    req = routes[1].calls.last.request
    assert req.url.params["$expand"] == "checklistItems,linkedResources"


@covers("todo task")
@pytest.mark.parametrize(
    "status,code,exit_code",
    [(404, "ErrorItemNotFound", 4), (403, "ErrorAccessDenied", 3), (400, "BadRequest", 1)],
)
def test_todo_task_error_exit_codes(invoke, graph, status, code, exit_code):
    mock_graph(graph, "todo/lists")
    graph.get(f"{GRAPH}/v1.0/me/todo/lists/list-0002/tasks/task-x").mock(
        return_value=graph_error(status, code)
    )
    result = invoke("todo", "task", "Groceries", "task-x")
    assert result.exit_code == exit_code
    assert result.stdout == ""
    assert result.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("todo task")
def test_todo_task_401_after_refresh(invoke, graph):
    mock_graph(graph, "todo/lists")
    route = graph.get(f"{GRAPH}/v1.0/me/todo/lists/list-0002/tasks/task-x").mock(
        return_value=graph_error(401, "InvalidAuthenticationToken")
    )
    result = invoke("todo", "task", "Groceries", "task-x")
    assert result.exit_code == 3 and route.call_count == 2
    assert result.stderr.startswith("error[UNAUTHORIZED]:") and "login --force" in result.stderr


@covers("todo create")
def test_todo_create_full_body(invoke, graph):
    routes = mock_graph(graph, "todo/create")
    r = invoke(
        "todo",
        "create",
        "Groceries",
        "--title",
        "T",
        "--due",
        "2026-09-10",
        "--body",
        "B",
        "--importance",
        "high",
        "--reminder",
        "2026-09-09T09:00",
        "--start",
        "2026-09-08",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    body = json.loads(routes[1].calls.last.request.content)
    assert body == {
        "title": "T",
        "body": {"content": "B", "contentType": "text"},
        "importance": "high",
        "dueDateTime": {"dateTime": "2026-09-10T00:00:00", "timeZone": "Europe/Warsaw"},
        "reminderDateTime": {"dateTime": "2026-09-09T09:00:00", "timeZone": "Europe/Warsaw"},
        "isReminderOn": True,
        "startDateTime": {"dateTime": "2026-09-08T00:00:00", "timeZone": "Europe/Warsaw"},
    }


@covers("todo create")
def test_todo_create_dry_run(invoke, graph):
    mock_graph(graph, "todo/create")
    r = invoke("todo", "create", "Groceries", "--title", "T", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["dryRun"] is True
    assert doc["requests"][0]["body"] == {"title": "T"}
    assert all(c.request.method == "GET" for c in graph.calls)


@covers("todo create")
@pytest.mark.scopes(["Tasks.Read"])
def test_todo_create_missing_scope(invoke, graph):
    result = invoke("todo", "create", "Groceries", "--title", "T")
    assert result.exit_code == 3 and graph.calls.call_count == 0
    assert result.stderr.startswith(
        "error[MISSING_SCOPE]: this command needs Tasks.ReadWrite; "
        "the current token has Tasks.Read\n"
    )
    assert "login --scopes extended" in result.stderr


@covers("todo update")
def test_todo_update_and_status(invoke, graph):
    routes = mock_graph(graph, "todo/update")
    r = invoke(
        "todo",
        "update",
        "Groceries",
        "task-0001",
        "--title",
        "Buy oat milk",
        "--status",
        "inProgress",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    body = json.loads(routes[1].calls.last.request.content)
    assert body == {"title": "Buy oat milk", "status": "inProgress"}
    doc = json.loads(r.stdout)
    assert doc["status"] == "inProgress"


@covers("todo update")
def test_todo_update_dry_run(invoke, graph):
    # An id:-shaped LIST needs no lookup, so this reaches true zero Graph calls (unlike the
    # name-resolving `test_todo_create_dry_run` above, which still issues the lists GET).
    r = invoke(
        "todo", "update", "id:list-0002", "task-0001", "--title", "New", "--dry-run", "--json"
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["requests"][0]["body"] == {"title": "New"}
    assert graph.calls.call_count == 0


@covers("todo update")
def test_todo_update_with_no_fields_is_usage_error(invoke, graph):
    result = invoke("todo", "update", "id:list-0002", "task-0001")
    assert result.exit_code == 2 and graph.calls.call_count == 0
    assert result.stderr.startswith("error[USAGE]: give at least one field to update")


@covers("todo complete")
def test_todo_complete(invoke, graph):
    routes = mock_graph(graph, "todo/complete")
    r = invoke("todo", "complete", "Groceries", "task-0001", "--json")
    assert r.exit_code == 0, r.stderr
    body = json.loads(routes[1].calls.last.request.content)
    assert body == {"status": "completed"}
    doc = json.loads(r.stdout)
    assert doc["status"] == "completed"


@covers("todo complete")
def test_todo_complete_dry_run(invoke, graph):
    r = invoke("todo", "complete", "id:list-0002", "task-0001", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["requests"][0]["body"] == {"status": "completed"}
    assert graph.calls.call_count == 0


@covers("todo delete")
def test_todo_delete(invoke, graph):
    mock_graph(graph, "todo/delete")
    r = invoke("todo", "delete", "Groceries", "task-0001", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc == {"status": "deleted", "id": "task-0001"}


@covers("todo delete")
def test_todo_delete_dry_run(invoke, graph):
    r = invoke("todo", "delete", "id:list-0002", "task-0001", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["requests"][0]["method"] == "DELETE"
    assert graph.calls.call_count == 0


@covers("todo from-mail")
def test_todo_from_mail(invoke, graph):
    routes = mock_graph(graph, "todo/from_mail")
    r = invoke("todo", "from-mail", "Groceries", "AAMk-msg-0001", "--json")
    assert r.exit_code == 0, r.stderr
    body = json.loads(routes[2].calls.last.request.content)
    assert body == {
        "title": "Sprint review",
        "body": {
            "content": "From: Ada Example <ada@example.com>\n"
            "Received: 2026-08-31T10:15+02:00\n\nLet's sync at 10am.",
            "contentType": "text",
        },
        "linkedResources": [
            {
                "webUrl": "https://outlook.office.com/mail/AAMk-msg-0001",
                "applicationName": "Microsoft Outlook",
                "displayName": "Sprint review",
                "externalId": "AAMk-msg-0001",
            }
        ],
    }


@covers("todo from-mail")
def test_todo_from_mail_title_overrides_task_title_only(invoke, graph):
    routes = mock_graph(graph, "todo/from_mail")
    r = invoke("todo", "from-mail", "Groceries", "AAMk-msg-0001", "--title", "Follow up", "--json")
    assert r.exit_code == 0, r.stderr
    body = json.loads(routes[2].calls.last.request.content)
    assert body["title"] == "Follow up"
    assert body["linkedResources"][0]["displayName"] == "Sprint review"


@covers("todo from-mail")
def test_todo_from_mail_dry_run_still_reads_message(invoke, graph):
    routes = mock_graph(graph, "todo/from_mail")
    r = invoke("todo", "from-mail", "Groceries", "AAMk-msg-0001", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert len(doc["requests"]) == 1 and doc["requests"][0]["method"] == "POST"
    assert routes[1].called  # the message GET is a read; it runs even under --dry-run
    assert not routes[2].called  # the POST must not have actually been sent


def test_todo_group_help(invoke):
    result = invoke("todo")
    assert result.exit_code == 0 and "Usage:" in result.stdout
