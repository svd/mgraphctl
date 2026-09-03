"""Shared test helpers: coverage registry, fixture loading, respx routing."""

import base64
import json
from pathlib import Path

import httpx
import respx

FIXTURES = Path(__file__).parent / "fixtures"
VERBS_TESTED: set[str] = set()
GRAPH = "https://graph.microsoft.com"


def covers(*verbs: str):
    """Mark a test as covering the given `noun verb` names (test_surface.py checks completeness)."""
    VERBS_TESTED.update(verbs)
    return lambda fn: fn


def load_fixture(name: str) -> list[dict]:
    noun, _, verb = name.partition("/")
    return json.loads((FIXTURES / noun / f"{verb}.json").read_text())


def _response(entry: dict) -> httpx.Response:
    headers = entry.get("headers") or {}
    if "json" in entry:
        return httpx.Response(entry["status"], json=entry["json"], headers=headers)
    if "text" in entry:
        return httpx.Response(entry["status"], text=entry["text"], headers=headers)
    if "b64" in entry:
        return httpx.Response(
            entry["status"], content=base64.b64decode(entry["b64"]), headers=headers
        )
    return httpx.Response(entry["status"], headers=headers)


def mock_graph(router: respx.MockRouter, name: str) -> list[respx.Route]:
    """One respx route per fixture entry; `path` exact, `query` (optional) decoded and exact."""
    routes = []
    for entry in load_fixture(name):
        kwargs = {"method": entry["method"], "url": GRAPH + entry["path"]}
        if "query" in entry:
            kwargs["params__eq"] = entry["query"]
        responses = entry.get("responses", [entry])
        route = router.route(**kwargs)
        if len(responses) > 1:
            route.mock(side_effect=[_response(r) for r in responses])
        else:
            route.mock(return_value=_response(responses[0]))
        routes.append(route)
    return routes


def graph_error(
    status: int, code: str, message: str = "boom", request_id: str = "req-0001"
) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "error": {
                "code": code,
                "message": message,
                "innerError": {"request-id": request_id, "date": "2026-09-02T00:00:00"},
            }
        },
    )
