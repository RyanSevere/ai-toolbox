#!/bin/sh
################################################################################
# File: tests.sh
# Path: {PROJECT_ROOT}/githooks/gates/tests.sh
# Created by: Ryan Severe
# Created: 2026-09-26
# Last Updated: 2026-11-24
# Description: Runs each test command a repository declares with a 'run:' line
#              in test-roots, in its gate-config config-dir, and refuses the
#              push if any fails. Given a pushed commit, the commands run in a
#              temporary worktree of that commit, removed on every exit; a
#              'link:' line links an untracked folder into it. A
#              repository that deliberately has no tests says 'none:' there
#              and passes; one that says neither fails. A
#              'parallel:' line runs the commands concurrently, at most N at
#              once - opt-in, because suites that share a port or a database
#              would collide. 'yes' means one per CPU, at most 16, a positive integer
#              means that many, 'no' means serial; anything else is refused.
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

# Git exports these to hooks. A test that runs git in a temp dir would act on this
# repo instead - one once re-initialised the repo as bare.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX GIT_COMMON_DIR \
      GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES 2>/dev/null || true

# shellcheck source=/dev/null
. "$(dirname "$0")/../lib/rendered_only.sh"
if rendered_only "${1:-}" "${2:-}"; then
  echo "skipped: every file in ${2}..${1} is rendered output, which this repo's tests do not read"
  exit 0
fi

# shellcheck source=/dev/null
. "$(dirname "$0")/../lib/gate_config.sh"
if ! config_dir="$(gate_config config-dir)"; then
  echo "REFUSED: .githooks/gate-config names no config-dir, so there is no telling where"
  echo "this repo declares its tests. Re-render it from its profile: python core/sync.py --profile . <repo> --write"
  exit 1
fi
decl="$config_dir/test-roots"
pattern='(^|/)(test_[^/]+\.py|[^/]+_test\.py|[^/]+\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs))$'
tail_lines=40

# A suite may narrow itself to what the push changed. Empty means unknown.
PUSH_LOCAL_SHA="${1:-}"
PUSH_REMOTE_SHA="${2:-}"

# Targeted on branches, where work collects; everything on the deploy branch. The hook
# names the ref being pushed. Without it (the gate run by hand) the range is as given.
# An unknown is never a narrower selection: every failure below exports an empty range.
if [ -n "${PUSH_REMOTE_REF:-}" ]; then
  if ! deploy_branch="$(gate_config deploy-branch)"; then
    echo "REFUSED: .githooks/gate-config names no deploy-branch, so there is no telling which"
    echo "push runs the whole suite. Re-render it from its profile: python core/sync.py --profile . <repo> --write"
    exit 1
  fi
  range_remote="${3:-origin}"
  if [ "$PUSH_REMOTE_REF" = "refs/heads/$deploy_branch" ]; then
    PUSH_REMOTE_SHA=""
    echo "range: none (deploy branch $deploy_branch, so every test runs)"
  else
    case "$PUSH_REMOTE_SHA" in
      *[!0]*)
        echo "range: as pushed (existing branch)"
        ;;
      *)
        if PUSH_REMOTE_SHA="$(git merge-base "$PUSH_LOCAL_SHA" "refs/remotes/$range_remote/$deploy_branch" 2>/dev/null)" \
            && [ -n "$PUSH_REMOTE_SHA" ]; then
          echo "range: merge-base with $range_remote/$deploy_branch (new branch)"
        else
          PUSH_REMOTE_SHA=""
          echo "range: none (new branch, no merge base with $range_remote/$deploy_branch, so every test runs)"
        fi
        ;;
    esac
  fi
fi
# The ref only chose the range above; a declared command that runs this gate again must not inherit it.
unset PUSH_REMOTE_REF
export PUSH_LOCAL_SHA PUSH_REMOTE_SHA

# Which tree the commands run in. A push can take twenty minutes, and an edit saved to
# the working tree in that time would be what got tested, then reported against the
# pushed commit. So a pushed commit is checked out into a temporary worktree and every
# command runs there. Run by hand, with no commit given, the working tree is the tree.
tree="."
tree_parent=""
links=""

