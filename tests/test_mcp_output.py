"""What a tool call returns: text, structured content, or a file link (MCP spec §5)."""

import json
from pathlib import Path

import pytest

from mgraphctl import render
from mgraphctl.errors import UsageError
from mgraphctl.mcp import output


@pytest.fixture
def store(tmp_path):
    return output.OutputStore(tmp_path / "out", max_inline_bytes=2000)


def a_list(n=1):
    return render.ListResult(
        items=[{"id": str(i), "subject": f"Subject {i}"} for i in range(n)],
        columns=[render.Column("Id", "id"), render.Column("Subject", "subject")],
    )


def test_the_store_is_created_private(store):
    store.ensure()
    assert store.root.is_dir()
    assert store.root.stat().st_mode & 0o777 == 0o700


def test_a_relative_name_resolves_inside_the_store(store):
    assert store.resolve("run.json") == store.root / "run.json"
    assert store.resolve("nested/run.json") == store.root / "nested" / "run.json"


@pytest.mark.parametrize("name", ["/etc/passwd", "../escape.json", "nested/../../escape.json"])
def test_a_path_that_leaves_the_store_is_refused(store, name):
    """The server writes where the operator configured, never where the caller asks."""
    with pytest.raises(UsageError):
        store.resolve(name)


def test_a_symlink_out_of_the_store_is_refused(store, tmp_path):
    store.ensure()
    (store.root / "escape").symlink_to(tmp_path)
    with pytest.raises(UsageError):
        store.resolve("escape/run.json")


def test_text_is_the_default_and_carries_no_structured_content(store):
    out = output.build(a_list(), store=store, tool_name="mail_list")
    assert out.text == render.to_text(a_list())
    assert out.payload is None and out.link is None


def test_notes_travel_with_the_text(store):
    res = a_list()
    res.truncated = True
    out = output.build(res, store=store, tool_name="mail_list")
    assert out.text.endswith("(more results available — rerun with --all)\n")


def test_json_returns_the_cli_document_as_structured_content(store):
    out = output.build(a_list(2), store=store, tool_name="mail_list", output_format="json")
    assert out.payload == render.to_json(a_list(2))
    # The spec asks for the serialized JSON alongside it, for clients that ignore the field.
    assert json.loads(out.text) == out.payload
    assert out.link is None


def test_output_file_writes_the_result_and_returns_a_link_instead_of_the_payload(store):
    out = output.build(
        a_list(3), store=store, tool_name="mail_list", output_format="json", output_file="run.json"
    )
    assert out.link is not None
    assert json.loads(out.link.path.read_text()) == render.to_json(a_list(3))
    assert out.link.uri == out.link.path.as_uri() and out.link.mime == "application/json"
    assert out.payload is None
    # The summary says what is in the file without repeating it.
    assert "3 items" in out.text and "run.json" in out.text


def test_output_file_honours_the_text_format_too(store):
    out = output.build(a_list(), store=store, tool_name="mail_list", output_file="run.txt")
    assert out.link.mime == "text/plain"
    assert out.link.path.read_text() == render.to_text(a_list())


def test_a_result_past_the_inline_limit_spills_to_a_file_on_its_own(store):
    """A runaway `--all` cannot flood the client, whatever the caller asked for."""
    out = output.build(a_list(200), store=store, tool_name="mail_list")
    assert out.link is not None and out.link.path.exists()
    assert len(out.text) < 2000
    assert "200 items" in out.text
    # The head excerpt is there so the model can see what it got.
    assert "Subject 0" in out.text


def test_a_small_result_does_not_spill(store):
    out = output.build(a_list(1), store=store, tool_name="mail_list")
    assert out.link is None


def test_spilled_names_do_not_collide(store):
    first = output.build(a_list(200), store=store, tool_name="mail_list").link
    second = output.build(a_list(200), store=store, tool_name="mail_list").link
    assert first.path != second.path


def test_a_file_the_verb_itself_wrote_is_returned_as_a_link(store):
    store.ensure()
    target = store.root / "photo.jpg"
    target.write_bytes(b"\xff\xd8\xff")
    res = render.FileResult(path=target, bytes=3, meta={}, message=f"Saved {target}")
    out = output.build(res, store=store, tool_name="me")
    assert out.link.path == target and out.link.mime == "image/jpeg"
    assert out.text == res.message + "\n"


def test_the_store_lists_and_reads_back_what_it_holds(store):
    out = output.build(
        a_list(3), store=store, tool_name="mail_list", output_format="json", output_file="run.json"
    )
    assert store.files() == [out.link.path]
    text, mime = store.read(out.link.uri)
    assert json.loads(text)["count"] == 3 and mime == "application/json"


def test_a_binary_file_reads_back_as_bytes(store):
    """A downloaded image is not text; reading it as text would raise."""
    store.ensure()
    (store.root / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    data, mime = store.read((store.root / "shot.png").as_uri())
    assert data == b"\x89PNG\r\n\x1a\n" and mime == "image/png"
    assert output.is_text("application/json") and output.is_text("text/csv")
    assert not output.is_text("image/png") and not output.is_text("application/pdf")


def test_a_store_reached_through_a_symlink_still_lists_its_files(tmp_path):
    """`--output-dir /tmp/...` on macOS: /tmp is a symlink, so root != root.resolve()."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    store = output.OutputStore(link)
    store.write("run.json", "{}")
    files = store.files()
    assert files and all(f.is_relative_to(store.root.resolve()) for f in files)
    assert output.link_to(store, files[0]).name == "run.json"
    # A verb's own destination is joined to the unresolved root; linking it must still work.
    assert output.link_to(store, store.root / "run.json").name == "run.json"


def test_a_file_uri_naming_another_host_is_refused(store):
    store.ensure()
    (store.root / "a.txt").write_text("x")
    with pytest.raises(UsageError):
        store.read("file://evil.example/" + str(store.root.resolve() / "a.txt").lstrip("/"))


def test_reading_outside_the_store_is_refused(store, tmp_path):
    outsider = tmp_path / "secret.txt"
    outsider.write_text("nope")
    with pytest.raises(UsageError):
        store.read(Path(outsider).as_uri())


def test_the_default_root_follows_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert output.default_root() == tmp_path / "mgraphctl" / "mcp"
    monkeypatch.delenv("XDG_CACHE_HOME")
    assert output.default_root() == Path.home() / ".cache" / "mgraphctl" / "mcp"
