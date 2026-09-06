"""GraphClient behaviour (spec §5.1–5.4, §5.7) through respx."""

import email.utils
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx

from mgraphctl import __version__, config, errors
from mgraphctl.http import (
    BatchRequest,
    GraphClient,
    PageResult,
    PlannedRequest,
    filter_page,
    plan_to_json,
    plan_to_text,
    with_routing,
)
from mgraphctl.http import timeouts as http_timeouts

V1 = "https://graph.microsoft.com/v1.0"


@pytest.fixture
def client(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(GraphClient, "sleep", staticmethod(sleeps.append))
    tokens = iter(["tok-1", "tok-2", "tok-3"])
    c = GraphClient(lambda force: next(tokens), tz="Europe/Warsaw")
    c.sleeps = sleeps  # type: ignore[attr-defined]
    yield c
    c.close()


@respx.mock
def test_retry_after_seconds_then_success(client):
    route = respx.get(f"{V1}/me").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"id": "1"}),
        ]
    )
    assert client.get("/me") == {"id": "1"}
    assert route.call_count == 2 and client.sleeps == [7]


@respx.mock
def test_retry_backoff_and_max_attempts(client):
    route = respx.get(f"{V1}/me").mock(return_value=httpx.Response(503))
    with pytest.raises(errors.GraphError) as info:
        client.get("/me")
    assert info.value.status == 503 and route.call_count == 5
    assert [int(s) for s in client.sleeps] == [2, 4, 8, 16]
    assert all(s - int(s) < 1 for s in client.sleeps)


@respx.mock
def test_401_refreshes_once_then_retries_once(client):
    route = respx.get(f"{V1}/me").mock(
        return_value=httpx.Response(
            401, json={"error": {"code": "InvalidAuthenticationToken", "message": "x"}}
        )
    )
    with pytest.raises(errors.AuthError) as info:
        client.get("/me")
    assert info.value.code == "UNAUTHORIZED" and route.call_count == 2
    assert [c.request.headers["Authorization"] for c in route.calls] == [
        "Bearer tok-1",
        "Bearer tok-2",
    ]


@respx.mock
def test_paginate_limit_and_truncated(client):
    respx.get(f"{V1}/me/messages", params__eq={"$select": "id", "$top": "25"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [{"id": "1"}, {"id": "2"}],
                "@odata.nextLink": f"{V1}/me/messages?$skiptoken=abc",
            },
        )
    )
    respx.get(f"{V1}/me/messages", params__contains={"$skiptoken": "abc"}).mock(
        return_value=httpx.Response(200, json={"value": [{"id": "3"}]})
    )
    page = client.paginate(
        "/me/messages", params={"$select": "id"}, limit=2, all_=False, cap=500, page_size=25
    )
    assert [i["id"] for i in page.items] == ["1", "2"]
    assert page.truncated is True and page.pages == 1
    page = client.paginate(
        "/me/messages", params={"$select": "id"}, limit=None, all_=True, cap=500, page_size=25
    )
    assert len(page.items) == 3 and page.truncated is False and page.pages == 2
    first = respx.calls[0].request
    assert first.url.query.decode() == "$select=id&$top=25"


@respx.mock
def test_paginate_cap_sets_truncated(client):
    respx.get(f"{V1}/me/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [{"id": "1"}, {"id": "2"}],
                "@odata.nextLink": f"{V1}/me/messages?$skiptoken=abc",
            },
        )
    )
    page = client.paginate("/me/messages", limit=None, all_=True, cap=2, page_size=50)
    assert len(page.items) == 2 and page.truncated is True and page.pages == 1


@respx.mock
def test_paginate_page_size_none_sends_no_top(client):
    route = respx.get(f"{V1}/me/joinedTeams").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "t1"}]})
    )
    page = client.paginate("/me/joinedTeams", limit=None, all_=True, cap=100, page_size=None)
    assert [t["id"] for t in page.items] == ["t1"]
    sent = route.calls[0].request.url
    assert sent.query == b"" and "?" not in str(sent)


def test_paginate_rejects_limit_below_one(client):
    with pytest.raises(errors.UsageError) as info:
        client.paginate("/me/messages", limit=0, all_=False, cap=500, page_size=25)
    assert info.value.code == "USAGE" and info.value.exit_code == 2


