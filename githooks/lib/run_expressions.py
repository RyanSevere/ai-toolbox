#!/usr/bin/env python3
################################################################################
# File: run_expressions.py
# Path: {PROJECT_ROOT}/githooks/lib/run_expressions.py
# Created by: Ryan Severe
# Created: 2026-09-28
# Last Updated: 2026-11-16
# Description: Refuses a push whose workflows or actions put a ${{ }} expression
#              inside a run: script. GitHub substitutes the expression into the
#              script text before the shell reads it, so any value a pusher or
#              dispatcher controls becomes code. Line-based, so it needs no YAML
#              library; reads the commit being pushed, never the working tree.
#             
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
import subprocess
import sys

TIMEOUT = 120
EXPRESSION = "${{"
# Rendered workflows and actions, plus a profile's own sources for them.
SCANNED = re.compile(r"^(\.github/)?(workflows/[^/]+|actions/[^/]+/action)\.ya?ml$")
RUN_KEY = re.compile(r"^(\s*)(-\s+)?run:\s*(.*)$")
BLOCK = re.compile(r"^[|>][-+0-9]*\s*(#.*)?$")
MAPPING_LINE = re.compile(r"^\s*[\w-]+:(\s|$)")


class ScanError(Exception):
    """The check could not be carried out. Never a pass."""


def git(*args: str) -> bytes:
    result = subprocess.run(["git", *args], capture_output=True, timeout=TIMEOUT)
    if result.returncode != 0:
        raise ScanError(f"git {' '.join(args)} failed: "
                        f"{result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def scan(text: str) -> list[tuple[int, str]]:
    """(line number, line) for every run: script line holding an expression."""
    lines = text.splitlines()
    hits: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        match = RUN_KEY.match(lines[i])
        if not match:
            i += 1
            continue
        key_column = len(match.group(1)) + len(match.group(2) or "")
        value = match.group(3).strip()
        if value and not BLOCK.match(value):
            if EXPRESSION in value:
                hits.append((i + 1, lines[i]))
            i += 1
            continue
        # A block scalar, or a key whose value is on the lines below it.
        body = []
        j = i + 1
        while j < len(lines) and (not lines[j].strip() or indent_of(lines[j]) > key_column):
            body.append(j)
            j += 1
        first = next((lines[k] for k in body if lines[k].strip()), "")
        # defaults: run: is a mapping (shell, working-directory), not a script.
        is_mapping = not value and MAPPING_LINE.match(first)
        if not is_mapping:
            hits += [(k + 1, lines[k]) for k in body if EXPRESSION in lines[k]]
        i = j
    return hits


def resolve(rev: str) -> str:
    if not re.fullmatch(r"[\w./^~@{}-]{1,100}", rev or ""):
        raise ScanError(f"--sha {rev!r} is not a revision")
    return git("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").decode().strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refuse ${{ }} inside run: scripts.")
    parser.add_argument("--sha", required=True, help="the commit being pushed")
    args = parser.parse_args(argv)
    try:
        sha = resolve(args.sha)
        paths = [p for p in git("ls-tree", "-r", "--name-only", sha).decode().splitlines()
                 if SCANNED.match(p)]
        found = []
        for path in paths:
            text = git("show", f"{sha}:{path}").decode("utf-8", errors="replace")
            found += [(path, n, line) for n, line in scan(text)]
    except (ScanError, subprocess.TimeoutExpired) as exc:
        print(f"REFUSED: {exc}")
        return 1
    if not paths:
        print("run-expressions: no workflows or actions in this commit. Nothing to check.")
        return 0
    if not found:
        print(f"run-expressions: {len(paths)} workflow/action file(s), "
              "no expression inside a run: script.")
        return 0
    print(f"run-expressions: {len(found)} expression(s) inside run: scripts:")
    for path, number, line in found:
        print(f"  {path}:{number}: {line.strip()}")
    print("\nGitHub pastes ${{ }} into the script as code before the shell reads it. Pass the "
          "value through the step's env: and use it quoted, as \"$NAME\".")
    return 1


if __name__ == "__main__":
    sys.exit(main())
