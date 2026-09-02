"""Result rendering, datetime helpers and the Windows→IANA timezone table.

Spec §6.2, §6.3, §7.3.
"""

from __future__ import annotations

import functools
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rich.console import Console
from rich.table import Table

from mgraphctl import errors

# CLDR windowsZones.xml territory="001" mappings, generated 2026-09-02; regenerate with the
# script in the plan.
WINDOWS_TO_IANA: dict[str, str] = {
    "AUS Central Standard Time": "Australia/Darwin",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "Afghanistan Standard Time": "Asia/Kabul",
    "Alaskan Standard Time": "America/Anchorage",
    "Aleutian Standard Time": "America/Adak",
    "Altai Standard Time": "Asia/Barnaul",
    "Arab Standard Time": "Asia/Riyadh",
    "Arabian Standard Time": "Asia/Dubai",
    "Arabic Standard Time": "Asia/Baghdad",
    "Argentina Standard Time": "America/Buenos_Aires",
    "Astrakhan Standard Time": "Europe/Astrakhan",
    "Atlantic Standard Time": "America/Halifax",
    "Aus Central W. Standard Time": "Australia/Eucla",
    "Azerbaijan Standard Time": "Asia/Baku",
    "Azores Standard Time": "Atlantic/Azores",
    "Bahia Standard Time": "America/Bahia",
    "Bangladesh Standard Time": "Asia/Dhaka",
    "Belarus Standard Time": "Europe/Minsk",
    "Bougainville Standard Time": "Pacific/Bougainville",
    "Canada Central Standard Time": "America/Regina",
    "Cape Verde Standard Time": "Atlantic/Cape_Verde",
    "Caucasus Standard Time": "Asia/Yerevan",
    "Cen. Australia Standard Time": "Australia/Adelaide",
    "Central America Standard Time": "America/Guatemala",
    "Central Asia Standard Time": "Asia/Bishkek",
    "Central Brazilian Standard Time": "America/Cuiaba",
    "Central Europe Standard Time": "Europe/Budapest",
    "Central European Standard Time": "Europe/Warsaw",
    "Central Pacific Standard Time": "Pacific/Guadalcanal",
    "Central Standard Time": "America/Chicago",
    "Central Standard Time (Mexico)": "America/Mexico_City",
    "Chatham Islands Standard Time": "Pacific/Chatham",
    "China Standard Time": "Asia/Shanghai",
    "Cuba Standard Time": "America/Havana",
    "Dateline Standard Time": "Etc/GMT+12",
    "E. Africa Standard Time": "Africa/Nairobi",
    "E. Australia Standard Time": "Australia/Brisbane",
    "E. Europe Standard Time": "Europe/Chisinau",
    "E. South America Standard Time": "America/Sao_Paulo",
    "Easter Island Standard Time": "Pacific/Easter",
    "Eastern Standard Time": "America/New_York",
    "Eastern Standard Time (Mexico)": "America/Cancun",
    "Egypt Standard Time": "Africa/Cairo",
    "Ekaterinburg Standard Time": "Asia/Yekaterinburg",
    "FLE Standard Time": "Europe/Kiev",
    "Fiji Standard Time": "Pacific/Fiji",
    "GMT Standard Time": "Europe/London",
    "GTB Standard Time": "Europe/Bucharest",
    "Georgian Standard Time": "Asia/Tbilisi",
    "Greenland Standard Time": "America/Godthab",
    "Greenwich Standard Time": "Atlantic/Reykjavik",
    "Haiti Standard Time": "America/Port-au-Prince",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "India Standard Time": "Asia/Calcutta",
    "Iran Standard Time": "Asia/Tehran",
    "Israel Standard Time": "Asia/Jerusalem",
    "Jordan Standard Time": "Asia/Amman",
    "Kaliningrad Standard Time": "Europe/Kaliningrad",
    "Korea Standard Time": "Asia/Seoul",
    "Libya Standard Time": "Africa/Tripoli",
    "Line Islands Standard Time": "Pacific/Kiritimati",
    "Lord Howe Standard Time": "Australia/Lord_Howe",
    "Magadan Standard Time": "Asia/Magadan",
    "Magallanes Standard Time": "America/Punta_Arenas",
    "Marquesas Standard Time": "Pacific/Marquesas",
    "Mauritius Standard Time": "Indian/Mauritius",
    "Middle East Standard Time": "Asia/Beirut",
    "Montevideo Standard Time": "America/Montevideo",
    "Morocco Standard Time": "Africa/Casablanca",
    "Mountain Standard Time": "America/Denver",
    "Mountain Standard Time (Mexico)": "America/Mazatlan",
    "Myanmar Standard Time": "Asia/Rangoon",
    "N. Central Asia Standard Time": "Asia/Novosibirsk",
    "Namibia Standard Time": "Africa/Windhoek",
    "Nepal Standard Time": "Asia/Katmandu",
    "New Zealand Standard Time": "Pacific/Auckland",
    "Newfoundland Standard Time": "America/St_Johns",
    "Norfolk Standard Time": "Pacific/Norfolk",
    "North Asia East Standard Time": "Asia/Irkutsk",
    "North Asia Standard Time": "Asia/Krasnoyarsk",
    "North Korea Standard Time": "Asia/Pyongyang",
    "Omsk Standard Time": "Asia/Omsk",
    "Pacific SA Standard Time": "America/Santiago",
    "Pacific Standard Time": "America/Los_Angeles",
    "Pacific Standard Time (Mexico)": "America/Tijuana",
    "Pakistan Standard Time": "Asia/Karachi",
    "Paraguay Standard Time": "America/Asuncion",
    "Qyzylorda Standard Time": "Asia/Qyzylorda",
    "Romance Standard Time": "Europe/Paris",
    "Russia Time Zone 10": "Asia/Srednekolymsk",
    "Russia Time Zone 11": "Asia/Kamchatka",
    "Russia Time Zone 3": "Europe/Samara",
    "Russian Standard Time": "Europe/Moscow",
    "SA Eastern Standard Time": "America/Cayenne",
    "SA Pacific Standard Time": "America/Bogota",
    "SA Western Standard Time": "America/La_Paz",
    "SE Asia Standard Time": "Asia/Bangkok",
    "Saint Pierre Standard Time": "America/Miquelon",
    "Sakhalin Standard Time": "Asia/Sakhalin",
    "Samoa Standard Time": "Pacific/Apia",
    "Sao Tome Standard Time": "Africa/Sao_Tome",
    "Saratov Standard Time": "Europe/Saratov",
    "Singapore Standard Time": "Asia/Singapore",
    "South Africa Standard Time": "Africa/Johannesburg",
    "South Sudan Standard Time": "Africa/Juba",
    "Sri Lanka Standard Time": "Asia/Colombo",
    "Sudan Standard Time": "Africa/Khartoum",
    "Syria Standard Time": "Asia/Damascus",
    "Taipei Standard Time": "Asia/Taipei",
    "Tasmania Standard Time": "Australia/Hobart",
    "Tocantins Standard Time": "America/Araguaina",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Tomsk Standard Time": "Asia/Tomsk",
    "Tonga Standard Time": "Pacific/Tongatapu",
    "Transbaikal Standard Time": "Asia/Chita",
    "Turkey Standard Time": "Europe/Istanbul",
    "Turks And Caicos Standard Time": "America/Grand_Turk",
    "US Eastern Standard Time": "America/Indianapolis",
    "US Mountain Standard Time": "America/Phoenix",
    "UTC": "Etc/UTC",
    "UTC+12": "Etc/GMT-12",
    "UTC+13": "Etc/GMT-13",
    "UTC-02": "Etc/GMT+2",
    "UTC-08": "Etc/GMT+8",
    "UTC-09": "Etc/GMT+9",
    "UTC-11": "Etc/GMT+11",
    "Ulaanbaatar Standard Time": "Asia/Ulaanbaatar",
    "Venezuela Standard Time": "America/Caracas",
    "Vladivostok Standard Time": "Asia/Vladivostok",
    "Volgograd Standard Time": "Europe/Volgograd",
    "W. Australia Standard Time": "Australia/Perth",
    "W. Central Africa Standard Time": "Africa/Lagos",
    "W. Europe Standard Time": "Europe/Berlin",
    "W. Mongolia Standard Time": "Asia/Hovd",
    "West Asia Standard Time": "Asia/Tashkent",
    "West Bank Standard Time": "Asia/Hebron",
    "West Pacific Standard Time": "Pacific/Port_Moresby",
    "Yakutsk Standard Time": "Asia/Yakutsk",
    "Yukon Standard Time": "America/Whitehorse",
}


