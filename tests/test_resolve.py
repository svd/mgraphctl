"""Generic id-shape detection and unique-name picking (spec §6.6)."""

import pytest

from mgraphctl import resolve
from mgraphctl.errors import AmbiguousError, NotFoundError

GUID = "00000000-0000-0000-0000-00000000000a"
LONG = "A" * 40


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("guid", GUID, True),
        ("guid", "inbox", False),
        ("mail_folder", "inbox", True),
        ("mail_folder", "SentItems", True),
        ("mail_folder", LONG, True),
        ("mail_folder", "A" * 20 + " " + "B" * 25, False),
        ("mail_folder", "Projects", False),
        ("team", GUID, True),
        ("team", "Platform", False),
        ("group", GUID, True),
        ("channel", "19:abc@thread.tacv2", True),
        ("channel", "General", False),
        ("chat", "19:chat-0001@thread.v2", True),
        ("chat", "ada@example.com", False),
        ("user", GUID, True),
        ("user", "ada@example.com", True),
        ("user", "me", True),
        ("user", "Ada Example", False),
        ("site", "https://contoso.sharepoint.com/sites/eng", True),
        ("site", "contoso.sharepoint.com:/sites/eng", True),
        ("site", "contoso.sharepoint.com,1,2", True),
        ("site", "Engineering", False),
        ("drive", "b!abc", True),
        ("drive", "Documents", False),
        ("drive_item", "id:x", True),
        ("drive_item", "01ABCDEFGHIJKLMNOPQRSTUV", True),
        ("drive_item", "Docs/a.txt", False),
        ("onenote", "1-abc!12", True),
        ("onenote", "0-x", True),
        ("onenote", "Meeting notes", False),
        ("planner", "a" * 28, True),
        ("planner", "a" * 27, False),
        ("todo_list", "AQMk" + "z" * 10, True),
        ("todo_list", "AAMk" + "z" * 10, True),
        ("todo_list", LONG, True),
        ("todo_list", "Groceries", False),
        ("calendar", LONG, True),
        ("calendar", "Team calendar", False),
        # `id:` forces the id reading for every kind (spec §6.6 prose).
        ("mail_folder", "id:Projects", True),
        ("team", "id:Platform", True),
        ("user", "id:Ada Example", True),
        ("planner", "id:short", True),
        ("calendar", "id:Team calendar", True),
        ("drive_item", "id:x", True),
    ],
)
def test_looks_like_id(kind, value, expected):
    assert resolve.looks_like_id(value, kind) is expected


def test_unknown_kind_is_a_programming_error():
    with pytest.raises(ValueError, match="unknown id kind"):
        resolve.looks_like_id("x", "bicycle")


def test_split_id_prefix():
    assert resolve.split_id_prefix("id:x") == ("x", True)
    assert resolve.split_id_prefix("Docs/a.txt") == ("Docs/a.txt", False)


def test_pick_unique_returns_the_single_case_insensitive_match():
    candidates = [{"id": "id-1", "displayName": "Eng"}, {"id": "id-2", "displayName": "Design"}]
    assert resolve.pick_unique(candidates, "displayName", "eng", what="team")["id"] == "id-1"
    assert (
        resolve.pick_unique(candidates, lambda c: c["displayName"], "ENG", what="team")["id"]
        == "id-1"
    )


def test_pick_unique_zero_candidates_is_not_found():
    with pytest.raises(NotFoundError) as excinfo:
        resolve.pick_unique([], "displayName", "x", what="team")
    assert excinfo.value.code == "NOT_FOUND" and excinfo.value.exit_code == 4
    assert excinfo.value.message == "team 'x' not found"


def test_pick_unique_two_candidates_is_ambiguous():
    candidates = [{"id": "id-1", "displayName": "Eng"}, {"id": "id-2", "displayName": "eng"}]
    with pytest.raises(AmbiguousError) as excinfo:
        resolve.pick_unique(candidates, "displayName", "eng", what="team")
    assert excinfo.value.code == "AMBIGUOUS" and excinfo.value.exit_code == 2
    assert excinfo.value.candidates == [("id-1", "Eng"), ("id-2", "eng")]
    assert excinfo.value.message == "team 'eng' matches 2 items"
