#!/usr/bin/env python3
################################################################################
# File: check_response.py
# Path: {PROJECT_ROOT}/responses/check_response.py
# Created by: Ryan Severe
# Created: 2026-10-09
# Last Updated: 2026-11-13
# Description: Checks assistant replies against the response shape in
#              rules/spec-response-shape.md, rendered into each repo as
#              .github/rules/response-shape.md. The entry point of a shared
#              shape core and one adapter per tool: it works out
#              which tool is running, has that adapter read the live transcript,
#              and owns the run budget. Structural only - it never judges
#              whether a claim is true. Replaces the single-file checker of
#              2026-09-22. --stop is the mode for a Claude Code Stop hook.
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

import argparse
import contextlib
import dataclasses
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

import claude  # noqa: E402
import copilot  # noqa: E402
import cursor  # noqa: E402
import shape  # noqa: E402

ADAPTERS = {adapter.NAME: adapter for adapter in (claude, copilot, cursor)}
RUN_LIMIT = 2
# Look-back grades a reply that is already posted, so a re-run cannot start a
# check-and-revise loop. One run per turn kept refusing a re-run the operator could not
# use (operator 2026-11-13).
PREVIOUS_RUN_LIMIT = 3
# A transcript that has not caught up is re-read for up to BEHIND_POLLS x BEHIND_SECONDS
# before giving up.
BEHIND_POLLS = 10
BEHIND_SECONDS = 0.5


def detect(env: Mapping[str, str]) -> str | None:
    """The one tool whose markers are set. Cursor also sets VSCODE_* variables, so each
    adapter names a marker only its tool sets; none or several is refused, not guessed."""
    found = [name for name, adapter in ADAPTERS.items() if adapter.detect(env)]
    return found[0] if len(found) == 1 else None


def verdictless_ledger(transcript: Path) -> Path:
    """Where runs that produced no verdict are recorded, per transcript.

    The transcript marks every run success: true whatever its exit code, so it
    cannot tell an UNKNOWN from a grade. Only this script knows.
    """
    return Path(tempfile.gettempdir()) / "check_response" / f"{transcript.stem}.json"


def verdictless_runs(transcript: Path, key: str) -> int:
    """Unreadable means 0, which restores the old count - never a larger budget."""
    try:
        data = json.loads(verdictless_ledger(transcript).read_text(encoding="utf-8"))
        return max(0, int(data.get(key, 0)))
    except (OSError, ValueError, AttributeError, TypeError):
        return 0


def record_verdictless(transcript: Path, key: str) -> None:
    path = verdictless_ledger(transcript)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[key] = verdictless_runs(transcript, key) + 1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError as exc:
        print(f"[WARN] could not record the verdictless run, so it will count "
              f"against this turn's limit: {exc}", file=sys.stderr)


def run_ledger(transcript: Path) -> Path:
    """--previous runs started and delivered, per turn. PREVIOUS_RUN_LIMIT successful runs per turn, so a
    run whose verdict was never seen does not spend it."""
    return Path(tempfile.gettempdir()) / "check_response" / f"{transcript.stem}.runs.json"


def read_run_ledger(transcript: Path) -> dict | None:
    """None when the ledger exists but cannot be read - the caller then counts strictly."""
    path = run_ledger(transcript)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def ledger_count(transcript: Path, key: str, *fields: str) -> int | None:
    """The first field minus the rest, for this turn. None if the ledger is unreadable."""
    data = read_run_ledger(transcript)
    if data is None:
        return None
    entry = data.get(key) or {}
    try:
        counts = [int(entry.get(f, 0)) for f in fields]
    except (AttributeError, TypeError, ValueError):
        return None
    return max(0, counts[0] - sum(counts[1:]))


def record_run(transcript: Path, key: str, field: str) -> None:
    data = read_run_ledger(transcript)
    if data is None:
        return  # already unreadable: every run counts, so nothing to add
    entry = data.get(key)
    entry = entry if isinstance(entry, dict) else {}
    entry[field] = int(entry.get(field, 0)) + 1
    data[key] = entry
    try:
        path = run_ledger(transcript)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError as exc:
        print(f"[WARN] could not record this run, so it counts against the limit: {exc}",
              file=sys.stderr)


def finish_previous_run(transcript: Path, key: str, adapter) -> None:
    """A verdict only counts once it can have been read. Piped or captured output can
    be cut off before the verdict line, as happened 2026-09-29. A tool whose shell is
    never a terminal counts a run that reached its end, or nothing would ever count."""
    if adapter.LEDGER_COUNTS or sys.stdout.isatty():
        record_run(transcript, key, "delivered")
    else:
        print("\n[NOTE] output is not going to a terminal, so this run does not count "
              "against the turn's limit. Re-run without a pipe to read the verdict.")