@dataclass
class Column:
    header: str
    path: str | Callable[[dict], Any]
    width: int | None = None


@dataclass
class ListResult:
    items: list[dict]
    columns: list[Column]
    truncated: bool = False
    empty_text: str = "No results."
    hit_cap: int | None = None
    extra: dict | None = None


@dataclass
class ObjectResult:
    obj: dict
    fields: list[tuple[str, str | Callable[[dict], Any]]]
    body: str | None = None


@dataclass
class TextResult:
    text: str
    json_obj: Any


@dataclass
class WriteResult:
    obj: dict | None
    message: str


@dataclass
class DryRunResult:
    # `plan` is `mgraphctl.http.Plan` (list[PlannedRequest]); not imported at module level so
    # this module can be implemented and tested in parallel with T3's http.py.
    plan: Any


@dataclass
class FileResult:
    path: Path
    bytes: int
    meta: dict
    message: str


Result = ListResult | ObjectResult | TextResult | WriteResult | DryRunResult | FileResult

_FRACTIONAL_RE = re.compile(r"(\.\d{6})\d+")
_RELATIVE_RE = re.compile(r"^([+-])(\d+)([dh])$")
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SIMPLE_DURATION_RE = re.compile(r"^(\d+)([mhd])$")
_ISO_TIME_DURATION_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")
_ISO_DAY_DURATION_RE = re.compile(r"^P(\d+)D$")

