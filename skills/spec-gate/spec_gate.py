#!/usr/bin/env python3
################################################################################
# File: spec_gate.py
# Path: {PROJECT_ROOT}/skills/spec-gate/spec_gate.py
# Created by: Ryan Severe
# Created: 2026-11-06
# Last Updated: 2026-11-08
# Description: Refuses a spec - a ticket body or a factory SPEC.md - that is not in
#              the spec format, naming every rule it breaks. Exit 0 passes, 1
#              refuses, 2 could not check.
#              Standard library only, so the rendered copy runs on its own.
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
import re
import sys
from pathlib import Path

MODES = ("ticket", "spec")
OK, REFUSED, UNCHECKED = 0, 1, 2

REQUIRED = ("Problem", "Decided", "Touches", "Edge cases", "Done when", "Verify",
            "Verification class", "Escalate when", "Out of scope", "Open questions")
ALIASES = {"fix": "Decided"}

CATEGORIES = ("Empty or missing", "Boundary values", "Malformed or wrong type",
              "A failed dependency or lookup", "Duplicates and ordering", "State across runs")
CLASSES = ("gated", "needs-live-host")

HEADING = re.compile(r"^##\s+(.+?)\s*$")
FOUND = re.compile(r"^\s*\*{0,2}Found\*{0,2}\s*:?\s*\*{0,2}\s*\d{4}-\d{2}-\d{2}", re.I)
SEVERITY = re.compile(r"^\s*\*{0,2}Severity:?\*{0,2}\s*:?\s*\*{0,2}\s*[A-Za-z]", re.I | re.M)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
POINTER = re.compile(r"[\w.\-]*[./][\w./\-]*:\d+")
ITEM = re.compile(r"^(?:[-*]|\d+\.)\s+(?:\[[ xX]\]\s+)?")
CODE_SPAN = re.compile(r"`[^`]*`")
BULLET = re.compile(r"^(?:[-*]|\d+\.)(?:\s+(?:\[[ xX]\]\s+)?|$)")
LEADING_PATH = re.compile(r"`[^`\s]+`")
PATH_JOINERS = " \t,;&/+"
PLACEHOLDER_WORD = re.compile(r"\b(?:TBD|TODO)\b")
PLACEHOLDER_LINE = ("?", "...", "\u2026")


def sections(text: str) -> tuple[dict[str, list[str]], list[str]]:
    """Each required section's bodies, in the order given, and the Found note's lines.

    A section runs to the next `##` heading, or to a Found note, which closes a ticket
    body. A Found note leads with its date; a line that only starts with the word is
    section content. A heading that is not a required section is kept out of every body.
    """
    found: dict[str, list[str]] = {}
    notes: list[str] = []
    current: list[str] | None = None
    in_found = False
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            title = heading.group(1)
            name = ALIASES.get(title.casefold()) or next(
                (r for r in REQUIRED if r.casefold() == title.casefold()), None)
            in_found = title.casefold() == "found"
            current = None
            if name:
                current = []
                found.setdefault(name, []).append(current)
            continue
        if FOUND.match(line):
            current, in_found = None, False
            notes.append(line)
            continue
        if in_found:
            notes.append(line)
        elif current is not None:
            current.append(line)
    return {name: ["\n".join(body) for body in bodies] for name, bodies in found.items()}, notes


def placeholders(text: str) -> list[str]:
    """Lines outside code that are only a gap: TBD, TODO, a bare ? or an ellipsis."""
    out, fenced = [], False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        bare = ITEM.sub("", CODE_SPAN.sub("", line).strip()).strip()
        if bare in PLACEHOLDER_LINE or PLACEHOLDER_WORD.search(bare):
            out.append(f"line {number}: {line.strip()}")
    return out


def items(body: str) -> list[str]:
    """A list section's top-level items, each with its continuation lines."""
    out: list[str] = []
    for line in body.splitlines():
        if ITEM.match(line):
            out.append(line)
        elif out:
            out[-1] += "\n" + line
        elif line.strip():
            out.append(line)
    return out


def first_line(item: str) -> str:
    return ITEM.sub("", item.splitlines()[0]).strip()