def delivered_runs(path: Path, turns: list[shape.Turn]) -> list[shape.Turn]:
    """Past turns' runs as the ledger saw them delivered.

    A command that matched and never ran - denied, rejected, cancelled - does not mean
    the reply before it was graded. Only turns from the ledger's first position key on
    are known to it; older turns, and every turn when the ledger is unreadable or holds
    no position key, keep the command count.
    """
    data = read_run_ledger(path)
    known = [int(k[1:]) for k in data or {} if k[:1] == "t" and k[1:].isdigit()]
    if not known:
        return turns
    first = min(known)
    out = []
    for position, turn in enumerate(turns):
        if position >= first:
            entry = data.get(turn.key)
            try:
                count = int(entry.get("delivered", 0)) if isinstance(entry, dict) else 0
            except (TypeError, ValueError):
                count = turn.runs
            turn = dataclasses.replace(turn, runs=count)
        out.append(turn)
    return out


def spent_runs(path: Path, current: shape.Turn, adapter) -> int:
    """Runs this turn that spent the budget. A broken ledger never widens it."""
    if adapter.LEDGER_COUNTS:
        delivered = ledger_count(path, current.key, "delivered")
        return RUN_LIMIT if delivered is None else delivered
    unseen = ledger_count(path, current.key, "started", "delivered")
    # Only a run whose verdict reached a terminal spends the budget. Unreadable
    # ledger: fall back to counting command runs, never a looser count.
    discount = verdictless_runs(path, current.key) if unseen is None else unseen
    return max(0, current.runs - discount)