_tz_fallback_warned = False


def note(text: str) -> None:
    """Write a diagnostic line to stderr (pagination notes, warnings)."""
    sys.stderr.write(text + "\n")


def dig(obj: Any, path: str) -> Any:
    """Dotted-path lookup into nested dicts, returning None on any missing/None segment."""
    current = obj
    for part in path.split("."):
        if current is None:
            return None
        current = current.get(part) if isinstance(current, dict) else getattr(current, part, None)
    return current


def truncate(text: str | None, n: int = 60) -> str:
    """Cap free text at `n` characters, appending an ellipsis when it was longer."""
    if text is None:
        return ""
    if len(text) > n:
        return text[: n - 1] + "…"
    return text


@functools.cache
def is_iana(name: str) -> bool:
    """Whether `name` is a resolvable IANA zone key."""
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError, IsADirectoryError):
        return False


def local_tz() -> str:
    """Detect the local IANA timezone (spec §6.3), warning once on the UTC fallback."""
    global _tz_fallback_warned
    env = os.environ
    for candidate in (env.get("MGRAPHCTL_TZ"), env.get("TZ")):
        if candidate and is_iana(candidate):
            return candidate
    try:
        link = os.readlink("/etc/localtime")
    except OSError:
        link = None
    if link:
        marker = "zoneinfo/"
        idx = link.rfind(marker)
        if idx != -1:
            candidate = link[idx + len(marker) :]
            if is_iana(candidate):
                return candidate
    if sys.platform == "win32":
        candidate = WINDOWS_TO_IANA.get(time.tzname[0])
        if candidate:
            return candidate
    if not _tz_fallback_warned:
        note("warning: could not detect the local time zone; using UTC (set MGRAPHCTL_TZ)")
        _tz_fallback_warned = True
    return "UTC"


def fmt_dt(value: str | None, tz: str) -> str:
    """Render an ISO datetime string (`Z` or offset) in `tz`, or "N/A" for None."""
    if value is None:
        return "N/A"
    v = _FRACTIONAL_RE.sub(r"\1", value)
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    return dt.astimezone(ZoneInfo(tz)).isoformat(timespec="minutes")


