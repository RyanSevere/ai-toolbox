#!/bin/sh
################################################################################
# File: secret-scan.sh
# Path: {PROJECT_ROOT}/githooks/gates/secret-scan.sh
# Created by: Ryan Severe
# Created: 2026-09-26
# Last Updated: 2026-11-16
# Description: Refuses a push whose added lines carry a credential shape: a
#              private key header, a bare 32-hex token, or an env-style
#              NAME=value where NAME ends in KEY, TOKEN, SECRET or PASSWORD and
#              the value is long and not a placeholder. Heuristic by design -
#              a line can opt out with 'secret-scan: allow'. The
#              shapes are in .githooks/lib/secret_shapes.py, shared
#              with the write-observer hook.
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

local_sha="${1:-HEAD}"
remote_sha="${2:-}"
allow="secret-scan: allow"

# No base means a new branch: every line in it is new, so every line is scanned.
case "$remote_sha" in
  ""|*[!0]*) base="$remote_sha" ;;
  *) base="" ;;
esac
if [ -z "$base" ] || ! git cat-file -e "$base^{commit}" 2>/dev/null; then
  base="$(git hash-object -t tree /dev/null)"
fi

added="$(mktemp)"
git diff --unified=0 --no-color --no-ext-diff "$base" "$local_sha" > "$added" 2>/dev/null

# The shapes live in one place, the core's secret_shapes.py, rendered beside the gates.
# The write-observer hook reads the same file, so the two cannot drift.
lib="$(cd "$(dirname "$0")/../lib" 2>/dev/null && pwd)/secret_shapes.py"
if [ ! -f "$lib" ]; then
  rm -f "$added"
  echo "REFUSED: $lib is missing. Run sync.py against this repo."
  exit 1
fi
# python3 first would find the Windows Store stub, which exists and does not run.
py=""
for candidate in python python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import sys" >/dev/null 2>&1; then
    py="$candidate"
    break
  fi
done
if [ -z "$py" ]; then
  rm -f "$added"
  echo "REFUSED: no working python, so the lines cannot be scanned."
  exit 1
fi

lines="$(awk -v allow="$allow" '
  /^\+\+\+ / { file = substr($0, 7); next }
  /^@@/      { split($3, a, ","); line = substr(a[1], 2) + 0; next }
  /^\+/      { if (index($0, allow) == 0) print file ":" line ": " substr($0, 2); line++; next }
' "$added")"
rm -f "$added"

# Every line in is "file:line: text"; every hit out is "file:line: <shape>".
found="$(printf '%s\n' "$lines" | "$py" "$lib" | grep . | sort -u || true)"

if [ -z "$found" ]; then
  echo "No credential-shaped strings in the lines being pushed."
  exit 0
fi

echo "REFUSED: $(printf '%s\n' "$found" | grep -c .) line(s) look like a committed credential."
# Report where, never what. Printing the match would copy the secret into the
# hook's output and from there into the published gate report.
printf '%s\n' "$found" | cut -d: -f1,2 | sed 's/^/  /'
echo ""
echo "Once pushed, a key is in history for good and the only remedy is rotation."
echo "Move it to an untracked .env, or if the line is genuinely not a secret,"
echo "add '$allow' to it."
exit 1
