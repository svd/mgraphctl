"""The server end to end, over the SDK's in-memory transport (MCP spec §4, §5)."""

import base64
import json

import httpx
import pytest
from mcp import Client

from helpers import GRAPH, graph_error, mock_graph
from mgraphctl.mcp import server

# anyio's plugin runs a fixture's setup and teardown in the same task; pytest-asyncio does not,
# and the SDK's cancel scopes require it.
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def settings(tmp_path):
    return server.Settings(
        capabilities=["core", "mail"], output_dir=tmp_path / "out", max_inline_bytes=2000
    )


@pytest.fixture
async def client(app, settings):
    async with Client(server.build(settings, app)) as connected:
        yield connected


def text_of(result):
    return "".join(b.text for b in result.content if b.type == "text")


def links_of(result):
    return [b for b in result.content if b.type == "resource_link"]


async def test_the_tool_list_is_what_the_capabilities_asked_for(client):
    listed = await client.list_tools()
    names = {tool.name for tool in listed.tools}
    assert "mail_list" in names and "me" in names
    assert not any(name.startswith("calendar") for name in names)
    # Read-only by default: no mutating verb is on the wire.
    assert "mail_send" not in names and "mail_delete" not in names


async def test_a_tool_advertises_its_schema_and_annotations(client):
    listed = await client.list_tools()
    tool = next(t for t in listed.tools if t.name == "mail_list")
    assert tool.title == "mail list"
    assert tool.input_schema["properties"]["folder"]["default"] == "inbox"
    assert tool.input_schema["additionalProperties"] is False
    assert tool.annotations.read_only_hint is True


async def test_the_tool_list_is_ordered_the_same_every_time(client):
    first = [t.name for t in (await client.list_tools()).tools]
    second = [t.name for t in (await client.list_tools()).tools]
    assert first == second == sorted(first)


async def test_a_call_reaches_graph_and_comes_back_as_a_text_table(client, graph):
    mock_graph(graph, "mail/list")
    result = await client.call_tool("mail_list", {})
    assert result.is_error is False
    body = text_of(result)
    assert "Sprint review" in body and "AAMk-msg-0001" in body
    assert result.structured_content is None


async def test_json_returns_the_cli_document_as_structured_content(client, graph):
    mock_graph(graph, "mail/list")
    result = await client.call_tool("mail_list", {"output_format": "json"})
    assert result.structured_content["count"] == 2
    assert result.structured_content["items"][0]["id"] == "AAMk-msg-0001"
    assert json.loads(text_of(result)) == result.structured_content


async def test_arguments_reach_the_verb(client, graph):
    """`--unread` shapes the request; `--limit` caps what comes back (`$top` is the page size)."""
    route = graph.get(f"{GRAPH}/v1.0/me/mailFolders/inbox/messages").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "1"}, {"id": "2"}]})
    )
    result = await client.call_tool(
        "mail_list", {"limit": 1, "unread": True, "output_format": "json"}
    )
    assert "isRead" in str(route.calls[0].request.url)
    assert result.structured_content["count"] == 1


async def test_a_flag_whose_python_name_had_to_be_escaped_still_works(client, graph):
    """`--from` is `from_` in Python and `from` on the wire."""
    route = graph.get(f"{GRAPH}/v1.0/me/mailFolders/inbox/messages").mock(
        return_value=httpx.Response(200, json={"value": []})
    )
    await client.call_tool("mail_list", {"from": ["ada@example.com"]})
    assert "ada%40example.com" in str(route.calls[0].request.url)


async def test_output_file_writes_the_result_and_links_it(client, graph, settings):
    mock_graph(graph, "mail/list")
    result = await client.call_tool(
        "mail_list", {"output_format": "json", "output_file": "inbox.json"}
    )
    link = links_of(result)[0]
    assert link.uri.endswith("/inbox.json")
    assert result.structured_content is None
    written = (settings.store().root / "inbox.json").read_text()
    assert json.loads(written)["count"] == 2


async def test_a_written_file_is_readable_as_a_resource(client, graph):
    mock_graph(graph, "mail/list")
    result = await client.call_tool(
        "mail_list", {"output_format": "json", "output_file": "inbox.json"}
    )
    uri = links_of(result)[0].uri
    listed = await client.list_resources()
    assert uri in {str(r.uri) for r in listed.resources}
    read = await client.read_resource(uri)
    assert json.loads(read.contents[0].text)["count"] == 2


async def test_a_file_path_that_escapes_the_output_directory_is_a_tool_error(client, graph):
    mock_graph(graph, "mail/list")
    result = await client.call_tool(
        "mail_list", {"output_format": "json", "output_file": "../escape.json"}
    )
    assert result.is_error is True
    assert "output directory" in text_of(result)


async def test_an_invalid_argument_is_a_tool_error_the_model_can_read(client):
    """The SDK advertises the schema but never applies it; the server validates."""
    result = await client.call_tool("mail_list", {"limit": "loads"})
    assert result.is_error is True
    assert "loads" in text_of(result)