def fmt_dtz(obj: dict | None, tz: str) -> str:
    """Render a Graph `dateTimeTimeZone` object in `tz`, or verbatim for a Windows zone name."""
    if obj is None:
        return "N/A"
    date_time = obj.get("dateTime")
    zone = obj.get("timeZone")
    if date_time is None:
        return "N/A"
    if zone == "UTC" or (zone and is_iana(zone)):
        v = _FRACTIONAL_RE.sub(r"\1", date_time)
        dt = datetime.fromisoformat(v).replace(tzinfo=ZoneInfo(zone))
        return dt.astimezone(ZoneInfo(tz)).isoformat(timespec="minutes")
    return f"{date_time} ({zone})"


def fmt_event_time(event: dict, key: str, tz: str) -> str:
    """Render an event's start/end: all-day events as `YYYY-MM-DD (all day)`."""
    if event.get("isAllDay"):
        return f"{event[key]['dateTime'][:10]} (all day)"
    return fmt_dtz(event[key], tz)


def fmt_date(value: str | None) -> str:
    """Render a date-only value: the `YYYY-MM-DD` prefix of a date or datetime string, or "N/A"."""
    if not value:
        return "N/A"
    return value[:10]


def fmt_size(n: int | None) -> str:
    """Render a byte count as `B`/`KB`/`MB`/`GB` with one decimal above bytes."""
    if n is None:
        return ""
    if n < 1024:
        return f"{n} B"
    value = float(n)
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} GB"


def fmt_person(obj: dict | None) -> str:
    """Render a Graph recipient/organizer object as `Name <address>`, address alone, or ""."""
    if not obj:
        return ""
    email = obj.get("emailAddress") or {}
    name = email.get("name")
    address = email.get("address")
    if name and address:
        return f"{name} <{address}>"
    return address or ""


def _now(zone: ZoneInfo) -> datetime:  # patched by tests
    return datetime.now(zone)


def _day(d: date, zone: ZoneInfo, end_of_day: bool) -> datetime:
    if end_of_day:
        return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=zone)
    return datetime(d.year, d.month, d.day, 0, 0, tzinfo=zone)


def parse_dt(value: str, tz: str, *, end_of_day: bool = False) -> datetime:
    """Parse a datetime option value (spec §6.3): ISO forms, keywords, or `±Nd`/`±Nh`."""
    zone = ZoneInfo(tz)
    v = value.strip()
    lowered = v.lower()
    if lowered == "now":
        return _now(zone)
    if lowered in ("today", "tomorrow", "yesterday"):
        offset = {"today": 0, "tomorrow": 1, "yesterday": -1}[lowered]
        target = _now(zone).date() + timedelta(days=offset)
        return _day(target, zone, end_of_day)
    m = _RELATIVE_RE.match(v)
    if m:
        sign, amount, unit = m.groups()
        n = int(amount) * (1 if sign == "+" else -1)
        delta = timedelta(days=n) if unit == "d" else timedelta(hours=n)
        return _now(zone) + delta
    if _DATE_ONLY_RE.match(v):
        return _day(date.fromisoformat(v), zone, end_of_day)
    iso = v[:-1] + "+00:00" if v.endswith("Z") else v
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise errors.UsageError(
            "USAGE",
            f"invalid datetime {value!r}: use YYYY-MM-DD, YYYY-MM-DDTHH:MM[:SS][Z|±HH:MM], "
            "now, today, tomorrow, yesterday, +Nd, -Nd, +Nh",
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone)
    return dt


