#!/usr/bin/env bash
################################################################################
# File: fetch.sh
# Path: {PROJECT_ROOT}/actions/report-gate/fetch.sh
# Created by: Ryan Severe
# Created: 2026-11-18
# Last Updated: 2026-11-18
# Description: Fetches the pre-push gate report published for one commit and
#              writes it to $RUNNER_TEMP/report.json. Called by the report-gate
#              action by fixed name; every value arrives through the
#              environment, never through the script text, so no input can
#              become code.
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


set -euo pipefail

: "${SHA:?SHA is required}"
: "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"

# It goes into a ref pattern. Not echoed back, since stdout carries workflow commands.
# Spelled out: a range like a-f follows locale collation and admitted uppercase.
if ! [[ "$SHA" =~ ^[0123456789abcdef]{40}$ ]]; then
  echo "REFUSED: SHA is not a full 40-character lowercase commit id."
  exit 1
fi

# One pattern, one commit. The date segment varies, the sha does not.
ref="$(git ls-remote origin "refs/tags/gate-report/*/$SHA" | awk '{print $2}' | tail -n 1)"

if [ -z "$ref" ]; then
  echo "No gate report published for $SHA."
  echo "found=no" >> "$GITHUB_OUTPUT"
  exit 0
fi

echo "Found $ref"
# Forced: a persistent runner keeps the last job's ref, and reports share no history.
git fetch --quiet origin "+$ref:refs/gate-report-check"
git show refs/gate-report-check:report.json > "$RUNNER_TEMP/report.json"
echo "found=yes" >> "$GITHUB_OUTPUT"