def touches_format(body: str) -> list[tuple[str, str]]:
    """One refusal per top-level bullet that does not start with exactly one backticked path.

    Prose after the path is allowed. An indented line belongs to the bullet above it, and a
    line that is not a bullet at all is left to the other rules. A section with no top-level
    bullet at all is refused once, because it names no file the run may change.
    """
    out = []
    seen = False
    for line in body.splitlines():
        bullet = BULLET.match(line)
        if not bullet:
            continue
        seen = True
        rest = line[bullet.end():].strip()
        path = LEADING_PATH.match(rest)
        if not path or rest[path.end():].lstrip(PATH_JOINERS).startswith("`"):
            out.append(("touches-format", f"bullet {rest!r} does not start with exactly one "
                                          "backticked path"))
    if not seen:
        out.append(("touches-format", "Touches section has no top-level bullet starting with "
                                      "a backticked path"))
    return out


def edge_cases(body: str) -> list[tuple[str, str]]:
    out = []
    for category in CATEGORIES:
        line = re.search(rf"^\s*[-*]\s+{re.escape(category)}\s*:(.*)$", body, re.I | re.M)
        rest = line.group(1).strip() if line else ""
        if not rest:
            out.append(("edge-case-missing", category))
        elif rest[:3].casefold() == "n/a" and not rest[3:].lstrip(" :").strip():
            out.append(("edge-case-no-reason", category))
    return out


def content(name: str, body: str) -> list[tuple[str, str]]:
    """The refusals a filled section can earn on its own."""
    if name == "Problem" and not POINTER.search(body):
        return [("problem-pointer", "Problem cites no path:line")]
    if name == "Done when":
        return [("done-when-unchecked", first_line(item)) for item in items(body)
                if "checked by:" not in item.replace("*", "").casefold()]
    if name == "Touches":
        return touches_format(body)
    if name == "Edge cases":
        return edge_cases(body)
    if name == "Verification class" and body.strip().strip("`") not in CLASSES:
        return [("verification-class", f"reads {body.strip()!r}, not one of {', '.join(CLASSES)}")]
    if name == "Open questions" and body.strip() != "None.":
        lines = [line.strip() for line in body.splitlines()
                 if line.strip() and line.strip() != "None."]
        shown = " | ".join(lines) or body.strip()
        return [("open-questions", f"reads {shown!r}, not 'None.'")]
    return []


def check(text: str, mode: str) -> list[tuple[str, str]]:
    """Every rule the spec breaks, as (rule, detail). Empty means it passes."""
    if mode not in MODES:
        raise ValueError(f"mode is {mode!r}, not one of {', '.join(MODES)}")
    found, notes = sections(text)
    out: list[tuple[str, str]] = []
    if mode == "ticket":
        if not SEVERITY.search(text):
            out.append(("severity", "no Severity line"))
        if not DATE.search("\n".join(notes)):
            out.append(("found", "no Found note with an ISO date"))
    for name in REQUIRED:
        bodies = found.get(name)
        if not bodies:
            out.append(("missing-section", name))
            continue
        if len(bodies) > 1:
            out.append(("duplicate-section", name))
        for body in bodies:
            if not body.strip():
                out.append(("empty-section", name))
            else:
                out.extend(content(name, body))
    out.extend(("placeholder", line) for line in placeholders(text))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refuse a spec that is not in the approved "
                                                 "format. Exit 0 passes, 1 refuses, 2 could "
                                                 "not check.")
    parser.add_argument("--mode", required=True, choices=MODES,
                        help="ticket requires Severity and Found; spec does not")
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        text = args.path.read_bytes().decode("utf-8").removeprefix("\ufeff")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"could not check {args.path}: {exc}", file=sys.stderr)
        return UNCHECKED
    refusals = check(text, args.mode)
    if not refusals:
        print(f"passed: {args.path}")
        return OK
    for rule, detail in refusals:
        print(f"refused: {rule}: {detail}")
    print(f"{args.path}: {len(refusals)} refusal(s)")
    return REFUSED


if __name__ == "__main__":
    sys.exit(main())