def parse_duration(value: str) -> timedelta:
    """Parse a duration option value: `30m`, `2h`, `1d`, or ISO 8601 `PT30M`/`P1D`."""
    v = value.strip()
    m = _SIMPLE_DURATION_RE.match(v)
    if m:
        amount, unit = m.groups()
        n = int(amount)
        return {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
    m = _ISO_TIME_DURATION_RE.match(v)
    if m and any(m.groups()):
        h, mi, s = (int(g) if g else 0 for g in m.groups())
        return timedelta(hours=h, minutes=mi, seconds=s)
    m = _ISO_DAY_DURATION_RE.match(v)
    if m:
        return timedelta(days=int(m.group(1)))
    raise errors.UsageError(
        "USAGE", f"invalid duration {value!r}: use 30m, 2h, 1d or ISO 8601 PT30M"
    )


def iso_duration(td: timedelta) -> str:
    """Render a timedelta as ISO 8601 `PT#H#M`, omitting zero parts (`PT0M` for zero)."""
    total_minutes = int(td.total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    if not hours and not minutes:
        return "PT0M"
    parts = []
    if hours:
        parts.append(f"{hours}H")
    if minutes or not hours:
        parts.append(f"{minutes}M")
    return "PT" + "".join(parts)


def to_graph_dtz(dt: datetime, tz: str) -> dict:
    """Render `dt` as a Graph `{"dateTime", "timeZone"}` body in `tz`."""
    local = dt.astimezone(ZoneInfo(tz))
    return {"dateTime": local.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz}


def to_iso_offset(dt: datetime) -> str:
    """Render `dt` as an ISO 8601 string with a numeric UTC offset."""
    return dt.isoformat(timespec="seconds")


def kql_date(dt: datetime, tz: str) -> str:
    """Render `dt` as a day-granular `YYYY-MM-DD` date in `tz`, for KQL filters."""
    return dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")


def _console(natural_width: int) -> Console:
    width = max(int(os.environ.get("COLUMNS") or 200), natural_width)
    return Console(
        file=sys.stdout,
        width=width,
        force_terminal=False,
        no_color="NO_COLOR" in os.environ,
        soft_wrap=True,
        highlight=False,
        markup=False,
    )


def _cell(col: Column, item: dict) -> str:
    value = col.path(item) if callable(col.path) else dig(item, col.path)
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _emit_list(res: ListResult) -> None:
    if not res.items:
        sys.stdout.write(res.empty_text + "\n")
    else:
        rows = [[_cell(c, it) for c in res.columns] for it in res.items]
        widths = [max(len(c.header), *(len(r[i]) for r in rows)) for i, c in enumerate(res.columns)]
        table = Table(
            box=None, show_edge=False, pad_edge=False, padding=(0, 2), header_style="bold"
        )
        for c in res.columns:
            table.add_column(c.header, no_wrap=True, overflow="ignore")
        for r in rows:
            table.add_row(*r)
        # padding=(0, 2) with pad_edge=False puts a 2-char pad on each side of every internal
        # column boundary (4 chars per gap) and none at the table's outer edges.
        natural_width = sum(widths) + 4 * (len(widths) - 1)
        _console(natural_width).print(table)
    if res.truncated:
        note(
            f"(hit the {res.hit_cap}-item cap — narrow the query)"
            if res.hit_cap
            else "(more results available — rerun with --all)"
        )


def _to_json(result: Result) -> Any:
    match result:
        case ListResult():
            return {
                "items": result.items,
                "count": len(result.items),
                "truncated": result.truncated,
                **(result.extra or {}),
            }
        case ObjectResult():
            return result.obj
        case TextResult():
            return result.json_obj
        case WriteResult():
            return result.obj if result.obj is not None else {"status": "ok"}
        case DryRunResult():
            from mgraphctl.http import plan_to_json

            return {"dryRun": True, "requests": plan_to_json(result.plan)}
        case FileResult():
            return {"path": str(result.path), "bytes": result.bytes, **result.meta}
        case _:  # pragma: no cover - exhaustive match
            raise TypeError(f"unsupported result type: {type(result)!r}")


def emit(result: Result, *, json_mode: bool) -> None:
    """Render `result` to stdout: one JSON document, or the appropriate text form."""
    if json_mode:
        sys.stdout.write(json.dumps(_to_json(result), indent=2, ensure_ascii=False) + "\n")
        return
    match result:
        case ListResult():
            _emit_list(result)
        case ObjectResult():
            width = max(len(label) for label, _ in result.fields)
            for label, path in result.fields:
                value = path(result.obj) if callable(path) else dig(result.obj, path)
                sys.stdout.write(f"{label:<{width}} : {'' if value is None else value}\n")
            if result.body is not None:
                sys.stdout.write("\n" + result.body.rstrip("\n") + "\n")
        case TextResult():
            sys.stdout.write(result.text.rstrip("\n") + "\n")
        case WriteResult() | FileResult():
            sys.stdout.write(result.message + "\n")
        case DryRunResult():
            from mgraphctl.http import plan_to_text

            sys.stdout.write(plan_to_text(result.plan))