case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*) on_windows=1 ;;
  *) on_windows=0 ;;
esac

# Removes one link this script made, and never what it points at. A junction is removed
# with rmdir, a symlink with a plain rm: neither recurses, and a recursive delete through
# a junction would wipe the folder it points at.
remove_link() {
  if [ "$on_windows" -eq 1 ]; then
    cmd //c rmdir "$(cygpath -w "$1")" >/dev/null 2>&1 || true
  else
    rm "$1" 2>/dev/null || true
  fi
}

# Safe to call with no temporary tree made: it then touches nothing. It runs on every
# exit path, and only ever removes a tree this script created. Links come out first.
remove_tree() {
  if [ -n "$tree_parent" ] && [ -n "$links" ]; then
    left=""
    while IFS= read -r made_link; do
      [ -n "$made_link" ] || continue
      remove_link "$made_link"
      if [ -e "$made_link" ] || [ -L "$made_link" ]; then
        left="$left $made_link"
      fi
    done <<EOF
$links
EOF
    links=""
    # A link still in place means a recursive delete of the tree would reach through it
    # into the folder it points at. Leave the tree behind rather than risk that.
    if [ -n "$left" ]; then
      echo "WARNING: could not remove the link(s)$left, so the temporary tree $tree is left in place."
      echo "Remove the links by hand, then run 'git worktree prune'."
      tree="."
      tree_parent=""
      return 0
    fi
  fi
  [ -z "$tree_parent" ] || git worktree remove --force "$tree" >/dev/null 2>&1 || true
  [ -z "$tree_parent" ] || git worktree prune >/dev/null 2>&1 || true
  [ -z "$tree_parent" ] || rm -rf "$tree_parent"
  tree="."
  tree_parent=""
}
trap remove_tree EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [ -n "$PUSH_LOCAL_SHA" ]; then
  if ! git rev-parse --verify --quiet "$PUSH_LOCAL_SHA^{commit}" >/dev/null 2>&1; then
    echo "REFUSED: the pushed commit $PUSH_LOCAL_SHA does not resolve to a commit in this repository,"
    echo "so there is no tree to run the tests against."
    exit 1
  fi
  tree_parent="$(mktemp -d)"
  tree="$tree_parent/tree"
  if ! git worktree add --detach --quiet "$tree" "$PUSH_LOCAL_SHA" >/dev/null 2>&1; then
    remove_tree
    echo "REFUSED: could not check out $PUSH_LOCAL_SHA into a temporary worktree to run the tests in."
    exit 1
  fi
  echo "tree: pushed commit $(printf '%.12s' "$PUSH_LOCAL_SHA") (temporary worktree)"
else
  echo "tree: working tree (no pushed commit given)"
fi

if [ ! -f "$tree/$decl" ]; then
  # shellcheck source=/dev/null
  . "$(dirname "$0")/../lib/vendored_core.sh"
  if [ -z "$(cd "$tree" && own_test_files "$pattern")" ]; then
    if (cd "$tree" && has_vendored_core); then
      echo "No test files of its own and no $decl: core/tests/ is the vendored core's, run upstream. Nothing to run."
    else
      echo "No test files and no $decl. Nothing to run."
    fi
    exit 0
  fi
  echo "REFUSED: test files exist and no $decl says how to run them."
  echo "Add a line such as:  run: python -m unittest discover -s tests"
  exit 1
fi

decl_file="$tree/$decl"

# 'link: <path>' names an untracked folder, relative to the repository root, that a suite
# needs and a clean checkout lacks. It is linked, never copied, into the temporary tree
# before any command runs. With no temporary tree the folders are already in place.
refuse_link() {
  echo "REFUSED: $decl has a 'link:' line the gate cannot use: $1"
  echo "A link names an untracked folder in the working tree, relative to the repository root:"
  echo "no absolute path, no '..', and nothing the pushed commit tracks."
  exit 1
}

