"""Rendering and datetime helpers (spec §6.2, §6.3)."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from mgraphctl import errors, render
from mgraphctl.http import PageResult, filter_page

TZ = "Europe/Warsaw"


def test_fmt_dt_converts_z_and_offsets_to_tz():
    assert render.fmt_dt("2026-08-31T08:15:00Z", TZ) == "2026-08-31T10:15+02:00"
    assert render.fmt_dt("2026-08-31T08:15:00.1234567Z", TZ) == "2026-08-31T10:15+02:00"
    assert render.fmt_dt("2026-01-10T05:00:00-05:00", TZ) == "2026-01-10T11:00+01:00"
    assert render.fmt_dt(None, TZ) == "N/A"


def test_parse_graph_dt_treats_a_naive_timestamp_as_utc():
    assert render.parse_graph_dt("2026-08-31T08:15:00") == datetime(
        2026, 8, 31, 8, 15, tzinfo=timezone.utc
    )
    assert render.parse_graph_dt("2026-08-31T08:15:00.1234567Z") == datetime(
        2026, 8, 31, 8, 15, 0, 123456, tzinfo=timezone.utc
    )


def test_parse_graph_dt_returns_none_for_empty_and_unparsable():
    assert render.parse_graph_dt(None) is None
    assert render.parse_graph_dt("") is None
    assert render.parse_graph_dt("last Tuesday") is None
    assert render.fmt_dt("last Tuesday", TZ) == "N/A"


def test_fmt_dtz_iana_utc_and_windows():
    assert (
        render.fmt_dtz({"dateTime": "2026-08-31T08:15:00.0000000", "timeZone": "UTC"}, TZ)
        == "2026-08-31T10:15+02:00"
    )
    assert (
        render.fmt_dtz(
            {"dateTime": "2026-08-31T10:15:00.0000000", "timeZone": "Europe/Warsaw"}, "UTC"
        )
        == "2026-08-31T08:15+00:00"
    )
    assert (
        render.fmt_dtz(
            {"dateTime": "2026-08-31T10:15:00.0000000", "timeZone": "Pacific Standard Time"}, TZ
        )
        == "2026-08-31T10:15:00.0000000 (Pacific Standard Time)"
    )
    assert render.fmt_dtz(None, TZ) == "N/A"


def test_fmt_dtz_treats_a_missing_timezone_as_utc():
    """Graph's documented default when no `Prefer: outlook.timezone` was sent."""
    assert (
        render.fmt_dtz({"dateTime": "2026-08-31T08:15:00.0000000"}, TZ) == "2026-08-31T10:15+02:00"
    )
    assert (
        render.fmt_dtz({"dateTime": "2026-08-31T08:15:00.0000000", "timeZone": ""}, TZ)
        == "2026-08-31T10:15+02:00"
    )
    assert (
        render.fmt_dtz({"dateTime": "2026-08-31T08:15:00.0000000", "timeZone": None}, TZ)
        == "2026-08-31T10:15+02:00"
    )


def test_fmt_dtz_still_renders_a_windows_zone_verbatim():
    """That branch is correct: a Windows name is not guessed at, it is shown as it came."""
    assert (
        render.fmt_dtz(
            {"dateTime": "2026-08-31T10:15:00.0000000", "timeZone": "Pacific Standard Time"}, TZ
        )
        == "2026-08-31T10:15:00.0000000 (Pacific Standard Time)"
    )


def test_fmt_event_time_all_day():
    ev = {"isAllDay": True, "start": {"dateTime": "2026-09-03T00:00:00.0000000", "timeZone": "UTC"}}
    assert render.fmt_event_time(ev, "start", TZ) == "2026-09-03 (all day)"