@respx.mock
def test_retry_after_http_date(client):
    when = email.utils.format_datetime(
        datetime.now(timezone.utc) + timedelta(seconds=90), usegmt=True
    )
    respx.get(f"{V1}/me").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": when}),
            httpx.Response(200, json={"id": "1"}),
        ]
    )
    assert client.get("/me") == {"id": "1"}
    assert len(client.sleeps) == 1 and 85 < client.sleeps[0] < 95


@respx.mock
def test_retry_after_capped_at_300(client):
    respx.get(f"{V1}/me").mock(
        side_effect=[
            httpx.Response(503, headers={"Retry-After": "900"}),
            httpx.Response(200, json={"id": "1"}),
        ]
    )
    assert client.get("/me") == {"id": "1"}
    assert client.sleeps == [300]


@respx.mock
def test_transport_error_retried_for_get_only(client):
    get_route = respx.get(f"{V1}/me").mock(
        side_effect=[httpx.ConnectError("x"), httpx.Response(200, json={"id": "1"})]
    )
    assert client.get("/me") == {"id": "1"}
    assert get_route.call_count == 2 and len(client.sleeps) == 1

    # A POST that failed after the request may have reached Graph is never replayed.
    post_route = respx.post(f"{V1}/me/sendMail").mock(side_effect=httpx.ReadError("x"))
    with pytest.raises(errors.MsgraphError) as info:
        client.post("/me/sendMail", json={"message": {}}, expect="none")
    assert info.value.code == "NETWORK" and info.value.exit_code == 1
    assert post_route.call_count == 1


@respx.mock
def test_connect_timeout_on_get_is_retried(client):
    route = respx.get(f"{V1}/me").mock(
        side_effect=[httpx.ConnectTimeout("slow"), httpx.Response(200, json={"id": "1"})]
    )
    assert client.get("/me") == {"id": "1"}
    assert route.call_count == 2 and len(client.sleeps) == 1


@respx.mock
def test_read_timeout_on_post_is_not_retried(client):
    route = respx.post(f"{V1}/me/sendMail").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(errors.MsgraphError) as info:
        client.post("/me/sendMail", json={"message": {}}, expect="none")
    assert info.value.code == "NETWORK" and info.value.exit_code == 1
    assert route.call_count == 1 and client.sleeps == []


@respx.mock
def test_connect_timeout_on_post_is_retried(client):
    # Connect-phase failures cannot have reached Graph, so even a write is safe to replay.
    route = respx.post(f"{V1}/me/sendMail").mock(
        side_effect=[httpx.ConnectTimeout("slow"), httpx.Response(202)]
    )
    assert client.post("/me/sendMail", json={"message": {}}, expect="none") is None
    assert route.call_count == 2 and len(client.sleeps) == 1


@respx.mock
def test_prefer_headers_joined(client):
    route = respx.get(f"{V1}/me/messages/m1").mock(
        return_value=httpx.Response(200, json={"id": "m1"})
    )
    client.get("/me/messages/m1", outlook_tz=True, text_body=True)
    assert route.calls[0].request.headers["Prefer"] == (
        'outlook.timezone="Europe/Warsaw", outlook.body-content-type="text"'
    )


@respx.mock
def test_default_headers(client):
    route = respx.get(f"{V1}/me").mock(return_value=httpx.Response(200, json={}))
    client.get("/me")
    headers = route.calls[0].request.headers
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"] == f"mgraphctl/{__version__}"
    assert uuid.UUID(headers["client-request-id"]).version == 4
    assert headers["Authorization"] == "Bearer tok-1"
    assert "Prefer" not in headers


@respx.mock
def test_beta_switch():
    beta = respx.get("https://graph.microsoft.com/beta/me").mock(
        return_value=httpx.Response(200, json={"v": "beta"})
    )
    v1 = respx.get(f"{V1}/me").mock(return_value=httpx.Response(200, json={"v": "v1"}))
    with GraphClient(lambda force: "tok", tz="Europe/Warsaw", beta=True) as c:
        assert c.get("/me") == {"v": "beta"}
        assert c.get("/me", beta=False) == {"v": "v1"}
    assert beta.call_count == 1 and v1.call_count == 1


@respx.mock
def test_absolute_url_used_verbatim(client):
    route = respx.get(f"{V1}/x", params__eq={"y": "1"}).mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    assert client.get(f"{V1}/x?y=1") == {"ok": True}
    assert route.calls[0].request.url.query.decode() == "y=1"


@respx.mock
def test_bearer_refused_for_non_graph_host(client):
    with pytest.raises(errors.UsageError) as info:
        client.get("https://evil.example/me")
    assert info.value.exit_code == 2
    assert "evil.example" in info.value.message
    assert "https://graph.microsoft.com" in info.value.message
    assert respx.calls.call_count == 0


