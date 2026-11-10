#!/bin/sh
################################################################################
# File: stamp.sh
# Path: {PROJECT_ROOT}/githooks/lib/stamp.sh
# Created by: Ryan Severe
# Created: 2026-10-29
# Last Updated: 2026-11-09
# Description: Sourced by gates. stamped succeeds when its standard input
#              carries a render stamp within its first 40 lines - deep enough
#              to pass an agent's frontmatter, which precedes its stamp. One
#              test, so the gates cannot disagree on what is rendered.
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


# The stamp names the profile that rendered the file, so any source name counts. A consuming
# repository's stamp carries the source SHA; the profile's own render carries none.
stamped() {
  head -n 40 | grep -Eq 'generated from [^ @]+(@[0-9a-f]{7}| - edit the source)'
}
