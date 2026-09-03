"""CLI tests for the people noun (spec §8.5)."""

import json

import httpx
import pytest

from helpers import GRAPH, covers, graph_error, mock_graph


@covers("people search")
def test_people_search_query_and_columns(invoke, graph):
    routes = mock_graph(graph, "people/search")
    r = invoke("people", "search", "Ada", "--json")
    assert r.exit_code == 0, r.stderr
    req = routes[0].calls.last.request
    assert dict(req.url.params) == {
        "$search": '"Ada"',
        "$top": "50",
        "$select": "id,displayName,scoredEmailAddresses,jobTitle,department,companyName,"
        "personType,userPrincipalName",
    }
    assert json.loads(r.stdout)["count"] == 1
    assert invoke("people", "search", "Ada").stdout.splitlines()[0].split() == [
        "id",
        "name",
        "email",
        "title",
        "department",
        "type",
    ]


@covers("people search")
def test_people_search_limit_zero_is_usage_error(invoke):
    assert invoke("people", "search", "Ada", "--limit", "0").exit_code == 2


@covers("people contacts")
def test_people_contacts_search_and_fallback(invoke, graph):
    routes = mock_graph(graph, "people/contacts")
    r = invoke("people", "contacts", "--search", "bob", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["count"] == 1
    assert doc["items"][0]["displayName"] == "Bob Example"
    first = routes[0].calls.last.request
    assert dict(first.url.params) == {
        "$select": "id,displayName,emailAddresses,mobilePhone,businessPhones,jobTitle,companyName",
        "$search": '"bob"',
        "$top": "50",
    }
    second = routes[1].calls.last.request
    assert dict(second.url.params) == {
        "$select": "id,displayName,emailAddresses,mobilePhone,businessPhones,jobTitle,companyName",
        "$top": "250",
    }


@covers("people contact")
def test_people_contact_get(invoke, graph):
    graph.get(f"{GRAPH}/v1.0/me/contacts/contact-0001").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "contact-0001",
                "displayName": "Bob Example",
                "emailAddresses": [{"address": "bob@example.com", "name": "Bob Example"}],
                "mobilePhone": "+48 000 000 002",
                "businessPhones": [],
                "jobTitle": "Sales",
                "companyName": "Contoso",
            },
        )
    )
    r = invoke("people", "contact", "contact-0001")
    assert r.exit_code == 0, r.stderr
    assert "Name" in r.stdout and "Bob Example" in r.stdout
    r = invoke("people", "contact", "contact-0001", "--json")
    assert json.loads(r.stdout)["displayName"] == "Bob Example"


@covers("people contact")
@pytest.mark.parametrize(
    "status,code,exit_code",
    [(404, "ErrorItemNotFound", 4), (403, "ErrorAccessDenied", 3), (400, "BadRequest", 1)],
)
def test_people_contact_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.get(f"{GRAPH}/v1.0/me/contacts/contact-x").mock(return_value=graph_error(status, code))
    result = invoke("people", "contact", "contact-x")
    assert result.exit_code == exit_code
    assert result.stdout == ""
    assert result.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("people contact")
def test_people_contact_401_after_refresh(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/me/contacts/contact-x").mock(
        return_value=graph_error(401, "InvalidAuthenticationToken")
    )
    result = invoke("people", "contact", "contact-x")
    assert result.exit_code == 3 and route.call_count == 2
    assert result.stderr.startswith("error[UNAUTHORIZED]:") and "login --force" in result.stderr


@covers("people users")
def test_people_users_directory_search(invoke, graph):
    routes = mock_graph(graph, "people/users")
    r = invoke("people", "users", "ada", "--json")
    assert r.exit_code == 0, r.stderr
    req = routes[0].calls.last.request
    assert dict(req.url.params) == {
        "$search": '"displayName:ada" OR "mail:ada"',
        "$count": "true",
        "$select": "id,displayName,userPrincipalName,mail,jobTitle,department,officeLocation",
        "$top": "100",
    }
    assert req.headers["ConsistencyLevel"] == "eventual"
    assert json.loads(r.stdout)["count"] == 1


@covers("people users")
@pytest.mark.scopes(["User.Read"])
def test_people_users_missing_scope(invoke, graph):
    result = invoke("people", "users", "ada")
    assert result.exit_code == 3 and graph.calls.call_count == 0
    assert result.stderr.startswith("error[MISSING_SCOPE]: this command needs User.ReadBasic.All")


@covers("people user")
def test_people_user_forms(invoke, graph):
    routes = mock_graph(graph, "people/user")
    r = invoke("people", "user", "me", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["userPrincipalName"] == "fixture-user@example.com"

    r = invoke("people", "user", "11111111-1111-1111-1111-111111111111", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["displayName"] == "Guid User"

    r = invoke("people", "user", "ada@example.com", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout)["displayName"] == "Ada Example"
    for route in routes:
        assert route.called


@covers("people user")
@pytest.mark.scopes(["User.Read"])
def test_people_user_name_needs_readbasic(invoke, graph):
    result = invoke("people", "user", "Ada Example")
    assert result.exit_code == 2 and graph.calls.call_count == 0
    assert "User.ReadBasic.All" in result.stderr


@covers("people user")
@pytest.mark.scopes(["User.Read", "User.ReadBasic.All"])
def test_people_user_name_search_with_readbasic(invoke, graph):
    hit = {
        "id": "00000000-0000-0000-0000-00000000000a",
        "displayName": "Ada Example",
        "userPrincipalName": "ada@example.com",
    }
    graph.get(f"{GRAPH}/v1.0/users").mock(return_value=httpx.Response(200, json={"value": [hit]}))
    result = invoke("people", "user", "Ada Example", "--json")
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["userPrincipalName"] == "ada@example.com"


@covers("people photo")
def test_people_photo_self_and_other(invoke, graph, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock_graph(graph, "people/photo_self")
    r = invoke("people", "photo")
    assert r.exit_code == 0, r.stderr
    default_dest = tmp_path / "fixture-user@example.com.jpg"
    assert default_dest.exists() and default_dest.read_bytes().startswith(b"\x89PNG")

    override = tmp_path / "p.jpg"
    r = invoke("people", "photo", "--output", str(override))
    assert r.exit_code == 0, r.stderr
    assert override.exists()

    route_other = graph.get(f"{GRAPH}/v1.0/users/bob@example.com/photos/96x96/$value").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "image/jpeg"}, content=b"\xff\xd8fake-jpeg"
        )
    )
    other_dest = tmp_path / "bob.jpg"
    r = invoke("people", "photo", "bob@example.com", "--size", "96x96", "--output", str(other_dest))
    assert r.exit_code == 0, r.stderr
    assert route_other.called and other_dest.exists()


@covers("people photo")
def test_people_photo_404_exit_4(invoke, graph, tmp_path):
    graph.get(f"{GRAPH}/v1.0/me/photo/$value").mock(
        return_value=httpx.Response(404, json={"error": {"code": "ImageNotFound", "message": "x"}})
    )
    r = invoke("people", "photo", "--output", str(tmp_path / "p.jpg"))
    assert r.exit_code == 4 and r.stdout == ""


def test_people_help(invoke):
    r = invoke("people")
    assert r.exit_code == 0 and "Usage:" in r.stdout