async def test_an_unknown_argument_is_refused(client):
    result = await client.call_tool("mail_list", {"nonsense": 1})
    assert result.is_error is True


async def test_a_graph_failure_comes_back_with_its_hint(client, graph):
    graph.get(f"{GRAPH}/v1.0/me/mailFolders/inbox/messages").mock(
        return_value=graph_error(403, "ErrorAccessDenied")
    )
    result = await client.call_tool("mail_list", {})
    assert result.is_error is True
    assert "error[" in text_of(result)


async def test_an_unknown_tool_is_a_protocol_error(client):
    """Not an `isError` result: a name that was never listed is nothing to self-correct from."""
    from mcp import MCPError

    with pytest.raises(MCPError):
        await client.call_tool("mail_launch_missiles", {})


async def test_a_local_verb_answers_without_touching_graph(client):
    result = await client.call_tool("version", {"output_format": "json"})
    assert result.is_error is False
    assert result.structured_content["version"] and result.structured_content["python"]


async def test_allow_write_puts_the_mutating_verbs_on_the_wire(app, tmp_path):
    settings = server.Settings(capabilities=["mail"], allow_write=True, output_dir=tmp_path / "out")
    async with Client(server.build(settings, app)) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert "mail_send" in names
        send = next(t for t in (await client.list_tools()).tools if t.name == "mail_send")
        assert send.annotations.read_only_hint is False
        assert "dry_run" in send.input_schema["properties"]


async def test_the_server_speaks_the_current_protocol_revision(app, settings):
    import mcp_types.version as version

    assert version.LATEST_PROTOCOL_VERSION == "2026-07-28"
    async with Client(server.build(settings, app)) as client:
        assert (await client.list_tools()).tools


async def test_a_large_result_spills_to_a_file_instead_of_flooding_the_client(client, graph):
    """The point of --max-inline-bytes: one wide fetch must not fill the conversation."""
    many = [{"id": f"id-{i}", "subject": f"Subject {i} " + "x" * 80} for i in range(200)]
    graph.get(f"{GRAPH}/v1.0/me/mailFolders/inbox/messages").mock(
        return_value=httpx.Response(200, json={"value": many})
    )
    result = await client.call_tool("mail_list", {"all": True})
    assert result.is_error is False
    link = links_of(result)[0]
    assert "too large to inline" in text_of(result)
    assert len(text_of(result)) < 2000
    read = await client.read_resource(link.uri)
    assert "Subject 199" in read.contents[0].text


async def test_a_verbs_own_file_lands_in_the_output_directory(client, graph, settings):
    """`me --photo` names a path; it is confined like every other path argument."""
    mock_graph(graph, "top/me_photo")
    result = await client.call_tool("me", {"photo": "avatar.jpg"})
    assert result.is_error is False
    link = links_of(result)[0]
    assert link.uri.endswith("/avatar.jpg")
    assert (settings.store().root / "avatar.jpg").exists()


async def test_a_verbs_own_file_cannot_escape_the_output_directory(client, graph):
    mock_graph(graph, "top/me_photo")
    result = await client.call_tool("me", {"photo": "/tmp/escape.jpg"})
    assert result.is_error is True
    assert "absolute path" in text_of(result)


async def test_dry_run_reaches_a_write_verb(app, tmp_path, graph):
    """A mutating tool can be asked what it would send, exactly as the CLI can."""
    settings = server.Settings(capabilities=["mail"], allow_write=True, output_dir=tmp_path / "out")
    async with Client(server.build(settings, app)) as client:
        result = await client.call_tool(
            "mail_send",
            {"to": ["ada@example.com"], "subject": "Hi", "body": "text", "dry_run": True},
        )
    assert result.is_error is False
    assert "POST" in text_of(result) and "sendMail" in text_of(result)
    assert not graph.calls


async def test_body_file_cannot_read_outside_the_output_directory(app, tmp_path, graph):
    """`--body-file` is typed `str`; unconfined it would be an arbitrary local file read."""
    secret = tmp_path / "id_rsa"
    secret.write_text("PRIVATE KEY MATERIAL")
    settings = server.Settings(capabilities=["mail"], allow_write=True, output_dir=tmp_path / "out")
    async with Client(server.build(settings, app)) as client:
        result = await client.call_tool(
            "mail_send",
            {"to": ["ada@example.com"], "body_file": str(secret), "dry_run": True},
        )
    assert result.is_error is True
    assert "PRIVATE KEY MATERIAL" not in text_of(result)
    assert not graph.calls


async def test_body_file_still_works_inside_the_output_directory(app, tmp_path):
    settings = server.Settings(capabilities=["mail"], allow_write=True, output_dir=tmp_path / "out")
    settings.store().write("body.txt", "the message body")
    async with Client(server.build(settings, app)) as client:
        result = await client.call_tool(
            "mail_send",
            {"to": ["ada@example.com"], "body_file": "body.txt", "dry_run": True},
        )
    assert result.is_error is False
    assert "the message body" in text_of(result)


