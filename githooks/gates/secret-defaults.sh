#!/bin/sh
################################################################################
# File: secret-defaults.sh
# Path: {PROJECT_ROOT}/githooks/gates/secret-defaults.sh
# Created by: Ryan Severe
# Created: 2026-09-26
# Last Updated: 2026-11-16
# Description: Refuses a push while any tracked compose, YAML or env-example
#              file gives a secret-named variable a default - ${X:-value},
#              ${X-value}, or the empty ${X:-}. A missing secret must abort,
#              which is what ${X:?message} does. Same pattern as the editor hook
#              hooks/no-secret-defaults, held to it by a parity test.
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

allow="no-secret-defaults: allow"
secretish='(secret|password|passwd|token|api[_-]?key|apikey|credential|private[_-]?key|jwt|auth)'
default='\$\{[A-Za-z0-9_]*'"$secretish"'[A-Za-z0-9_]*:?-[^}]*\}'

files="$(git ls-files '*.yml' '*.yaml' '*.env.example' '*compose*' | sort -u || true)"
if [ -z "$files" ]; then
  echo "No compose, YAML or env-example files."
  exit 0
fi

list="$(mktemp)"
printf '%s\n' "$files" > "$list"
hits=""
checked=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  checked=$((checked + 1))
  found="$(grep -niE "$default" "$f" | grep -vF "$allow" | cut -d: -f1 || true)"
  for n in $found; do
    hits="${hits}${f}:${n}
"
  done
done < "$list"
rm -f "$list"

if [ -z "$hits" ]; then
  echo "$checked file(s) checked, no secret given a default."
  exit 0
fi

echo "REFUSED: $(printf '%s' "$hits" | grep -c .) secret(s) given a default:"
printf '%s' "$hits" | sed 's/^/  /'
echo ""
echo "A missing secret must abort, not continue with a placeholder or an empty"
echo "string. Use \${NAME:?NAME must be set}. If a match is not a secret, add"
echo "'$allow' to the line."
exit 1
