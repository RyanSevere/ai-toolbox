#!/usr/bin/env python3
################################################################################
# File: claude.py
# Path: {PROJECT_ROOT}/responses/claude.py
# Created by: Ryan Severe
# Created: 2026-11-13
# Last Updated: 2026-11-13
# Description: The Claude Code adapter for the response checker.
#              Finds the session's transcript from CLAUDE_CODE_SESSION_ID and
#              turns its one-line-per-content-block records into Turns. A turn
#              opens at an operator prompt, or at a background task's
#              notification; tool results, attachments and injected context stay
#              inside it. The reply is the text from the reply marker line to the
#              end of the turn, or, with no marker, the text after the turn's
#              last tool call, flagged. A turn with no end_turn text is cut short.
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
import sys
from pathlib import Path
from typing import Mapping

import shape

NAME = "claude"
# Claude Code writes each content block to the transcript as it is produced (observed
# 2026-11-13: the file's modification time matched the clock mid-turn), so the turn
# being written can be graded in flight.
IN_FLIGHT = True
# The transcript records this turn's own runs, and output reaches a terminal, so a
# run is spent only once its verdict was seen there.
LEDGER_COUNTS = False
NO_IDENTITY = ("UNKNOWN: CLAUDE_CODE_SESSION_ID is not set and no --session was given, so "
               "there is no way to know which transcript is this session's. This is not a pass.")

# The line that opens the final reply. The Claude Code addendum to the response shape
# names this constant, and a test keeps the two in step.
REPLY_MARKER = "=== REPLY STARTS HERE ==="
MARKER_MISSING = "reply marker missing"

# Externally supplied, and it ends up in a glob. Anything else is refused.
SESSION_ID = re.compile(r"[0-9A-Fa-f-]{8,64}")
# A turn opens at a user record with one of these origins: the operator typing, or a
# background task reporting back. Other user records are tool results or injected context.
OPENERS = {"human": shape.OPERATOR, "task-notification": shape.NOTIFICATION}


def detect(env: Mapping[str, str]) -> bool:
    """Claude Code sets this in every shell it runs."""
    return env.get("CLAUDECODE") == "1"


def identity(args, env: Mapping[str, str]) -> str | None:
    return args.session or env.get("CLAUDE_CODE_SESSION_ID") or None


def projects_base() -> Path:
    return Path.home() / ".claude" / "projects"


def locate(args, env: Mapping[str, str]) -> Path | None:
    """The one transcript named after this session's id, across every project folder.

    The folder is named after the directory the session started in, not the current
    one, so every folder is searched. A subagent's transcript sits a level deeper and
    never matches. Two matches identify nothing: both are named and neither is read.
    """
    session = identity(args, env)
    if not session or not SESSION_ID.fullmatch(session):
        return None
    hits = sorted(projects_base().glob(f"*/{session}.jsonl"))
    if len(hits) > 1:
        print(f"UNKNOWN: session {session} has a transcript in more than one project "
              f"folder: {hits[0]} and {hits[1]}"
              + (f" (and {len(hits) - 2} more)" if len(hits) > 2 else "")
              + ". Neither was read. This is not a pass.", file=sys.stderr)
    return hits[0] if len(hits) == 1 else None


def first_turn(args, env: Mapping[str, str]) -> bool:
    """Never: the transcript exists from the session's first prompt."""
    return False


def behind(path: Path) -> bool:
    """Never: Claude Code writes the turn being written to its transcript live."""
    return False


def read_records(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue  # a partially flushed final line is expected, not an error
        if isinstance(record, dict) and not record.get("isSidechain"):
            out.append(record)
    return out


def blocks(record: dict) -> list[dict]:
    content = (record.get("message") or {}).get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def opener(record: dict) -> str | None:
    """The kind of turn this record opens, or None for anything that stays inside one."""
    if record.get("type") != "user" or record.get("isMeta") or "toolUseResult" in record:
        return None
    if any(b.get("type") == "tool_result" for b in blocks(record)):
        return None
    return OPENERS.get((record.get("origin") or {}).get("kind"))


def prompt_text(record: dict) -> str:
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    return "\n".join(str(b.get("text") or "") for b in blocks(record) if b.get("type") == "text")


def ended(records: list[dict]) -> bool:
    """Whether the turn has a text block that closed it."""
    return any(
        r.get("type") == "assistant"
        and (r.get("message") or {}).get("stop_reason") == "end_turn"
        and any(b.get("type") == "text" for b in blocks(r))
        for r in records
    )


def reply_of(records: list[dict]) -> tuple[str, list[str]]:
    """The turn's reply and the findings about how it was found.

    From the last marker line to the end of the turn, across text blocks. With no
    marker, the text blocks after the last tool call, and a finding, so a forgotten
    marker is visible rather than silently absorbed.
    """
    items: list[str | None] = []  # a text block, or None for a tool call
    for record in records:
        if record.get("type") != "assistant":
            continue
        for block in blocks(record):
            if block.get("type") == "text":
                items.append(str(block.get("text") or ""))
            elif block.get("type") == "tool_use":
                items.append(None)
    lines = "\n".join(t for t in items if t is not None).split("\n")
    marks = [i for i, line in enumerate(lines) if line.strip() == REPLY_MARKER]
    if marks:
        return "\n".join(lines[marks[-1]:]), []
    after = items[max((i for i, t in enumerate(items) if t is None), default=-1) + 1:]
    text = "\n".join(after)
    return text, ([MARKER_MISSING] if text.strip() else [])


def runs_in(records: list[dict]) -> int:
    return sum(
        1
        for r in records
        if r.get("type") == "assistant"
        for b in blocks(r)
        if b.get("type") == "tool_use"
        and shape.INVOCATION.search(str((b.get("input") or {}).get("command", "")))
    )


def turns(path: Path) -> list[shape.Turn]:
    """Every turn, in order; the last is the one being written.

    A turn without end_turn text was interrupted or is still being written. A finished
    one that is cut short has no reply, so the look-back skips it; the last is never
    marked, because its reply is read as it grows. The key is the turn's position.
    """
    records = read_records(path)
    starts = [i for i, r in enumerate(records) if opener(r)]
    if not starts:
        return [shape.Turn(shape.OPERATOR, "", "t0")]
    edges = starts + [len(records)]
    out = []
    for position, (lo, hi) in enumerate(zip(edges, edges[1:])):
        span = records[lo:hi]
        current = position == len(starts) - 1
        cut = not current and not ended(span)
        text, findings = ("", []) if cut else reply_of(span)
        out.append(shape.Turn(
            kind=opener(records[lo]),
            text=text,
            key=f"t{position}",
            invoked=shape.invoked_in(prompt_text(records[lo])),
            runs=runs_in(span),
            cut_short=cut,
            last=text,
            findings=findings,
        ))
    return out
