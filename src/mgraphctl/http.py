"""The Graph HTTP client: retries, paging, batching, uploads, downloads (spec §5.1–5.4, §5.7)."""

from __future__ import annotations

import contextlib
import email.utils
import json as jsonlib
import logging
import mimetypes
import os
import random
import re
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from mgraphctl import config, errors, odata
from mgraphctl.errors import AuthError, GraphError, MsgraphError, UsageError

log = logging.getLogger("mgraphctl.http")

TIMEOUT = httpx.Timeout(connect=10, read=60, write=60, pool=10)
LONG = httpx.Timeout(connect=10, read=300, write=300, pool=10)
BATCH_CHUNK = 20
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
LOG_BODY_LIMIT = 2048

Expect = Literal["json", "bytes", "text", "none", "response"]

_TOKEN_IN_BODY = re.compile(r'("(?:access|refresh)_token"\s*:\s*")[^"]*"')


@dataclass(frozen=True)
class PageResult:
    items: list[dict]
    truncated: bool
    pages: int


@dataclass
class PlannedRequest:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    note: str | None = None
    file: Path | None = None
    chunk_size: int | None = None
    expect: Expect = "json"


Plan = list[PlannedRequest]


@dataclass(frozen=True)
class BatchRequest:
    id: str
    method: str
    url: str
    headers: dict[str, str] | None = None
    body: Any = None


@dataclass(frozen=True)
class BatchResponse:
    id: str
    status: int
    headers: dict[str, str]
    body: Any
    error: GraphError | None


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    bytes: int
    content_type: str


@dataclass(frozen=True)
class SearchResult:
    hits: list[dict]
    total: int | None
    more: bool


def _strip_query(url: str) -> str:
    return url.split("?", 1)[0]


def _file_step(path: Path) -> dict:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return {"$file": str(path), "bytes": path.stat().st_size, "contentType": content_type}


def _plan_body(step: PlannedRequest) -> Any:
    if step.chunk_size is not None:
        body: dict[str, Any] = {"createUploadSession": step.body}
        if step.file is not None:
            body["upload"] = _file_step(step.file)
        body["chunkSize"] = step.chunk_size
        return body
    if step.file is not None:
        return _file_step(step.file)
    return step.body


def plan_to_json(plan: Plan) -> list[dict]:
    """Render a plan as the `requests` array of the `--dry-run --json` document (§6.4)."""
    steps: list[dict] = []
    for step in plan:
        rendered = {
            "method": step.method,
            "url": step.url,
            "headers": dict(step.headers),
            "body": _plan_body(step),
        }
        if step.note:
            rendered["note"] = step.note
        steps.append(rendered)
    return steps


def plan_to_text(plan: Plan) -> str:
    """Render a plan as the `--dry-run` text block (§6.4)."""
    lines = ["DRY RUN — nothing sent"]
    for number, step in enumerate(plan, 1):
        lines.append(f"{number}. {step.method} {step.url}")
        if step.note:
            lines.append(f"   # {step.note}")
        lines.extend(f"   {key}: {value}" for key, value in step.headers.items())
        body = _plan_body(step)
        if body is None:
            continue
        text = body if isinstance(body, str) else jsonlib.dumps(body, indent=2, ensure_ascii=False)
        lines.extend(f"   {line}" for line in text.splitlines())
    return "\n".join(lines) + "\n"


