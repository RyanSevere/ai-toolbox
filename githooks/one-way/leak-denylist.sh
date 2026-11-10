#!/bin/sh
################################################################################
# File: leak-denylist.sh
# Path: {PROJECT_ROOT}/githooks/one-way/leak-denylist.sh
# Created by: Ryan Severe
# Created: 2026-10-15
# Last Updated: 2026-11-06
# Description: One-way gate 1. Refuses a push whose added lines contain any
#              string in the profile's denylist - repository names, private
#              address prefixes, employer strings. Reports where, never what.
#              Usage: leak-denylist.sh PATTERNS LOCAL_SHA REMOTE_SHA.
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

lib="$(dirname "$0")/../lib"
. "$lib/pattern_file.sh"
. "$lib/commit_range.sh"

pattern_file="${1:-}"
local_sha="${2:-}"
remote_sha="${3:-}"

work="$(mktemp -d)" || { echo "REFUSED: no temporary directory."; exit 1; }
trap 'rm -rf "$work"' EXIT

load_patterns "$pattern_file" "$work/patterns" || exit 1

if [ -z "$local_sha" ]; then
  echo "REFUSED: no commit given, so there is nothing to scan."
  exit 1
fi

# A new branch is diffed against the empty tree: every line in it is new.
if is_new_branch "$remote_sha" || ! git cat-file -e "$remote_sha^{commit}" 2>/dev/null; then
  base="$(git hash-object -t tree /dev/null)"
else
  base="$remote_sha"
fi

# A diff that fails yields no added lines, and scanning no lines is not a pass.
if ! git diff --unified=0 --no-color --no-ext-diff "$base" "$local_sha" > "$work/diff" 2>/dev/null; then
  echo "REFUSED: could not compute the lines this push adds, so none were checked."
  exit 1
fi

# Locations and texts in two files, line for line, so only the text is matched and
# only the location is ever printed.
awk -v locs="$work/locs" -v texts="$work/texts" '
  /^\+\+\+ / { file = substr($0, 7); next }
  /^@@/      { split($3, a, ","); line = substr(a[1], 2) + 0; next }
  /^\+/      { print file ":" line > locs; print substr($0, 2) > texts; line++; next }
' "$work/diff"
: >> "$work/locs"
: >> "$work/texts"

# Fixed strings, case-folded in awk: grep 3.0, which Git for Windows ships, aborts
# on -F -i together.
if ! awk '
  FILENAME == ARGV[1] { want[++n] = tolower($0); next }
  { text = tolower($0); for (i = 1; i <= n; i++) if (index(text, want[i])) { print FNR; next } }
' "$work/patterns" "$work/texts" > "$work/index"; then
  echo "REFUSED: the denylist could not be matched, so nothing was checked."
  exit 1
fi

if [ ! -s "$work/index" ]; then
  echo "No denylisted string in the lines being pushed."
  exit 0
fi

echo "REFUSED: $(grep -c . "$work/index") added line(s) match the profile's leak denylist."
# Where, never what: the report is published, and the denylist is secret-held.
awk 'NR == FNR { want[$1]; next } FNR in want { print "  " $0 }' "$work/index" "$work/locs"
echo ""
echo "These lines carry something that must not reach the public core. Remove it,"
echo "or move the content to the profile."
exit 1
