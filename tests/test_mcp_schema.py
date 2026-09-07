"""Click parameters become JSON Schema (MCP spec §4.2)."""

import pytest

from mgraphctl.mcp import discover, schema


@pytest.fixture
def commands(app):
    return discover.walk(app)


def built(commands, path):
    return schema.build(commands[path])


def test_the_schema_is_a_closed_object(commands):
    doc, _ = built(commands, "mail list")
    assert doc["type"] == "object" and doc["additionalProperties"] is False


def test_options_become_properties_with_their_help_and_flags(commands):
    doc, _ = built(commands, "mail list")
    folder = doc["properties"]["folder"]
    assert folder["type"] == "string"
    assert folder["default"] == "inbox"
    assert folder["description"] == "Folder name, id, or 'all'. (--folder)"
    assert doc["properties"]["unread"]["type"] == "boolean"
    assert doc["properties"]["limit"]["type"] == "integer"


def test_a_repeatable_option_becomes_an_array(commands):
    doc, _ = built(commands, "mail list")
    assert doc["properties"]["to"] == {
        "type": "array",
        "items": {"type": "string"},
        "description": "Recipient address (repeatable). (--to)",
    }


def test_a_trailing_underscore_is_dropped_and_mapped_back(commands):
    """`--from` had to be `from_` in Python; the schema shows the flag the user knows."""
    doc, params = built(commands, "mail list")
    assert "from" in doc["properties"] and "from_" not in doc["properties"]
    assert params["from"] == "from_"
    assert params["all"] == "all_"


def test_a_positional_argument_is_required(commands):
    doc, _ = built(commands, "mail read")
    assert doc["required"] == ["message_id"]
    assert doc["properties"]["message_id"]["type"] == "string"
    assert doc["properties"]["message_id"]["description"] == "Message id."


def test_a_command_with_no_arguments_has_no_required_key(commands):
    doc, _ = built(commands, "mail list")
    assert "required" not in doc


def test_the_json_flag_is_replaced_by_the_two_output_params(commands):
    """`--json` is a switch on a stream the CLI owns; MCP has three channels for it."""
    for path in ("mail list", "me", "calendar list"):
        doc, params = built(commands, path)
        assert "json" not in doc["properties"] and "json_" not in params
        assert doc["properties"]["output_format"]["enum"] == ["text", "json"]
        assert doc["properties"]["output_format"]["default"] == "text"
        assert doc["properties"]["output_file"]["type"] == "string"


def test_dry_run_survives_on_the_verbs_that_offer_it(commands):
    doc, _ = built(commands, "mail send")
    assert doc["properties"]["dry_run"]["type"] == "boolean"


def test_every_generated_schema_is_valid_json_schema(app):
    """The SDK advertises the schema without checking it; a bad one only fails at the client."""
    jsonschema = pytest.importorskip("jsonschema")
    for spec in discover.discover(app, capabilities=discover.ALL, allow_write=True):
        jsonschema.Draft202012Validator.check_schema(spec.input_schema)


def test_int_range_bounds_survive_into_the_schema(commands):
    """Without them `--limit 0` validates here and fails at Graph instead of as a usage error."""
    doc, _ = built(commands, "calendar availability")
    assert doc["properties"]["interval"]["minimum"] == 5
    assert doc["properties"]["interval"]["maximum"] == 1440
    assert built(commands, "mail list")[0]["properties"]["limit"]["minimum"] == 1


def test_a_parameter_naming_a_local_file_is_confined(commands):
    """`--body-file` is typed `str`, so the Click type alone does not reveal it is a path."""
    doc = discover.spec_for("mail send", commands["mail send"])
    assert "body_file" in doc.path_params
    assert "attach" in doc.path_params


def test_every_at_file_convention_in_the_cli_is_declared():
    """A parameter that reads a file behind a leading `@` names a path the type does not reveal.

    `api --body @FILE` was such a parameter and escaped confinement; this fails if another
    appears without being declared in AT_FILE_PARAMS.
    """
    import re
    from pathlib import Path

    commands_dir = Path(__file__).resolve().parents[1] / "src" / "mgraphctl" / "commands"
    declared = {verb.split(" ")[-1] for verb in schema.AT_FILE_PARAMS}
    found = {
        path.stem.replace("_cmd", "")
        for path in commands_dir.glob("*.py")
        if re.search(r'startswith\(\s*[\'"]@[\'"]\s*\)', path.read_text())
    }
    assert found <= declared, f"modules using the @FILE convention but not declared: {found}"


def test_the_api_body_is_declared_as_an_at_file_parameter(app):
    spec = next(
        s for s in discover.discover(app, capabilities=["api"], allow_write=True) if s.path == "api"
    )
    assert spec.at_file_params == {"body"}


PATH_SHAPED = ("file", "path", "dir", "output", "photo", "attach")


def test_every_path_shaped_parameter_is_classified(app):
    """A new parameter naming a local file must be confined, or be declared a Graph path."""
    unclassified = []
    for spec in discover.discover(app, capabilities=discover.ALL, allow_write=True):
        exempt = schema.NOT_LOCAL_PATHS.get(spec.path, set())
        for name, node in spec.input_schema["properties"].items():
            if node.get("type") == "boolean":  # a flag names nothing
                continue
            if name in spec.path_params or name in exempt:
                continue
            if name in ("output_format", "output_file"):  # the server's own, not the verb's
                continue
            if any(token in name for token in PATH_SHAPED):
                unclassified.append(f"{spec.path}:{name}")
    assert not unclassified, (
        "path-shaped parameters that are neither confined nor declared a Graph path: "
        f"{sorted(unclassified)}"
    )
