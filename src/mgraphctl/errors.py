"""Exception hierarchy, exit-code mapping and error rendering (spec §5.6, §6.5)."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any

from mgraphctl import config

_STATUS_HINT_KEYS = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 429: "THROTTLED"}


class MsgraphError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        exit_code: int = 1,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.exit_code = exit_code
        self.request_id = request_id
        self.correlation_id = correlation_id


class UsageError(MsgraphError):
    """Semantic argument errors raised inside commands. Exit 2."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(
            code,
            message,
            hint=hint,
            exit_code=2,
            request_id=request_id,
            correlation_id=correlation_id,
        )


class AuthError(MsgraphError):
    """NOT_LOGGED_IN, MISSING_SCOPE, CONSENT_REQUIRED, LOGIN_TIMEOUT, UNAUTHORIZED. Exit 3."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(
            code,
            message,
            hint=hint,
            exit_code=3,
            request_id=request_id,
            correlation_id=correlation_id,
        )


class NotFoundError(MsgraphError):
    """404 and failed name resolution. Exit 4."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(
            code,
            message,
            hint=hint,
            exit_code=4,
            request_id=request_id,
            correlation_id=correlation_id,
        )


class AmbiguousError(MsgraphError):
    """Name resolution with more than one candidate. Exit 2; candidates listed on stderr."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        candidates: list[tuple[str, str]],
        hint: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(
            code,
            message,
            hint=hint,
            exit_code=2,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        self.candidates = candidates


class GraphError(MsgraphError):
    """A Graph HTTP error. Exit 3 for 401/403, 4 for 404, else 1."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        request_id: str | None = None,
        url: str = "",
        body: Any = None,
    ) -> None:
        exit_code = 3 if status in (401, 403) else 4 if status == 404 else 1
        super().__init__(
            code, message, hint=hint_for(code, status), exit_code=exit_code, request_id=request_id
        )
        self.status = status
        self.url = url
        self.body = body


class FixtureError(MsgraphError):
    """FIXTURE_MISSING / FIXTURE_EXHAUSTED / FIXTURE_FORBIDDEN_HOST. Exit 1."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(
            code,
            message,
            hint=hint,
            exit_code=1,
            request_id=request_id,
            correlation_id=correlation_id,
        )


def _build_hints() -> dict[str, str]:
    shim = config.shim_path()
    return {
        "NOT_LOGGED_IN": f"run '{shim} login' in your own terminal (opens a browser)",
        "UNAUTHORIZED": f"run '{shim} login --force' in your own terminal",
        "MISSING_SCOPE": f"run '{shim} login --scopes extended' in your own terminal",
        "FORBIDDEN": (
            f"the token lacks a permission for this call; run '{shim} login --scopes extended' "
            "or ask an admin to grant consent"
        ),
        "CONSENT_REQUIRED": "an admin must grant consent once (URL above)",
        "NOT_FOUND": "check the id; ids returned by 'mail move' change",
        "THROTTLED": "throttled; wait and retry with a smaller --limit",
        "InefficientFilter": "use --search (KQL) instead of date filters with this ordering",
        "NETWORK": "check the network or HTTPS_PROXY and retry",
        "UPLOAD_SESSION_LOST": "the upload session expired; rerun the upload",
        "ErrorAttachmentSizeShouldNotBeLessThanMinimumSize": (
            "internal error: attachment routed to the wrong path; report it"
        ),
    }


class _HintsMapping(Mapping[str, str]):
    """A `code -> hint text` mapping that resolves `config.shim_path()` fresh on every access.

    Every read (`HINTS[code]`, `code in HINTS`, `HINTS.get(code)`, iteration, `.items()`, ...)
    rebuilds the underlying dict from the *current* `config.shim_path()`, so a test that patches
    `config.shim_path` after import still sees up-to-date hint text through `errors.HINTS`
    directly, not just through `hint_for()`.
    """

    def __getitem__(self, key: str) -> str:
        return _build_hints()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(_build_hints())

    def __len__(self) -> int:
        return len(_build_hints())

    def __repr__(self) -> str:
        return repr(_build_hints())


HINTS: Mapping[str, str] = _HintsMapping()


def hint_for(code: str, status: int | None) -> str | None:
    if code in HINTS:
        return HINTS[code]
    key = _STATUS_HINT_KEYS.get(status) if status is not None else None
    return HINTS.get(key) if key else None


def _parse_error_dict(data: Any) -> tuple[str | None, str | None, str | None]:
    if not isinstance(data, dict):
        return None, None, None
    error = data.get("error")
    if not isinstance(error, dict):
        return None, None, None
    code = error.get("code")
    message = error.get("message")
    inner = error.get("innerError")
    request_id = inner.get("request-id") if isinstance(inner, dict) else None
    if code is None or message is None:
        return None, None, None
    return code, message, request_id


def graph_error_from_response(
    status: int, headers: Mapping[str, str], body: bytes, url: str
) -> GraphError:
    data = None
    if body:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = None
    code, message, request_id = _parse_error_dict(data)
    if code is None:
        text = body.decode("utf-8", errors="replace")[:500] if body else ""
        code = f"HTTP_{status}"
        message = text or f"HTTP {status}"
    return GraphError(status, code, message, request_id=request_id, url=url, body=body)


def graph_error_from_batch(
    status: int, headers: Mapping[str, str], body: Any, url: str
) -> GraphError:
    code, message, request_id = _parse_error_dict(body)
    if code is None:
        text = json.dumps(body)[:500] if body is not None else ""
        code = f"HTTP_{status}"
        message = text or f"HTTP {status}"
    return GraphError(status, code, message, request_id=request_id, url=url, body=body)


def format_error(exc: MsgraphError) -> str:
    lines = [f"error[{exc.code}]: {exc.message}"]
    if isinstance(exc, AmbiguousError):
        for candidate_id, name in exc.candidates:
            lines.append(f"  candidate: {candidate_id}  {name}")
    if exc.request_id:
        lines.append(f"  request-id: {exc.request_id}")
    if exc.correlation_id:
        lines.append(f"  correlation-id: {exc.correlation_id}")
    if exc.hint:
        lines.append(f"  hint: {exc.hint}")
    return "".join(line + "\n" for line in lines)
