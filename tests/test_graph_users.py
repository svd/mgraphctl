"""Directory reads shared by several nouns (spec §8.1, §8.5, §8.16)."""

import httpx
import pytest

from helpers import GRAPH, mock_graph
from mgraphctl.errors import UsageError
from mgraphctl.graph import users
from mgraphctl.http import GraphClient, PageResult

GUID = "00000000-0000-0000-0000-00000000000a"


@pytest.fixture
def client():
    with GraphClient(lambda force_refresh: "tok", tz="Europe/Warsaw") as c:
        yield c


def test_get_me_selects_the_profile_fields(client, graph):
    routes = mock_graph(graph, "top/me")
    assert users.get_me(client)["userPrincipalName"] == "ada@example.com"
    assert routes[0].calls.last.request.url.params["$select"] == users.ME_SELECT


def test_get_user_paths(client, graph):
    me = graph.get(f"{GRAPH}/v1.0/me").mock(return_value=httpx.Response(200, json={"id": "1"}))
    by_id = graph.get(f"{GRAPH}/v1.0/users/{GUID}").mock(
        return_value=httpx.Response(200, json={"id": GUID})
    )
    assert users.get_user(client, "me")["id"] == "1" and me.called
    assert users.get_user(client, GUID)["id"] == GUID and by_id.called
    routes = mock_graph(graph, "users/get_user")
    assert users.get_user(client, "ada@example.com")["displayName"] == "Ada Example"
    assert (
        routes[0]
        .calls.last.request.url.raw_path.decode()
        .startswith("/v1.0/users/ada%40example.com?")
    )


def test_search_users_sends_search_count_and_consistency_level(client, graph):
    routes = mock_graph(graph, "users/search_users")
    page = users.search_users(client, "ada", limit=20, all_=False)
    assert [u["displayName"] for u in page.items] == ["Ada Example", "Adam Example"]
    request = routes[0].calls.last.request
    assert request.url.params["$search"] == '"displayName:ada" OR "mail:ada"'
    assert request.url.params["$count"] == "true" and request.url.params["$top"] == "100"
    assert request.url.params["$select"] == users.USERS_SEARCH_SELECT
    assert request.headers["ConsistencyLevel"] == "eventual"


def test_list_unified_groups_filters_and_caps(client, graph, monkeypatch):
    routes = mock_graph(graph, "users/unified_groups")
    groups = users.list_unified_groups(client)
    assert [g["displayName"] for g in groups] == ["Platform Guild", "Release Managers"]
    request = routes[0].calls.last.request
    assert request.url.params["$filter"] == "groupTypes/any(c:c eq 'Unified')"
    assert request.url.params["$count"] == "true" and request.url.params["$top"] == "999"
    assert request.url.params["$select"] == "id,displayName"
    assert request.headers["ConsistencyLevel"] == "eventual"

    seen: dict = {}

    def record(self, path, **kw):
        seen.update(kw)
        return PageResult([], False, 1)

    monkeypatch.setattr(GraphClient, "paginate", record)
    users.list_unified_groups(client)
    assert seen["cap"] == 999 and seen["page_size"] == 999
    assert seen["all_"] is True and seen["limit"] is None


def test_resolve_user_by_id_shape_and_by_search(client, graph):
    mock_graph(graph, "users/get_user")
    assert users.resolve_user(client, "ada@example.com", can_search=False)["id"] == GUID
    hit = dict(id=GUID, displayName="Ada Example", userPrincipalName="ada@example.com")
    search = graph.get(f"{GRAPH}/v1.0/users").mock(
        return_value=httpx.Response(200, json=dict(value=[hit]))
    )
    matched = users.resolve_user(client, "Ada Example", can_search=True)
    assert matched["userPrincipalName"] == "ada@example.com" and search.called
    sent = search.calls.last.request.url.params["$search"]
    assert sent == '"displayName:Ada Example" OR "mail:Ada Example"'


def test_resolve_user_without_search_permission_is_a_usage_error(client):
    with pytest.raises(UsageError) as excinfo:
        users.resolve_user(client, "Ada Example", can_search=False)
    assert excinfo.value.exit_code == 2 and "User.ReadBasic.All" in excinfo.value.message
