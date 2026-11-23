#!/bin/sh
################################################################################
# File: ruff.sh
# Path: {PROJECT_ROOT}/githooks/gates/ruff.sh
# Created by: Ryan Severe
# Created: 2026-09-28
# Last Updated: 2026-11-23
# Description: Refuses a push that adds a ruff finding the repo's baseline does
#              not already hold. Uses the repo's committed ruff config where one
#              exists and ruff's defaults otherwise. Lints the commit being
#              pushed, not the working tree. A machine without ruff is refused,
#              never passed.
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
    exec "$py" "$lib" --tool ruff --sha "${1:-}" --base "${2:-}" --remote "${3:-origin}"
  fi
done
echo "REFUSED: no working python, so ruff cannot run."
exit 1
