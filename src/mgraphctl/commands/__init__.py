"""The noun registry. Phase 1 tasks add `commands/<noun>.py`; they never edit this file.

A module that does not exist yet is skipped, so the CLI is usable at every point of the build.
A module that does exist must expose `app: typer.Typer` (kind "group") or `command: Callable`
(kind "command").
"""

import importlib
import logging
from dataclasses import dataclass
from typing import Literal

import typer

log = logging.getLogger("mgraphctl.commands")


@dataclass(frozen=True)
class Noun:
    name: str
    module: str
    help: str
    kind: Literal["group", "command"] = "group"


NOUNS: list[Noun] = [
    Noun("mail", "mgraphctl.commands.mail", "Outlook mail."),
    Noun(
        "mailbox",
        "mgraphctl.commands.mailbox",
        "Mailbox settings, automatic replies, focused inbox.",
    ),
    Noun(
        "calendar", "mgraphctl.commands.calendar", "Calendar events, availability, meeting times."
    ),
    Noun("people", "mgraphctl.commands.people", "People, contacts and directory users."),
    Noun("org", "mgraphctl.commands.org", "Manager, direct reports, management chain."),
    Noun("groups", "mgraphctl.commands.groups", "Microsoft 365 groups."),
    Noun("teams", "mgraphctl.commands.teams", "Teams and channels."),
    Noun("chats", "mgraphctl.commands.chats", "Teams chats and direct messages."),
    Noun("presence", "mgraphctl.commands.presence", "Teams presence."),
    Noun("meetings", "mgraphctl.commands.meetings", "Online meetings, transcripts, AI insights."),
    Noun("onedrive", "mgraphctl.commands.onedrive", "OneDrive files."),
    Noun("sharepoint", "mgraphctl.commands.sharepoint", "SharePoint sites, drives and lists."),
    Noun("onenote", "mgraphctl.commands.onenote", "OneNote notebooks and pages."),
    Noun("planner", "mgraphctl.commands.planner", "Planner plans and tasks."),
    Noun("todo", "mgraphctl.commands.todo", "Microsoft To Do."),
    Noun(
        "search",
        "mgraphctl.commands.search",
        "Unified search across Microsoft 365.",
        kind="command",
    ),
]


def register_all(root: typer.Typer) -> None:
    """Attach every noun that has a module. Missing modules are a debug line, not an error."""
    for noun in NOUNS:
        try:
            module = importlib.import_module(noun.module)
        except ModuleNotFoundError as exc:
            # Only the noun's own module may be missing; a broken import inside it must surface.
            if exc.name != noun.module:
                raise
            log.debug("noun %s not implemented yet", noun.name)
            continue
        if noun.kind == "command":
            root.command(noun.name, help=noun.help)(module.command)
        else:
            root.add_typer(module.app, name=noun.name, help=noun.help)
