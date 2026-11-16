#!/bin/sh
################################################################################
# File: typecheck.sh
# Path: {PROJECT_ROOT}/githooks/gates/typecheck.sh
# Created by: Ryan Severe
# Created: 2026-09-23
# Last Updated: 2026-11-16
# Description: Refuses TypeScript no tsconfig covers, then type-checks each
#              project against its own config. Ported from
#              workflows/typecheck.yml. Assumes dependencies are already
#              installed - if they are not, that is reported as a distinct
#              failure rather than blamed on the types.
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
. "$(dirname "$0")/../lib/rendered_only.sh"
if rendered_only "${1:-}" "${2:-}"; then
  echo "skipped: every file in ${2}..${1} is rendered output, which no tsconfig here covers"
  exit 0
fi

ts="$(git ls-files '*.ts' '*.tsx' | grep -v '\.d\.ts$' || true)"
if [ -z "$ts" ]; then
  echo "No TypeScript files."
  exit 0
fi
ts_count=$(printf '%s' "$ts" | grep -c . || true)

configs="$(git ls-files '*tsconfig*.json' || true)"
if [ -z "$configs" ]; then
  echo "REFUSED: $ts_count TypeScript file(s) and no tsconfig anywhere."
  echo "Type-checking cannot be attempted, so nothing here is verified."
  exit 1
fi

# Coarser than tsc's own include/exclude resolution, and deliberately so: a file
# under a config's directory is treated as covered by it.
uncovered=""
for f in $ts; do
  covered=""
  for cfg in $configs; do
    root="$(dirname "$cfg")"
    [ "$root" = "." ] && root=""
    if [ -z "$root" ] || [ "${f#"$root"/}" != "$f" ]; then
      covered=yes
      break
    fi
  done
  [ -n "$covered" ] || uncovered="$uncovered$f
"
done

if [ -n "$uncovered" ]; then
  echo "$(printf '%s' "$uncovered" | grep -c .) TypeScript file(s) that no tsconfig covers:"
  printf '%s' "$uncovered" | sed 's/^/  /'
  echo ""
  echo "Give the directory a tsconfig.json, or delete the files."
  exit 1
fi

# Only configs beside a package.json can have had their dependencies installed,
# which tsc needs to resolve imports and @types.
projects=""
for cfg in $configs; do
  dir="$(dirname "$cfg")"
  [ -f "$dir/package.json" ] || continue
  printf '%s' "$projects" | grep -qx "$dir" && continue
  projects="$projects$dir
"
done

if [ -z "$projects" ]; then
  echo "$ts_count TypeScript file(s), all covered. No project has a package.json."
  exit 0
fi

# "your dependencies are missing" and "your types are wrong" are different
# problems with different owners. Conflating them under one red cross is how a
# gate starts getting waved through.
missing_deps=""
type_failed=""
tool_failed=""
out="$(mktemp)"
for dir in $projects; do
  if [ ! -d "$dir/node_modules" ]; then
    missing_deps="$missing_deps$dir
"
    continue
  fi
  echo "type-checking $dir"
  # A solution-style tsconfig ("files": [] plus references) checks nothing itself -
  # one such did, so a planted error passed. Read with TypeScript's own parser,
  # which accepts the comments JSON does not; empty output means "check tsconfig.json".
  refs="$(cd "$dir" && node -e '
    const ts = require("typescript");
    const c = ts.readConfigFile("tsconfig.json", ts.sys.readFile).config || {};
    if (Array.isArray(c.files) && c.files.length === 0 && !c.include && Array.isArray(c.references))
      for (const r of c.references) console.log(r.path);
  ' 2>/dev/null || true)"
  for cfg in ${refs:-tsconfig.json}; do
    # To a file, never a pipe: piped through sed, tsc's status was sed's.
    (cd "$dir" && npx --no-install tsc -p "$cfg" --noEmit) > "$out" 2>&1
    rc=$?
    sed 's/^/    /' "$out"
    [ "$rc" -eq 0 ] && continue
    if grep -q 'error TS' "$out"; then
      type_failed="$type_failed$dir ($cfg)
"
    else
      tool_failed="$tool_failed$dir ($cfg), exit $rc
"
    fi
  done
done
rm -f "$out"

if [ -n "$missing_deps" ]; then
  echo ""
  echo "Dependencies are not installed in:"
  printf '%s' "$missing_deps" | sed 's/^/  /'
  echo ""
  echo "Run npm ci there. This is not a type error - nothing was checked, and"
  echo "reporting it as a pass would be the false-healthy reading that"
  echo "counts as a defect."
fi

if [ -n "$tool_failed" ]; then
  echo ""
  echo "tsc could not run in:"
  printf '%s' "$tool_failed" | sed 's/^/  /'
  echo ""
  echo "Not a type error and not a pass: nothing was checked. Under WSL 1, npx"
  echo "cannot find Node - push from a shell where 'npx tsc --version' works."
fi

if [ -n "$type_failed" ]; then
  echo ""
  echo "Type errors in:"
  printf '%s' "$type_failed" | sed 's/^/  /'
fi

if [ -n "$missing_deps" ] || [ -n "$tool_failed" ] || [ -n "$type_failed" ]; then
  exit 1
fi

echo ""
echo "$ts_count TypeScript file(s) type-check clean."
