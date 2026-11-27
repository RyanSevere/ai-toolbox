#!/usr/bin/env python3
################################################################################
# File: hook.py
# Path: {PROJECT_ROOT}/.claude/hooks/title-prefix/hook.py
# Created by: Ryan Severe
# Created: 2026-11-21
# Last Updated: 2026-11-26
# Description: Claude Code Stop hook. Reads the session's latest title from the
#              transcript and grades its status prefix against the reply, by the
#              rules in prefixes.yaml beside this file. A stale prefix sends the
#              turn back once. Its own failure, a missing vocabulary, or the off
#              switch never blocks the turn.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import hookio  # noqa: E402  - the shared runtime library, rendered beside this hook's folder

# The vocabulary, rendered beside this file.
PREFIXES = Path(__file__).resolve().parent / "prefixes.yaml"
TITLE_TOOL = "mcp__ccd_session_mgmt__set_session_title"
REPLY_MARKER = "=== REPLY STARTS HERE ==="
# An ask is a line that opens with a DC, Q or OS item ID, after any list marker. The ID form is
# carried from the response checker's ITEM_START and QUESTION patterns in responses/shape.py,
# which this hook cannot import (it is rendered into a different tree), with the number
# narrowed to 1 or more.
ASK_ITEM = re.compile(r"^(?:(?:[-*]|\d+\.)\s+)?(?:DC|Q|OS)[1-9]\d*\b")
SEPARATOR = " - "
SEND_BACK = 2


def latest_title(transcript: Path) -> str | None:
    """The title of the last set_session_title call for "self", or None when there is none.
    OSError when the transcript cannot be read."""
    title = None
    with transcript.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            message = entry.get("message") if isinstance(entry, dict) else None
            blocks = message.get("content") if isinstance(message, dict) else None
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not (isinstance(block, dict) and block.get("type") == "tool_use"
                        and block.get("name") == TITLE_TOOL):
                    continue
                args = block.get("input")
                if (isinstance(args, dict) and args.get("session_id") == "self"
                        and isinstance(args.get("title"), str)):
                    title = args["title"]
    return title


def has_ask(reply: str) -> bool:
    """True when a line after the last reply marker (the whole reply with no marker) opens with
    an ask's item ID, outside fenced code blocks."""
    lines = reply.split("\n")
    marks = [i for i, line in enumerate(lines) if line.strip() == REPLY_MARKER]
    if marks:
        lines = lines[marks[-1]:]
    fenced = False
    for line in lines:
        text = line.strip()
        if text.startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and ASK_ITEM.match(text):
            return True
    return False


def load_entries(path: Path) -> list[dict]:
    """The vocabulary entries in file order. OSError or ValueError when unusable."""
    import yaml  # not at import: a missing library must be a reported failure, not a crash

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"not valid YAML: {exc}") from exc
    entries = data.get("prefixes") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError("no prefixes list")
    for entry in entries:
        if not (isinstance(entry, dict) and entry.get("rule") in ("ask", "no-ask", "unchecked")
                and (isinstance(entry.get("prefix"), str) or isinstance(entry.get("pattern"), str))):
            raise ValueError(f"bad entry {entry!r}")
    return entries


def match(entries: list[dict], prefix: str) -> dict | None:
    """The first entry that matches the prefix, case-insensitively."""
    for entry in entries:
        if "prefix" in entry and prefix.lower() == entry["prefix"].lower():
            return entry
        if "pattern" in entry and re.fullmatch(entry["pattern"], prefix, re.IGNORECASE):
            return entry
    return None


def main() -> int:
    if hookio.hooks_off():
        return 0
    payload, problem = hookio.read_payload(sys.stdin.buffer)
    if payload is None:
        print(f"title-prefix: unreadable payload ({problem}), so the title was not graded",
              file=sys.stderr)
        return 0
    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not transcript:
        print("title-prefix: no transcript_path in the payload, so the title was not graded",
              file=sys.stderr)
        return 0
    try:
        title = latest_title(Path(transcript))
    except OSError as exc:
        print(f"title-prefix: transcript unreadable ({exc}), so the title was not graded",
              file=sys.stderr)
        return 0
    if title is None:
        return 0
    try:
        entries = load_entries(PREFIXES)
    except (OSError, ValueError, ImportError, re.error) as exc:
        print(f"title-prefix: prefixes.yaml unusable ({exc}), so the title was not graded",
              file=sys.stderr)
        return 0
    prefix = title.split(SEPARATOR, 1)[0].strip()
    entry = match(entries, prefix)
    if entry is None or entry["rule"] == "unchecked":
        return 0
    reply = payload.get("last_assistant_message")
    if not isinstance(reply, str):
        print("title-prefix: no last_assistant_message, so the title was not graded",
              file=sys.stderr)
        return 0
    asks = has_ask(reply)
    if entry["rule"] == "ask" and not asks:
        wrong = "the reply carries no open ask, but this prefix says the operator is needed"
    elif entry["rule"] == "no-ask" and asks:
        wrong = "the reply carries an open ask, but this prefix says nothing is needed"
    else:
        return 0
    label = entry.get("label") or entry.get("prefix")
    print(f"title-prefix: the session title starts '{prefix}' ({label}), but {wrong}. Re-set "
          "the title with a prefix that matches this reply, or change the reply.",
          file=sys.stderr)
    return 0 if payload.get("stop_hook_active") is True else SEND_BACK


if __name__ == "__main__":
    sys.exit(main())
