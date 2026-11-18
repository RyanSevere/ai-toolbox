#!/bin/sh
################################################################################
# File: rendered_only.sh
# Path: {PROJECT_ROOT}/githooks/lib/rendered_only.sh
# Created by: Ryan Severe
# Created: 2026-09-29
# Last Updated: 2026-11-16
# Description: Sourced by gates. rendered_only LOCAL REMOTE succeeds only when
#              every file the pushed range changes is rendered output - stamped
#              within its first 40 lines - or .gitignore. Such a range cannot
#              change the result of a check on this repository's own code.
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


# shellcheck source=/dev/null
. "$(dirname "$0")/../lib/stamp.sh"

rendered_only() {
  ro_local="${1:-}"
  ro_remote="${2:-}"
  [ -n "$ro_local" ] && [ -n "$ro_remote" ] || return 1
  # All zeros is a new branch: there is no range to judge.
  case "$ro_remote" in *[!0]*) ;; *) return 1 ;; esac
  # One python reads the whole range in two git processes. Only exit 0 skips: 1 is "not
  # rendered-only" and 2 is "could not judge", and an unknown is never a skip. With no
  # python that runs, the per-file loop below does the same job one process at a time.
  ro_script="$(dirname "$0")/../lib/rendered_only.py"
  for ro_py in python python3; do
    "$ro_py" -c '' >/dev/null 2>&1 || continue
    "$ro_py" -B "$ro_script" "$ro_local" "$ro_remote" 2>/dev/null
    [ "$?" -eq 0 ] && return 0
    return 1
  done
  git cat-file -e "$ro_remote^{commit}" 2>/dev/null || return 1
  ro_changed="$(git diff --name-only "$ro_remote" "$ro_local" 2>/dev/null)" || return 1
  [ -n "$ro_changed" ] || return 1
  printf '%s\n' "$ro_changed" | {
    while IFS= read -r ro_file; do
      [ "$ro_file" = ".gitignore" ] && continue
      # A deleted file is judged by the side that still has it.
      ro_side="$ro_local"
      git cat-file -e "$ro_local:$ro_file" 2>/dev/null || ro_side="$ro_remote"
      git show "$ro_side:$ro_file" 2>/dev/null | stamped || exit 1
    done
    exit 0
  }
}