if [ -n "$tree_parent" ]; then
  link_root="$(git rev-parse --show-toplevel)"
  while IFS= read -r raw_link || [ -n "$raw_link" ]; do
    raw_link="$(printf '%s' "$raw_link" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    # With no 'link:' lines the here-document below still yields one empty line.
    [ -n "$raw_link" ] || continue
    link_path="$(printf '%s' "$raw_link" | sed 's/^link:[[:space:]]*//')"
    link_path="${link_path%/}"
    [ -n "$link_path" ] || refuse_link "'$raw_link' (empty path)"
    case "$link_path" in
      /*|[A-Za-z]:*|*\\*) refuse_link "'$raw_link' (not relative to the repository root)" ;;
    esac
    case "/$link_path/" in
      */../*) refuse_link "'$raw_link' (contains '..')" ;;
    esac
    [ -d "$link_root/$link_path" ] || refuse_link "'$raw_link' (not a folder in the working tree)"
    if git cat-file -e "$PUSH_LOCAL_SHA:$link_path" 2>/dev/null; then
      refuse_link "'$raw_link' (tracked in the pushed commit)"
    fi
    [ ! -e "$tree/$link_path" ] || refuse_link "'$raw_link' (already present in the checkout)"
    mkdir -p "$(dirname "$tree/$link_path")"
    if [ "$on_windows" -eq 1 ]; then
      # '//J' because the shell turns a lone '/J' into a path before cmd sees it.
      cmd //c mklink //J "$(cygpath -w "$tree/$link_path")" "$(cygpath -w "$link_root/$link_path")" >/dev/null 2>&1 \
        || refuse_link "'$raw_link' (the junction could not be made)"
    else
      ln -s "$link_root/$link_path" "$tree/$link_path" \
        || refuse_link "'$raw_link' (the symlink could not be made)"
    fi
    links="$links$tree/$link_path
"
  done <<EOF
$(grep -E '^[[:space:]]*link:' "$decl_file" || true)
EOF
fi
commands="$(sed -n 's/^[[:space:]]*run:[[:space:]]*//p' "$decl_file" | sed 's/[[:space:]]*$//' | grep . || true)"

if [ -z "$commands" ]; then
  if grep -qiE '^[[:space:]]*#?[[:space:]]*none:' "$decl_file"; then
    echo "$decl declares no tests deliberately. Nothing to run."
    exit 0
  fi
  echo "REFUSED: $decl declares where tests live but not how to run them."
  echo "Add one 'run: <command>' line per suite, run from the repository root."
  echo "A suite nothing runs is a claim of coverage that nobody checks."
  exit 1
fi

# How many commands may run at once. A line the gate cannot read never decides how
# the suite runs: it is refused before anything starts, not skipped.
refuse_parallel() {
  echo "REFUSED: $decl has a 'parallel:' line the gate cannot use: $1"
  echo "Use 'parallel: yes' (one command per CPU, at most 16), 'parallel: <positive integer>',"
  echo "or 'parallel: no'. Only one 'parallel:' line is allowed."
  exit 1
}

cpu_count() {
  n="$(nproc 2>/dev/null | tr -d '\r ' || true)"
  case "$n" in ''|*[!0-9]*|0) n="$(getconf _NPROCESSORS_ONLN 2>/dev/null | tr -d '\r ' || true)" ;; esac
  case "$n" in ''|*[!0-9]*|0) return 1 ;; esac
  echo "$n"
}

# 'yes' never goes above this. Measured on 39 commands: 36 at once saved 4 percent over
# 16 and more than doubled the load. An explicit number is a choice and is not clamped.
yes_ceiling=16