@respx.mock
def test_bearer_refused_for_non_https_graph_host(client):
    with pytest.raises(errors.UsageError) as info:
        client.get("http://graph.microsoft.com/v1.0/me")
    assert info.value.exit_code == 2
    assert respx.calls.call_count == 0


@respx.mock
def test_expect_none_on_empty_body(client):
    respx.post(f"{V1}/me/messages/m1/send").mock(return_value=httpx.Response(202))
    assert client.post("/me/messages/m1/send", expect="none") is None
    respx.get(f"{V1}/me/messages/m1").mock(return_value=httpx.Response(202))
    assert client.get("/me/messages/m1") is None


@respx.mock
def test_batch_chunks_and_reorders(client):
    def responder(request):
        payload = json.loads(request.content)
        out = []
        for sub in reversed(payload["requests"]):  # deliberately out of order
            name = sub["url"].rsplit("/", 1)[-1]
            if name == "m03":
                out.append(
                    {
                        "id": sub["id"],
                        "status": 404,
                        "headers": {"Content-Type": "application/json"},
                        "body": {"error": {"code": "ErrorItemNotFound", "message": "gone"}},
                    }
                )
            else:
                out.append({"id": sub["id"], "status": 200, "headers": {}, "body": {"id": name}})
        return httpx.Response(200, json={"responses": out})

    route = respx.post(f"{V1}/$batch").mock(side_effect=responder)
    requests = [
        BatchRequest(
            id=f"c{i:02d}",
            method="PATCH" if i % 2 == 0 else "GET",
            url=f"/me/messages/m{i:02d}",
            body={"isRead": True} if i % 2 == 0 else None,
        )
        for i in range(1, 26)
    ]
    results = client.batch(requests)

    assert route.call_count == 2
    first = json.loads(route.calls[0].request.content)["requests"]
    second = json.loads(route.calls[1].request.content)["requests"]
    assert [r["id"] for r in first] == [str(i) for i in range(1, 21)]
    assert [r["id"] for r in second] == [str(i) for i in range(1, 6)]
    assert first[1]["headers"]["Content-Type"] == "application/json"
    assert "body" not in first[0] and "headers" not in first[0]

    assert [r.id for r in results] == [f"c{i:02d}" for i in range(1, 26)]
    assert results[0].status == 200 and results[0].body == {"id": "m01"}
    assert results[2].status == 404 and results[2].error is not None
    assert isinstance(results[2].error, errors.GraphError) and results[2].error.exit_code == 4
    assert results[1].error is None


@respx.mock
def test_batch_resubmits_sub_429(client):
    rounds: list[list[dict]] = []

    def responder(request):
        subs = json.loads(request.content)["requests"]
        rounds.append(subs)
        out = []
        for sub in subs:
            if sub["id"] == "2" and len(rounds) == 1:
                out.append(
                    {"id": "2", "status": 429, "headers": {"Retry-After": "1"}, "body": None}
                )
            else:
                out.append(
                    {"id": sub["id"], "status": 200, "headers": {}, "body": {"u": sub["url"]}}
                )
        return httpx.Response(200, json={"responses": out})

    route = respx.post(f"{V1}/$batch").mock(side_effect=responder)
    requests = [BatchRequest(id=f"c{i}", method="GET", url=f"/me/messages/m{i}") for i in range(3)]
    results = client.batch(requests)

    assert route.call_count == 2
    assert [s["id"] for s in rounds[1]] == ["2"]
    assert rounds[1][0]["url"] == "/me/messages/m1"
    assert client.sleeps == [1]
    assert [r.status for r in results] == [200, 200, 200]
    assert results[1].body == {"u": "/me/messages/m1"}


@respx.mock
def test_upload_session_320k_chunks(client, tmp_path):
    src = tmp_path / "big.bin"
    src.write_bytes(b"x" * 700_000)
    respx.post(f"{V1}/me/drive/root:/big.bin:/createUploadSession").mock(
        return_value=httpx.Response(200, json={"uploadUrl": "https://upload.example.com/s1"})
    )
    puts = respx.put("https://upload.example.com/s1").mock(
        side_effect=[
            httpx.Response(202, json={"nextExpectedRanges": ["327680-"]}),
            httpx.Response(202, json={"nextExpectedRanges": ["655360-"]}),
            httpx.Response(201, json={"id": "item-1", "name": "big.bin"}),
        ]
    )
    result = client.upload_session(
        "/me/drive/root:/big.bin:/createUploadSession",
        {"item": {"name": "big.bin"}},
        src,
        chunk_size=327_680,
    )
    assert result == {"id": "item-1", "name": "big.bin"}
    assert [c.request.headers["Content-Range"] for c in puts.calls] == [
        "bytes 0-327679/700000",
        "bytes 327680-655359/700000",
        "bytes 655360-699999/700000",
    ]
    assert [c.request.headers["Content-Length"] for c in puts.calls] == [
        "327680",
        "327680",
        "44640",
    ]
    assert all("authorization" not in c.request.headers for c in puts.calls)


