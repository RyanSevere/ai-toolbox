#!/bin/sh
################################################################################
# File: shellcheck.sh
# Path: {PROJECT_ROOT}/githooks/gates/shellcheck.sh
# Created by: Ryan Severe
# Created: 2026-09-28
# Last Updated: 2026-11-16
# Description: Refuses a push that adds a ShellCheck warning or error the repo's
#              baseline does not already hold. Covers .sh files and any file with
#              an sh or bash shebang, so extensionless scripts are checked too.
#              Lints the commit being pushed, not the working tree. A machine
#              without shellcheck is refused, never passed.
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

set -u

lib="$(cd "$(dirname "$0")/../lib" 2>/dev/null && pwd)/lint_baseline.py"
if [ ! -f "$lib" ]; then
  echo "REFUSED: $lib is missing. Run sync.py against this repo."
  exit 1
fi

# python3 first would find the Windows Store stub, which exists and does not run.
for py in python python3; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c "import sys" >/dev/null 2>&1; then
    exec "$py" "$lib" --tool shellcheck --sha "${1:-}" --base "${2:-}"
  fi
done
echo "REFUSED: no working python, so the scripts cannot be checked."
exit 1