async def test_an_omitted_destination_lands_in_the_output_directory(
    app, tmp_path, graph, monkeypatch
):
    """`onedrive download` with no --output names the file itself, relative to the working
    directory. The server moves into the store at startup so that default cannot escape it."""
    settings = server.Settings(capabilities=["onedrive"], output_dir=tmp_path / "out")
    monkeypatch.chdir(tmp_path)  # a hostile default would land here
    mock_graph(graph, "onedrive/download")
    graph.get("https://files.contoso.example/blob", params__contains={"tempauth": "abc"}).mock(
        return_value=httpx.Response(200, content=b"Hello Graph!")
    )
    monkeypatch.chdir(server.enter_output_dir(settings.store()))
    async with Client(server.build(settings, app)) as client:
        result = await client.call_tool("onedrive_download", {"ref": "01ABCDEFGHIJKLMNOPQRSTUV"})
    assert result.is_error is False, text_of(result)
    assert (settings.store().root / "report.pdf").read_bytes() == b"Hello Graph!"
    assert not (tmp_path / "report.pdf").exists()
    assert links_of(result)[0].uri.endswith("/report.pdf")


async def test_the_api_body_at_file_form_cannot_read_outside_the_output_directory(
    app, tmp_path, graph
):
    """`api --body @FILE` reads a local file, but `body` is typed `str` and so escapes the
    Path-based confinement unless the `@` form is resolved through the store."""
    secret = tmp_path / "secret.json"
    secret.write_text('{"token": "SECRET-VALUE"}')
    settings = server.Settings(capabilities=["api"], allow_write=True, output_dir=tmp_path / "out")
    async with Client(server.build(settings, app)) as client:
        result = await client.call_tool(
            "api",
            {"method": "POST", "path": "/me/sendMail", "body": f"@{secret}", "dry_run": True},
        )
    assert result.is_error is True
    assert "SECRET-VALUE" not in text_of(result)
    assert not graph.calls


async def test_the_api_body_at_file_form_still_works_inside_the_output_directory(app, tmp_path):
    settings = server.Settings(capabilities=["api"], allow_write=True, output_dir=tmp_path / "out")
    settings.store().write("payload.json", '{"comment": "hello"}')
    async with Client(server.build(settings, app)) as client:
        result = await client.call_tool(
            "api",
            {"method": "POST", "path": "/me/events", "body": "@payload.json", "dry_run": True},
        )
    assert result.is_error is False, text_of(result)
    assert "hello" in text_of(result)


async def test_a_downloaded_binary_reads_back_as_a_blob(app, tmp_path, graph, monkeypatch):
    """`resources/read` on a PNG must not try to decode it as text."""
    settings = server.Settings(capabilities=["onedrive"], output_dir=tmp_path / "out")
    monkeypatch.chdir(server.enter_output_dir(settings.store()))
    mock_graph(graph, "onedrive/download")
    graph.get("https://files.contoso.example/blob", params__contains={"tempauth": "abc"}).mock(
        return_value=httpx.Response(200, content=b"\x89PNG\r\n\x1a\n")
    )
    async with Client(server.build(settings, app)) as client:
        result = await client.call_tool(
            "onedrive_download", {"ref": "01ABCDEFGHIJKLMNOPQRSTUV", "output": "shot.png"}
        )
        read = await client.read_resource(links_of(result)[0].uri)
    contents = read.contents[0]
    assert contents.mime_type == "image/png"
    assert base64.b64decode(contents.blob) == b"\x89PNG\r\n\x1a\n"


async def test_output_format_reaches_a_verb_that_shapes_its_result_by_it(app, tmp_path, graph):
    """`chats messages` keeps Graph's order for JSON and reverses it for the table."""
    settings = server.Settings(capabilities=["chats"], output_dir=tmp_path / "out")
    page = {
        "value": [
            {"id": "2", "body": {"content": "newer"}, "createdDateTime": "2026-09-02T10:00:00Z"},
            {"id": "1", "body": {"content": "older"}, "createdDateTime": "2026-09-01T10:00:00Z"},
        ]
    }
    async with Client(server.build(settings, app)) as client:
        graph.get(f"{GRAPH}/v1.0/chats/19:abc/messages").mock(
            return_value=httpx.Response(200, json=page)
        )
        as_json = await client.call_tool(
            "chats_messages", {"chat": "id:19:abc", "output_format": "json"}
        )
    assert [item["id"] for item in as_json.structured_content["items"]] == ["2", "1"]


async def test_concurrent_local_verbs_do_not_cross_their_output(client):
    """`redirect_stdout` swaps a process-global; interleaved calls would cross or lose output —
    and on stdio transport the stdout one of them could free is the JSON-RPC channel."""
    import asyncio

    results = await asyncio.gather(
        *(client.call_tool("version", {"output_format": "json"}) for _ in range(8))
    )
    for result in results:
        assert result.is_error is False, text_of(result)
        assert result.structured_content["version"]
