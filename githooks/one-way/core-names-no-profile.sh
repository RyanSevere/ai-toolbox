#!/bin/sh
################################################################################
# File: core-names-no-profile.sh
# Path: {PROJECT_ROOT}/githooks/one-way/core-names-no-profile.sh
# Created by: Ryan Severe
# Created: 2026-10-15
# Last Updated: 2026-11-06
# Description: One-way gate 4. Refuses a core tree in which any file names a
#              profile from the profile-supplied list. Scans a given tree,
#              because in a profile the core is a directory inside it. Reports
#              where, never what. Usage: core-names-no-profile.sh NAMES TREE.
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

. "$(dirname "$0")/../lib/pattern_file.sh"

name_file="${1:-}"
tree="${2:-}"

work="$(mktemp -d)" || { echo "REFUSED: no temporary directory."; exit 1; }
trap 'rm -rf "$work"' EXIT

load_patterns "$name_file" "$work/names" || exit 1

# A tree that is not there had nothing scanned, which is not nothing found.
if [ -z "$tree" ] || [ ! -d "$tree" ]; then
  echo "REFUSED: core tree '${tree:-<none given>}' does not exist, so nothing was scanned."
  exit 1
fi

# Relative to the tree, so a Windows drive letter's colon cannot split a location.
(cd "$tree" && grep -r -l -I --exclude-dir=.git '' .) > "$work/files"
case $? in
  0) ;;
  1)
    echo "REFUSED: core tree '$tree' holds no text files, so nothing was scanned."
    exit 1
    ;;
  *)
    echo "REFUSED: the core tree could not be listed, so nothing was checked."
    exit 1
    ;;
esac

# Fixed strings, case-folded in awk: grep 3.0, which Git for Windows ships, aborts
# on -F -i together.
if ! (cd "$tree" && tr '\n' '\0' < "$work/files" | xargs -0 awk '
  FILENAME == ARGV[1] { want[++n] = tolower($0); next }
  { text = tolower($0); for (i = 1; i <= n; i++) if (index(text, want[i])) { print FILENAME ":" FNR; next } }
' "$work/names") > "$work/hits"; then
  echo "REFUSED: the core tree could not be scanned, so nothing was checked."
  exit 1
fi

if [ ! -s "$work/hits" ]; then
  echo "The core names no profile."
  exit 0
fi

echo "REFUSED: $(grep -c . "$work/hits") line(s) in the core name a profile."
# Where, never what.
sed -e 's#^\./##' -e 's/^/  /' "$work/hits"
echo ""
echo "The core is generic: profile names belong in the profile, never in core files."
exit 1
