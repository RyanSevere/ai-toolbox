#!/bin/sh
################################################################################
# File: no-change-docs.sh
# Path: {PROJECT_ROOT}/githooks/gates/no-change-docs.sh
# Created by: Ryan Severe
# Created: 2026-09-23
# Last Updated: 2026-11-16
# Description: Refuses markdown added outside the places documents live. Ported
#              from workflows/no-change-docs.yml. The only gate that compares a
#              range rather than a tree, which is why the hook passes it the
#              pushed sha and the sha already on the remote. A repo may declare
#              extra homes in doc-paths in its gate-config config-dir, one
#              directory per line.
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

local_sha="${1:-}"
remote_sha="${2:-}"

# An all-zero or empty remote sha means a new branch: nothing on the remote to
# compare against. Treat it as nothing to check rather than diffing the world.
case "$remote_sha" in
  "" | *[!0]*) ;;
  *) remote_sha="" ;;
esac

if [ -z "$local_sha" ] || [ -z "$remote_sha" ]; then
  echo "No comparable base - first push or a new branch. Nothing to compare."
  exit 0
fi

echo "Comparing $remote_sha..$local_sha"
added="$(git diff --name-only --diff-filter=A "$remote_sha..$local_sha" -- '*.md' || true)"

if [ -z "$added" ]; then
  echo "No markdown added."
  exit 0
fi

# Repo-specific homes, hand-owned like test-roots: one directory per line, '#'
# starts a comment, a trailing '/' is optional. Kept in the profile's config-dir.
# shellcheck source=/dev/null
. "$(dirname "$0")/../lib/gate_config.sh"
# shellcheck source=/dev/null
. "$(dirname "$0")/../lib/stamp.sh"
if ! config_dir="$(gate_config config-dir)"; then
  echo "REFUSED: .githooks/gate-config names no config-dir, so there is no telling where"
  echo "this repo declares its doc-paths. Re-render it from its profile: python core/sync.py --profile . <repo> --write"
  exit 1
fi
decl="$config_dir/doc-paths"
declared=""
if [ -f "$decl" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    line="$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    line="${line%/}"
    [ -n "$line" ] && declared="$declared$line
"
  done < "$decl"
fi

# One verdict per file, used by both loops below so they cannot disagree.
classify() {
  # Generated output carries a stamp and is owned by the renderer.
  if [ -f "$1" ] && stamped < "$1"; then
    echo "generated"; return
  fi
  case "$1" in
    docs/*|project-docs/*|planning-docs/*|session-logs/*|.github/*|.cursor/*)
      echo "allowed path"; return ;;
    README.md|*/README.md|AGENTS.md|*/AGENTS.md|CHANGELOG.md|LICENSE.md)
      echo "conventional"; return ;;
  esac
  # Line by line: an entry is one literal directory, never split or globbed.
  if printf '%s' "$declared" | {
    while IFS= read -r dir; do
      case "$1" in "$dir"/*) exit 0 ;; esac
    done
    exit 1
  }; then
    echo "declared"; return
  fi
  echo "REFUSED"
}

fail=0
printf '%s\n' "$added" | while IFS= read -r file; do
  [ -z "$file" ] && continue
  verdict="$(classify "$file")"
  if [ "$verdict" = "REFUSED" ]; then
    echo "  REFUSED             $file"
  else
    printf '  %-19s %s\n' "ok ($verdict)" "$file"
  fi
done

# The loop above runs in a subshell, so its exit state cannot be read directly.
# Recomputing the refusals is cheaper than a temp file and cannot drift, because
# classify decides both.
refused="$(printf '%s\n' "$added" | while IFS= read -r file; do
  [ -n "$file" ] && [ "$(classify "$file")" = "REFUSED" ] && echo "$file"
done | grep -c . || true)"

if [ "$refused" -ne 0 ]; then
  echo ""
  echo "A new markdown file was added outside the places documents live."
  echo ""
  echo "If it explains a change, it belongs in the commit message or the issue,"
  echo "both of which stay attached to the change. A separate file describing"
  echo "work that just happened goes stale the moment anything else moves."
  echo ""
  echo "If it is a genuine design document, put it in docs/, project-docs/ or"
  echo "planning-docs/ and this will pass. If this repo keeps source markdown"
  echo "somewhere else, declare that directory in $decl."
  exit 1
fi

echo "All added markdown accounted for."
exit "$fail"
