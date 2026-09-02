"""URL and query-string encoding helpers for Microsoft Graph paths (spec §5.5)."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlsplit

_SITE_REF_TYPES = ("sites", "teams", "personal")


def p(*segments: str) -> str:
    """Build an absolute path from raw segments, each fully percent-encoded."""
    return "/" + "/".join(quote(str(segment), safe="") for segment in segments)


def drive_path(path: str) -> str:
    """Quote each `/`-separated segment of a drive-relative path; no leading slash."""
    return "/".join(quote(segment, safe="") for segment in path.split("/"))


def query(params: Mapping[str, Any]) -> str:
    """Render `params` as a query string: keys verbatim, values percent-encoded (%20 not +)."""
    parts: list[str] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        parts.append(f"{key}={quote(str(value), safe='')}")
    return "&".join(parts)


def with_query(path: str, params: Mapping[str, Any] | None) -> str:
    """Append `?query()` to `path`, omitting the `?` entirely when there are no params."""
    q = query(params or {})
    return f"{path}?{q}" if q else path


def kql(*terms: str) -> str:
    """Join KQL terms with ` AND ` and wrap the result in double quotes for `$search`."""
    return '"' + " AND ".join(terms) + '"'


def odata_str(s: str) -> str:
    """Escape a string literal for use inside an OData `$filter`/`search()` expression."""
    return s.replace("'", "''")


def share_id(url: str) -> str:
    """Encode a sharing URL as a Graph `shares/{share_id}` id."""
    encoded = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
    return f"u!{encoded}"


def site_ref(value: str) -> str:
    """Resolve a site reference (URL, `host:/a/b`, composite id, or plain id) to a Graph path."""
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlsplit(value)
        host = quote(parsed.netloc, safe="")
        segments = [s for s in parsed.path.split("/") if s]
        if len(segments) >= 2 and segments[0] in _SITE_REF_TYPES:
            return f"/sites/{host}:/{segments[0]}/{quote(segments[1], safe='')}"
        return f"/sites/{host}"
    if ":/" in value:
        host, _, rest = value.partition(":/")
        quoted_segments = "/".join(quote(segment, safe="") for segment in rest.split("/"))
        return f"/sites/{quote(host, safe='')}:/{quoted_segments}"
    if "," in value:
        return f"/sites/{quote(value, safe=',')}"
    return p("sites", value)
