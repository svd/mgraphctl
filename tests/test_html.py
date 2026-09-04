"""HTML → Markdown, text → HTML and VTT → text (spec §6.2, §7.1)."""

from mgraphctl import html

TEAMS = (
    '<div><style>p{color:red}</style><p>Hi <at id="0">Ada Example</at>, see '
    '<attachment id="a1" name="plan.docx"></attachment> and '
    '<img src="https://graph.microsoft.com/v1.0/chats/19:c@thread.v2/messages/1/'
    'hostedContents/aWQ=/$value" width="10">'
    "</p><p></p><p></p><p>Done &amp; dusted</p><systemEventMessage/></div>"
)


def test_to_markdown_teams_markers():
    md = html.to_markdown(TEAMS, "teams")
    assert (
        "@Ada Example" in md
        and "[attachment: plan.docx]" in md
        and "[image: hostedContents/aWQ=]" in md
    )
    assert "[system event]" in md and "color:red" not in md and "Done & dusted" in md
    assert "\n\n\n" not in md


def test_to_markdown_mail_keeps_at_text_and_links():
    md = html.to_markdown(
        '<p><b>Bold</b> <a href="https://example.com/x">link</a> <at id="1">Ada</at></p>'
        "<script>x()</script>",
        "mail",
    )
    assert md == "**Bold** [link](https://example.com/x) Ada"


def test_to_markdown_onenote_headings():
    assert (
        html.to_markdown("<html><body><h1>Title</h1><p>Body</p></body></html>", "onenote")
        == "# Title\n\nBody"
    )


def test_text_to_html_escapes_and_paragraphs():
    assert html.text_to_html("a <b>\nc\n\nd & e") == "<p>a &lt;b&gt;<br>c</p><p>d &amp; e</p>"


def test_vtt_to_text():
    vtt = (
        "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\n<v Ada Example>Hello there</v>\n\n"
        "00:00:03.500 --> 00:00:05.000\nplain line\n"
    )
    assert html.vtt_to_text(vtt) == "[00:00:01] Ada Example: Hello there\n[00:00:03] plain line"


def test_vtt_to_speaker_turns_merges_consecutive_cues_from_one_speaker():
    vtt = (
        "WEBVTT\n\n"
        "1\n00:00:01.000 --> 00:00:03.000\n<v Ada Example>Hello there</v>\n\n"
        "2\n00:00:03.000 --> 00:00:05.000\n<v Ada Example>and one more thing</v>\n\n"
        "3\n00:00:05.000 --> 00:00:07.000\n<v Bob Example>Agreed</v>\n\n"
        "4\n00:00:07.000 --> 00:00:09.000\n<v Ada Example>Good</v>\n"
    )
    assert html.vtt_to_speaker_turns(vtt) == (
        "**Ada Example:** Hello there and one more thing\n\n"
        "**Bob Example:** Agreed\n\n"
        "**Ada Example:** Good"
    )


def test_vtt_to_speaker_turns_continues_a_turn_through_an_untagged_line():
    vtt = (
        "WEBVTT\n\n"
        "1\n00:00:01.000 --> 00:00:03.000\n<v Ada Example>Hello</v>\n\n"
        "2\n00:00:03.000 --> 00:00:05.000\nstill Ada\n"
    )
    assert html.vtt_to_speaker_turns(vtt) == "**Ada Example:** Hello still Ada"


def test_vtt_to_speaker_turns_renders_an_unattributed_opening_without_a_label():
    vtt = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\nnobody said this\n"
    assert html.vtt_to_speaker_turns(vtt) == "nobody said this"


def test_vtt_to_speaker_turns_and_vtt_to_text_read_the_same_cues():
    """The two renderers share one parser, so neither can drift from the other."""
    vtt = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\n<v Ada>x</v>\n<v Bob>y</v>\n"
    assert html.vtt_to_text(vtt) == "[00:00:01] Ada: x Bob: y"
    assert html.vtt_to_speaker_turns(vtt) == "**Ada:** x\n\n**Bob:** y"


def test_vtt_to_text_keeps_a_speaker_name_exactly_as_the_tag_spelled_it():
    """Only turn-merging, which compares names, normalises them."""
    vtt = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\n<v Ada Example >Hi</v>\n"
    assert html.vtt_to_text(vtt) == "[00:00:01] Ada Example : Hi"
    assert html.vtt_to_speaker_turns(vtt) == "**Ada Example:** Hi"


def test_vtt_to_speaker_turns_merges_across_inconsistent_tag_spacing():
    vtt = (
        "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\n<v Ada>one</v>\n\n"
        "2\n00:00:03.000 --> 00:00:05.000\n<v Ada >two</v>\n"
    )
    assert html.vtt_to_speaker_turns(vtt) == "**Ada:** one two"
