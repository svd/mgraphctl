from mgraphctl import config, errors


def test_hints_resolve_shim_path_lazily(monkeypatch):
    before = errors.HINTS["NOT_LOGGED_IN"]
    monkeypatch.setattr(config, "shim_path", lambda: "/patched/mgraphctl")
    after = errors.HINTS["NOT_LOGGED_IN"]
    assert after != before
    assert "/patched/mgraphctl login" in after
    assert "/patched/mgraphctl" in errors.hint_for("NOT_LOGGED_IN", None)


def test_hierarchy_exit_codes():
    assert errors.UsageError("USAGE", "x").exit_code == 2
    assert errors.AuthError("NOT_LOGGED_IN", "x").exit_code == 3
    assert errors.NotFoundError("NOT_FOUND", "x").exit_code == 4
    assert errors.AmbiguousError("AMBIGUOUS", "x", candidates=[("1", "a")]).exit_code == 2
    body = (
        b'{"error":{"code":"ErrorItemNotFound","message":"gone","innerError":{"request-id":"r-1"}}}'
    )
    e = errors.graph_error_from_response(
        404,
        {"content-type": "application/json"},
        body,
        "https://graph.microsoft.com/v1.0/me/messages/x",
    )
    assert (e.status, e.code, e.message, e.request_id, e.exit_code) == (
        404,
        "ErrorItemNotFound",
        "gone",
        "r-1",
        4,
    )
    assert errors.graph_error_from_response(403, {}, b"nope", "u").exit_code == 3
    assert errors.graph_error_from_response(401, {}, b"", "u").exit_code == 3
    e = errors.graph_error_from_response(500, {}, b"<html>x</html>", "u")
    assert (e.code, e.exit_code, e.message) == ("HTTP_500", 1, "<html>x</html>")


def test_format_error_block():
    e = errors.GraphError(404, "ErrorItemNotFound", "gone", request_id="r-1", url="u", body=None)
    expected_e = (
        "error[ErrorItemNotFound]: gone\n"
        "  request-id: r-1\n"
        "  hint: check the id; ids returned by 'mail move' change\n"
    )
    assert errors.format_error(e) == expected_e
    a = errors.AmbiguousError(
        "AMBIGUOUS", "team 'Eng' matches 2 teams", candidates=[("id-1", "Eng"), ("id-2", "eng")]
    )
    expected_a = (
        "error[AMBIGUOUS]: team 'Eng' matches 2 teams\n"
        "  candidate: id-1  Eng\n"
        "  candidate: id-2  eng\n"
    )
    assert errors.format_error(a) == expected_a


def test_hints_cover_spec_codes():
    for code in (
        "NOT_LOGGED_IN",
        "UNAUTHORIZED",
        "MISSING_SCOPE",
        "CONSENT_REQUIRED",
        "NOT_FOUND",
        "THROTTLED",
        "InefficientFilter",
        "UPLOAD_SESSION_LOST",
        "NETWORK",
    ):
        assert code in errors.HINTS
    assert errors.hint_for("Whatever", 429) == errors.HINTS["THROTTLED"]
