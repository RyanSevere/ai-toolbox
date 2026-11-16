#!/bin/sh
################################################################################
# File: vendored_core.sh
# Path: {PROJECT_ROOT}/githooks/lib/vendored_core.sh
# Created by: Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-16
# Description: Sourced by gates. own_test_files lists the tracked test files this
#              repository owns: every tracked file matching the pattern it is
#              given, minus core/tests/ where core/VENDORED exists, since that
#              tree is the vendored core's own suite, run upstream, not this
#              profile's.
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


# True when this repository carries a vendored copy of the core.
has_vendored_core() {
  [ -n "$(git ls-files -- core/VENDORED)" ]
}

# own_test_files PATTERN: tracked files matching the egrep PATTERN, without the vendored
# core's own tests. Never fails: no match is an empty list.
own_test_files() {
  if has_vendored_core; then
    git ls-files | grep -E "$1" | grep -v '^core/tests/' || true
  else
    git ls-files | grep -E "$1" || true
  fi
}
