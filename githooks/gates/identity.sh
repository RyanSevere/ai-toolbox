#!/bin/sh
################################################################################
# File: identity.sh
# Path: {PROJECT_ROOT}/githooks/gates/identity.sh
# Created by: Ryan Severe
# Created: 2026-10-09
# Last Updated: 2026-11-16
# Description: Refuses a push carrying any commit whose author or committer
#              address is not the profile identity in .githooks/gate-config,
#              which sync.py renders from profile.yaml, or whose trailers name
#              another identity: a foreign Co-authored-by, or Made-with. Checks
#              every commit not yet on the deploy branch; existing history is
#              not rewritten.
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
remote_name="${3:-origin}"

# Rendered, not git config: a config key let one command choose the address the
# gate compares against.
. "$(dirname "$0")/../lib/gate_config.sh"
if ! expected="$(gate_config identity-email)"; then
  echo "REFUSED: .githooks/gate-config has no identity-email, so there is nothing to"
  echo "check commits against. Run 'python core/sync.py --profile . <this repo> --write' from the profile,"
  echo "which renders it from identity in profile.yaml."
  exit 1
fi

if [ -z "$local_sha" ]; then
  echo "REFUSED: no commit given. The pre-push hook passes the pushed sha; run the"
  echo "gate through it rather than directly."
  exit 1
fi

. "$(dirname "$0")/../lib/commit_range.sh"

# On a stale clone the remote's head is not a local object, so its deploy ref is behind
# too. Say why rather than check against it.
if ! is_new_branch "$remote_sha" && ! git cat-file -e "$remote_sha^{commit}" 2>/dev/null; then
  echo "REFUSED: the remote is at $remote_sha, which this clone has not fetched,"
  echo "so the commits this push adds cannot be listed. Run 'git pull --ff-only'"
  echo "and push again."
  exit 1
fi
echo "Checking commits on $local_sha not yet on $remote_name's deploy branch against $expected"
commits="$(commit_list "$local_sha" "$remote_sha" "$remote_name")" || {
  echo "REFUSED: could not list the commits on $local_sha"
  exit 1
}

if [ -z "$commits" ]; then
  echo "No new commits."
  exit 0
fi

lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

want="$(lower "$expected")"

# GitHub's merge button commits as noreply@github.com. Such a commit passes only when GitHub
# made it: authored by the profile identity, a merge (two or more parents), and already on a
# branch of the remote pushed to. A clone forging that committer has not pushed it yet, so
# it is not on the remote and stays refused.
github_merge() {
  [ "$(lower "$2")" = "noreply@github.com" ] || return 1
  [ "$(lower "$3")" = "$want" ] || return 1
  [ "$(git rev-list --parents -n 1 "$1" | wc -w)" -ge 3 ] || return 1
  [ -n "$(git for-each-ref --contains "$1" "refs/remotes/$remote_name/" 2>/dev/null)" ]
}

# The list is lowercased once, outside the loop, and read beside the original on a second
# descriptor: the comparison costs no process per commit, and a refusal still prints each
# address as it was written.
commits_lower="$(printf '%s\n' "$commits" | tr '[:upper:]' '[:lower:]')"
checked=0
bad=""
shas=""
while IFS=' ' read -r sha lower_author lower_committer && IFS=' ' read -r _ author committer <&3; do
  [ -n "$sha" ] || continue
  checked=$((checked + 1))
  shas="${shas}${sha}
"
  if [ "$lower_author" != "$want" ]; then
    bad="${bad}  $sha author    $author
"
  fi
  if [ "$lower_committer" != "$want" ] && ! github_merge "$sha" "$committer" "$author"; then
    bad="${bad}  $sha committer $committer
"
  fi
done 3<<EOF_ORIGINAL <<EOF_LOWER
$commits
EOF_ORIGINAL
$commits_lower
EOF_LOWER

# A trailer is a second identity the author and committer lines do not show. Cursor adds
# one to an agent's git commit unless its Commit Attribution setting is off.
# Every line of the last paragraph is read, not git's %(trailers): git drops a paragraph
# that is mostly not trailers, such as "Refs #1" above a Co-authored-by line.
# One git log reads every message, NUL between records. tr turns each NUL into the ASCII
# record separator (octal 036), because mawk and BWK awk do not take NUL as RS. awk then
# reads each record's last paragraph and ends with the number of records it read. A
# failed git log, or a message carrying its own 036 that merges two records, reads fewer
# records than commits checked, and that is a refusal.
trailer_out="$(printf '%s' "$shas" |
  git log --no-walk=unsorted --stdin -z --format='%h%n%B' |
  tr '\000' '\036' |
  WANT="$want" awk '
    BEGIN { RS = "\036"; want = ENVIRON["WANT"] }
    {
      records++
      split_at = index($0, "\n")
      sha = substr($0, 1, split_at - 1)
      count = split(substr($0, split_at + 1), lines, "\n")
      size = 0
      inside = 0
      for (i = 1; i <= count; i++) {
        if (lines[i] == "") { inside = 0; continue }
        if (!inside) { size = 0; inside = 1 }
        paragraph[++size] = lines[i]
      }
      for (i = 1; i <= size; i++) {
        line = paragraph[i]
        folded = tolower(line)
        if (index(folded, "co-authored-by:") == 1) {
          address = ""
          rest = line
          while (match(rest, /<[^<>]*>/)) {
            address = substr(rest, RSTART + 1, RLENGTH - 2)
            rest = substr(rest, RSTART + RLENGTH)
          }
          if (tolower(address) != want) print "  " sha " " line
        } else if (index(folded, "made-with:") == 1) {
          print "  " sha " " line
        }
      }
    }
    END { print "READ " records + 0 }
  ')"
messages_read="${trailer_out##*READ }"
trailer_bad="${trailer_out%READ *}"
if [ "$messages_read" != "$checked" ]; then
  echo "REFUSED: could not read the messages of the $checked commit(s) on $local_sha"
  exit 1
fi

if [ -z "$bad" ] && [ -z "$trailer_bad" ]; then
  echo "$checked commit(s) checked, all authored and committed as $expected, with no other identity in a trailer."
  exit 0
fi

if [ -n "$bad" ]; then
  echo "REFUSED: commits not made as $expected:"
  printf '%s' "$bad"
  echo ""
  echo "Every estate commit is made as the profile identity, never the machine's global"
  echo "one. Check 'git config --show-origin user.email' here, fix it, then rewrite the"
  echo "listed commits before pushing - for the last one, 'git commit --amend --reset-author'."
fi
if [ -n "$trailer_bad" ]; then
  echo "REFUSED: commits carrying an identity other than $expected in a trailer:"
  printf '%s' "$trailer_bad"
  echo ""
  echo "Cursor adds 'Co-authored-by: Cursor' to an agent's git commit unless Cursor Settings >"
  echo "Git & PRs > Commit Attribution is off. Turn it off, then rewrite the listed commits"
  echo "before pushing - for the last one, 'git commit --amend' and delete the trailer line."
fi
exit 1