@respx.mock
def test_upload_session_4mb_chunks(client, tmp_path):
    src = tmp_path / "mail.bin"
    src.write_bytes(b"y" * 9_000_000)
    respx.post(f"{V1}/me/messages/m1/attachments/createUploadSession").mock(
        return_value=httpx.Response(200, json={"uploadUrl": "https://upload.example.com/s2"})
    )
    puts = respx.put("https://upload.example.com/s2").mock(
        side_effect=[
            httpx.Response(202, json={}),
            httpx.Response(202, json={}),
            httpx.Response(201, json={"id": "att-1"}),
        ]
    )
    assert client.upload_session(
        "/me/messages/m1/attachments/createUploadSession",
        {"AttachmentItem": {"name": "mail.bin"}},
        src,
        chunk_size=3_932_160,
    ) == {"id": "att-1"}
    assert [c.request.headers["Content-Range"] for c in puts.calls] == [
        "bytes 0-3932159/9000000",
        "bytes 3932160-7864319/9000000",
        "bytes 7864320-8999999/9000000",
    ]


@respx.mock
def test_upload_session_honours_next_expected_ranges(client, tmp_path):
    src = tmp_path / "big.bin"
    src.write_bytes(b"z" * 700_000)
    respx.post(f"{V1}/me/drive/root:/big.bin:/createUploadSession").mock(
        return_value=httpx.Response(200, json={"uploadUrl": "https://upload.example.com/s3"})
    )
    puts = respx.put("https://upload.example.com/s3").mock(
        side_effect=[
            httpx.Response(202, json={"nextExpectedRanges": ["100000-"]}),
            httpx.Response(202, json={}),
            httpx.Response(201, json={"id": "item-2"}),
        ]
    )
    client.upload_session(
        "/me/drive/root:/big.bin:/createUploadSession", {}, src, chunk_size=327_680
    )
    assert [c.request.headers["Content-Range"] for c in puts.calls] == [
        "bytes 0-327679/700000",
        "bytes 100000-427679/700000",
        "bytes 427680-699999/700000",
    ]


@respx.mock
def test_upload_session_404_is_lost(client, tmp_path):
    src = tmp_path / "small.bin"
    src.write_bytes(b"a" * 100)
    respx.post(f"{V1}/me/drive/root:/small.bin:/createUploadSession").mock(
        return_value=httpx.Response(200, json={"uploadUrl": "https://upload.example.com/s4"})
    )
    respx.put("https://upload.example.com/s4").mock(return_value=httpx.Response(404))
    with pytest.raises(errors.MsgraphError) as info:
        client.upload_session(
            "/me/drive/root:/small.bin:/createUploadSession", {}, src, chunk_size=1000
        )
    assert info.value.code == "UPLOAD_SESSION_LOST" and info.value.exit_code == 1


@respx.mock
def test_upload_session_stalled_ranges_is_lost(client, tmp_path):
    src = tmp_path / "big.bin"
    src.write_bytes(b"s" * 700_000)
    respx.post(f"{V1}/me/drive/root:/big.bin:/createUploadSession").mock(
        return_value=httpx.Response(200, json={"uploadUrl": "https://upload.example.com/s7"})
    )
    # The server keeps asking for a range that never advances past the first chunk.
    puts = respx.put("https://upload.example.com/s7").mock(
        return_value=httpx.Response(202, json={"nextExpectedRanges": ["0-"]})
    )
    with pytest.raises(errors.MsgraphError) as info:
        client.upload_session(
            "/me/drive/root:/big.bin:/createUploadSession", {}, src, chunk_size=327_680
        )
    assert info.value.code == "UPLOAD_SESSION_LOST" and info.value.exit_code == 1
    assert puts.call_count == 3


