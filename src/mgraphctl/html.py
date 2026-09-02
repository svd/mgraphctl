"""HTML → Markdown, plain text → HTML and WebVTT → text conversion (spec §6.2, §7.1)."""

from __future__ import annotations

import html as html_stdlib
import re
from typing import Literal

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

_HOSTED_CONTENT_RE = re.compile(r"/hostedContents/([^/]+)/\$value")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n{2,}")
_CUE_TIMING_RE = re.compile(r"^(\d{2}:\d{2}:\d{2})\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}")
_VOICE_RE = re.compile(r"^<v\s+([^>]+)>(.*)</v>$", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

_CONVERT_OPTIONS = {
    "heading_style": "ATX",
    "bullets": "-",
    "escape_underscores": False,
    "escape_asterisks": False,
}


class _TeamsConverter(MarkdownConverter):
    """Renders Teams-specific markup: mentions, attachments, hosted images, system events."""

    def convert_at(self, el, text, parent_tags):
        return f"@{text}"

    def convert_attachment(self, el, text, parent_tags):
        name = el.attrs.get("name") or el.attrs.get("id") or ""
        return f"[attachment: {name}]"

    def convert_img(self, el, text, parent_tags):
        src = el.attrs.get("src") or ""
        match = _HOSTED_CONTENT_RE.search(src)
        if match:
            return f"[image: hostedContents/{match.group(1)}]"
        return super().convert_img(el, text, parent_tags)

    def convert_systemeventmessage(self, el, text, parent_tags):
        return "[system event]"


def to_markdown(html: str, mode: Literal["teams", "onenote", "mail"]) -> str:
    """Convert a Graph HTML body to Markdown, applying Teams markers only in "teams" mode."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(("style", "script")):
        tag.decompose()
    converter_cls = _TeamsConverter if mode == "teams" else MarkdownConverter
    text = converter_cls(**_CONVERT_OPTIONS).convert_soup(soup)
    return _BLANK_LINES_RE.sub("\n\n", text).strip()


def text_to_html(text: str) -> str:
    """Convert plain text to escaped HTML: blank-line-separated `<p>`, `<br>` within a paragraph."""
    paragraphs = _PARAGRAPH_SPLIT_RE.split(text)
    rendered = []
    for paragraph in paragraphs:
        lines = paragraph.split("\n")
        escaped = "<br>".join(html_stdlib.escape(line) for line in lines)
        rendered.append(f"<p>{escaped}</p>")
    return "".join(rendered)


def vtt_to_text(vtt: str) -> str:
    """Convert a WebVTT transcript to `[HH:MM:SS] Speaker: text` lines, one per cue."""
    lines_out = []
    for block in _PARAGRAPH_SPLIT_RE.split(vtt.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        timing_idx = next(
            (i for i, ln in enumerate(lines) if _CUE_TIMING_RE.match(ln.strip())), None
        )
        if timing_idx is None:
            continue
        stamp = _CUE_TIMING_RE.match(lines[timing_idx].strip()).group(1)
        rendered = []
        for text_line in lines[timing_idx + 1 :]:
            voice = _VOICE_RE.match(text_line.strip())
            if voice:
                name, content = voice.groups()
                rendered.append(f"{name}: {_TAG_RE.sub('', content).strip()}")
            else:
                rendered.append(_TAG_RE.sub("", text_line).strip())
        lines_out.append(f"[{stamp}] {' '.join(rendered)}")
    return "\n".join(lines_out)