def test_parse_dt_forms(monkeypatch):
    fixed = datetime(2026, 9, 2, 12, 0, tzinfo=ZoneInfo(TZ))
    monkeypatch.setattr(render, "_now", lambda zone: fixed.astimezone(zone))
    assert render.parse_dt("2026-09-05", TZ) == datetime(2026, 9, 5, 0, 0, tzinfo=ZoneInfo(TZ))
    assert render.parse_dt("2026-09-05", TZ, end_of_day=True) == datetime(
        2026, 9, 5, 23, 59, 59, tzinfo=ZoneInfo(TZ)
    )
    assert render.parse_dt("2026-09-05T14:30", TZ) == datetime(
        2026, 9, 5, 14, 30, tzinfo=ZoneInfo(TZ)
    )
    assert render.parse_dt("2026-09-05T14:30:15Z", TZ) == datetime(
        2026, 9, 5, 14, 30, 15, tzinfo=timezone.utc
    )
    assert render.parse_dt("2026-09-05T14:30+02:00", TZ).utcoffset() == timedelta(hours=2)
    assert render.parse_dt("now", TZ) == fixed
    assert render.parse_dt("today", TZ) == fixed.replace(hour=0, minute=0)
    assert render.parse_dt("tomorrow", TZ, end_of_day=True) == datetime(
        2026, 9, 3, 23, 59, 59, tzinfo=ZoneInfo(TZ)
    )
    assert render.parse_dt("yesterday", TZ).day == 1
    assert render.parse_dt("+2d", TZ) == fixed + timedelta(days=2)
    assert render.parse_dt("-30d", TZ) == fixed - timedelta(days=30)
    assert render.parse_dt("+3h", TZ) == fixed + timedelta(hours=3)
    with pytest.raises(errors.UsageError):
        render.parse_dt("next tuesday", TZ)


def test_parse_duration_and_iso():
    assert render.parse_duration("30m") == timedelta(minutes=30)
    assert render.parse_duration("2h") == timedelta(hours=2)
    assert render.parse_duration("1d") == timedelta(days=1)
    assert render.parse_duration("PT30M") == timedelta(minutes=30)
    assert render.parse_duration("PT1H30M") == timedelta(hours=1, minutes=30)
    assert render.iso_duration(timedelta(hours=1, minutes=30)) == "PT1H30M"
    with pytest.raises(errors.UsageError):
        render.parse_duration("2026-09-05T10:00")


def test_to_graph_dtz_and_iso_offset_and_kql_date():
    dt = datetime(2026, 9, 5, 14, 30, tzinfo=ZoneInfo(TZ))
    assert render.to_graph_dtz(dt, TZ) == {"dateTime": "2026-09-05T14:30:00", "timeZone": TZ}
    assert render.to_graph_dtz(datetime(2026, 9, 5, 12, 30, tzinfo=timezone.utc), TZ) == {
        "dateTime": "2026-09-05T14:30:00",
        "timeZone": TZ,
    }
    assert render.to_iso_offset(dt) == "2026-09-05T14:30:00+02:00"
    assert render.kql_date(datetime(2026, 9, 5, 23, 30, tzinfo=timezone.utc), TZ) == "2026-09-06"


def test_fmt_size_and_person():
    assert (
        render.fmt_size(0) == "0 B"
        and render.fmt_size(1536) == "1.5 KB"
        and render.fmt_size(5 * 1024 * 1024) == "5.0 MB"
    )
    assert (
        render.fmt_person({"emailAddress": {"name": "Ada Example", "address": "ada@example.com"}})
        == "Ada Example <ada@example.com>"
    )
    assert render.fmt_person({"emailAddress": {"address": "ada@example.com"}}) == "ada@example.com"
    assert render.fmt_person(None) == ""


def test_list_table_never_truncates_ids(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    long_id = "AAMk" + "x" * 150
    res = render.ListResult(
        items=[{"id": long_id, "s": "hello"}],
        columns=[render.Column("id", "id"), render.Column("subject", "s")],
    )
    render.emit(res, json_mode=False)
    out = capsys.readouterr().out.splitlines()
    assert (
        out[0].split() == ["id", "subject"]
        and long_id in out[1]
        and "hello" in out[1]
        and "\x1b[" not in out[1]
    )


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, "(more results available — rerun with --all)"),
        ({"supports_all": False}, "(more results available — raise --limit)"),
        ({"hit_cap": 200}, "(hit the 200-item cap — narrow the query)"),
    ],
    ids=["no-all-flag-given", "verb-without-all", "all-hit-cap"],
)
def test_list_truncation_note_matches_what_the_verb_supports(capsys, kwargs, expected):
    res = render.ListResult(
        items=[{"id": "1"}], columns=[render.Column("id", "id")], truncated=True, **kwargs
    )
    render.emit(res, json_mode=False)
    assert capsys.readouterr().err.strip() == expected


