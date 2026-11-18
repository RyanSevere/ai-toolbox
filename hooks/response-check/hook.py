#!/usr/bin/env python3
################################################################################
# File: hook.py
# Path: {PROJECT_ROOT}/.claude/hooks/response-check/hook.py
# Created by: Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-18
# Description: Claude Code Stop hook. Hands the hook payload to the rendered
#              response checker, check_response.py --stop, found from the
#              project root, so a reply that fails the response shape is sent
#              back once. Its own failure, a missing checker, or the off switch
#              never blocks the turn.
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

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import hookio  # noqa: E402  - the shared runtime library, rendered beside this hook's folder

# Where sync renders the response checker in every repository.
CHECKER = Path(".github") / "scripts" / "responses" / "check_response.py"
# The checker reads one reply; far longer than it needs, far shorter than the hook's timeout.
CHECK_TIMEOUT = 25
# check_response --stop exits 2 to send the turn back, 0 otherwise. Anything else is the
# checker failing, which must never block a turn.
SEND_BACK = 2


def find_checker(start: Path | None = None) -> Path | None:
    """The rendered checker, from the nearest ancestor of this file that holds it."""
    here = (start or Path(__file__)).resolve().parent
    for directory in (here, *here.parents):
        candidate = directory / CHECKER
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    if hookio.hooks_off():
        return 0
    payload = sys.stdin.buffer.read()
    checker = find_checker()
    if checker is None or not checker.is_file():
        print(f"response-check: {CHECKER.as_posix()} not found above {Path(__file__).parent}, "
              "so the reply was not graded", file=sys.stderr)
        return 0
    try:
        ran = subprocess.run([sys.executable, "-B", str(checker), "--stop"], input=payload,
                             capture_output=True, timeout=CHECK_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"response-check: the checker did not run ({exc}), so the reply was not graded",
              file=sys.stderr)
        return 0
    findings = ran.stderr.decode("utf-8", errors="replace").strip()
    if findings:
        print(findings, file=sys.stderr)
    return SEND_BACK if ran.returncode == SEND_BACK else 0


if __name__ == "__main__":
    sys.exit(main())
