#!/bin/sh
################################################################################
# File: commit_range.sh
# Path: {PROJECT_ROOT}/githooks/lib/commit_range.sh
# Created by: Ryan Severe
# Created: 2026-10-15
# Last Updated: 2026-11-06
# Description: Sourced by gates that check the commits a push adds. commit_list
#              LOCAL REMOTE [REMOTE_NAME] prints "<short sha> <author> <committer>" for each
#              of them, and fails when git cannot list them. Shared by the
#              identity gate and the author-domains one-way gate.
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


# Sourced, so no `set` here: it would leak into the caller.

# An empty or all-zero remote sha is a new branch. Skipping it would let a whole
# branch of commits through, so it means every commit no remote already has.
is_new_branch() {
  case "${1:-}" in
    "" | *[!0]*) [ -z "${1:-}" ] ;;
    *) return 0 ;;
  esac
}

# Ranged against the deploy branch as fetched from the remote pushed to ($3, default
# origin), never the pushed branch's own remote sha. GitHub's merge commits are on the
# deploy branch, so a branch that merged main passes; a feature branch's failing gate
# still pushes, so a refused commit is on its remote and only this keeps it refused on
# the next push. A stale deploy ref only widens the range. The caller
# sources gate_config.sh for deploy-branch.
commit_list() {
  cl_remote="${3:-origin}"
  cl_branch="$(gate_config deploy-branch 2>/dev/null)" || cl_branch=""
  cl_ref="refs/remotes/$cl_remote/${cl_branch:-<deploy-branch>}"
  if [ -n "$cl_branch" ] && git rev-parse --verify --quiet "$cl_ref^{commit}" >/dev/null; then
    git log --format='%h %ae %ce' "$1" --not "$cl_ref"
  else
    echo "No $cl_ref in this clone: checking every commit no remote has." >&2
    git log --format='%h %ae %ce' "$1" --not --remotes
  fi
}
