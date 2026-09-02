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
