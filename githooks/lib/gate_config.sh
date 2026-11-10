#!/bin/sh
################################################################################
# File: gate_config.sh
# Path: {PROJECT_ROOT}/githooks/lib/gate_config.sh
# Created by: Ryan Severe
# Created: 2026-10-13
# Last Updated: 2026-11-06
# Description: Sourced by the pre-push hook and its gates. gate_config KEY prints
#              KEY's value from the rendered .githooks/gate-config, and fails
#              when the file, the key or the value is missing. Tracked rather
#              than git config, which one command could change unseen.
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


# Read with sed, never sourced: sourcing would run whatever the file holds. A
# caller that gets a failure must refuse - a default would make deleting the
# file a way to change the setting.
gate_config() {
  gc_root="$(git rev-parse --show-toplevel 2>/dev/null)" || return 1
  gc_file="$gc_root/.githooks/gate-config"
  [ -f "$gc_file" ] || return 1
  # tr strips the carriage return an autocrlf checkout leaves on Windows.
  gc_value="$(sed -n "s/^$1=//p" "$gc_file" | head -n 1 | tr -d '\r')"
  [ -n "$gc_value" ] || return 1
  printf '%s\n' "$gc_value"
}
