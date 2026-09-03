"""CLI tests for the org noun (spec §8.6)."""

import json

import httpx
import pytest

from helpers import GRAPH, covers, graph_error, mock_graph

MANAGER_SELECT = "id,displayName,userPrincipalName,mail,jobTitle,department"
CHAIN_SELECT = "id,displayName,userPrincipalName,jobTitle"


@covers("org manager")
def test_org_manager_self_and_other(invoke, graph):
    routes = mock_graph(graph, "org/manager")
    r = invoke("org", "manager", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["displayName"] == "Bob Manager"
    assert dict(routes[0].calls.last.request.url.params) == {"$select": MANAGER_SELECT}

    r = invoke("org", "manager", "bob@example.com", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["displayName"] == "Carol Manager"
    assert dict(routes[1].calls.last.request.url.params) == {"$select": MANAGER_SELECT}

    r = invoke("org", "manager")
    assert r.exit_code == 0
    assert "Name" in r.stdout and "Bob Manager" in r.stdout


@covers("org manager")
def test_org_manager_404_no_manager_found(invoke, graph):
    graph.get(f"{GRAPH}/v1.0/me/manager").mock(
        return_value=graph_error(404, "ErrorItemNotFound", message="not found")
    )
    r = invoke("org", "manager")
    assert r.exit_code == 4 and r.stdout == ""
    assert r.stderr.startswith("error[NOT_FOUND]: No manager found\n")


@covers("org manager")
@pytest.mark.scopes(["User.Read"])
def test_org_manager_other_needs_user_read_all(invoke, graph):
    r = invoke("org", "manager", "bob@example.com")
    assert r.exit_code == 3 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[MISSING_SCOPE]: this command needs User.Read.All")
    assert "login --scope User.Read.All" in r.stderr


@covers("org reports")
def test_org_reports(invoke, graph):
    routes = mock_graph(graph, "org/reports")
    r = invoke("org", "reports", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert set(doc) == {"items", "count", "truncated"}
    assert doc["count"] == 2
    req = routes[0].calls.last.request
    assert req.url.path == "/v1.0/me/directReports"
    assert dict(req.url.params) == {"$select": MANAGER_SELECT, "$top": "100"}


@covers("org reports")
@pytest.mark.parametrize(
    "status,code,exit_code",
    [(404, "ErrorItemNotFound", 4), (403, "ErrorAccessDenied", 3), (400, "BadRequest", 1)],
)
def test_org_reports_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.get(f"{GRAPH}/v1.0/me/directReports").mock(return_value=graph_error(status, code))
    result = invoke("org", "reports")
    assert result.exit_code == exit_code
    assert result.stdout == ""
    assert result.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("org reports")
def test_org_reports_401_after_refresh(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/me/directReports").mock(
        return_value=graph_error(401, "InvalidAuthenticationToken")
    )
    result = invoke("org", "reports")
    assert result.exit_code == 3 and route.call_count == 2
    assert result.stderr.startswith("error[UNAUTHORIZED]:") and "login --force" in result.stderr


@covers("org chain")
def test_org_chain_expand_then_fallback(invoke, graph):
    routes = mock_graph(graph, "org/chain")
    r = invoke("org", "chain")
    assert r.exit_code == 0, r.stderr
    lines = r.stdout.splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("0: Ada Example <ada@example.com>")
    assert lines[1].startswith("1: Bob Manager <bob@example.com>")
    assert lines[2].startswith("2: Carol Director <carol@example.com>")
    req = routes[0].calls.last.request
    assert dict(req.url.params) == {
        "$expand": f"manager($levels=max;$select={CHAIN_SELECT})",
        "$count": "true",
    }
    assert req.headers["ConsistencyLevel"] == "eventual"

    r = invoke("org", "chain", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert [level["displayName"] for level in doc] == [
        "Ada Example",
        "Bob Manager",
        "Carol Director",
    ]


@covers("org chain")
def test_org_chain_falls_back_iteratively_on_400(invoke, graph):
    expand_query = {
        "$expand": f"manager($levels=max;$select={CHAIN_SELECT})",
        "$count": "true",
    }
    graph.route(method="GET", url=f"{GRAPH}/v1.0/me", params__eq=expand_query).mock(
        return_value=graph_error(400, "BadRequest")
    )
    graph.route(method="GET", url=f"{GRAPH}/v1.0/me", params__eq={"$select": CHAIN_SELECT}).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "u-ada",
                "displayName": "Ada Example",
                "userPrincipalName": "ada@example.com",
                "jobTitle": "Engineer",
            },
        )
    )
    manager1 = graph.get(
        f"{GRAPH}/v1.0/users/u-ada/manager", params={"$select": CHAIN_SELECT}
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "u-bob",
                "displayName": "Bob Manager",
                "userPrincipalName": "bob@example.com",
                "jobTitle": "Team Lead",
            },
        )
    )
    manager2 = graph.get(
        f"{GRAPH}/v1.0/users/u-bob/manager", params={"$select": CHAIN_SELECT}
    ).mock(return_value=graph_error(404, "ErrorItemNotFound"))

    r = invoke("org", "chain", "--max", "5")
    assert r.exit_code == 0, r.stderr
    lines = r.stdout.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("0: Ada Example")
    assert lines[1].startswith("1: Bob Manager")
    assert manager1.called and manager2.called


@covers("org chain")
@pytest.mark.scopes(["User.Read"])
def test_org_chain_fallback_needs_user_read_all(invoke, graph):
    expand_query = {
        "$expand": f"manager($levels=max;$select={CHAIN_SELECT})",
        "$count": "true",
    }
    graph.route(method="GET", url=f"{GRAPH}/v1.0/me", params__eq=expand_query).mock(
        return_value=graph_error(400, "BadRequest")
    )
    r = invoke("org", "chain")
    assert r.exit_code == 3
    assert r.stderr.startswith("error[MISSING_SCOPE]: this command needs User.Read.All")


def test_org_help(invoke):
    r = invoke("org")
    assert r.exit_code == 0 and "Usage:" in r.stdout
