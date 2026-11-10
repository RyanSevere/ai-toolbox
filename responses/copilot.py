#!/usr/bin/env python3
################################################################################
# File: copilot.py
# Path: {PROJECT_ROOT}/responses/copilot.py
# Created by: Ryan Severe
# Created: 2026-10-09
# Last Updated: 2026-11-06
# Description: The GitHub Copilot Chat adapter for the response checker.
#              Finds this session's transcript and turns its
#              user.message / assistant.message / tool.execution_* records into
#              Turns: subagent records dropped, a reply joined across its
#              messageIds, restarts and mid-turn messages detected.
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
import os
import re
from pathlib import Path
from typing import Mapping

import shape

NAME = "copilot"
# The turn being written is already in the transcript, so it can be graded in flight.
IN_FLIGHT = True
# The transcript records every run of this turn, and output reaches a terminal, so a
# run is spent only once its verdict was seen there.
LEDGER_COUNTS = False
NO_IDENTITY = ("UNKNOWN: no --session or --nonce, so there is no way to know which "
               "transcript is this session's. This is not a pass.")

TRANSCRIPT_GLOB = "*/GitHub.copilot-chat/transcripts/{name}.jsonl"
# Externally supplied, and both end up in a glob. Anything else is refused.
SESSION_ID = re.compile(r"[0-9A-Fa-f-]{8,64}")
NONCE = re.compile(r"[A-Za-z0-9_-]{6,64}")
NONCE_SCAN = 20

SUBAGENT_TOOL = re.compile(r"subagent", re.IGNORECASE)
TURN_RECORDS = ("assistant.turn_start", "assistant.turn_end")


def detect(env: Mapping[str, str]) -> bool:
    """Copilot hands each session its log path; nothing else sets this."""
    return bool(env.get("VSCODE_TARGET_SESSION_LOG"))


def identity(args, env: Mapping[str, str]) -> str | None:
    return args.session or args.nonce


def behind(path: Path) -> bool:
    """Never: Copilot flushes the turn being written to its transcript live."""
    return False


def first_turn(args, env: Mapping[str, str]) -> bool:
    """Never: the transcript exists from the session's first message."""
    return False


def locate(args, env: Mapping[str, str]) -> Path | None:
    if args.session:
        return session_transcript(args.session)
    if args.nonce:
        return nonce_transcript(args.nonce)
    return None


def transcripts_base() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Code/User/workspaceStorage"


def session_transcript(session: str) -> Path | None:
    """The transcript is named after the chat session id, which each Copilot session
    is handed as the last segment of VSCODE_TARGET_SESSION_LOG."""
    if not SESSION_ID.fullmatch(session):
        return None
    hits = list(transcripts_base().glob(TRANSCRIPT_GLOB.format(name=session)))
    return hits[0] if len(hits) == 1 else None


def nonce_transcript(nonce: str) -> Path | None:
    """The one recent transcript whose recorded commands contain this token.

    Commands are written to the transcript before they run, so the invocation
    carrying the nonce is always there to find. More than one match is refused -
    a reused token cannot identify anything.
    """
    if not NONCE.fullmatch(nonce):
        return None
    files = sorted(transcripts_base().glob(TRANSCRIPT_GLOB.format(name="*")),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:NONCE_SCAN]
    matches = [
        f for f in files
        if nonce in f.read_text(encoding="utf-8", errors="replace")
        and any(r.get("type") == "tool.execution_start"
                and nonce in str(r.get("data", {}).get("arguments", {}).get("command", ""))
                for r in read_records(f))
    ]
    return matches[0] if len(matches) == 1 else None


