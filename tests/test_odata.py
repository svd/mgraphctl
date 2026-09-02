from mgraphctl import odata


def test_p_encodes_every_segment():
    assert (
        odata.p("me", "mailFolders", "Sent Items/2026#1'x")
        == "/me/mailFolders/Sent%20Items%2F2026%231%27x"
    )


def test_query_uses_percent20_never_plus_and_drops_none():
    q = odata.query(
        {"$select": "id,subject", "$search": '"from:a b"', "$count": True, "skip": None}
    )
    assert q == "$select=id%2Csubject&$search=%22from%3Aa%20b%22&$count=true"
    assert "+" not in q


def test_with_query_omits_question_mark_when_empty():
    assert odata.with_query("/me", {}) == "/me"
    assert odata.with_query("/me", {"$top": 5}) == "/me?$top=5"


def test_kql_joins_and_quotes():
    assert odata.kql("from:x", "received>=2026-08-01") == '"from:x AND received>=2026-08-01"'


def test_odata_str_doubles_quotes():
    assert odata.odata_str("O'Brien") == "O''Brien"


def test_share_id_known_vector():
    assert odata.share_id("https://example.com/a") == "u!aHR0cHM6Ly9leGFtcGxlLmNvbS9h"


def test_drive_path_quotes_segments():
    assert odata.drive_path("Docs/Q3 plan.docx") == "Docs/Q3%20plan.docx"


def test_site_ref_forms():
    assert (
        odata.site_ref("https://contoso.example/sites/Eng Team/Shared")
        == "/sites/contoso.example:/sites/Eng%20Team"
    )
    assert (
        odata.site_ref("https://contoso.example/teams/ops") == "/sites/contoso.example:/teams/ops"
    )
    assert odata.site_ref("https://contoso.example/") == "/sites/contoso.example"
    assert odata.site_ref("contoso.example:/sites/a b") == "/sites/contoso.example:/sites/a%20b"
    composite_id = (
        "contoso.example,11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222"
    )
    assert odata.site_ref(composite_id) == f"/sites/{composite_id}"
    assert odata.site_ref("root") == "/sites/root"
