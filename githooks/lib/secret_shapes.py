#!/usr/bin/env python3
################################################################################
# File: secret_shapes.py
# Path: {PROJECT_ROOT}/githooks/lib/secret_shapes.py
# Created by: Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-17
# Description: The one source of the credential shapes, read by the push gate
#              and by the write-time observer hook. find(lines) reports a
#              private key header, a bare 32-hex token, an env-style
#              NAME=value where NAME ends in KEY, TOKEN, SECRET, PASSWORD or
#              PASSWD, a known provider token prefix anywhere in a line, a
#              secret-named assignment in any case and common syntax, and a
#              URL carrying a password. Values that are paths or name
#              themselves as placeholders are excused. Heuristic
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
    r"(?P<value>[A-Za-z0-9+_-][A-Za-z0-9+/_-]{23,})")
# A known token prefix anywhere in a line. Never excused as a placeholder.
PROVIDER = re.compile(
    r"gh[pousr]_[A-Za-z0-9]{36,}"
    r"|github_pat_[A-Za-z0-9_]{60,}"
    r"|sk-ant-[A-Za-z0-9_-]{32,}"
    r"|sk-[A-Za-z0-9_-]{40,}"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|xox[abpr]-[A-Za-z0-9-]{10,}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
# An assignment in any case and the common syntaxes, anchored at the start of the line:
# name = value, name: value, "name": "value", const name = value.
KEYED = re.compile(
    r"^\s*(?:export\s+|-\s+|(?:const|let|var)\s+)?[\"']?(?P<name>[A-Za-z0-9_.-]+)[\"']?"
    r"\s*[:=]\s*[\"']?(?P<value>[A-Za-z0-9+/_=-]{24,})")
# The last part of a keyed name must be one of these.
SECRET_PARTS = ("key", "apikey", "token", "secret", "password", "passwd", "credential",
                "credentials")
# A published checksum is not a secret: a key named as one is skipped.
CHECKSUM_NAME = re.compile(r"sha|hash|sum|digest|fingerprint", re.IGNORECASE)
# A URL carrying a non-empty password that is not an interpolation.
URLCRED = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:(?![$%{])[^/\s@]+@", re.IGNORECASE)

PLACEHOLDER_WORDS = ("your", "example", "change", "dummy", "placeholder", "sample", "fake",
                     "test", "xxxx")
PLACEHOLDER_PREFIXES = ("your", "example", "change", "dummy")


def is_placeholder(value: str) -> bool:
    """True when a value, judged as a whole, is a path or names itself as not real.

    Applied to an assignment and a keyed value only: a bare hex token, a key header and a
    provider token are never excused by a nearby word.
    """
    folded = value.strip("\"'").lower()
    if folded.startswith(("/", "ci-") + PLACEHOLDER_PREFIXES) or "<" in folded:
        return True
    return any(part in PLACEHOLDER_WORDS for part in re.split(r"[-_.]", folded))


def secret_name(name: str) -> bool:
    """True when the last part of a name, split on _ - . and camelCase, names a secret."""
    parts = re.split(r"[_.-]|(?<=[a-z0-9])(?=[A-Z])", name)
    return parts[-1].lower() in SECRET_PARTS


def is_keyed(text: str, assigned: bool) -> bool:
    """True when the line is a secret-named assignment that assign did not already report."""
    match = KEYED.search(text)
    if assigned or match is None:
        return False
    name, value = match.group("name"), match.group("value")
    return (secret_name(name) and not CHECKSUM_NAME.search(name)
            and re.search(r"\d", value) is not None and re.search(r"[A-Za-z]", value) is not None
            and not is_placeholder(value))


# The shape names, in the order a line is checked.
SHAPES = ("hex", "privkey", "assign", "provider", "keyed", "urlcred")


def shapes_in(text: str) -> list[str]:
    """The shapes one line carries. A line with the opt-out carries none."""
    if ALLOW in text:
        return []
    found = []
    if HEX.search(text):
        found.append("hex")
    if PRIVKEY.search(text):
        found.append("privkey")
    assign = ASSIGN.search(text)
    assigned = bool(assign) and not is_placeholder(assign.group("value"))
    if assigned:
        found.append("assign")
    if PROVIDER.search(text):
        found.append("provider")
    if is_keyed(text, bool(assign)):
        found.append("keyed")
    if URLCRED.search(text):
        found.append("urlcred")
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
