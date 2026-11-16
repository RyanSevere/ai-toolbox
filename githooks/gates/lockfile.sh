#!/bin/sh
################################################################################
# File: lockfile.sh
# Path: {PROJECT_ROOT}/githooks/gates/lockfile.sh
# Created by: Ryan Severe
# Created: 2026-09-26
# Last Updated: 2026-11-16
# Description: Refuses a push while any tracked package-lock.json describes a
#              dependency tree npm itself calls invalid. Uses npm ls in
#              lockfile-only mode, so nothing is installed and a directory
#              without node_modules is still checked. npm ci does not catch
#              this - it passed on a broken tree.
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

locks="$(git ls-files '*package-lock.json' | grep -v '/node_modules/' || true)"
if [ -z "$locks" ]; then
  echo "No package-lock.json tracked."
  exit 0
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "REFUSED: $(printf '%s\n' "$locks" | grep -c .) lockfile(s) tracked and npm is not on PATH."
  echo "Nothing was checked. Reporting that as a pass would be a false healthy reading."
  exit 1
fi

list="$(mktemp)"
log="$(mktemp)"
printf '%s\n' "$locks" > "$list"
failed=""
checked=0
while IFS= read -r lock; do
  dir="$(dirname "$lock")"
  checked=$((checked + 1))
  # To a file, never through a pipe: the pipe is how typecheck.sh lost its exit status.
  (cd "$dir" && npm ls --all --package-lock-only) > "$log" 2>&1 < /dev/null
  if [ "$?" -ne 0 ]; then
    failed="${failed}${dir}
"
    echo "invalid tree in $dir:"
    grep -E 'invalid|missing|ERR' "$log" | head -n 8 | sed 's/^/    /'
  fi
done < "$list"
rm -f "$list" "$log"

if [ -n "$failed" ]; then
  echo ""
  echo "REFUSED: npm reports an invalid dependency tree in the lockfile(s) above."
  echo "A clean checkout would install something the manifest does not allow."
  exit 1
fi

echo "$checked lockfile(s), every tree valid."
