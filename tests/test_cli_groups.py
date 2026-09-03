"""CLI tests for the groups noun (spec §8.16)."""

import json

import pytest

from helpers import GRAPH, covers, graph_error, mock_graph


@covers("groups list")
def test_groups_list_plain_and_unified(invoke, graph):
    routes = mock_graph(graph, "groups/list")
    r = invoke("groups", "list", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert set(doc) == {"items", "count", "truncated"}
    assert doc["count"] == 2
    assert dict(routes[0].calls.last.request.url.params) == {
        "$select": "id,displayName,mail,groupTypes,description",
        "$top": "100",
    }

    r = invoke("groups", "list", "--unified", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 2
    req = routes[1].calls.last.request
    assert dict(req.url.params) == {
        "$filter": "groupTypes/any(c:c eq 'Unified')",
        "$count": "true",
        "$select": "id,displayName",
        "$top": "999",
    }
    assert req.headers["ConsistencyLevel"] == "eventual"

    r = invoke("groups", "list")
    assert r.exit_code == 0
    assert r.stdout.splitlines()[0].split() == ["id", "name", "mail", "types", "description"]


@covers("groups list")
@pytest.mark.parametrize(
    "status,code,exit_code",
    [(404, "ErrorItemNotFound", 4), (403, "ErrorAccessDenied", 3), (400, "BadRequest", 1)],
)
def test_groups_list_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.get(f"{GRAPH}/v1.0/me/memberOf/microsoft.graph.group").mock(
        return_value=graph_error(status, code)
    )
    result = invoke("groups", "list")
    assert result.exit_code == exit_code
    assert result.stdout == ""
    assert result.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("groups list")
def test_groups_list_401_after_refresh(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/me/memberOf/microsoft.graph.group").mock(
        return_value=graph_error(401, "InvalidAuthenticationToken")
    )
    result = invoke("groups", "list")
    assert result.exit_code == 3 and route.call_count == 2
    assert result.stderr.startswith("error[UNAUTHORIZED]:") and "login --force" in result.stderr


@covers("groups members")
def test_groups_members_by_name(invoke, graph):
    routes = mock_graph(graph, "groups/members")
    r = invoke("groups", "members", "Platform Guild", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 2
    lookup_req = routes[0].calls.last.request
    assert dict(lookup_req.url.params) == {
        "$select": "id,displayName,mail,groupTypes,description",
        "$top": "100",
    }
    members_req = routes[1].calls.last.request
    assert members_req.url.path == "/v1.0/groups/grp-0001/members"
    assert dict(members_req.url.params) == {
        "$select": "id,displayName,userPrincipalName,mail,jobTitle",
        "$top": "100",
    }


@covers("groups members")
@pytest.mark.scopes(["User.Read"])
def test_groups_members_missing_scope(invoke, graph):
    result = invoke("groups", "members", "grp-0001")
    assert result.exit_code == 3 and graph.calls.call_count == 0
    assert result.stderr.startswith("error[MISSING_SCOPE]: this command needs Group.Read.All")


def test_groups_help(invoke):
    r = invoke("groups")
    assert r.exit_code == 0 and "Usage:" in r.stdout
