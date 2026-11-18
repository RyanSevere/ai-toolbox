#!/bin/sh
################################################################################
# File: rerun.sh
# Path: {PROJECT_ROOT}/actions/report-gate/rerun.sh
# Created by: Ryan Severe
# Created: 2026-11-18
# Last Updated: 2026-11-18
# Description: Runs the gates a profile lists as report-rerun= in gate-config,
#              from the core release it vendored, against the pushed commit.
#              The gate scripts are fetched at core-tag from core-source into a
#              fresh directory under $RUNNER_TEMP and never taken from the
#              pushed commit's own .githooks/gates/. Writes one '<gate> pass|fail'
#              line each to $RUNNER_TEMP/rerun.txt. A fetch that fails, a tag the
#              core lacks, or a listed gate it does not have fails the step.
#              Values arrive through the environment, never the script text.
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


set -eu

: "${SHA:?SHA is required}"
: "${GATE_CONFIG:?GATE_CONFIG is required}"
: "${RUNNER_TEMP:?RUNNER_TEMP is required}"
# Only a test sets this, to point the fetch at a local bare repository.
base_url="${CORE_URL_BASE:-https://github.com}"

verdicts="$RUNNER_TEMP/rerun.txt"
rm -f "$verdicts"

# tr strips the carriage return an autocrlf checkout leaves on Windows.
config_values() {
  sed -n "s/^$1=//p" "$GATE_CONFIG" | tr -d '\r'
}

if [ ! -f "$GATE_CONFIG" ]; then
  echo "REFUSED: gate-config $GATE_CONFIG cannot be read, so the gates to re-run are unknown."
  exit 1
fi

gates="$(config_values report-rerun | awk 'NF && !seen[$0]++')"
if [ -z "$gates" ]; then
  echo "No report-rerun= line in gate-config: no gate is run again."
  exit 0
fi

source_repo="$(config_values core-source | head -n 1)"
tag="$(config_values core-tag | head -n 1)"
if ! printf '%s' "$source_repo" | grep -Eqx '[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_][A-Za-z0-9._-]*'; then
  echo "REFUSED: gate-config lists gates to re-run but has no valid core-source=, so the core"
  echo "cannot be fetched. Render the profile from a vendored core."
  exit 1
fi
if printf '%s' "$tag" | grep -Eqx 'v[0-9]+\.[0-9]+\.[0-9]+'; then
  ref="refs/tags/$tag"
elif printf '%s' "$tag" | grep -Eqx '[0123456789abcdef]{40}'; then
  ref="$tag"
else
  echo "REFUSED: gate-config lists gates to re-run but has no valid core-tag= (a vX.Y.Z tag or"
  echo "a full commit id), so there is no release to fetch the gates at."
  exit 1
fi

# A fresh directory every run: nothing a previous run fetched can stand in for this one.
core="$(mktemp -d "$RUNNER_TEMP/core-rerun.XXXXXX")"
url="$base_url/$source_repo.git"
if ! git -C "$core" init --quiet \
    || ! git -C "$core" fetch --quiet --depth=1 "$url" "$ref" \
    || ! git -C "$core" checkout --quiet FETCH_HEAD; then
  echo "REFUSED: could not fetch $tag from $source_repo, so the gates cannot be run again."
  exit 1
fi
if [ ! -d "$core/githooks/gates" ]; then
  echo "REFUSED: $source_repo at $tag has no githooks/gates/, so there is nothing to run."
  exit 1
fi

# The hook passes all zeros for a new branch; so does this, for an empty before.
before="${BEFORE:-}"
[ -n "$before" ] || before="0000000000000000000000000000000000000000"

failed=0
while IFS= read -r name; do
  if ! printf '%s' "$name" | grep -Eqx '[a-z0-9][a-z0-9-]*'; then
    echo "REFUSED: '$name' is not a gate name."
    exit 1
  fi
  gate="$core/githooks/gates/$name.sh"
  if [ ! -f "$gate" ]; then
    echo "REFUSED: $name is not a gate in $source_repo at $tag."
    exit 1
  fi
  # Closed stdin, as the hook runs it, because this loop's stdin is the list itself.
  if output="$(sh "$gate" "$SHA" "$before" origin 2>&1 < /dev/null)"; then
    echo "rerun $name: pass"
    echo "$name pass" >> "$verdicts"
  else
    echo "rerun $name: FAIL"
    printf '%s\n' "$output" | sed 's/^/    /'
    echo "$name fail" >> "$verdicts"
    failed=1
  fi
done <<EOF
$gates
EOF

# A failing gate is not this step's failure: the check judges it against the report, and
# names the mismatch. Only a re-run that could not happen fails here.
[ "$failed" -eq 0 ] || echo "At least one gate failed when run again from $source_repo at $tag."
exit 0
