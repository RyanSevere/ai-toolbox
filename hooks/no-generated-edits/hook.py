#!/usr/bin/env python3
################################################################################
# File: hook.py
# Path: {PROJECT_ROOT}/.cursor/hooks/no-generated-edits/hook.py
# Created by: Ryan Severe
# Created: 2026-11-15
# Last Updated: 2026-11-15
# Description: Agent hook on file.write.before. Denies an agent write to a file
#              that carries the generated-file stamp, and names the source to
#              edit instead, because the next render overwrites the edit. A new
#              file and an unstamped file are allowed; a target it cannot read
#              is denied. Design in hooks/README.md.
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

import os
import re
import sys
from pathlib import Path

# The shared library renders beside the hooks, in a folder next to this one.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import hookio  # noqa: E402

NAME = "no-generated-edits"

# The window the pre-push gate reads for the stamp (`head -n 40`), and every render puts the
# stamp inside it. A stamp on a later line is not a rendered file's.
HEAD_LINES = 40
# Bytes read, so a binary file with no newline is not read whole. Well past 40 ordinary lines.
HEAD_BYTES = 64 * 1024

# The whole stamp sync.py writes: either form of its `stamp()`, with a SHA or without. The
# whole, not the opening: a file that only quotes "generated from <repo>@<sha>" is not
# generated. This pattern is the hook's own because a rendered hook cannot import sync.py, and
# a test ties it to sync.stamp().
STAMP_PATTERN = re.compile(
    r"generated from (?P<source>[^\s@]+)(?:@[0-9a-f]+)? - edit the source, not this file")


def stamp_source(text: str) -> str | None:
    """The source name in the first stamp in text, or None when there is no whole stamp."""
    match = STAMP_PATTERN.search(text)
    return match.group("source") if match else None


def unreadable(path, reason: str) -> tuple[str, str]:
    return (f"{NAME}: could not read {path!r} ({reason}).",
            f"The {NAME} hook could not read {path!r} ({reason}), so it could not tell whether "
            "the file is generated, and denied the write by default.")


def decide(payload: dict) -> tuple[str, str] | None:
    path, cwd = payload["path"], payload.get("cwd")
    if not isinstance(path, str) or not path:
        return unreadable(path, "the path is empty or not text")
    target = path
    if not os.path.isabs(path):
        if not isinstance(cwd, str) or not os.path.isabs(cwd):
            return unreadable(path, "it is a relative path and the payload has no usable cwd")
        target = os.path.join(cwd, path)
    try:
        if not os.path.exists(target):
            return None  # a new file
        if os.path.isdir(target):
            return unreadable(path, "it is a directory")
        with open(target, "rb") as handle:
            head = handle.read(HEAD_BYTES)
    except (OSError, ValueError) as exc:
        return unreadable(path, f"{type(exc).__name__}: {exc}")
    lines = head.decode("utf-8", errors="replace").split("\n")[:HEAD_LINES]
    source = stamp_source("\n".join(lines))
    if source is None:
        return None
    return (f"{NAME}: {path} is generated from {source}; edit the source.",
            f"This write was blocked because {path} is a generated file: its stamp reads "
            f"\"generated from {source} ... edit the source, not this file\". The file is "
            f"overwritten at the next render, so an edit here is lost.\n\nEdit the source in "
            f"{source} and re-render instead. If you are sure the file is not generated, ask "
            "the operator.")


def main() -> int:
    return hookio.run_permission(NAME, "file.write.before", decide)


if __name__ == "__main__":
    sys.exit(main())