@respx.mock
def test_upload_session_unreadable_range_is_lost(client, tmp_path):
    src = tmp_path / "big.bin"
    src.write_bytes(b"u" * 700_000)
    respx.post(f"{V1}/me/drive/root:/big.bin:/createUploadSession").mock(
        return_value=httpx.Response(200, json={"uploadUrl": "https://upload.example.com/s8"})
    )
    puts = respx.put("https://upload.example.com/s8").mock(
        return_value=httpx.Response(202, json={"nextExpectedRanges": ["not-a-number-"]})
    )
    with pytest.raises(errors.MsgraphError) as info:
        client.upload_session(
            "/me/drive/root:/big.bin:/createUploadSession", {}, src, chunk_size=327_680
        )
    assert info.value.code == "UPLOAD_SESSION_LOST" and info.value.exit_code == 1
    assert puts.call_count == 1


@respx.mock
def test_upload_session_retries_chunk_on_503(client, tmp_path):
    src = tmp_path / "small.bin"
    src.write_bytes(b"b" * 100)
    respx.post(f"{V1}/me/drive/root:/small.bin:/createUploadSession").mock(
        return_value=httpx.Response(200, json={"uploadUrl": "https://upload.example.com/s5"})
    )
    puts = respx.put("https://upload.example.com/s5").mock(
        side_effect=[httpx.Response(503), httpx.Response(201, json={"id": "item-3"})]
    )
    assert client.upload_session(
        "/me/drive/root:/small.bin:/createUploadSession", {}, src, chunk_size=1000
    ) == {"id": "item-3"}
    assert puts.call_count == 2 and len(client.sleeps) == 1
    assert [c.request.headers["Content-Range"] for c in puts.calls] == [
        "bytes 0-99/100",
        "bytes 0-99/100",
    ]


@respx.mock
def test_download_follows_302_without_bearer(client, tmp_path):
    payload = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
    respx.get(f"{V1}/me/drive/items/i1/content").mock(
        return_value=httpx.Response(
            302, headers={"Location": "https://files.example.com/blob?tempauth=abc"}
        )
    )
    blob = respx.get("https://files.example.com/blob", params__contains={"tempauth": "abc"}).mock(
        return_value=httpx.Response(200, content=payload, headers={"Content-Type": "image/png"})
    )
    dest = tmp_path / "i1.png"
    result = client.download("/me/drive/items/i1/content", dest)
    assert "authorization" not in blob.calls[0].request.headers
    assert isinstance(result.path, Path) and result.path == dest
    assert result.bytes == len(payload) and result.content_type == "image/png"
    assert dest.read_bytes() == payload
    assert not dest.with_name(dest.name + ".part").exists()


@respx.mock
def test_download_200_direct_and_creates_parent(client, tmp_path):
    respx.get(f"{V1}/me/drive/items/i2/content").mock(
        return_value=httpx.Response(
            200, content=b"plain bytes", headers={"Content-Type": "text/plain"}
        )
    )
    dest = tmp_path / "new" / "deeper" / "note.txt"
    result = client.download("/me/drive/items/i2/content", dest)
    assert dest.read_bytes() == b"plain bytes"
    assert result.bytes == 11 and result.content_type == "text/plain"


@respx.mock
def test_download_error_status_raises_graph_error(client, tmp_path):
    respx.get(f"{V1}/me/drive/items/gone/content").mock(
        return_value=httpx.Response(
            404, json={"error": {"code": "ErrorItemNotFound", "message": "gone"}}
        )
    )
    dest = tmp_path / "gone.bin"
    with pytest.raises(errors.GraphError) as info:
        client.download("/me/drive/items/gone/content", dest)
    assert info.value.exit_code == 4 and info.value.code == "ErrorItemNotFound"
    assert not dest.exists() and not dest.with_name(dest.name + ".part").exists()


def _hit(hit_id):
    return {"hitId": hit_id, "rank": 1, "summary": "s", "resource": {"id": hit_id}}


@respx.mock
def test_search_pages_on_more_results(client):
    route = respx.post(f"{V1}/search/query").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "hitsContainers": [
                                {
                                    "hits": [_hit("h1"), _hit("h2")],
                                    "total": 3,
                                    "moreResultsAvailable": True,
                                }
                            ]
                        }
                    ]
                },
            ),
            httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "hitsContainers": [
                                {
                                    "hits": [_hit("h3")],
                                    "total": 3,
                                    "moreResultsAvailable": False,
                                }
                            ]
                        }
                    ]
                },
            ),
        ]
    )
    result = client.search(["message"], "q", size=25, limit=50)
    assert [h["hitId"] for h in result.hits] == ["h1", "h2", "h3"]
    assert result.total == 3 and result.more is False
    bodies = [json.loads(c.request.content) for c in route.calls]
    assert bodies[0] == {
        "requests": [
            {"entityTypes": ["message"], "query": {"queryString": "q"}, "from": 0, "size": 25}
        ]
    }
    assert bodies[1]["requests"][0]["from"] == 25