cap=1
parallel_lines="$(grep -iE '^[[:space:]]*parallel:' "$decl_file" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' || true)"
if [ -n "$parallel_lines" ]; then
  if [ "$(printf '%s\n' "$parallel_lines" | grep -c .)" -gt 1 ]; then
    refuse_parallel "more than one: $(printf '%s' "$parallel_lines" | tr '\n' '|')"
  fi
  value="$(printf '%s' "$parallel_lines" | sed 's/^[^:]*:[[:space:]]*//' | tr '[:upper:]' '[:lower:]')"
  case "$value" in
    yes)
      if cap="$(cpu_count)"; then
        [ "$cap" -le "$yes_ceiling" ] || cap="$yes_ceiling"
      else
        cap=1
        echo "parallel: yes, but the CPU count could not be read - running serially"
      fi
      ;;
    no) cap=1 ;;
    ''|*[!0-9]*) refuse_parallel "'$parallel_lines'" ;;
    *)
      [ "$value" -gt 0 ] || refuse_parallel "'$parallel_lines'"
      cap="$value"
      ;;
  esac
fi

# Windows and some Linux images ship only one of python and python3. A declared
# command should not have to know which machine the push comes from.
shim=""
if ! command -v python >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
  shim="$(mktemp -d)"
  ln -s "$(command -v python3)" "$shim/python"
  PATH="$shim:$PATH"
  export PATH
fi

failed=0
ran=0
logs="$(mktemp -d)"

report() {
  # $1 index, $2 command. Reads the exit status and output the run left behind.
  rc="$(cat "$logs/$1.rc" 2>/dev/null || echo 127)"
  secs="$(cat "$logs/$1.secs" 2>/dev/null || echo '?')"
  echo "run: $2"
  if [ "$rc" -eq 0 ]; then
    echo "  pass ($secs s)"
  else
    failed=1
    echo "  FAILED (exit $rc, $secs s). Last $tail_lines lines:"
    # The suite's timing and selection lines are reported below; left out here
    # so they cannot push the failure out of the tail. A no-match grep is fine.
    { grep -Ev '^(timing|selected):' "$logs/$1.log" || true; } | tail -n "$tail_lines" | sed 's/^/    /'
  fi
  # A suite's own 'timing:' and 'selected:' lines go into the gate report.
  grep -E '^(timing|selected):' "$logs/$1.log" 2>/dev/null | sed 's/^/  /' || true
}

# Output goes to a file, never through a pipe: in sh a pipeline's status is its
# last command's, and piping tsc through sed is how the typecheck gate lost
# every failure it ever had.
run_one() {
  started="$(date +%s)"
  (cd "$tree" && sh -c "$2") < /dev/null > "$logs/$1.log" 2>&1
  echo "$?" > "$logs/$1.rc"
  echo "$(( $(date +%s) - started ))" > "$logs/$1.secs"
}

finished_count() {
  done_count=0
  for rc_file in "$logs"/*.rc; do
    [ -f "$rc_file" ] && done_count=$((done_count + 1))
  done
  echo "$done_count"
}

# Slots, not batches: a new command starts as soon as one finishes, so one long suite
# cannot hold the other slots idle. A finished command is one with an .rc file. The
# loop polls once a second because 'wait -n' is bash-only and this runs under sh.
if [ "$cap" -gt 1 ]; then
  i=0
  while IFS= read -r cmd; do
    i=$((i + 1))
    while [ $((i - 1 - $(finished_count))) -ge "$cap" ]; do
      sleep 1
    done
    run_one "$i" "$cmd" &
  done <<EOF
$commands
EOF
  wait
  echo "ran $i command(s), at most $cap at once"
fi

i=0
while IFS= read -r cmd; do
  i=$((i + 1))
  ran=$i
  [ -f "$logs/$i.rc" ] || run_one "$i" "$cmd"
  report "$i" "$cmd"
done <<EOF
$commands
EOF

rm -rf "$logs"
[ -z "$shim" ] || rm -rf "$shim"

if [ "$failed" -ne 0 ]; then
  echo ""
  echo "REFUSED: a declared test command failed. Fix it, or push to a"
  echo "non-deploy branch and let the report carry the failure forward."
  exit 1
fi

echo ""
echo "$ran declared test command(s) passed."