def test_list_json_envelope_and_notes(capsys):
    res = render.ListResult(
        items=[{"id": "1"}], columns=[render.Column("id", "id")], truncated=True
    )
    render.emit(res, json_mode=True)
    captured = capsys.readouterr()
    assert (
        json.loads(captured.out)
        == {
            "items": [{"id": "1"}],
            "count": 1,
            "fetched": 1,
            "cap": None,
            "truncated": True,
        }
        and captured.err == ""
    )
    render.emit(res, json_mode=False)
    assert capsys.readouterr().err.strip() == "(more results available — rerun with --all)"
    render.emit(render.ListResult(items=[], columns=[render.Column("id", "id")]), json_mode=False)
    assert capsys.readouterr().out == "No results.\n"
    render.emit(render.ListResult(items=[], columns=[], extra={"note": "n"}), json_mode=True)
    assert json.loads(capsys.readouterr().out) == {
        "items": [],
        "count": 0,
        "fetched": 0,
        "cap": None,
        "truncated": False,
        "note": "n",
    }


def test_object_text_write_file_results(capsys, tmp_path):
    render.emit(
        render.ObjectResult(
            obj={"subject": "Hi", "from": {"emailAddress": {"address": "a@example.com"}}},
            fields=[("Subject", "subject"), ("From", lambda o: render.fmt_person(o["from"]))],
            body="Body text",
        ),
        json_mode=False,
    )
    assert capsys.readouterr().out == "Subject : Hi\nFrom    : a@example.com\n\nBody text\n"
    render.emit(render.TextResult(text="plain", json_obj={"text": "plain"}), json_mode=True)
    assert json.loads(capsys.readouterr().out) == {"text": "plain"}
    render.emit(render.WriteResult(obj={"status": "sent"}, message="Sent."), json_mode=False)
    assert capsys.readouterr().out == "Sent.\n"
    render.emit(
        render.FileResult(
            path=tmp_path / "a.png",
            bytes=12,
            meta={"contentType": "image/png"},
            message="Downloaded a.png (12 B) to x",
        ),
        json_mode=True,
    )
    assert json.loads(capsys.readouterr().out) == {
        "path": str(tmp_path / "a.png"),
        "bytes": 12,
        "contentType": "image/png",
    }


def test_truncate_and_dig():
    assert (
        render.truncate("a" * 70) == "a" * 59 + "…"
        and render.truncate("short") == "short"
        and render.truncate(None) == ""
    )
    assert render.dig({"a": {"b": [1]}}, "a.b") == [1] and render.dig({"a": None}, "a.b") is None


def test_local_tz_detection(monkeypatch):
    monkeypatch.setenv("MGRAPHCTL_TZ", "Asia/Tokyo")
    assert render.local_tz() == "Asia/Tokyo"
    monkeypatch.delenv("MGRAPHCTL_TZ")
    monkeypatch.setenv("TZ", "Europe/Paris")
    assert render.local_tz() == "Europe/Paris"
    monkeypatch.setenv("TZ", "Nowhere/City")
    monkeypatch.setattr(render.os, "readlink", lambda p: "/usr/share/zoneinfo/America/New_York")
    assert render.local_tz() == "America/New_York"


def test_windows_table_anchor_entries():
    assert len(render.WINDOWS_TO_IANA) >= 130
    for win, iana in {
        "Pacific Standard Time": "America/Los_Angeles",
        "Eastern Standard Time": "America/New_York",
        "Central European Standard Time": "Europe/Warsaw",
        "W. Europe Standard Time": "Europe/Berlin",
        "GMT Standard Time": "Europe/London",
        "India Standard Time": "Asia/Calcutta",
        "Tokyo Standard Time": "Asia/Tokyo",
        "UTC": "Etc/UTC",
    }.items():  # CLDR canonical ids
        assert render.WINDOWS_TO_IANA[win] == iana
    assert all(render.is_iana(v) for v in render.WINDOWS_TO_IANA.values())