@respx.mock
def test_search_stops_at_limit(client):
    route = respx.post(f"{V1}/search/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "hitsContainers": [
                            {
                                "hits": [_hit(f"h{i}") for i in range(25)],
                                "total": 400,
                                "moreResultsAvailable": True,
                            }
                        ]
                    }
                ]
            },
        )
    )
    result = client.search(["chatMessage"], "q", size=25, limit=25)
    assert route.call_count == 1 and len(result.hits) == 25
    assert result.total == 400 and result.more is True


@respx.mock
def test_execute_json_string_and_file_bodies(tmp_path):
    # Four API calls, so this test brings its own never-exhausting token provider.
    client = GraphClient(lambda force: "tok", tz="Europe/Warsaw")
    send = respx.post(f"{V1}/me/sendMail").mock(return_value=httpx.Response(202))
    patch = respx.patch(f"{V1}/me/messages/m1").mock(
        return_value=httpx.Response(200, json={"id": "m1"})
    )
    put = respx.put(f"{V1}/me/messages/m1/attach").mock(
        return_value=httpx.Response(201, json={"id": "a1"})
    )
    create = respx.post(f"{V1}/me/drive/root:/f.bin:/createUploadSession").mock(
        return_value=httpx.Response(200, json={"uploadUrl": "https://upload.example.com/s6"})
    )
    chunks = respx.put("https://upload.example.com/s6").mock(
        return_value=httpx.Response(201, json={"id": "d1"})
    )

    assert (
        client.execute(
            PlannedRequest(
                "POST",
                f"{V1}/me/sendMail",
                {"Content-Type": "application/json"},
                {"a": 1},
                expect="none",
            )
        )
        is None
    )
    assert json.loads(send.calls[0].request.content) == {"a": 1}
    assert send.calls[0].request.headers["Content-Type"] == "application/json"

    client.execute(
        PlannedRequest("PATCH", f"{V1}/me/messages/m1", {"Content-Type": "text/html"}, "<p>hi</p>")
    )
    assert patch.calls[0].request.content == b"<p>hi</p>"
    assert patch.calls[0].request.headers["Content-Type"] == "text/html"

    blob = tmp_path / "a.txt"
    blob.write_bytes(b"file-bytes")
    client.execute(
        PlannedRequest(
            "PUT",
            f"{V1}/me/messages/m1/attach",
            {"Content-Type": "application/octet-stream"},
            None,
            file=blob,
        )
    )
    assert put.calls[0].request.content == b"file-bytes"

    src = tmp_path / "f.bin"
    src.write_bytes(b"c" * 10)
    out = client.execute(
        PlannedRequest(
            "POST",
            f"{V1}/me/drive/root:/f.bin:/createUploadSession",
            {"Content-Type": "application/json"},
            {"item": {"name": "f.bin"}},
            file=src,
            chunk_size=1000,
        )
    )
    assert out == {"id": "d1"} and create.call_count == 1 and chunks.call_count == 1
    client.close()


def test_plan_to_json_and_text(tmp_path):
    blob = tmp_path / "notes.txt"
    blob.write_bytes(b"hello")
    plan = [
        PlannedRequest(
            "POST",
            f"{V1}/me/sendMail",
            {"Content-Type": "application/json"},
            {"message": {"subject": "Hi"}},
        ),
        PlannedRequest(
            "PUT",
            f"{V1}/me/messages/{{draftId}}/attach",
            {"Content-Type": "text/plain"},
            None,
            note="uses the draft id from step 1",
            file=blob,
        ),
        PlannedRequest(
            "POST",
            f"{V1}/me/drive/root:/notes.txt:/createUploadSession",
            {"Content-Type": "application/json"},
            {"item": {"name": "notes.txt"}},
            file=blob,
            chunk_size=327_680,
        ),
    ]
    doc = plan_to_json(plan)
    assert doc[0] == {
        "method": "POST",
        "url": f"{V1}/me/sendMail",
        "headers": {"Content-Type": "application/json"},
        "body": {"message": {"subject": "Hi"}},
    }
    file_body = {"$file": str(blob), "bytes": 5, "contentType": "text/plain"}
    assert doc[1]["body"] == file_body
    assert doc[1]["note"] == "uses the draft id from step 1"
    assert "note" not in doc[0]
    assert doc[2]["body"] == {
        "createUploadSession": {"item": {"name": "notes.txt"}},
        "upload": file_body,
        "chunkSize": 327_680,
    }

    text = plan_to_text(plan)
    assert text.startswith(
        "DRY RUN — nothing sent\n"
        "1. POST https://graph.microsoft.com/v1.0/me/sendMail\n"
        "   Content-Type: application/json\n"
        "   {"
    )
    assert '\n     "message": {' in text
    assert "\n2. PUT https://graph.microsoft.com/v1.0/me/messages/{draftId}/attach\n" in text


