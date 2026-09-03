"""The raw `api` escape hatch (spec §8.17)."""

import json

import httpx
import pytest

from helpers import GRAPH, covers, graph_error, mock_graph


@covers("api")
def test_api_get_json_passthrough(invoke, graph):
    routes = mock_graph(graph, "api/get_me")
    r = invoke("api", "GET", "/me", "--query", "$select=id", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout) == {"id": "00000000-0000-0000-0000-00000000000a"}
    assert routes[0].calls.last.request.url.query.decode() == "$select=id"


@covers("api")
def test_api_absolute_url_and_beta(invoke, graph):
    beta_me = graph.get(f"{GRAPH}/beta/me").mock(return_value=httpx.Response(200, json={"id": "1"}))
    assert invoke("api", "--beta", "GET", "/me").exit_code == 0
    assert beta_me.called
    beta_x = graph.get(f"{GRAPH}/beta/x").mock(return_value=httpx.Response(200, json={"id": "2"}))
    r = invoke("api", "GET", f"{GRAPH}/beta/x")
    assert r.exit_code == 0 and beta_x.called
    assert json.loads(r.stdout) == {"id": "2"}


@covers("api")
def test_api_post_body_inline_and_file(invoke, graph, tmp_path):
    route = graph.post(f"{GRAPH}/v1.0/me/sendMail").mock(return_value=httpx.Response(202))
    r = invoke(
        "api", "POST", "/me/sendMail", "--body", '{"a": 1}', "--header", "X-Custom:1", "--json"
    )
    assert r.exit_code == 0, r.stderr
    request = route.calls.last.request
    assert json.loads(request.content) == {"a": 1}
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["X-Custom"] == "1"
    body_file = tmp_path / "body.json"
    body_file.write_text('{"a": 2}')
    assert invoke("api", "POST", "/me/sendMail", "--body", f"@{body_file}").exit_code == 0
    assert json.loads(route.calls.last.request.content) == {"a": 2}


@covers("api")
def test_api_all_follows_next_link(invoke, graph):
    mock_graph(graph, "api/paged")
    r = invoke("api", "GET", "/me/messages", "--all", "--json")
    assert r.exit_code == 0, r.stderr
    doc = json.loads(r.stdout)
    assert [item["id"] for item in doc["value"]] == [
        "AAMk-msg-0001",
        "AAMk-msg-0002",
        "AAMk-msg-0003",
    ]
    assert set(doc) == {"value"}


@covers("api")
def test_api_raw_streams_bytes_to_output(invoke, graph, tmp_path):
    graph.get(f"{GRAPH}/v1.0/me/photo/$value").mock(
        return_value=httpx.Response(
            200, content=b"\x89PNG-raw", headers={"content-type": "image/png"}
        )
    )
    dest = tmp_path / "f.bin"
    r = invoke("api", "GET", "/me/photo/$value", "--raw", "--output", str(dest))
    assert r.exit_code == 0, r.stderr
    assert dest.read_bytes() == b"\x89PNG-raw"
    r = invoke("api", "GET", "/me/photo/$value", "--raw")
    assert r.exit_code == 0 and r.stdout_bytes == b"\x89PNG-raw"


@covers("api")
def test_api_non_json_body_printed_as_text(invoke, graph):
    graph.get(f"{GRAPH}/v1.0/me/drive/root:/notes.txt:/content").mock(
        return_value=httpx.Response(200, text="hello\n", headers={"content-type": "text/plain"})
    )
    r = invoke("api", "GET", "/me/drive/root:/notes.txt:/content")
    assert r.exit_code == 0 and r.stdout == "hello\n"


@covers("api")
def test_api_dry_run(invoke, graph):
    r = invoke("api", "POST", "/me/sendMail", "--body", '{"x":1}', "--dry-run", "--json")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout) == {
        "dryRun": True,
        "requests": [
            {
                "method": "POST",
                "url": f"{GRAPH}/v1.0/me/sendMail",
                "headers": {"Content-Type": "application/json"},
                "body": {"x": 1},
            }
        ],
    }
    assert graph.calls.call_count == 0


@covers("api")
@pytest.mark.scopes(["User.Read"])
def test_api_no_scope_gate(invoke, graph):
    route = graph.get(f"{GRAPH}/v1.0/me/messages").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    assert invoke("api", "GET", "/me/messages").exit_code == 0
    assert route.called


@covers("api")
@pytest.mark.parametrize(
    "status,code,exit_code", [(403, "Forbidden", 3), (404, "NotFound", 4), (500, "Internal", 1)]
)
def test_api_error_exit_codes(invoke, graph, status, code, exit_code):
    graph.get(f"{GRAPH}/v1.0/me").mock(return_value=graph_error(status, code))
    r = invoke("api", "GET", "/me")
    assert r.exit_code == exit_code and r.stdout == ""
    assert r.stderr.startswith(f"error[{code}]: boom\n  request-id: req-0001\n")


@covers("api")
def test_api_bad_query_format(invoke, graph):
    r = invoke("api", "GET", "/me", "--query", "nokey")
    assert r.exit_code == 2 and graph.calls.call_count == 0
    assert r.stderr.startswith("error[USAGE]:")
