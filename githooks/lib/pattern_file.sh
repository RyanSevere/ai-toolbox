#!/bin/sh
################################################################################
# File: pattern_file.sh
# Path: {PROJECT_ROOT}/githooks/lib/pattern_file.sh
# Created by: Ryan Severe
# Created: 2026-10-15
# Last Updated: 2026-11-06
# Description: Sourced by the one-way gates. load_patterns FILE OUT writes
#              FILE's patterns to OUT, one fixed string per line, and fails
#              when FILE is missing or declares none. The pattern lists are
#              profile data, kept outside the tracked tree.
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


# Sourced, so no `set` here: it would leak into the caller.
#
# Comments and blank lines are dropped before anything matches: grep -F -f reads an
# empty line as a pattern that matches every line, so one stray blank line would
# refuse every push. A file with nothing left is refused - an empty denylist passing
# everything is the defect these gates exist to stop.
load_patterns() {
  pf_file="${1:-}"
  pf_out="${2:-}"
  if [ -z "$pf_file" ] || [ ! -f "$pf_file" ]; then
    echo "REFUSED: pattern file '${pf_file:-<none given>}' is missing. Its gate has"
    echo "nothing to check against, and passing would report a check that never ran."
    return 1
  fi
  if ! sed -e 's/\r$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
       -e '/^#/d' -e '/^$/d' "$pf_file" > "$pf_out"; then
    echo "REFUSED: pattern file '$pf_file' could not be read."
    return 1
  fi
  if [ ! -s "$pf_out" ]; then
    echo "REFUSED: pattern file '$pf_file' declares no patterns - only comments or"
    echo "blank lines. An empty list would pass everything."
    return 1
  fi
}
