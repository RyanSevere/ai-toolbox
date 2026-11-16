#!/bin/sh
################################################################################
# File: test-orphans.sh
# Path: {PROJECT_ROOT}/githooks/gates/test-orphans.sh
# Created by: Ryan Severe
# Created: 2026-09-23
# Last Updated: 2026-11-16
# Description: Refuses a test file that no declared test root covers, and a
#              declaration that covers nothing. Ported from
#              workflows/test-orphans.yml, whose bash arrays are newline lists
#              here because the hook runs gates with sh.
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

# shellcheck source=/dev/null
. "$(dirname "$0")/../lib/gate_config.sh"
if ! config_dir="$(gate_config config-dir)"; then
  echo "REFUSED: .githooks/gate-config names no config-dir, so there is no telling where"
  echo "this repo declares its test roots. Re-render it from its profile: python core/sync.py --profile . <repo> --write"
  exit 1
fi
decl="$config_dir/test-roots"
pattern='(^|/)(test_[^/]+\.py|[^/]+_test\.py|[^/]+\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs))$'

# Tracked files only. An untracked stray belongs to whoever made it.
tests="$(git ls-files | grep -E "$pattern" || true)"
test_count=$(printf '%s' "$tests" | grep -c . || true)

if [ ! -f "$decl" ]; then
  if [ "$test_count" -eq 0 ]; then
    echo "No test files and no declaration. Nothing to check."
    exit 0
  fi
  echo "REFUSED: $test_count test file(s) present, and no $decl says where tests live."
  printf '%s\n' "$tests" | sed 's/^/  /'
  echo ""
  echo "Create $decl listing one path per line. Prefix a line with '!' to"
  echo "exclude an archived tree that is deliberately not run."
  exit 1
fi

roots=""
excludes=""
while IFS= read -r line || [ -n "$line" ]; do
  line="${line%%#*}"
  line="$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  line="${line%/}"
  [ -z "$line" ] && continue
  case "$line" in
    run:*|parallel:*) continue ;;  # directives for the tests gate, not roots
    !*) excludes="$excludes${line#!}
" ;;
    *) roots="$roots$line
" ;;
  esac
done < "$decl"

if [ -z "$roots" ] && [ -z "$excludes" ]; then
  # 'none:' is the deliberate answer this file also carries for the test-policy
  # gate. It is a comment, so the stripping above leaves nothing - which read as
  # an empty declaration until this case existed.
  if grep -qiE '^[[:space:]]*#?[[:space:]]*none:' "$decl"; then
    if [ "$test_count" -eq 0 ]; then
      echo "$decl declares no tests deliberately, and there are none."
      exit 0
    fi
    echo "REFUSED: $decl declares 'none', but $test_count test file(s) exist:"
    printf '%s\n' "$tests" | sed 's/^/  /'
    exit 1
  fi
  echo "REFUSED: $decl exists but declares nothing."
  exit 1
fi

covered_by() {
  # $1 file, $2 newline list of prefixes. Echoes the matching prefix, or nothing.
  for prefix in $2; do
    case "$1" in "$prefix"/*|"$prefix") printf '%s' "$prefix"; return 0 ;; esac
  done
  return 1
}

orphans=""
hit_roots=""
hit_excludes=""
for f in $tests; do
  if prefix="$(covered_by "$f" "$roots")"; then
    echo "  ok         $f"
    hit_roots="$hit_roots$prefix
"
  elif prefix="$(covered_by "$f" "$excludes")"; then
    echo "  excluded   $f"
    hit_excludes="$hit_excludes$prefix
"
  else
    echo "  ORPHAN     $f"
    orphans="$orphans$f
"
  fi
done

# A declaration that matches nothing is drift. It reads as coverage that exists,
# which is the same failure this gate catches, pointed the other way.
stale=""
for r in $roots; do
  printf '%s' "$hit_roots" | grep -qx "$r" || stale="${stale}root '$r' contains no test file
"
done
for e in $excludes; do
  printf '%s' "$hit_excludes" | grep -qx "$e" || stale="${stale}exclusion '!$e' matched nothing
"
done

fail=0

if [ -n "$orphans" ]; then
  fail=1
  echo ""
  echo "$(printf '%s' "$orphans" | grep -c .) test file(s) sit outside every declared test root:"
  printf '%s' "$orphans" | sed 's/^/  /'
  echo ""
  echo "A test nothing runs is worse than no test - it reads as coverage."
  echo "Either add its directory to $decl and make sure something runs it, or"
  echo "delete the file. Present-and-unrun is the state to eliminate."
fi

if [ -n "$stale" ]; then
  fail=1
  echo ""
  echo "$(printf '%s' "$stale" | grep -c .) stale entr(ies) in $decl:"
  printf '%s' "$stale" | sed 's/^/  /'
  echo ""
  echo "Remove them. A declaration pointing at nothing is a claim that tests"
  echo "live somewhere they do not."
fi

[ "$fail" -eq 0 ] || exit 1

echo ""
echo "$test_count test file(s), all accounted for."
