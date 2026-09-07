"""Tool discovery: the Click tree becomes MCP tools (MCP spec §4)."""

import pytest

from mgraphctl.errors import UsageError
from mgraphctl.mcp import discover


@pytest.fixture
def specs(app):
    return {s.path: s for s in discover.discover(app, capabilities=discover.ALL, allow_write=True)}


def test_every_verb_becomes_exactly_one_tool(app, specs):
    verbs = set(discover.walk(app))
    assert verbs - discover.EXCLUDED == set(specs)
    assert len(specs) == len({s.name for s in specs.values()})


def test_tool_names_follow_the_spec_character_rules(specs):
    legal = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")
    for spec in specs.values():
        assert set(spec.name) <= legal, spec.name
        assert 1 <= len(spec.name) <= 128


def test_tool_name_is_the_verb_path_joined_with_underscores(specs):
    assert specs["mail list"].name == "mail_list"
    assert specs["mail drafts create"].name == "mail_drafts_create"
    assert specs["calendar find-times"].name == "calendar_find-times"
    assert specs["me"].name == "me"


def test_capability_is_the_command_group_and_top_level_verbs_are_core(specs):
    assert specs["mail list"].capability == "mail"
    assert specs["mail drafts create"].capability == "mail"
    assert specs["me"].capability == "core"
    assert specs["search"].capability == "core"
    assert specs["api"].capability == "api"


def test_interactive_and_host_local_verbs_are_never_exposed(app):
    """`login` opens a browser; `config` edits the operator's file. Neither is the model's job."""
    assert {
        "login",
        "logout",
        "config path",
        "config show",
        "config init",
        "config set",
        "config unset",
    } == discover.EXCLUDED
    assert set(discover.walk(app)) >= discover.EXCLUDED


def test_description_comes_from_the_verbs_own_help(specs):
    assert specs["mail list"].description.startswith("List messages")


def test_capability_filtering_selects_whole_command_groups(app):
    got = discover.discover(app, capabilities=["mail", "calendar"], allow_write=True)
    assert {s.capability for s in got} == {"mail", "calendar"}
    assert "mail list" in {s.path for s in got}


def test_resolve_capabilities_defaults_and_all(app):
    assert discover.resolve(None) == list(discover.DEFAULT)
    assert "api" not in discover.resolve("all")
    assert set(discover.resolve("all")) == set(discover.ALL) - {"api"}
    assert discover.resolve("mail,calendar") == ["mail", "calendar"]
    # The escape hatch is reachable, but only by naming it.
    assert discover.resolve("api") == ["api"]


def test_resolve_capabilities_rejects_an_unknown_name():
    with pytest.raises(UsageError) as excinfo:
        discover.resolve("mail,mailx")
    assert "mailx" in str(excinfo.value)


def test_read_only_is_the_default_and_allow_write_opens_the_rest(app):
    read_only = {s.path for s in discover.discover(app, capabilities=discover.ALL)}
    everything = {
        s.path for s in discover.discover(app, capabilities=discover.ALL, allow_write=True)
    }
    assert not any(discover.MUTATING & {p} for p in read_only)
    assert everything - read_only == discover.MUTATING


def test_every_verb_is_classified_and_the_classification_is_sound(app, specs):
    """Scopes bound what a verb can do: a verb holding only read scopes cannot be mutating."""
    for path, spec in specs.items():
        assert spec.mutating is (path in discover.MUTATING)
        if spec.mutating and path != "api":
            assert discover.can_write(spec.scopes), path


def test_a_verb_that_could_write_is_either_mutating_or_knowingly_excused(specs):
    """A new write verb fails here until it is classified; the excuse list is finite and named."""
    for path, spec in specs.items():
        if discover.can_write(spec.scopes) and not spec.mutating:
            assert path in discover.READ_WITH_WRITE_SCOPE, path
    assert set(specs) >= discover.READ_WITH_WRITE_SCOPE


def test_annotations_describe_the_verb(specs):
    assert specs["mail list"].annotations == {"readOnlyHint": True, "openWorldHint": True}
    delete = specs["calendar delete"].annotations
    assert delete["readOnlyHint"] is False and delete["destructiveHint"] is True
    update = specs["calendar update"].annotations
    assert update["destructiveHint"] is False and update["idempotentHint"] is True


def test_graph_verbs_carry_the_undecorated_function_and_their_scopes(specs):
    spec = specs["mail list"]
    assert spec.scopes == ["Mail.Read"]
    assert spec.fn is not None and "client" in spec.fn.__code__.co_varnames


def test_local_verbs_have_no_graph_function(specs):
    """`status`, `claims` and `version` answer from the cache; they run through the CLI callback."""
    for path in ("status", "claims", "version"):
        assert specs[path].fn is None


def test_the_capability_list_matches_the_command_groups_the_cli_registers(app):
    """A new noun must be reachable: adding one without naming it here fails the build."""
    assert discover.capabilities_of(app) == set(discover.ALL)
    assert set(discover.DEFAULT) <= set(discover.ALL)