def stop_hook() -> int:
    """A Claude Code Stop hook: grade the reply about to end the turn.

    The hook's stdin is JSON; `last_assistant_message` is the reply, read from there because
    the transcript may lag. Findings go to stderr and exit 2, which sends the turn back once;
    with `stop_hook_active` set the turn is already a revision, so they are reported and the
    exit is 0 - one forced revision, never a loop. The checker's own failure never blocks.
    Nothing is recorded in the run ledgers.
    """
    try:
        data = json.loads(sys.stdin.read())
        message = data.get("last_assistant_message") if isinstance(data, dict) else None
    except (OSError, ValueError):
        message = None
        data = None
    if not isinstance(message, str) or not message.strip():
        print("check_response --stop: no readable last_assistant_message on stdin, so nothing "
              "was graded", file=sys.stderr)
        return 0
    lines = message.split("\n")
    marks = [i for i, line in enumerate(lines) if line.strip() == claude.REPLY_MARKER]
    if marks:
        text, extra = "\n".join(lines[marks[-1]:]), []
    else:
        text, extra = message, [claude.MARKER_MISSING]
    report = io.StringIO()
    with contextlib.redirect_stdout(report):
        result = shape.grade("reply", text, extra=extra)
    if result != 1:
        return 0
    # The ledger line is about --previous's run ledgers, which this mode never touches.
    print("\n".join(l for l in report.getvalue().strip().splitlines()
                    if l != shape.LEDGER_FILE_LINE), file=sys.stderr)
    return 0 if data.get("stop_hook_active") is True else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a reply against the response shape.")
    parser.add_argument("--tool", choices=sorted(ADAPTERS),
                        help="which tool wrote the transcript. Detected when omitted")
    parser.add_argument("--session", help="chat session id. Copilot: the last segment of "
                                          "VSCODE_TARGET_SESSION_LOG. Cursor: defaults to "
                                          "CURSOR_CONVERSATION_ID. Claude Code: defaults to "
                                          "CLAUDE_CODE_SESSION_ID")
    parser.add_argument("--nonce", help="a fresh token unique to this invocation, for a tool "
                                        "that supplies no session id (Copilot)")
    parser.add_argument("--transcript", type=Path, help="explicit path, for test fixtures only")
    parser.add_argument(
        "--previous",
        action="store_true",
        help="grade the previous reply rather than the one being written (the intended mode)",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="a Claude Code Stop hook: read the hook JSON from stdin and grade its "
             "last_assistant_message. Exit 2 with the findings on stderr, once; 0 otherwise",
    )
    args = parser.parse_args()
    if args.stop:
        return stop_hook()
    env = os.environ

    tool = args.tool or detect(env)
    if tool is None:
        print("UNKNOWN: cannot tell which tool is running - no single tool's markers are "
              f"set. Pass --tool ({', '.join(sorted(ADAPTERS))}). This is not a pass.",
              file=sys.stderr)
        return 3
    adapter = ADAPTERS[tool]

    if args.transcript:
        path = args.transcript
    elif adapter.identity(args, env) is None:
        # Guessing the newest transcript grades whichever session wrote last,
        # including one in another workspace. A refusal is honest; a guess is not.
        print(adapter.NO_IDENTITY, file=sys.stderr)
        return 3
    else:
        path = adapter.locate(args, env)
    if path is None and args.previous and adapter.first_turn(args, env):
        print("NOT APPLICABLE: no transcript for this chat yet - this is its first reply, and "
              "the tool writes a transcript only when a turn ends. Nothing to grade.\n"
              "This is a completed run, not a skip. The next reply is graded normally.")
        return shape.EXIT_NOT_APPLICABLE
    if path is None or not path.exists():
        named = args.transcript or adapter.identity(args, env)
        print(f"UNKNOWN: no single transcript matches {named!r}. This is not a pass.",
              file=sys.stderr)
        return 3
    # An adapter whose transcripts sit at another depth names its own workspace folder.
    where = (adapter.workspace(path) if hasattr(adapter, "workspace")
             else path.parent.parent.parent.name)
    print(f"transcript: {where}/{path.name} | tool: {tool}")

    if not args.previous and not adapter.IN_FLIGHT:
        print(f"UNKNOWN: {tool} writes a turn to its transcript only when the turn ends, so "
              "the reply being written cannot be read. Run with --previous. This is not a pass.",
              file=sys.stderr)
        return 3

    # Before the run count and the choice of reply: both would read the previous turn
    # as this one. Nothing is recorded, so the re-run is free.
    for _ in range(BEHIND_POLLS):
        if not adapter.behind(path):
            break
        time.sleep(BEHIND_SECONDS)
    if adapter.behind(path):
        print(f"BEHIND: the transcript has not caught up with this turn after "
              f"{BEHIND_POLLS * BEHIND_SECONDS:g}s - it still ends at the previous turn. "
              "Nothing was graded and this run does not count. Re-run. This is not a pass.",
              file=sys.stderr)
        return 3

    turns = adapter.turns(path)
    current = turns[-1]
    limit = PREVIOUS_RUN_LIMIT if args.previous else RUN_LIMIT

    if not args.previous:
        runs = max(0, current.runs - verdictless_runs(path, current.key))
        if runs >= limit:
            print(f"REFUSED: already ran {runs} time(s) this turn, limit is {limit}. Post what you have.")
            return 2
        if not current.last.strip():
            print("UNKNOWN: no reply text found for this turn. This is not a pass.", file=sys.stderr)
            record_verdictless(path, current.key)
            return 3
        print(f"run {runs + 1} of {limit} | in-flight")
        results = [shape.grade("reply being written", current.last, extra=current.findings)]
        truncated = False
    else:
        walked = delivered_runs(path, turns) if adapter.LEDGER_COUNTS else turns
        picked, _, truncated = shape.lookback(walked)
        runs = spent_runs(path, current, adapter)
        if runs >= limit:
            print(f"REFUSED: already ran {runs} time(s) this turn, limit is {limit}. "
                  "A run counts once its verdict has been delivered. Post what you have.")
            return 2
        record_run(path, current.key, "started")
        if not picked:
            # No earlier turn at all is a different state from an earlier turn
            # that produced no text, and the two must not read alike.
            if not [t for t in turns[:-1] if t.kind == shape.OPERATOR]:
                print("NOT APPLICABLE: no earlier turn in this transcript - this is the first "
                      "reply of the session, or the session opened with a command whose turn "
                      "is not recorded. Nothing to grade.\n"
                      "This is a completed run, not a skip. The next reply is graded normally.")
                finish_previous_run(path, current.key, adapter)
                return shape.EXIT_NOT_APPLICABLE
            # Started and never delivered, so the re-run is free.
            print("UNKNOWN: no reply text found to grade. This is not a pass.", file=sys.stderr)
            return 3

        arrears = len(picked) - 1
        print(f"run {runs + 1} of {limit} | grading {len(picked)} reply(s)", end="")
        print(f", {arrears} in arrears - their turn never ran the check" if arrears else "")
        results = [
            shape.grade("previous reply" if back == 0 else f"{back} turn(s) back, UNGRADED",
                        turn.text, turn.cut_short, turn.invoked, turn.findings)
            for back, turn in picked
        ]

    if truncated:
        print(
            f"\nTRUNCATED: stopped at the {shape.LOOKBACK_CAP}-reply cap without reaching a "
            "graded turn.\nAnything older than this is not covered and will not be collected "
            "later."
        )

    print("\nNOT CHECKED BY THIS SCRIPT - a pass means well-formed, never correct:")
    for line in (
        "whether evidence actually supports the claim above it",
        "whether a verdict is right",
        "whether the falsifier named is the strong one or a convenient weak one",
        "whether a use case is real",
        "whether any reasoning is sound",
        "anything written after this ran, including the verdict line itself",
    ):
        print(f"  - {line}")

    if args.previous:
        finish_previous_run(path, current.key, adapter)
    if 1 in results:
        return 1
    return shape.EXIT_NOT_APPLICABLE if all(r == shape.EXIT_NOT_APPLICABLE for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
