"""CLI tests for the planner noun (spec §8.14)."""

import json

import pytest

from helpers import covers, graph_error, mock_graph
from mgraphctl.graph import planner
from mgraphctl.http import GraphClient

GRAPH = "https://graph.microsoft.com"


@covers("planner plans")
def test_planner_plans_union_via_batch(invoke, graph):
    # /me/planner/plans (1 plan); memberOf unified (2 groups); $batch (2 sub GETs, overlap)
    routes = mock_graph(graph, "planner/plans")
    r = invoke("planner", "plans", "--json")
    assert r.exit_code == 0, r.stderr
    batch = json.loads(routes[2].calls.last.request.content)
    assert [b["url"] for b in batch["requests"]] == [
        "/groups/11111111-1111-1111-1111-111111111111/planner/plans",
        "/groups/22222222-2222-2222-2222-222222222222/planner/plans",
    ]
    doc = json.loads(r.stdout)
    assert doc["count"] == 2 and "_groupName" not in doc["items"][0]
    text = invoke("planner", "plans").stdout
    assert text.splitlines()[0].split() == ["id", "title", "group"] and "Engineering" in text


@covers("planner plan")
def test_planner_plan_with_details(invoke, graph):
    mock_graph(graph, "planner/plan")
    r = invoke("planner", "plan", "Roadmap", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["id"] == "plan-0001" and doc["title"] == "Roadmap"
    assert doc["details"] == {"@odata.etag": 'W/"etag-d1"', "description": "Plan description"}

    text = invoke("planner", "plan", "Roadmap").stdout
    assert "Roadmap" in text and "Plan description" in text


@covers("planner buckets")
def test_planner_buckets_by_plan_title(invoke, graph):
    mock_graph(graph, "planner/buckets")
    r = invoke("planner", "buckets", "Roadmap", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 2
    assert [b["name"] for b in doc["items"]] == ["Backlog", "Doing"]

    text = invoke("planner", "buckets", "Roadmap").stdout
    assert text.splitlines()[0].split() == ["id", "name"]


@covers("planner tasks")
def test_planner_tasks_hides_completed_and_names_buckets(invoke, graph):
    mock_graph(graph, "planner/tasks")

    default = json.loads(invoke("planner", "tasks", "Roadmap", "--json").stdout)
    assert default["count"] == 2
    assert {t["id"] for t in default["items"]} == {"task-0001", "task-0003"}

    everything = json.loads(
        invoke("planner", "tasks", "Roadmap", "--include-completed", "--json").stdout
    )
    assert everything["count"] == 3

    filtered = json.loads(
        invoke("planner", "tasks", "Roadmap", "--bucket", "Backlog", "--json").stdout
    )
    assert filtered["count"] == 1 and filtered["items"][0]["id"] == "task-0001"

    text = invoke("planner", "tasks", "Roadmap").stdout
    assert text.splitlines()[0].split() == ["id", "%", "priority", "due", "bucket", "title"]
    assert "Backlog" in text


@covers("planner tasks")
def test_planner_tasks_my_with_plan_titles_batch(invoke, graph):
    routes = mock_graph(graph, "planner/my_tasks")
    r = invoke("planner", "tasks", "--my", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 2
    batch = json.loads(routes[1].calls.last.request.content)
    assert [b["url"] for b in batch["requests"]] == [
        "/planner/plans/plan-0001",
        "/planner/plans/plan-0002",
    ]

    text = invoke("planner", "tasks", "--my").stdout
    assert text.splitlines()[0].split() == ["id", "%", "priority", "due", "plan", "title"]
    assert "Roadmap" in text and "Onboarding" in text


@covers("planner tasks")
def test_planner_tasks_requires_plan_unless_my(invoke):
    result = invoke("planner", "tasks")
    assert result.exit_code == 2


@covers("planner tasks")
def test_planner_tasks_limit_zero_is_usage_error(invoke):
    assert invoke("planner", "tasks", "Roadmap", "--limit", "0").exit_code == 2


@covers("planner tasks")
def test_planner_tasks_limit_client_side(invoke, graph):
    routes = mock_graph(graph, "planner/tasks_limit")
    r = invoke("planner", "tasks", "Roadmap", "--limit", "2", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 2 and doc["truncated"] is True
    assert [t["id"] for t in doc["items"]] == ["task-0001", "task-0002"]
    tasks_route = routes[3]
    assert tasks_route.calls.last.request.url.query == b""

    text_result = invoke("planner", "tasks", "Roadmap", "--limit", "2")
    assert text_result.stderr == "(more results available — raise --limit)\n"


@covers("planner plans")
def test_planner_plans_truncated_by_limit(invoke, graph):
    mock_graph(graph, "planner/plans")
    r = invoke("planner", "plans", "--limit", "1", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 1 and doc["truncated"] is True

    text_result = invoke("planner", "plans", "--limit", "1")
    assert text_result.stderr == "(more results available — raise --limit)\n"


@covers("planner tasks")
def test_planner_tasks_my_truncated_by_limit(invoke, graph):
    mock_graph(graph, "planner/my_tasks")
    r = invoke("planner", "tasks", "--my", "--limit", "1", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 1 and doc["truncated"] is True

    text_result = invoke("planner", "tasks", "--my", "--limit", "1")
    assert text_result.stderr == "(more results available — raise --limit)\n"


@covers("planner plans")
def test_planner_plans_batch_failure_degrades_gracefully(invoke, graph):
    mock_graph(graph, "planner/plans_partial_failure")
    r = invoke("planner", "plans", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    # The failed group's plan is skipped; the owned plan and the other group's plan remain.
    assert doc["count"] == 2
    assert "no planner access" in r.stderr


@covers("planner task")
def test_planner_task_details_error_swallowed(invoke, graph):
    mock_graph(graph, "planner/task_details_error")
    r = invoke("planner", "task", "task-0001", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["title"] == "Design schema" and doc["details"] == {}


def test_planner_no_odata_params(graph):
    mock_graph(graph, "planner/no_odata_params")
    with GraphClient(lambda force_refresh: "tok", tz="Europe/Warsaw") as client:
        planner.get_plan(client, "plan-0001")
        planner.list_buckets(client, "plan-0001")
        planner.list_tasks(client, "plan-0001")
        planner.get_task(client, "task-0001")
    assert graph.calls.call_count > 0
    for call in graph.calls:
        assert call.request.url.query == b""


@covers("planner task")
@pytest.mark.parametrize(
    "status,code,exit_code",
    [(404, "ErrorItemNotFound", 4), (403, "ErrorAccessDenied", 3), (400, "BadRequest", 1)],
)
def test_planner_task_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.get(f"{GRAPH}/v1.0/planner/tasks/task-x").mock(return_value=graph_error(status, code))
    result = invoke("planner", "task", "task-x")
    assert result.exit_code == exit_code
    assert result.stdout == ""
    assert result.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("planner task")
def test_planner_task_401_after_refresh(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/planner/tasks/task-x").mock(
        return_value=graph_error(401, "InvalidAuthenticationToken")
    )
    result = invoke("planner", "task", "task-x")
    assert result.exit_code == 3 and route.call_count == 2
    assert result.stderr.startswith("error[UNAUTHORIZED]:") and "login --force" in result.stderr


@covers("planner create")
def test_planner_create_assign_and_description(invoke, graph):
    mock_graph(graph, "planner/create")
    r = invoke(
        "planner",
        "create",
        "--plan",
        "Roadmap",
        "--title",
        "T",
        "--bucket",
        "Backlog",
        "--due",
        "2026-09-10",
        "--assign",
        "ada@example.com",
        "--priority",
        "3",
        "--description",
        "D",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["id"] == "task-0001" and doc["details"]["description"] == "D"


@covers("planner create")
def test_planner_create_dry_run_shows_etag_placeholder(invoke, graph):
    mock_graph(graph, "planner/create")
    r = invoke(
        "planner",
        "create",
        "--plan",
        "Roadmap",
        "--title",
        "T",
        "--bucket",
        "Backlog",
        "--due",
        "2026-09-10",
        "--assign",
        "ada@example.com",
        "--priority",
        "3",
        "--description",
        "D",
        "--dry-run",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["dryRun"] is True
    assert doc["requests"][0]["method"] == "POST"
    assert doc["requests"][0]["body"] == {
        "planId": "plan-0001",
        "bucketId": "bucket-0001",
        "title": "T",
        "dueDateTime": "2026-09-10T00:00:00+02:00",
        "priority": 3,
        "assignments": {
            "oid-ada-0001": {"@odata.type": "#microsoft.graph.plannerAssignment", "orderHint": " !"}
        },
    }
    second = doc["requests"][1]
    assert second["method"] == "PATCH" and "{taskId}" in second["url"]
    assert second["headers"]["If-Match"] == "{etag}"
    # No POST/PATCH should have actually reached the server.
    assert all(c.request.method == "GET" for c in graph.calls)


@covers("planner update")
def test_planner_update_etag_and_412_retry(invoke, graph):
    mock_graph(graph, "planner/update")
    r = invoke(
        "planner",
        "update",
        "task-0001",
        "--percent",
        "50",
        "--unassign",
        "bob@example.com",
        "--json",
    )
    assert r.exit_code == 0, r.stderr
    patch_calls = [c for c in graph.calls if c.request.method == "PATCH"]
    assert len(patch_calls) == 2
    assert patch_calls[0].request.headers["If-Match"] == 'W/"etag-1"'
    assert patch_calls[0].request.headers["Prefer"] == "return=representation"
    assert patch_calls[1].request.headers["If-Match"] == 'W/"etag-2"'
    body = json.loads(patch_calls[1].request.content)
    assert body == {"percentComplete": 50, "assignments": {"oid-bob-0001": None}}


@covers("planner update")
def test_planner_update_dry_run(invoke, graph):
    r = invoke("planner", "update", "task-0001", "--title", "New Title", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["requests"][0]["headers"]["If-Match"] == "{etag}"
    assert doc["requests"][0]["body"] == {"title": "New Title"}
    assert graph.calls.call_count == 0


@covers("planner update")
def test_planner_update_percent_is_a_choice(invoke, graph):
    """Graph rejects anything but 0, 50 or 100, so the parser does it first."""
    assert "--percent <0|50|100>" in invoke("planner", "update", "--help").stdout
    r = invoke("planner", "update", "task-0001", "--percent", "42")
    assert r.exit_code == 2 and r.stdout == "" and graph.calls.call_count == 0
    assert "--percent" in r.stderr


@covers("planner complete")
def test_planner_complete_is_percent_100(invoke, graph):
    mock_graph(graph, "planner/complete")
    r = invoke("planner", "complete", "task-0001", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["percentComplete"] == 100


@covers("planner complete")
def test_planner_complete_dry_run(invoke, graph):
    r = invoke("planner", "complete", "task-0001", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["requests"][0]["body"] == {"percentComplete": 100}
    assert graph.calls.call_count == 0


@covers("planner delete")
def test_planner_delete_with_if_match(invoke, graph):
    mock_graph(graph, "planner/delete")
    r = invoke("planner", "delete", "task-0001", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc == {"status": "deleted", "id": "task-0001"}
    delete_calls = [c for c in graph.calls if c.request.method == "DELETE"]
    assert len(delete_calls) == 1 and delete_calls[0].request.headers["If-Match"] == 'W/"etag-1"'


@covers("planner delete")
def test_planner_delete_dry_run(invoke, graph):
    r = invoke("planner", "delete", "task-0001", "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["requests"][0]["method"] == "DELETE"
    assert doc["requests"][0]["headers"]["If-Match"] == "{etag}"
    assert graph.calls.call_count == 0


def test_planner_group_help(invoke):
    result = invoke("planner")
    assert result.exit_code == 0 and "Usage:" in result.stdout
