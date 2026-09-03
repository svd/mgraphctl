"""Rendering and datetime helpers (spec §6.2, §6.3)."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mgraphctl import errors, render

TZ = "Europe/Warsaw"


def test_fmt_dt_converts_z_and_offsets_to_tz():
    assert render.fmt_dt("2026-08-31T08:15:00Z", TZ) == "2026-08-31T10:15+02:00"
    assert render.fmt_dt("2026-08-31T08:15:00.1234567Z", TZ) == "2026-08-31T10:15+02:00"
    assert render.fmt_dt("2026-01-10T05:00:00-05:00", TZ) == "2026-01-10T11:00+01:00"
    assert render.fmt_dt(None, TZ) == "N/A"


def test_parse_graph_dt_treats_a_naive_timestamp_as_utc():
    assert render.parse_graph_dt("2026-08-31T08:15:00") == datetime(2026, 8, 31, 8, 15, tzinfo=UTC)
    assert render.parse_graph_dt("2026-08-31T08:15:00.1234567Z") == datetime(
        2026, 8, 31, 8, 15, 0, 123456, tzinfo=UTC
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
        2026, 9, 5, 14, 30, 15, tzinfo=UTC
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
    assert render.to_graph_dtz(datetime(2026, 9, 5, 12, 30, tzinfo=UTC), TZ) == {
        "dateTime": "2026-09-05T14:30:00",
        "timeZone": TZ,
    }
    assert render.to_iso_offset(dt) == "2026-09-05T14:30:00+02:00"
    assert render.kql_date(datetime(2026, 9, 5, 23, 30, tzinfo=UTC), TZ) == "2026-09-06"


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


def test_list_json_envelope_and_notes(capsys):
    res = render.ListResult(
        items=[{"id": "1"}], columns=[render.Column("id", "id")], truncated=True
    )
    render.emit(res, json_mode=True)
    captured = capsys.readouterr()
    assert (
        json.loads(captured.out) == {"items": [{"id": "1"}], "count": 1, "truncated": True}
        and captured.err == ""
    )
    render.emit(res, json_mode=False)
    assert capsys.readouterr().err.strip() == "(more results available — rerun with --all)"
    render.emit(
        render.ListResult(
            items=[{"id": "1"}], columns=[render.Column("id", "id")], truncated=True, hit_cap=200
        ),
        json_mode=False,
    )
    assert capsys.readouterr().err.strip() == "(hit the 200-item cap — narrow the query)"
    render.emit(render.ListResult(items=[], columns=[render.Column("id", "id")]), json_mode=False)
    assert capsys.readouterr().out == "No results.\n"
    render.emit(render.ListResult(items=[], columns=[], extra={"note": "n"}), json_mode=True)
    assert json.loads(capsys.readouterr().out) == {
        "items": [],
        "count": 0,
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
