#!/bin/sh
################################################################################
# File: self-render.sh
# Path: {PROJECT_ROOT}/githooks/gates/self-render.sh
# Created by: Ryan Severe
# Created: 2026-09-27
# Last Updated: 2026-11-16
# Description: Refuses a profile-source push whose rendered copies of its own rules
#              do not match what its source renders, checked on the commit being
#              pushed rather than the working tree. Passes as not applicable in
#              every other repo. The rules-drift workflow stays as the backstop
#              for pushes that skip hooks.
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

sha="${1:-}"
case "$sha" in
  *[!0-9a-f]* | "")
    echo "REFUSED: no commit to check was given."
    exit 1
    ;;
esac

# Only a profile renders itself: profile.yaml at the root, the core under core/.
if ! git cat-file -e "$sha:core/sync.py" 2>/dev/null || ! git cat-file -e "$sha:profile.yaml" 2>/dev/null; then
  echo "Not a profile source repository. Nothing to check."
  exit 0
fi

# python3 first would find the Windows Store stub, which exists and does not run.
py=""
for candidate in python python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import yaml" >/dev/null 2>&1; then
    py="$candidate"
    break
  fi
done
if [ -z "$py" ]; then
  echo "REFUSED: no python that can import yaml, so the render cannot be checked."
  echo "Install PyYAML. A check that cannot run is not a pass."
  exit 1
fi

tree="$(mktemp -d)"
cleanup() {
  git worktree remove --force "$tree" >/dev/null 2>&1 || true
  rm -rf "$tree"
}
trap cleanup EXIT

# The commit being pushed, not the working tree - they differ whenever work is uncommitted.
if ! git worktree add --quiet --detach "$tree" "$sha" >/dev/null 2>&1; then
  echo "REFUSED: could not check out $sha to compare it."
  exit 1
fi

# Hooks run with GIT_DIR set, which would point sync.py's git calls at the main tree.
if (cd "$tree" && env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE \
      "$py" core/sync.py --profile . --self --check --no-fetch); then
  exit 0
fi
echo ""
echo "Run: python core/sync.py --profile . --self --write, commit the result, and push again."
exit 1
