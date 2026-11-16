#!/usr/bin/env python3
################################################################################
# File: secret_shapes.py
# Path: {PROJECT_ROOT}/githooks/lib/secret_shapes.py
# Created by: Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-16
# Description: The one source of the credential shapes, read by the push gate
#              and by the write-time observer hook. find(lines) reports a
#              private key header, a bare 32-hex token, and an env-style
#              NAME=value where NAME ends in KEY, TOKEN, SECRET, PASSWORD or
#              PASSWD and the value is long and not a placeholder. Heuristic
#              by design: a line can opt out with 'secret-scan: allow'. As a
#              command line it reads 'path:line: text' lines on stdin, prints
#              'path:line: <shape>' per hit - where, never what - and exits 1
#              on any hit. Stdlib only.
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

import re
import sys
from typing import Iterable

ALLOW = "secret-scan: allow"

# Bounded by characters that cannot sit inside a path, URL, UUID or longer hash, so directory
# names in logs and 40-hex commit ids do not match.
HEX = re.compile(r"(?:^|[^0-9A-Za-z/\\._-])[0-9a-f]{32}(?:[^0-9A-Za-z/\\._-]|$)")
PRIVKEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
ASSIGN = re.compile(
    r"^\s*(?:export\s+|-\s+)?[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)\s*[=:]\s*[\"']?"
    r"[A-Za-z0-9+_-][A-Za-z0-9+/_-]{23,}")
# A value that names itself as not real. Case-folded, and applied to an assignment only: a bare
# hex token or a key header is never excused by a nearby word.
PLACEHOLDER = re.compile(
    r"[=:]\s*[\"']?\S*(?:your|change|example|placeholder|dummy|sample|xxxx|<|ci-|test|fake)",
    re.IGNORECASE)

# The shape names, in the order a line is checked.
SHAPES = ("hex", "privkey", "assign")


def shapes_in(text: str) -> list[str]:
    """The shapes one line carries. A line with the opt-out carries none."""
    if ALLOW in text:
        return []
    found = []
    if HEX.search(text):
        found.append("hex")
    if PRIVKEY.search(text):
        found.append("privkey")
    if ASSIGN.search(text) and not PLACEHOLDER.search(text):
        found.append("assign")
    return found


def find(lines: Iterable[str]) -> list[tuple[int, str]]:
    """(line_number, shape) for each shape in each line, numbered from 1."""
    return [(number, shape)
            for number, text in enumerate(lines, start=1)
            for shape in shapes_in(text)]


# 'path:line: text'. The path is matched lazily so a drive letter's colon stays in it.
LOCATED = re.compile(r"^(?P<path>.*?):(?P<line>\d+): (?P<text>.*)$")


def main() -> int:
    hits = []
    for raw in sys.stdin:
        located = LOCATED.match(raw.rstrip("\r\n"))
        if located is None:
            continue
        for shape in shapes_in(located.group("text")):
            hits.append(f"{located.group('path')}:{located.group('line')}: {shape}")
    for hit in hits:
        print(hit)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
