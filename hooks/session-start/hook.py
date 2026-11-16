#!/usr/bin/env python3
################################################################################
# File: hook.py
# Path: {PROJECT_ROOT}/.claude/hooks/session-start/hook.py
# Created by: Ryan Severe
# Created: 2026-11-15
# Last Updated: 2026-11-15
# Description: Agent hook on session.start. When AI_TOOLBOX_HOOKS=off it tells
#              the session its hooks are off, through Claude Code's SessionStart
#              context; otherwise it says nothing. It runs while the switch is
#              off, because it is how a session finds out. Design in
#              hooks/README.md, "The off switch".
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


def notice(seen: dict) -> str | None:
    return LINE if hookio.hooks_off() else None


def main() -> int:
    return hookio.run_notice(NAME, "session.start", notice)


if __name__ == "__main__":
    sys.exit(main())
