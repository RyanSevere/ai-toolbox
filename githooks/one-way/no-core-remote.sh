#!/bin/sh
################################################################################
# File: no-core-remote.sh
# Path: {PROJECT_ROOT}/githooks/one-way/no-core-remote.sh
# Created by: Ryan Severe
# Created: 2026-10-15
# Last Updated: 2026-11-06
# Description: One-way gate 2. Refuses a push whose remote is the core
#              repository, whatever URL form names it. A backstop: a vendored
#              profile has no such remote by construction.
#              Usage: no-core-remote.sh CORE_URL PUSH_URL.
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

core_url="${1:-}"
push_url="${2:-}"

# owner/repo, lowercased, without a trailing slash or .git. Host-blind on purpose:
# https, ssh and an ssh host alias such as `github-personal:` all name one
# repository, and as a backstop this errs toward refusing.
repo_of() {
  printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]' \
    | sed -e 's#/*$##' -e 's#\.git$##' -n -e 's#^.*[:/]\([^/:][^/:]*/[^/:][^/:]*\)$#\1#p'
}

if [ -z "$core_url" ]; then
  echo "REFUSED: no core repository URL given, so there is nothing to compare against."
  exit 1
fi
if [ -z "$push_url" ]; then
  echo "REFUSED: no push URL given, so the destination is unknown."
  exit 1
fi

core="$(repo_of "$core_url")"
if [ -z "$core" ]; then
  echo "REFUSED: '$core_url' names no owner/repo, so it cannot be compared."
  exit 1
fi

if [ "$(repo_of "$push_url")" = "$core" ]; then
  echo "REFUSED: this push goes to the core repository ($core)."
  echo "A profile changes the core only through a pull request on the core itself,"
  echo "never by pushing to it from here."
  exit 1
fi

echo "Push destination is not the core repository."
exit 0