def read_records(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a partially flushed final line is expected, not an error
    return without_subagents(out)


def without_subagents(records: list[dict]) -> list[dict]:
    """Drop everything a subagent recorded between its call and its completion.

    Its prompt is written as a user.message and its answer as assistant.message, so
    left in, the prompt split the operator's turn in two and the answer was joined
    into the reply. A call with no completion is left alone: hiding
    records could grade the wrong reply, while keeping them risks only a false FAIL.
    """
    opened: dict[str, int] = {}
    inside: set[int] = set()
    for i, r in enumerate(records):
        data = r.get("data", {})
        call = data.get("toolCallId")
        if not call:
            continue
        if (r.get("type") == "tool.execution_start"
                and SUBAGENT_TOOL.search(str(data.get("toolName", "")))):
            opened[call] = i
        elif r.get("type") == "tool.execution_complete" and call in opened:
            inside.update(range(opened.pop(call) + 1, i))
    return [r for i, r in enumerate(records) if i not in inside]


def reply_text(records: list[dict], lo: int, hi: int, last_only: bool = False) -> str:
    """Assistant text in a slice, joined across every messageId it spans."""
    by_id: dict[str, list[str]] = {}
    order: list[str] = []
    for r in records[lo:hi]:
        if r.get("type") != "assistant.message":
            continue
        data = r.get("data", {})
        mid = data.get("messageId", "")
        if mid not in by_id:
            by_id[mid] = []
            order.append(mid)
        by_id[mid].append(data.get("content") or "")
    if last_only:
        return "".join(by_id[order[-1]]) if order else ""
    return "\n".join("".join(by_id[m]) for m in order)


def runs_in(records: list[dict], lo: int, hi: int) -> int:
    return sum(
        1
        for r in records[lo:hi]
        if r.get("type") == "tool.execution_start"
        and shape.INVOCATION.search(str(r.get("data", {}).get("arguments", {}).get("command", "")))
    )


def turn_bounds(records: list[dict]) -> list[tuple[int, int]]:
    starts = [i for i, rec in enumerate(records) if rec.get("type") == "user.message"]
    starts = sorted(set(starts) | set(restarted_turns(records))) or [0]
    edges = starts + [len(records)]
    return [(edges[i], edges[i + 1]) for i in range(len(starts))]


def restarted_turns(records: list[dict]) -> list[int]:
    """Turns whose operator message was never written.

    After a VS Code restart the transcript resumed with the turn counter back at 0 and
    no user.message before it. Every ordinary turn also resets the counter, but only
    straight after a user.message, so a drop to 0 with none since the last turn record
    is the only sign the operator spoke. The turn starts after that last record.
    """
    starts = []
    last = None
    last_turn = None
    since_user = False
    for i, rec in enumerate(records):
        kind = rec.get("type")
        if kind == "user.message":
            since_user = True
        elif kind in TURN_RECORDS:
            turn = str(rec.get("data", {}).get("turnId", ""))
            if turn == "0" and last_turn not in (None, "0") and not since_user:
                starts.append(last + 1)
            last, last_turn = i, turn
            since_user = False
    return starts


def cut_short(records: list[dict], start: int) -> bool:
    """Whether the user.message at start was sent before the turn it follows ended.

    An operator message is parented on assistant.turn_end. One parented on anything
    else arrived mid-turn, and that turn carried on after it, so the slice before it
    is narration rather than a reply. No resolvable parent keeps the
    old reading, because nothing says otherwise.
    """
    parent = records[start].get("parentId")
    if not parent:
        return False
    for r in reversed(records[:start]):
        if r.get("id") == parent:
            return r.get("type") != "assistant.turn_end"
    return False


def cut_short_backs(records: list[dict]) -> set[int]:
    """The look-back positions of slices a mid-turn message ended."""
    finished = turn_bounds(records)[:-1]
    return {len(finished) - 1 - j for j, (_, hi) in enumerate(finished)
            if cut_short(records, hi)}


def invoked_command(records: list[dict], lo: int) -> str | None:
    """The session command the turn starting at lo was opened with, if any."""
    first = records[lo] if lo < len(records) else {}
    if first.get("type") != "user.message":
        return None
    return shape.invoked_in(str(first.get("data", {}).get("content") or ""))


def turns(path: Path) -> list[shape.Turn]:
    """Every turn in the transcript. Copilot has no notification turns, so all are
    the operator's; the last is the one being written."""
    records = read_records(path)
    bounds = turn_bounds(records)
    return [
        shape.Turn(
            kind=shape.OPERATOR,
            text=reply_text(records, lo, hi),
            key=str(lo),
            invoked=invoked_command(records, lo),
            runs=runs_in(records, lo, hi),
            cut_short=i < len(bounds) - 1 and cut_short(records, hi),
            last=reply_text(records, lo, hi, last_only=True),
        )
        for i, (lo, hi) in enumerate(bounds)
    ]
