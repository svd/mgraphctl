"""Direct tests for graph.groups helpers not fully exercised through the CLI (spec §8.16)."""

from mgraphctl.graph import groups
from mgraphctl.http import GraphClient

GUID = "11111111-2222-3333-4444-555555555555"


def test_resolve_group_by_literal_guid_skips_the_lookup(graph):
    """A GUID is already an id shape (resolve.looks_like_id): no memberOf lookup call at all."""
    with GraphClient(lambda force_refresh: "tok", tz="Europe/Warsaw") as client:
        resolved = groups.resolve_group(client, GUID)
    assert resolved == {"id": GUID}
    assert graph.calls.call_count == 0