class GraphClient:
    """Every Graph call goes through here; service modules never touch httpx directly."""

    sleep = staticmethod(time.sleep)

    def __init__(
        self,
        token_provider: Callable[[bool], str],
        *,
        tz: str,
        beta: bool = False,
        debug: int = 0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token_provider = token_provider
        self.tz = tz
        self.beta = beta
        self.debug = int(debug)
        # Both clients share one transport so record/replay also covers downloads and uploads.
        self._api = httpx.Client(
            timeout=TIMEOUT, follow_redirects=False, trust_env=True, transport=transport
        )
        self._plain = httpx.Client(
            timeout=LONG,
            follow_redirects=True,
            max_redirects=5,
            trust_env=True,
            transport=transport,
        )

    # -- plumbing ---------------------------------------------------------------

    def url(self, path: str, *, beta: bool | None = None) -> str:
        """Absolute URL for an already-encoded path; absolute paths pass through verbatim."""
        if path.startswith(("https://", "http://")):
            return path
        base = config.GRAPH_BETA if (self.beta if beta is None else beta) else config.GRAPH_V1
        return base + path

    def _build(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        outlook_tz: bool = False,
        text_body: bool = False,
        accept: str = "application/json",
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Request:
        if params:
            url = odata.with_query(url, params)
        hdrs: dict[str, str] = {
            "Accept": accept,
            "User-Agent": config.user_agent(),
            "client-request-id": str(uuid.uuid4()),
        }
        prefer = []
        if outlook_tz:
            prefer.append(f'outlook.timezone="{self.tz}"')
        if text_body:
            prefer.append('outlook.body-content-type="text"')
        if prefer:
            hdrs["Prefer"] = ", ".join(prefer)
        hdrs.update(headers or {})
        if client is self._api:
            hdrs["Authorization"] = f"Bearer {self._token_provider(False)}"
        if json_body is not None:
            content = jsonlib.dumps(json_body, ensure_ascii=False).encode()
            hdrs.setdefault("Content-Type", "application/json")
        extra = {} if timeout is None else {"timeout": timeout}
        return client.build_request(method, url, content=content, headers=hdrs, **extra)

    def _send(
        self,
        client: httpx.Client,
        request: httpx.Request,
        *,
        retry_transport_errors: bool,
        stream: bool = False,
    ) -> httpx.Response:
        attempt, refreshed = 0, False
        while True:
            attempt += 1
            started = time.monotonic()
            try:
                response = client.send(request, stream=stream)
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                if not retry_transport_errors or attempt >= config.MAX_ATTEMPTS:
                    raise MsgraphError(
                        "NETWORK",
                        f"{type(exc).__name__}: {exc}",
                        hint=errors.HINTS["NETWORK"],
                    ) from exc
                delay = self._backoff(attempt, None)
                self._log_retry(delay, type(exc).__name__)
                self.sleep(delay)
                continue
            self._log(client, request, response, attempt, started, streaming=stream)
            if response.status_code == 401 and not refreshed and client is self._api:
                refreshed = True
                response.close()
                new_token = self._token_provider(True)
                if not new_token:
                    raise AuthError(
                        "UNAUTHORIZED",
                        "token refresh failed",
                        hint=errors.HINTS["UNAUTHORIZED"],
                    )
                request.headers["Authorization"] = f"Bearer {new_token}"
                continue
            if response.status_code in config.RETRY_STATUSES and attempt < config.MAX_ATTEMPTS:
                delay = self._backoff(attempt, response.headers.get("Retry-After"))
                response.close()
                self._log_retry(delay, f"HTTP {response.status_code}")
                self.sleep(delay)
                continue
            return response

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            value = retry_after.strip()
            if value.isdigit():
                return float(min(int(value), config.RETRY_AFTER_CAP))
            with contextlib.suppress(TypeError, ValueError):
                when = email.utils.parsedate_to_datetime(value)
                seconds = (when - datetime.now(UTC)).total_seconds()
                return max(0.0, min(seconds, config.RETRY_AFTER_CAP))
        return min(2**attempt, 30) + random.uniform(0, 1)

    def _log_retry(self, delay: float, reason: str) -> None:
        if self.debug >= 1:
            log.debug("DEBUG retry in %.1fs after %s", delay, reason)

    def _log(
        self,
        client: httpx.Client,
        request: httpx.Request,
        response: httpx.Response,
        attempt: int,
        started: float,
        *,
        streaming: bool,
    ) -> None:
        if self.debug < 1:
            return
        # Pre-authenticated URLs (download targets, uploadUrl) carry a token in the query.
        url = _strip_query(str(request.url)) if client is self._plain else str(request.url)
        elapsed = int((time.monotonic() - started) * 1000)
        line = (
            f"DEBUG {request.method} {url} -> {response.status_code} "
            f"{elapsed}ms [attempt {attempt}]"
        )
        request_id = response.headers.get("request-id")
        if request_id:
            line = f"{line} [{request_id}]"
        log.debug("%s", line)
        prefer = request.headers.get("Prefer")
        if prefer:
            log.debug("DEBUG Prefer: %s", prefer)
        if self.debug >= 2 and not streaming and response.content:
            body = response.text[:LOG_BODY_LIMIT]
            log.debug("DEBUG body: %s", _TOKEN_IN_BODY.sub(r'\1***"', body))

    # -- single requests --------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        beta: bool | None = None,
        outlook_tz: bool = False,
        text_body: bool = False,
        expect: Expect = "json",
    ) -> Any:
        request = self._build(
            self._api,
            method,
            self.url(path, beta=beta),
            params=params,
            json_body=json,
            content=content,
            headers=headers,
            outlook_tz=outlook_tz,
            text_body=text_body,
            accept="*/*" if expect == "bytes" else "application/json",
        )
        response = self._send(
            self._api,
            request,
            retry_transport_errors=(method == "GET"),
            stream=(expect == "response"),
        )
        if expect == "response":
            if response.status_code >= 400:
                response.read()
                response.close()
                raise self._error(response)
            return response
        if response.status_code == 401:
            detail = self._error(response)
            raise AuthError(
                "UNAUTHORIZED",
                detail.message,
                hint=errors.HINTS["UNAUTHORIZED"],
                request_id=detail.request_id,
            )
        if response.status_code >= 400:
            raise self._error(response)
        if expect == "none" or not response.content:
            return None
        if expect == "bytes":
            return response.content
        if expect == "text":
            return response.text
        return response.json()

    @staticmethod
    def _error(response: httpx.Response) -> GraphError:
        return errors.graph_error_from_response(
            response.status_code,
            response.headers,
            response.content,
            _strip_query(str(response.url)),
        )

    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        return self.request("POST", path, **kw)

    def patch(self, path: str, **kw: Any) -> Any:
        return self.request("PATCH", path, **kw)

    def put(self, path: str, **kw: Any) -> Any:
        return self.request("PUT", path, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self.request("DELETE", path, **kw)

    # -- paging -----------------------------------------------------------------

    def paginate(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        beta: bool | None = None,
        outlook_tz: bool = False,
        limit: int | None,
        all_: bool,
        cap: int,
        page_size: int | None,
    ) -> PageResult:
        if all_:
            bound = cap
        elif limit is None or limit < 1:
            raise UsageError("USAGE", "--limit must be 1 or more")
        else:
            bound = min(limit, cap)
        query = dict(params or {})
        if page_size is not None:
            query["$top"] = page_size
        url = odata.with_query(path, query)
        items: list[dict] = []
        pages = 0
        next_link: str | None = None
        while True:
            payload = (
                self.request("GET", url, headers=headers, beta=beta, outlook_tz=outlook_tz) or {}
            )
            pages += 1
            items.extend(payload.get("value") or [])
            next_link = payload.get("@odata.nextLink")
            if not next_link or len(items) >= bound:
                break
            url = next_link
        return PageResult(
            items=items[:bound],
            truncated=len(items) > bound or bool(next_link),
            pages=pages,
        )

    # -- $batch -----------------------------------------------------------------

    @staticmethod
    def _batch_sub(internal_id: str, request: BatchRequest) -> dict:
        sub: dict[str, Any] = {"id": internal_id, "method": request.method, "url": request.url}
        headers = dict(request.headers or {})
        if request.body is not None:
            headers.setdefault("Content-Type", "application/json")
        if headers:
            sub["headers"] = headers
        if request.body is not None:
            sub["body"] = request.body
        return sub

    def batch(
        self, requests: list[BatchRequest], *, beta: bool | None = None
    ) -> list[BatchResponse]:
        results: dict[str, BatchResponse] = {}
        for start in range(0, len(requests), BATCH_CHUNK):
            chunk = requests[start : start + BATCH_CHUNK]
            pending = {str(i): request for i, request in enumerate(chunk, 1)}
            attempt = 0
            while pending:
                attempt += 1
                payload = {"requests": [self._batch_sub(key, req) for key, req in pending.items()]}
                response = self.post("/$batch", json=payload, beta=beta) or {}
                retry_delays: list[float] = []
                retrying: dict[str, BatchRequest] = {}
                answered: set[str] = set()
                for sub in response.get("responses") or []:
                    key = str(sub.get("id"))
                    request = pending.get(key)
                    if request is None:
                        continue
                    answered.add(key)
                    status = int(sub.get("status") or 0)
                    headers = {k.lower(): v for k, v in (sub.get("headers") or {}).items()}
                    if status == 429 and attempt < config.MAX_ATTEMPTS:
                        retrying[key] = request
                        retry_delays.append(self._backoff(attempt, headers.get("retry-after")))
                        continue
                    error = None
                    if status >= 400:
                        error = errors.graph_error_from_batch(
                            status, headers, sub.get("body"), request.url
                        )
                    results[request.id] = BatchResponse(
                        request.id, status, headers, sub.get("body"), error
                    )
                for key, request in pending.items():
                    if key in answered or key in retrying:
                        continue
                    missing = GraphError(
                        502,
                        "HTTP_502",
                        "the $batch response carried no entry for this request",
                        url=request.url,
                    )
                    results[request.id] = BatchResponse(request.id, 502, {}, None, missing)
                if not retrying:
                    break
                self.sleep(max(retry_delays))
                pending = retrying
        return [results[request.id] for request in requests]

    # -- upload / download ------------------------------------------------------

    def upload_session(
        self,
        create_path: str,
        create_body: dict,
        file: Path,
        *,
        chunk_size: int,
        beta: bool | None = None,
    ) -> dict:
        created = self.post(create_path, json=create_body, beta=beta) or {}
        upload_url = created.get("uploadUrl")
        if not upload_url:
            raise MsgraphError(
                "UPLOAD_SESSION_LOST",
                "the createUploadSession response carried no uploadUrl",
                hint=errors.HINTS["UPLOAD_SESSION_LOST"],
            )
        total = file.stat().st_size
        offset = 0
        last: Any = {}
        with file.open("rb") as handle:
            while offset < total:
                end = min(offset + chunk_size, total) - 1
                handle.seek(offset)
                chunk = handle.read(end - offset + 1)
                request = self._build(
                    self._plain,
                    "PUT",
                    upload_url,
                    content=chunk,
                    headers={
                        "Content-Range": f"bytes {offset}-{end}/{total}",
                        "Content-Length": str(len(chunk)),
                    },
                    timeout=LONG,
                )
                response = self._send(self._plain, request, retry_transport_errors=True)
                if response.status_code == 404:
                    raise MsgraphError(
                        "UPLOAD_SESSION_LOST",
                        f"the upload session for {file.name} is gone (HTTP 404)",
                        hint=errors.HINTS["UPLOAD_SESSION_LOST"],
                    )
                if response.status_code >= 400:
                    raise self._error(response)
                last = response.json() if response.content else {}
                ranges = last.get("nextExpectedRanges") if isinstance(last, dict) else None
                offset = int(str(ranges[0]).split("-")[0]) if ranges else end + 1
        return last if isinstance(last, dict) else {}

    def download(self, path_or_url: str, dest: Path, *, beta: bool | None = None) -> DownloadResult:
        request = self._build(
            self._api, "GET", self.url(path_or_url, beta=beta), accept="*/*", timeout=LONG
        )
        response = self._send(self._api, request, retry_transport_errors=True, stream=True)
        try:
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("Location")
                if not location:
                    response.read()
                    raise self._error(response)
                response.close()
                request = self._build(self._plain, "GET", location, accept="*/*", timeout=LONG)
                response = self._send(
                    self._plain, request, retry_transport_errors=True, stream=True
                )
            if response.status_code >= 400:
                response.read()
                raise self._error(response)
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            content_type = content_type.split(";", 1)[0].strip()
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_name(dest.name + ".part")
            written = 0
            try:
                with part.open("wb") as handle:
                    for block in response.iter_bytes():
                        handle.write(block)
                        written += len(block)
            except BaseException:
                part.unlink(missing_ok=True)
                raise
        finally:
            response.close()
        os.replace(part, dest)
        return DownloadResult(path=dest, bytes=written, content_type=content_type)

    # -- search -----------------------------------------------------------------

    def search(
        self,
        entity_types: list[str],
        query: str,
        *,
        size: int,
        limit: int,
        fields: list[str] | None = None,
        enable_top_results: bool = False,
    ) -> SearchResult:
        hits: list[dict] = []
        total: int | None = None
        pending = False
        offset = 0
        while True:
            body: dict[str, Any] = {
                "entityTypes": list(entity_types),
                "query": {"queryString": query},
                "from": offset,
                "size": size,
            }
            if fields:
                body["fields"] = list(fields)
            if enable_top_results:
                body["enableTopResults"] = True
            payload = self.post("/search/query", json={"requests": [body]}) or {}
            pending = False
            for value in payload.get("value") or []:
                for container in value.get("hitsContainers") or []:
                    hits.extend(container.get("hits") or [])
                    if total is None and container.get("total") is not None:
                        total = container["total"]
                    if container.get("moreResultsAvailable"):
                        pending = True
            offset += size
            if not pending or len(hits) >= limit:
                break
        return SearchResult(hits=hits[:limit], total=total, more=pending or len(hits) > limit)

    # -- planned requests -------------------------------------------------------

    def execute(self, planned: PlannedRequest) -> Any:
        """Run one step of a `Plan` (the non-dry-run half of §6.4)."""
        if planned.chunk_size is not None:
            if planned.file is None:
                raise UsageError("USAGE", "an upload-session step needs a file")
            return self.upload_session(
                planned.url, planned.body or {}, planned.file, chunk_size=planned.chunk_size
            )
        kwargs: dict[str, Any] = {
            "headers": dict(planned.headers) or None,
            "expect": planned.expect,
        }
        if planned.file is not None:
            kwargs["content"] = planned.file.read_bytes()
        elif isinstance(planned.body, bytes):
            kwargs["content"] = planned.body
        elif isinstance(planned.body, str):
            kwargs["content"] = planned.body.encode()
        elif planned.body is not None:
            kwargs["json"] = planned.body
        return self.request(planned.method, planned.url, **kwargs)

    # -- lifecycle --------------------------------------------------------------

    def close(self) -> None:
        self._api.close()
        self._plain.close()

    def __enter__(self) -> GraphClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
