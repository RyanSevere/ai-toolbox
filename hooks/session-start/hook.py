#!/usr/bin/env python3
################################################################################
# File: hook.py
# Path: {PROJECT_ROOT}/.claude/hooks/session-start/hook.py
# Created by: Ryan Severe
# Created: 2026-11-15
# Last Updated: 2026-11-15
# Description: Agent hook on session.start. It orients every new session through
#              Claude Code's SessionStart context: the response-shape rule when
#              the repository holds it, and the role-skill step. When
#              AI_TOOLBOX_HOOKS=off it first tells the session its hooks are
#              off. It runs while the switch is off, because it is how a session
#              finds out. Design in hooks/README.md, "session-start".
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

import sys
from pathlib import Path

# The shared library renders beside the hooks, in a folder next to this one.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import hookio  # noqa: E402

NAME = "session-start"

LINE = ("Agent hooks are OFF on this machine: AI_TOOLBOX_HOOKS=off is set, so no hook guards "
        "this session. Clear it to turn them back on.")


RULE = Path(".github") / "rules" / "response-shape.md"

SHAPE_LINE = ("Before your first reply, read `.github/rules/response-shape.md`. At the start of "
              "every turn, run `python .github/scripts/responses/check_response.py --previous` "
              "from the repository root and fix what it reports in the reply you are writing.")

ROLE_LINE = ("If your instructions name a role skill for this session, load it before acting and "
             "do the steps it says belong on your first tool call.")


def has_rule(seen: dict) -> bool:
    """True only when the payload's cwd is a directory that holds the rule file. A missing or
    non-string cwd, or a filesystem error, is absence: never a guess at the path."""
    raw = seen.get("raw")
    cwd = raw.get("cwd") if isinstance(raw, dict) else None
    if not isinstance(cwd, str) or not cwd:
        return False
    try:
        root = Path(cwd)
        return root.is_dir() and (root / RULE).is_file()
    except (OSError, ValueError):
        return False


def notice(seen: dict) -> str | None:
    lines = [LINE] if hookio.hooks_off() else []
    if has_rule(seen):
        lines.append(SHAPE_LINE)
    lines.append(ROLE_LINE)
    return "\n".join(lines)


def main() -> int:
    return hookio.run_notice(NAME, "session.start", notice)


if __name__ == "__main__":
    sys.exit(main())
