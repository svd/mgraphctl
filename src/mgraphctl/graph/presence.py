"""Graph operations for Teams presence (spec §8.9).

Pure: client and parameters in, Graph dicts or a `Plan` out.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from mgraphctl import odata
from mgraphctl.errors import UsageError
from mgraphctl.http import GraphClient, Plan, PlannedRequest
from mgraphctl.render import iso_duration

# The CLI state, and the `availability` / `activity` pair Graph wants for it.
PRESENCE_PAIRS: dict[str, tuple[str, str]] = {
    "available": ("Available", "Available"),
    "busy": ("Busy", "Busy"),
    "dnd": ("DoNotDisturb", "DoNotDisturb"),
    "brb": ("BeRightBack", "BeRightBack"),
    "away": ("Away", "Away"),
    "offline": ("Offline", "OffWork"),
}

JSON = {"Content-Type": "application/json"}


def resolve_pair(state: str) -> tuple[str, str]:
    """The Graph availability/activity pair for a CLI state name."""
    pair = PRESENCE_PAIRS.get(state.casefold())
    if pair is None:
        raise UsageError(
            "USAGE", f"unknown presence {state!r}; use one of {', '.join(PRESENCE_PAIRS)}"
        )
    return pair


def get_presence(client: GraphClient) -> dict:
    return client.get("/me/presence")


def get_presences(client: GraphClient, ids: Iterable[str]) -> list[dict]:
    payload = client.post("/communications/getPresencesByUserId", json={"ids": list(ids)}) or {}
    return payload.get("value") or []


def _presence_base(client: GraphClient, my_oid: str) -> str:
    """`/users/{oid}/presence`; the oid comes from the token, so there is no `/me` call."""
    return client.url(odata.p("users", my_oid, "presence"))


def plan_set(
    client: GraphClient,
    my_oid: str,
    availability: str,
    *,
    expiration: timedelta,
    message: str | None,
) -> Plan:
    state, activity = resolve_pair(availability)
    base = _presence_base(client, my_oid)
    steps = [
        PlannedRequest(
            "POST",
            f"{base}/setUserPreferredPresence",
            dict(JSON),
            {
                "availability": state,
                "activity": activity,
                "expirationDuration": iso_duration(expiration),
            },
            expect="none",
        )
    ]
    if message is not None:
        steps.append(
            PlannedRequest(
                "POST",
                f"{base}/setStatusMessage",
                dict(JSON),
                {"statusMessage": {"message": {"content": message, "contentType": "text"}}},
                expect="none",
            )
        )
    return steps


def plan_clear(client: GraphClient, my_oid: str) -> Plan:
    base = _presence_base(client, my_oid)
    return [PlannedRequest("POST", f"{base}/clearUserPreferredPresence", {}, None, expect="none")]