@respx.mock
def test_debug_log_redacts(caplog, monkeypatch):
    monkeypatch.setattr(GraphClient, "sleep", staticmethod(lambda _: None))
    respx.get(f"{V1}/me").mock(
        return_value=httpx.Response(
            200,
            content=(
                b'{"access_token": "s3cr3t-value",'
                b' "uploadUrl": "https://up.example.com/s?tempauth=t0ken", "id": "1"}'
            ),
            headers={"Content-Type": "application/json", "request-id": "req-0001"},
        )
    )
    with (
        caplog.at_level(logging.DEBUG, logger="mgraphctl.http"),
        GraphClient(lambda force: "tok-1", tz="Europe/Warsaw", debug=2) as c,
    ):
        c.get("/me")
    assert re.search(
        r"GET https://graph\.microsoft\.com/v1\.0/me -> 200 \d+ms \[attempt 1\]", caplog.text
    )
    body_lines = [m for m in caplog.messages if "access_token" in m]
    assert body_lines and '"access_token": "***"' in body_lines[0]
    # An upload session's uploadUrl carries its bearer in the query string (spec §5.4); the
    # path stays so a recorded session remains replayable.
    assert '"uploadUrl": "https://up.example.com/s?<redacted>"' in body_lines[0]
    assert "s3cr3t-value" not in caplog.text and "t0ken" not in caplog.text
    assert "Authorization" not in caplog.text and "tok-1" not in caplog.text


def test_filter_page_preserves_what_the_fetch_reported():
    page = PageResult(items=[{"id": "a"}, {"id": "b"}, {"id": "c"}], truncated=True, pages=2)
    assert page.fetched_count == 3
    kept = filter_page(page, lambda item: item["id"] != "b")
    assert [i["id"] for i in kept.items] == ["a", "c"]
    assert kept.truncated is True and kept.pages == 2 and kept.fetched_count == 3


def test_filter_page_returns_the_page_itself_when_nothing_is_dropped():
    page = PageResult(items=[{"id": "a"}], truncated=False, pages=1)
    assert filter_page(page, lambda item: True) is page


def test_filter_page_chains_keep_the_original_fetch_count():
    page = PageResult(items=[{"n": 1}, {"n": 2}, {"n": 3}], truncated=False, pages=1)
    once = filter_page(page, lambda item: item["n"] > 1)
    twice = filter_page(once, lambda item: item["n"] > 2)
    assert twice.fetched_count == 3 and len(twice.items) == 1


def _page(client, items, *, next_link=False, **kw):
    """One mocked page of `items`, fetched through `paginate` with `kw`."""
    url = f"{V1}/me/things"
    payload = {"value": items}
    if next_link:
        payload["@odata.nextLink"] = f"{url}?$skiptoken=more"
    respx.get(url__startswith=url).mock(return_value=httpx.Response(200, json=payload))
    return client.paginate("/me/things", page_size=None, cap=500, **kw)


@respx.mock
def test_paginate_stop_ends_the_fetch_without_calling_it_truncated(client):
    """Everything ahead of the boundary fits, so the tail past it is not a truncation."""
    items = [{"n": n} for n in range(50)]
    page = _page(client, items, next_link=True, limit=20, all_=False, stop=lambda i: i["n"] >= 5)
    assert page.truncated is False
    assert [i["n"] for i in page.items] == list(range(20))


@respx.mock
def test_paginate_stop_still_reports_the_cap_that_cut_real_results(client):
    """The boundary sits past the bound, so results the caller asked for were left behind."""
    items = [{"n": n} for n in range(50)]
    page = _page(client, items, next_link=True, limit=20, all_=False, stop=lambda i: i["n"] >= 30)
    assert page.truncated is True


