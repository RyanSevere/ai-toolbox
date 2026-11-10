#!/usr/bin/env python3
################################################################################
# File: cursor.py
# Path: {PROJECT_ROOT}/responses/cursor.py
# Created by: Ryan Severe
# Created: 2026-10-09
# Last Updated: 2026-11-06
# Description: The Cursor adapter for the response checker.
#              Finds the chat's transcript from CURSOR_CONVERSATION_ID and turns
#              its role/message records into Turns. A Cursor turn is one long
#              stream of progress notes and tool calls ending in the reply, and
#              a background task can open a notification turn, graded like any
#              other. An aborted turn has no reply. A turn is keyed by its
#              position.
################################################################################
# ===========================================================================
#
#
#            "~,
#                *m,
#                   *9m;
#                       *%pg
#                          "YRWu
#                              *9$&w
#                                  *R$&w
#   ;j]@@W;                   *w,      79&&w;
#   :|*%MT"                     7&&w,      ?78BWw
# . ,|*       -p     ~            *R$$$gw,     '*MU@m,
#            =W/?*%NMWgw             *T&$F ,@w;     "*4[%m,
#              7R$$$$$$$$g          yg$$Gg$@@Hh!j ,w     "*w|j=,
#       ..     ]K@ww[T$Fff            >*MB&&@@Hh ]hk{!!~^     "*v'
#          '|;, *M@@&&$P                 $$&@HHH\  ` ;w,,   ,~""
#            "|jj]]%@F"                  ]$@@H, ;*M%P)a$$C  c
#           . :|j[M"                     ]@@HHr TfR4&$NE*,/~<'
#             `!||j]@@@A`                ]@@Hh~ *TT"" "* ^ r  '~
#                *ojKM"                  l@Hh~  "*|"'   /        `
#                                        @HHkC ,;!"
#                                       ]HHhr/|!"'
#                                       #Hhr!||"
#                             ,@r       hkr!||'
#                                      [k{|!"
#                                     (r!!"        r
#                                     !!"        r
#                                      ";      /
#                                             '
#                                            '
# ===========================================================================


from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping

import shape

NAME = "cursor"
# The turn being written reaches the transcript only when it ends - 2026-10-09, the
# file stayed at 176 lines across three tool calls - so there is nothing in flight.
IN_FLIGHT = False
# The current turn's own runs are not in the transcript either, and the shell is never
# a TTY, so the ledger alone counts this turn's runs.
LEDGER_COUNTS = True
NO_IDENTITY = ("UNKNOWN: CURSOR_CONVERSATION_ID is not set and no --session was given, so "
               "there is no way to know which transcript is this chat's. This is not a pass.")

CONVERSATION_ID = re.compile(r"[0-9A-Fa-f-]{8,64}")
QUERY = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.DOTALL)
# The fixed text of a background-task completion, copied from the transcript.
NOTIFICATION = ("Briefly inform the user about the task result and perform any follow-up "
                "actions (if needed).")


def detect(env: Mapping[str, str]) -> bool:
    return bool(env.get("CURSOR_AGENT"))


def identity(args, env: Mapping[str, str]) -> str | None:
    return args.session or env.get("CURSOR_CONVERSATION_ID") or None


def projects_base() -> Path:
    return Path.home() / ".cursor" / "projects"


def cwd() -> Path:
    return Path.cwd()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def first_turn(args, env: Mapping[str, str]) -> bool:
    """Whether a missing transcript is this chat's first turn.

    Cursor writes a chat's transcript when its first turn ends, so the first reply
    finds no file. That reads as a first turn only for an
    id from CURSOR_CONVERSATION_ID, never a typed --session, and only where this
    workspace's transcript folder already holds other chats - Cursor's own name for
    the folder is the working directory with every non-alphanumeric run made '-'.
    Anything that does not match stays UNKNOWN.
    """
    chat = env.get("CURSOR_CONVERSATION_ID")
    if args.session or not chat or not CONVERSATION_ID.fullmatch(chat):
        return False
    if list(projects_base().glob(f"*/agent-transcripts/{chat}/{chat}.jsonl")):
        return False
    here = slug(str(cwd()))
    for project in projects_base().iterdir():
        folder = project / "agent-transcripts"
        if slug(project.name) == here and folder.is_dir():
            return any(p.is_dir() and p.name != chat for p in folder.iterdir())
    return False


def locate(args, env: Mapping[str, str]) -> Path | None:
    """The one transcript named after this chat's id, across every workspace."""
    chat = identity(args, env)
    if not chat or not CONVERSATION_ID.fullmatch(chat):
        return None
    hits = list(projects_base().glob(f"*/agent-transcripts/{chat}/{chat}.jsonl"))
    return hits[0] if len(hits) == 1 else None


def read_records(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a partially flushed final line is expected, not an error
    return out


def behind(path: Path) -> bool:
    """Whether the file has not caught up with the turn running the check.

    The check always runs inside a turn that has started, and a running turn has no
    turn_ended of its own. One after the last user query means the current turn is
    not on disk yet, and reading it would take the previous turn as this one. Not
    only the last record: an aborted turn is followed by an orphan assistant record.
    Transcripts written before Cursor added turn_ended records never read as behind.
    """
    records = read_records(path)
    starts = [i for i, r in enumerate(records) if query(r) is not None]
    return any(r.get("type") == "turn_ended" for r in records[starts[-1] if starts else 0:])


def blocks(record: dict) -> list[dict]:
    content = (record.get("message") or {}).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def query(record: dict) -> str | None:
    """The operator's text, or None for a user record that is injected context."""
    if record.get("role") != "user":
        return None
    for block in blocks(record):
        match = QUERY.search(str(block.get("text") or "")) if block.get("type") == "text" else None
        if match:
            return match.group(1)
    return None


def aborted(records: list[dict]) -> bool:
    """Whether a turn's records end it in an abort or error.

    The first turn_ended decides. A finished turn is often followed by a stray abort
    record before the next query, and an aborted one by an orphan assistant record;
    neither later record changes how the turn ended.
    """
    ended = next((r for r in records if r.get("type") == "turn_ended"), None)
    return ended is not None and ended.get("status") != "success"


def turns(path: Path) -> list[shape.Turn]:
    """Every turn, opened by a record carrying a user query. The reply is the turn's
    last text block; everything before it is progress notes between tool calls. An
    aborted turn has no reply, so the look-back skips it.

    The key is the turn's position, not its record index: summarizing a chat rewrites
    the transcript without earlier turns' turn_ended records, which moves every later
    index and keeps every user record. The prefix keeps it apart from
    the index keys already in a chat's ledger, which would otherwise name other turns."""
    records = read_records(path)
    starts = [i for i, r in enumerate(records) if query(r) is not None] or [0]
    edges = starts + [len(records)]
    out = []
    for position, (lo, hi) in enumerate(zip(edges, edges[1:])):
        message = query(records[lo]) or ""
        cut = aborted(records[lo:hi])
        texts: list[str] = []
        runs = 0
        for record in records[lo:hi]:
            if record.get("role") != "assistant":
                continue
            for block in blocks(record):
                if block.get("type") == "text":
                    texts.append(str(block.get("text") or ""))
                elif block.get("type") == "tool_use" and shape.INVOCATION.search(
                        str((block.get("input") or {}).get("command", ""))):
                    runs += 1
        reply = texts[-1] if texts and not cut else ""
        out.append(shape.Turn(
            kind=shape.NOTIFICATION if message == NOTIFICATION else shape.OPERATOR,
            text=reply,
            key=f"t{position}",
            invoked=shape.invoked_in(message),
            runs=runs,
            last=reply,
        ))
    return out