def test_has_time_of_day_recognises_day_boundaries():
    tz = "Europe/Warsaw"
    day_start = render.parse_dt("2026-08-31", tz)
    day_end = render.parse_dt("2026-08-31", tz, end_of_day=True)
    assert render.has_time_of_day(None, tz, end_of_day=False) is False
    assert render.has_time_of_day(day_start, tz, end_of_day=False) is False
    assert render.has_time_of_day(day_end, tz, end_of_day=True) is False
    # A day's end is not a day's start, and vice versa.
    assert render.has_time_of_day(day_end, tz, end_of_day=False) is True
    assert render.has_time_of_day(day_start, tz, end_of_day=True) is True
    assert render.has_time_of_day(render.parse_dt("2026-08-31T14:00", tz), tz, end_of_day=False)
    # The boundary is the one in `tz`, not the one in the value's own offset.
    noon_utc = render.parse_dt("2026-08-31T22:00:00Z", tz)
    assert render.has_time_of_day(noon_utc, tz, end_of_day=False) is False


def test_list_envelope_takes_cap_fetched_and_truncated_from_the_page():
    """The page describes the fetch; `items` may have been filtered or reordered since."""
    page = PageResult(items=[{"id": "1"}, {"id": "2"}], truncated=True, pages=1, cap=2)
    res = render.ListResult(items=[{"id": "1"}], columns=[], page=filter_page(page, lambda i: True))
    assert res.truncated is True and res.cap == 2 and res.fetched == 2


def test_list_envelope_reports_fetched_above_count_after_a_post_filter():
    page = PageResult(items=[{"id": "1"}, {"id": "2"}], truncated=False, pages=1, cap=50)
    kept = filter_page(page, lambda item: item["id"] == "1")
    doc = render.to_json(render.ListResult(items=kept.items, columns=[], page=kept))
    assert doc["count"] == 1 and doc["fetched"] == 2 and doc["cap"] == 50


def test_list_envelope_window_is_present_with_both_bounds_unset():
    doc = render.to_json(render.ListResult(items=[], columns=[], window=render.Window()))
    assert doc["window"] == {"after": None, "before": None}


def test_list_envelope_window_renders_iso_offsets():
    tz = "Europe/Warsaw"
    window = render.Window(
        after=render.parse_dt("2026-08-01", tz),
        before=render.parse_dt("2026-08-31", tz, end_of_day=True),
    )
    doc = render.to_json(render.ListResult(items=[], columns=[], window=window))
    assert doc["window"] == {
        "after": "2026-08-01T00:00:00+02:00",
        "before": "2026-08-31T23:59:59+02:00",
    }


def test_list_envelope_omits_window_and_query_when_the_command_has_none():
    doc = render.to_json(render.ListResult(items=[], columns=[]))
    assert "window" not in doc and "query" not in doc
    assert doc["fetched"] == 0 and doc["cap"] is None


def test_list_envelope_page_overrides_an_explicit_truncated():
    """The page is the authority on the fetch; a filtered `items` cannot talk over it."""
    page = PageResult(items=[{"id": "1"}], truncated=False, pages=1, cap=10)
    res = render.ListResult(items=[], columns=[], page=page, truncated=True)
    assert res.truncated is False


def test_to_text_returns_the_body_emit_writes_to_stdout(capsys):
    """`emit` composes `to_text`; a caller that owns stdout (the MCP server) can take the string."""
    res = render.ListResult(
        items=[{"id": "1", "subject": "Hello"}],
        columns=[render.Column("Id", "id"), render.Column("Subject", "subject")],
    )
    render.emit(res, json_mode=False)
    assert render.to_text(res) == capsys.readouterr().out


def test_to_text_covers_every_result_type(capsys):
    for res in (
        render.ListResult(items=[], columns=[], empty_text="Nothing."),
        render.ObjectResult(obj={"a": "1"}, fields=[("Alpha", "a")], body="body text"),
        render.TextResult(text="plain", json_obj={"k": "v"}),
        render.WriteResult(obj=None, message="Done."),
        render.FileResult(path=Path("/tmp/x"), bytes=3, meta={}, message="Saved."),
    ):
        render.emit(res, json_mode=False)
        assert render.to_text(res) == capsys.readouterr().out


def test_notes_returns_the_truncation_lines_emit_writes_to_stderr(capsys):
    res = render.ListResult(
        items=[{"id": "1"}], columns=[render.Column("Id", "id")], truncated=True
    )
    render.emit(res, json_mode=False)
    assert capsys.readouterr().err.splitlines() == render.notes(res)
    assert render.notes(res) == ["(more results available — rerun with --all)"]


def test_notes_is_empty_when_the_fetch_was_complete():
    assert render.notes(render.ListResult(items=[], columns=[])) == []
    assert render.notes(render.TextResult(text="x", json_obj=None)) == []