@respx.mock
def test_paginate_stop_at_exactly_the_bound_is_not_truncated(client):
    items = [{"n": n} for n in range(50)]
    page = _page(client, items, next_link=True, limit=20, all_=False, stop=lambda i: i["n"] >= 20)
    assert page.truncated is False


@respx.mock
def test_paginate_without_stop_still_truncates_on_the_bound(client):
    items = [{"n": n} for n in range(5)]
    page = _page(client, items, next_link=True, limit=3, all_=False)
    assert page.truncated is True and len(page.items) == 3


def test_with_routing_fills_a_null_id_but_keeps_a_real_one():
    """Graph sends `chatId: null` on a channel message, which is exactly what to fill in."""
    page = PageResult(
        items=[{"id": "a", "chatId": None}, {"id": "b"}, {"id": "c", "chatId": "19:real"}],
        truncated=True,
        pages=2,
        cap=50,
        fetched=9,
        query={"$top": "50"},
    )
    stamped = with_routing(page, chatId="19:here")
    assert [i.get("chatId") for i in stamped.items] == ["19:here", "19:here", "19:real"]
    # Stamping ids is not a fetch, so everything the fetch reported survives it.
    assert stamped.truncated is True and stamped.pages == 2
    assert stamped.cap == 50 and stamped.fetched == 9 and stamped.query == {"$top": "50"}


@respx.mock
def test_retries_zero_disables_retrying(monkeypatch):
    """`MGRAPHCTL_RETRIES=0` means one attempt: the error surfaces immediately."""
    monkeypatch.setattr(GraphClient, "sleep", staticmethod(lambda _s: None))
    client = GraphClient(lambda force: "tok", tz="UTC", retries=0)
    route = respx.get(f"{V1}/me").mock(return_value=httpx.Response(503))
    with pytest.raises(errors.GraphError):
        client.get("/me")
    assert route.call_count == 1
    client.close()


@respx.mock
def test_retries_zero_still_refreshes_a_token_once():
    """The 401 refresh is not part of the retry budget: it is one re-auth, not a retry."""
    tokens = iter(["tok-1", "tok-2"])
    client = GraphClient(lambda force: next(tokens), tz="UTC", retries=0)
    route = respx.get(f"{V1}/me").mock(
        return_value=httpx.Response(
            401, json={"error": {"code": "InvalidAuthenticationToken", "message": "x"}}
        )
    )
    with pytest.raises(errors.AuthError):
        client.get("/me")
    assert route.call_count == 2
    client.close()


@respx.mock
def test_retries_zero_disables_the_batch_429_retry(monkeypatch):
    monkeypatch.setattr(GraphClient, "sleep", staticmethod(lambda _s: None))
    client = GraphClient(lambda force: "tok", tz="UTC", retries=0)
    route = respx.post(f"{V1}/$batch").mock(
        return_value=httpx.Response(
            200, json={"responses": [{"id": "1", "status": 429, "headers": {}, "body": {}}]}
        )
    )
    results = client.batch([BatchRequest(id="a", method="GET", url="/me")])
    assert route.call_count == 1
    assert results[0].status == 429 and results[0].error is not None
    client.close()


@respx.mock
def test_retry_base_ms_scales_the_backoff_and_its_jitter():
    sleeps: list[float] = []
    client = GraphClient(lambda force: "tok", tz="UTC", retry_base_ms=10)
    client.sleep = sleeps.append  # type: ignore[method-assign]
    respx.get(f"{V1}/me").mock(return_value=httpx.Response(503))
    with pytest.raises(errors.GraphError):
        client.get("/me")
    # Base 10 ms: 20, 40, 80, 160 ms, each with at most 10 ms of jitter on top.
    assert [round(s, 3) for s in sleeps] == pytest.approx([0.02, 0.04, 0.08, 0.16], abs=0.011)
    client.close()


def test_timeouts_scale_the_long_profile_off_the_configured_base():
    normal, long = http_timeouts(30_000)
    assert normal.read == 30.0 and normal.write == 30.0
    assert long.read == 30.0 * config.LONG_TIMEOUT_FACTOR
    # The connect budget is not part of the configured read/write budget.
    assert normal.connect == config.CONNECT_TIMEOUT and long.connect == config.CONNECT_TIMEOUT


@respx.mock
def test_timeout_ms_reaches_both_clients():
    client = GraphClient(lambda force: "tok", tz="UTC", timeout_ms=7_000)
    assert client.long_timeout.read == 7.0 * config.LONG_TIMEOUT_FACTOR
    client.close()
