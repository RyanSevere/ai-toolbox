#!/bin/sh
################################################################################
# File: pre-push.sh
# Path: {PROJECT_ROOT}/githooks/pre-push.sh
# Created by: Ryan Severe
# Created: 2026-09-23
# Last Updated: 2026-11-07
# Description: Runs the gates named in the pushed commit's .githooks/gates/enabled
#              before a push, and names every gate it skips. A failing gate
#              refuses the push here; a passing set is published as a report
#              tag so CI can confirm the push was gated. In the profile repo it
#              first refuses a profile.lock that disagrees with features:.
#              Transport and sequencing only - it owns no gate logic.
################################################################################

set -eu

# Guard first, and before anything expensive. Verified 2026-09-23: a push issued
# from inside this hook re-invokes it, so without this the inner push recurses.
if [ "${GATE_REPORT_PUSH:-}" = "1" ]; then
  exit 0
fi

remote_name="${1:-origin}"
hook_started="$(date +%s)"
repo_root="$(git rev-parse --show-toplevel)"
gates_dir="$repo_root/.githooks/gates"
tag_root="gate-report"
retain_days=7

if [ ! -d "$gates_dir" ]; then
  echo "pre-push: no $gates_dir, nothing to gate" >&2
  exit 0
fi

# Which branch a failing gate actually blocks. Rendered by sync.py from the
# manifest, because a repository may deploy from dev rather than main -
# and rendered rather than git config, which one command changed unseen.
. "$(dirname "$0")/lib/gate_config.sh"
if ! deploy_branch="$(gate_config deploy-branch)"; then
  echo "pre-push: refusing - .githooks/gate-config has no deploy-branch, so there is no" >&2
  echo "          telling which branch a failing gate blocks. Re-render this repo from" >&2
  echo "          its profile: python core/sync.py --profile . <this repo> --write" >&2
  exit 1
fi

# Rendered only into the profile repo, the one that holds a lock. A target trusts its
# rendered list, so absence here is a target, not a default.
consent_script="$(gate_config consent-check)" || consent_script=""

json_escape() {
  sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\t/\\t/g' | tr '\n' ' '
}

json_list() {
  # Lines on stdin as a JSON array of strings.
  jl_first=1
  printf '['
  while IFS= read -r jl_item; do
    [ "$jl_first" -eq 1 ] || printf ', '
    jl_first=0
    printf '"%s"' "$(printf '%s' "$jl_item" | json_escape)"
  done
  printf ']'
}

enabled_at() {
  # The gate names in the enabled list as committed at $1: comments, blanks and the
  # carriage return an autocrlf checkout leaves are dropped. Fails if there is no list.
  ea_text="$(git show "$1:.githooks/gates/enabled" 2>/dev/null)" || return 1
  printf '%s\n' "$ea_text" | tr -d '\r' \
    | sed -e 's/#.*//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | grep -v '^$' || true
}

listed() {
  # Is $1 one of the newline-separated names in $2? Exact, never a pattern.
  printf '%s\n' "$2" | grep -qxF -- "$1"
}

