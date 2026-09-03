"""Record/replay httpx transport for offline runs and tests (spec §5.8)."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import httpx

from mgraphctl import config
from mgraphctl.errors import FixtureError
from mgraphctl.http import redact_body

# Recorded responses never carry credentials, and never carry framing that would not
# survive re-serialising the body.
DROPPED_HEADERS = frozenset(
    {"authorization", "set-cookie", "content-length", "content-encoding", "transfer-encoding"}
)


def fixture_key(request: httpx.Request) -> str:
    """`"<METHOD> <path>?<query>"`; the query is dropped for unauthenticated requests.

    Download targets and `uploadUrl` PUTs are pre-authenticated: their query strings carry
    per-request tokens that differ on every run, so they cannot be part of the key.
    """
    if "authorization" in request.headers:
        return f"{request.method} {request.url.raw_path.decode()}"
    return f"{request.method} {request.url.path}"


def fixture_path(dir: Path, key: str) -> Path:  # noqa: A002 - name fixed by the Phase 0 contract
    """File holding the recorded responses for `key`."""
    return Path(dir) / (hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] + ".json")


def _clean_headers(headers: httpx.Headers) -> dict[str, str]:
    cleaned = {}
    for name, value in headers.items():
        lowered = name.lower()
        if lowered in DROPPED_HEADERS:
            continue
        cleaned[lowered] = value.split("?", 1)[0] if lowered == "location" else value
    return cleaned


def _encode_body(response: httpx.Response) -> dict:
    raw = response.content
    if not raw:
        return {}
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        try:
            # A recorded body must never keep a token: the OAuth pair and the `uploadUrl`
            # query string are redacted here exactly as the debug log redacts them.
            return {"body": json.loads(redact_body(raw.decode("utf-8")))}
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    if content_type.startswith("text/"):
        return {"body_text": raw.decode("utf-8", errors="replace")}
    return {"body_b64": base64.b64encode(raw).decode("ascii")}


def _decode_body(entry: dict) -> bytes:
    if "body" in entry:
        return json.dumps(entry["body"], ensure_ascii=False).encode("utf-8")
    if "body_text" in entry:
        return entry["body_text"].encode("utf-8")
    if "body_b64" in entry:
        return base64.b64decode(entry["body_b64"])
    return b""


class FixtureTransport(httpx.BaseTransport):
    """Replays recorded Graph traffic, or records it when `record` is set."""

    def __init__(
        self,
        dir: Path,  # noqa: A002 - name fixed by the Phase 0 contract
        *,
        record: bool,
        inner: httpx.BaseTransport | None = None,
    ) -> None:
        self.dir = Path(dir)
        self.record = record
        self.inner = inner if inner is not None else (httpx.HTTPTransport() if record else None)
        self._cursor: dict[str, int] = {}

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == config.TOKEN_HOST:
            raise FixtureError(
                "FIXTURE_FORBIDDEN_HOST",
                f"refusing to record or replay {config.TOKEN_HOST} traffic",
            )
        key = fixture_key(request)
        path = fixture_path(self.dir, key)
        return self._record(request, key, path) if self.record else self._replay(key, path)

    def _record(self, request: httpx.Request, key: str, path: Path) -> httpx.Response:
        if self.inner is None:  # pragma: no cover - guarded by __init__
            raise FixtureError("FIXTURE_MISSING", "recording needs an inner transport")
        response = self.inner.handle_request(request)
        response.request = request
        response.read()
        entry = {
            "status": response.status_code,
            "headers": _clean_headers(response.headers),
            **_encode_body(response),
        }
        document = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"key": key, "responses": []}
        )
        document["responses"].append(entry)
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # Hand back the live response, headers untouched, so recording behaves like a real run.
        return httpx.Response(
            response.status_code, headers=response.headers, content=response.content
        )

    def _replay(self, key: str, path: Path) -> httpx.Response:
        if not path.exists():
            raise FixtureError("FIXTURE_MISSING", f"no fixture for {key} (expected {path})")
        document = json.loads(path.read_text(encoding="utf-8"))
        responses = document.get("responses") or []
        index = self._cursor.get(key, 0)
        if index >= len(responses):
            raise FixtureError(
                "FIXTURE_EXHAUSTED",
                f"fixture for {key} has only {len(responses)} response(s) ({path})",
            )
        self._cursor[key] = index + 1
        entry = responses[index]
        return httpx.Response(
            entry["status"], headers=entry.get("headers") or {}, content=_decode_body(entry)
        )

    def close(self) -> None:
        if self.inner is not None:
            self.inner.close()


def transport_from_env(s: config.Settings) -> FixtureTransport | None:
    """The transport implied by `MGRAPHCTL_FIXTURE_DIR` / `MGRAPHCTL_RECORD`, or `None`."""
    return FixtureTransport(s.fixture_dir, record=s.record) if s.fixture_dir else None
