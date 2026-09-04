#!/usr/bin/env python3
"""Scan tracked text files for credentials.

A backstop for review, not a replacement for it. The recorded Graph fixtures under `tests/`
are the likely leak path: a real bearer token or client secret pasted into a recording.
Stdlib only, so CI needs no `uv sync` to run it.

Usage: python3 scripts/scan_secrets.py [paths...]   (default: all git-tracked files)
"""

import re
import subprocess
import sys
from pathlib import Path

SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".ico", ".woff", ".woff2"}
SELF = "scan_secrets.py"

PATTERNS = [
    ("AWS access key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("GitLab token", re.compile(r"glpat-[A-Za-z0-9_-]{20,}")),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenAI API key", re.compile(r"sk-[A-Za-z0-9]{32,}")),
    ("Slack token", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # Microsoft identity tokens (access, id, refresh) are JWTs.
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    (
        "assigned secret",
        re.compile(
            r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|"
            r"client[_-]?secret)\b\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"
        ),
    ),
]


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, text=True, check=True
    ).stdout
    return [Path(p) for p in out.split("\0") if p]


def scan(path):
    if path.suffix.lower() in SKIP_SUFFIXES or path.name == SELF:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []  # binary or unreadable; nothing to scan

    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for label, pattern in PATTERNS:
            if pattern.search(line):
                hits.append((path, lineno, label, line.strip()[:120]))
    return hits


def main(argv):
    paths = [Path(p) for p in argv[1:]] or tracked_files()
    hits = [hit for path in paths if path.is_file() for hit in scan(path)]

    for path, lineno, label, snippet in hits:
        print(f"ERROR: {path}:{lineno}: possible {label}: {snippet}")

    if hits:
        print(
            f"\n{len(hits)} potential secret(s) found. Remove them, or narrow the pattern "
            f"in {SELF} if this is a false positive."
        )
        return 1

    print(f"No secrets found in {len(paths)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