skipped_gates() {
  # Every gate script here that the enabled list $1 leaves out.
  for sg_gate in "$gates_dir"/*.sh; do
    [ -e "$sg_gate" ] || continue
    sg_name="$(basename "$sg_gate" .sh)"
    listed "$sg_name" "$1" || printf '%s\n' "$sg_name"
  done
}

flag_changes() {
  # One line per gate that differs between the enabled lists $1 (before) and $2 (after).
  printf '%s\n' "$1" | while IFS= read -r fc_name; do
    [ -z "$fc_name" ] || listed "$fc_name" "$2" || printf '%s: on -> off\n' "$fc_name"
  done
  printf '%s\n' "$2" | while IFS= read -r fc_name; do
    [ -z "$fc_name" ] || listed "$fc_name" "$1" || printf '%s: off -> on\n' "$fc_name"
  done
}

consent_check() {
  # The profile repo only: profile.lock and features: must agree at the pushed commit $1,
  # checked in a worktree of that commit because the working tree can differ from it.
  case "$consent_script" in
    "" | /* | *..* | *[!A-Za-z0-9._/-]*)
      echo "pre-push: refusing - gate-config consent-check '$consent_script' is not a" >&2
      echo "          repo-relative path. Re-render this repo: python core/sync.py --profile . --self --write" >&2
      return 1 ;;
  esac
  # python3 first would find the Windows Store stub, which exists and does not run.
  cc_py=""
  for cc_candidate in python python3; do
    if command -v "$cc_candidate" >/dev/null 2>&1 \
        && "$cc_candidate" -c "import yaml" >/dev/null 2>&1; then
      cc_py="$cc_candidate"
      break
    fi
  done
  if [ -z "$cc_py" ]; then
    echo "pre-push: refusing - no python that can import yaml, so profile.lock cannot be" >&2
    echo "          checked. A check that cannot run is not a pass." >&2
    return 1
  fi
  cc_tree="$(mktemp -d)"
  if ! git worktree add --quiet --detach "$cc_tree" "$1" >/dev/null 2>&1; then
    rm -rf "$cc_tree"
    echo "pre-push: refusing - could not check out $1 to check its profile.lock" >&2
    return 1
  fi
  cc_status=0
  cc_out="$(cd "$cc_tree" && env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE \
    "$cc_py" "$consent_script" --check --profile . 2>&1)" || cc_status=1
  git worktree remove --force "$cc_tree" >/dev/null 2>&1 || true
  rm -rf "$cc_tree"
  if [ "$cc_status" -ne 0 ]; then
    echo "pre-push: refusing - profile.lock and profile.yaml features: disagree at $1." >&2
    printf '%s\n' "$cc_out" | sed 's/^/    /' >&2
    return 1
  fi
}

cutoff_stamp() {
  # GNU first, BSD second. Neither is guaranteed, and a wrong cutoff would
  # delete live reports - so failure here skips pruning rather than guessing.
  date -u -d "$retain_days days ago" +%Y%m%d 2>/dev/null \
    || date -u -v-"$retain_days"d +%Y%m%d 2>/dev/null \
    || return 1
}

prune_reports() {
  cutoff="$(cutoff_stamp)" || {
    echo "pre-push: cannot compute a $retain_days-day cutoff with this date(1); not pruning" >&2
    return 0
  }
  # '**' and not '*'. A single star does not cross a '/' in a ref pattern, so
  # 'refs/tags/gate-report/*' matched none of gate-report/<date>/<sha> and the
  # prune silently did nothing while exiting zero. Found 2026-09-23 by tagging
  # synthetic old reports rather than waiting a week.
  pruned=0
  for ref in $(git for-each-ref --format='%(refname:short)' "refs/tags/$tag_root/**"); do
    stamp="$(printf '%s' "$ref" | cut -d/ -f2 | cut -d- -f1)"
    case "$stamp" in
      [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
      *) continue ;;  # not a stamp this hook wrote; leave it alone
    esac
    [ "$stamp" -lt "$cutoff" ] || continue
    git tag -d "$ref" >/dev/null 2>&1 || true
    # stdin is redirected because the hook's own stdin is the ref list git is
    # about to push, and an inner command must not consume it. The failure is
    # reported rather than swallowed - a prune that quietly does nothing leaves
    # the remote growing forever with nothing to show for it.
    if GATE_REPORT_PUSH=1 git push --quiet "$remote_name" ":refs/tags/$ref" < /dev/null; then
      pruned=$((pruned + 1))
    else
      echo "pre-push: could not delete remote tag $ref" >&2
    fi
  done
  [ "$pruned" -eq 0 ] || echo "pre-push: pruned $pruned report tag(s) older than $cutoff" >&2
}

run_gates() {
  # Emits the gates object on stdout; returns 1 if any gate failed.
  # $1 is the sha being pushed, $2 the sha already on the remote. Gates that
  # compare a range need both, and the remote's name, passed third; the rest
  # ignore them. $3 is the enabled list.
  local_sha="$1"
  remote_sha="$2"
  failed=0
  first=1
  # Read line by line, never word-split: an unquoted list would glob a forged '*'.
  # A gate's stdin is closed, because the loop's stdin is the list itself.
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    gate="$gates_dir/$name.sh"
    started="$(date +%s)"
    if ! printf '%s' "$name" | grep -qx '[a-z0-9][a-z0-9-]*'; then
      status="fail"
      detail="listed in enabled, but not a gate name"
    elif [ ! -f "$gate" ]; then
      status="fail"
      detail="listed in enabled, but $gate does not exist"
    elif detail="$(sh "$gate" "$local_sha" "$remote_sha" "$remote_name" 2>&1 < /dev/null)"; then
      status="pass"
    else
      status="fail"
    fi
    if [ "$status" = "fail" ]; then
      failed=1
      echo "pre-push: $name FAILED" >&2
      printf '%s\n' "$detail" | sed 's/^/    /' >&2
    fi
    seconds=$(( $(date +%s) - started ))
    [ "$first" -eq 1 ] || printf ',\n'
    first=0
    printf '    "%s": {"status": "%s", "seconds": %s, "detail": "%s"}' \
      "$(printf '%s' "$name" | json_escape)" "$status" "$seconds" \
      "$(printf '%s' "$detail" | json_escape)"
  done <<EOF
$3
EOF
  return "$failed"
}

publish_report() {
  commit="$1"
  gates_json="$2"
  skipped_json="$3"
  changes_json="$4"
  tag="$tag_root/$(date -u +%Y%m%d-%H%M%S)/$commit"

  tmp="$(mktemp)"
  # seconds is the whole hook so far, pruning included.
  printf '{\n  "commit": "%s",\n  "generated": "%s",\n  "seconds": %s,\n  "skipped": %s,\n  "flag_changes": %s,\n  "gates": {\n%s\n  }\n}\n' \
    "$commit" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(( $(date +%s) - hook_started ))" \
    "$skipped_json" "$changes_json" "$gates_json" > "$tmp"

  blob="$(git hash-object -w "$tmp")"
  rm -f "$tmp"
  tree="$(printf '100644 blob %s\treport.json\n' "$blob" | git mktree)"
  object="$(git commit-tree "$tree" -m "gate report for $commit")"

  git update-ref "refs/tags/$tag" "$object"
  # The push is the thing that has to have happened, not the update-ref. A report
  # that never reached the remote is indistinguishable from one never written.
  if ! GATE_REPORT_PUSH=1 git push --quiet "$remote_name" "refs/tags/$tag"; then
    echo "pre-push: could not publish $tag. CI will refuse this push." >&2
    return 1
  fi
}

prune_reports

# stdin carries: <local ref> <local sha> <remote ref> <remote sha>
while read -r _local_ref local_sha remote_ref remote_sha; do
  # The last field keeps any carriage return a CRLF-fed stdin leaves, and a sha with one
  # matches neither the all-zero test nor any commit.
  remote_sha="$(printf '%s' "$remote_sha" | tr -d '\r')"
  # Branches only, tested on the remote ref. A push of --tags hands this loop one
  # line per tag, and without this the hook published a report for each - four
  # reports for one push, observed 2026-09-23. The local ref is not usable here:
  # 'git push origin HEAD:refs/heads/main' reports it as 'HEAD'.
  case "$remote_ref" in
    refs/heads/*) ;;
    *) continue ;;
  esac

  # An all-zero local sha means the ref is being deleted. Nothing to gate.
  case "$local_sha" in
    *[!0]*) ;;
    *) continue ;;
  esac

  # The list as pushed, not as checked out - CI reads the pushed commit's copy. A
  # missing list refuses: running everything or nothing would both be a guess.
  if ! enabled="$(enabled_at "$local_sha")"; then
    echo "pre-push: refusing - $local_sha has no .githooks/gates/enabled, so there is no" >&2
    echo "          telling which gates this repo runs. Re-render this repo from" >&2
    echo "          its profile: python core/sync.py --profile . <this repo> --write" >&2
    exit 1
  fi

  if [ -n "$consent_script" ]; then
    consent_check "$local_sha" < /dev/null || exit 1
  fi

  # A new branch has no remote sha, so it is compared with the deploy branch. With
  # neither, say so - printing nothing would read as "no flag changed".
  base="$remote_sha"
  case "$base" in
    *[!0]*) ;;
    *) base="$(git rev-parse --verify --quiet "refs/remotes/$remote_name/$deploy_branch")" \
         || base="" ;;
  esac
  if [ -z "$base" ]; then
    echo "pre-push: no earlier pushed list to compare gate flags with" >&2
    changes=""
  elif ! before="$(enabled_at "$base")"; then
    echo "pre-push: cannot read an enabled list at $base to compare gate flags with" >&2
    changes=""
  else
    changes="$(flag_changes "$before" "$enabled")"
  fi
  [ -z "$changes" ] || printf '%s\n' "$changes" | sed 's/^/pre-push: flag changed: /' >&2

  skipped="$(skipped_gates "$enabled")"
  [ -z "$skipped" ] || printf '%s\n' "$skipped" \
    | sed 's/^/pre-push: skipped /; s/$/ (off in profile.lock)/' >&2

  if ! gates_json="$(run_gates "$local_sha" "$remote_sha" "$enabled")"; then
    # The deploy branch is the only one a failing gate blocks. Moving gates to
    # push time was to stop failing checks emailing and building, not to stop
    # work leaving a machine - so a feature branch carries the failure forward
    # as a published report and lets the push through.
    if [ "$remote_ref" = "refs/heads/$deploy_branch" ]; then
      echo "pre-push: refusing - $deploy_branch is the deploy branch." >&2
      echo "          Push this to another branch, or fix the gate above." >&2
      exit 1
    fi
    echo "pre-push: publishing a failing report for $remote_ref and continuing." >&2
    echo "          CI will show this red. It will not merge into $deploy_branch." >&2
  fi

  # '%s\n', because read drops a last line with no newline - and with it a name.
  skipped_json="$(printf '%s\n' "$skipped" | sed '/^$/d' | json_list)"
  changes_json="$(printf '%s\n' "$changes" | sed '/^$/d' | json_list)"
  publish_report "$local_sha" "$gates_json" "$skipped_json" "$changes_json" || exit 1
done

exit 0
