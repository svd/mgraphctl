"""Record/replay fixture transport (spec §5.8)."""

import base64
import json

import httpx
import pytest
import respx

from mgraphctl import config, errors, fixtures
from mgraphctl.http import GraphClient

V1 = "https://graph.microsoft.com/v1.0"


def _client(transport):
    return GraphClient(lambda force: "tok", tz="UTC", transport=transport)


def test_record_then_replay_json_roundtrip(tmp_path):
    with respx.mock:
        respx.get(f"{V1}/me", params__eq={"$select": "id"}).mock(
            return_value=httpx.Response(
                200,
                json={"id": "u1", "displayName": "Ada Example"},
                headers={"Set-Cookie": "session=1"},
            )
        )
        recorder = fixtures.FixtureTransport(tmp_path, record=True, inner=httpx.HTTPTransport())
        with _client(recorder) as c:
            assert c.get("/me", params={"$select": "id"}) == {
                "id": "u1",
                "displayName": "Ada Example",
            }

    path = fixtures.fixture_path(tmp_path, "GET /v1.0/me?$select=id")
    assert path.exists()
    doc = json.loads(path.read_text())
    assert doc["key"] == "GET /v1.0/me?$select=id"
    assert len(doc["responses"]) == 1
    entry = doc["responses"][0]
    assert entry["status"] == 200
    assert entry["body"] == {"id": "u1", "displayName": "Ada Example"}
    assert "authorization" not in entry["headers"]
    assert "set-cookie" not in entry["headers"]
    assert "content-length" not in entry["headers"]

    replayer = fixtures.FixtureTransport(tmp_path, record=False)
    with _client(replayer) as c:
        assert c.get("/me", params={"$select": "id"}) == {
            "id": "u1",
            "displayName": "Ada Example",
        }


def test_record_redacts_credentials_in_a_json_body(tmp_path):
    with respx.mock:
        respx.post(f"{V1}/me/drive/items/i1/createUploadSession").mock(
            return_value=httpx.Response(
                200, json={"uploadUrl": "https://up.example.com/s?tempauth=abc", "id": "s1"}
            )
        )
        recorder = fixtures.FixtureTransport(tmp_path, record=True, inner=httpx.HTTPTransport())
        with _client(recorder) as c:
            live = c.post("/me/drive/items/i1/createUploadSession", json={})
    # The live response still carries the real URL; only what lands on disk is redacted.
    assert live["uploadUrl"] == "https://up.example.com/s?tempauth=abc"

    key = "POST /v1.0/me/drive/items/i1/createUploadSession"
    entry = json.loads(fixtures.fixture_path(tmp_path, key).read_text())["responses"][0]
    assert entry["body"] == {"uploadUrl": "***", "id": "s1"}
    assert "tempauth" not in json.dumps(entry)


def test_replay_binary_download_strips_query_on_unauthenticated_client(tmp_path):
    payload = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
    fixture_dir = tmp_path / "fx"
    with respx.mock:
        respx.get(f"{V1}/me/drive/items/i1/content").mock(
            return_value=httpx.Response(
                302, headers={"Location": "https://files.example.com/blob?tempauth=abc"}
            )
        )
        respx.get("https://files.example.com/blob", params__contains={"tempauth": "abc"}).mock(
            return_value=httpx.Response(200, content=payload, headers={"Content-Type": "image/png"})
        )
        recorder = fixtures.FixtureTransport(fixture_dir, record=True, inner=httpx.HTTPTransport())
        with _client(recorder) as c:
            first = c.download("/me/drive/items/i1/content", tmp_path / "first.png")
    assert first.bytes == len(payload)

    redirect = json.loads(
        fixtures.fixture_path(fixture_dir, "GET /v1.0/me/drive/items/i1/content").read_text()
    )
    assert redirect["responses"][0]["headers"]["location"] == "https://files.example.com/blob"
    blob = json.loads(fixtures.fixture_path(fixture_dir, "GET /blob").read_text())
    assert blob["key"] == "GET /blob"
    assert base64.b64decode(blob["responses"][0]["body_b64"]) == payload

    replayer = fixtures.FixtureTransport(fixture_dir, record=False)
    dest = tmp_path / "second.png"
    with _client(replayer) as c:
        second = c.download("/me/drive/items/i1/content", dest)
    assert dest.read_bytes() == payload
    assert second.bytes == len(payload) and second.content_type == "image/png"


def test_replay_consumes_sequentially_and_exhausts(tmp_path):
    key = "GET /v1.0/me"
    path = fixtures.fixture_path(tmp_path, key)
    path.write_text(
        json.dumps(
            {
                "key": key,
                "responses": [
                    {
                        "status": 200,
                        "headers": {"content-type": "application/json"},
                        "body": {"n": 1},
                    },
                    {
                        "status": 200,
                        "headers": {"content-type": "application/json"},
                        "body": {"n": 2},
                    },
                ],
            }
        )
    )
    with _client(fixtures.FixtureTransport(tmp_path, record=False)) as c:
        assert c.get("/me") == {"n": 1}
        assert c.get("/me") == {"n": 2}
        with pytest.raises(errors.FixtureError) as info:
            c.get("/me")
    assert info.value.code == "FIXTURE_EXHAUSTED" and info.value.exit_code == 1
    assert key in info.value.message


def test_replay_missing_key(tmp_path):
    with (
        _client(fixtures.FixtureTransport(tmp_path, record=False)) as c,
        pytest.raises(errors.FixtureError) as info,
    ):
        c.get("/me")
    assert info.value.code == "FIXTURE_MISSING"
    assert "GET /v1.0/me" in info.value.message
    assert str(fixtures.fixture_path(tmp_path, "GET /v1.0/me")) in info.value.message


@pytest.mark.parametrize("record", [True, False])
def test_token_host_refused(tmp_path, record):
    transport = fixtures.FixtureTransport(tmp_path, record=record, inner=httpx.HTTPTransport())
    request = httpx.Request(
        "POST", f"https://{config.TOKEN_HOST}/common/oauth2/v2.0/token", content=b"grant_type=x"
    )
    with pytest.raises(errors.FixtureError) as info:
        transport.handle_request(request)
    assert info.value.code == "FIXTURE_FORBIDDEN_HOST"
    assert list(tmp_path.iterdir()) == []


def test_transport_from_env(tmp_path, monkeypatch):
    monkeypatch.delenv("MGRAPHCTL_FIXTURE_DIR", raising=False)
    monkeypatch.delenv("MGRAPHCTL_RECORD", raising=False)
    assert fixtures.transport_from_env(config.settings()) is None

    monkeypatch.setenv("MGRAPHCTL_FIXTURE_DIR", str(tmp_path))
    monkeypatch.setenv("MGRAPHCTL_RECORD", "1")
    recording = fixtures.transport_from_env(config.settings())
    assert isinstance(recording, fixtures.FixtureTransport)
    assert recording.record is True and recording.dir == tmp_path

    monkeypatch.delenv("MGRAPHCTL_RECORD")
    assert fixtures.transport_from_env(config.settings()).record is False


def test_fixture_key_forms():
    authed = httpx.Request("GET", f"{V1}/me?$select=id", headers={"Authorization": "Bearer x"})
    assert fixtures.fixture_key(authed) == "GET /v1.0/me?$select=id"
    anonymous = httpx.Request("PUT", "https://upload.example.com/upload?tempauth=abc")
    assert fixtures.fixture_key(anonymous) == "PUT /upload"
