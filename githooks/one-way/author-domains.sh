#!/bin/sh
################################################################################
# File: author-domains.sh
# Path: {PROJECT_ROOT}/githooks/one-way/author-domains.sh
# Created by: Ryan Severe
# Created: 2026-10-15
# Last Updated: 2026-11-06
# Description: One-way gate 3. Refuses a push carrying any commit authored or
#              committed under a denylisted domain or its subdomains. Names the
#              commit, never the address. Shares its commit walk with the
#              identity gate. Usage: author-domains.sh DOMAINS LOCAL_SHA
#              REMOTE_SHA.
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

lib="$(dirname "$0")/../lib"
. "$lib/pattern_file.sh"
. "$lib/gate_config.sh"
. "$lib/commit_range.sh"

domain_file="${1:-}"
local_sha="${2:-}"
remote_sha="${3:-}"

work="$(mktemp -d)" || { echo "REFUSED: no temporary directory."; exit 1; }
trap 'rm -rf "$work"' EXIT

load_patterns "$domain_file" "$work/domains" || exit 1

if [ -z "$local_sha" ]; then
  echo "REFUSED: no commit given, so there is nothing to check."
  exit 1
fi

if ! commit_list "$local_sha" "$remote_sha" > "$work/commits"; then
  echo "REFUSED: could not list the commits this push adds, so none were checked."
  exit 1
fi

if [ ! -s "$work/commits" ]; then
  echo "No new commits."
  exit 0
fi

# A domain matches itself and its subdomains: mail.corp.example is corp.example,
# notcorp.example is not.
awk '
  function denied(addr,    dom, d) {
    dom = tolower(addr)
    sub(/^[^@]*@/, "", dom)
    for (d in deny)
      if (dom == d || (length(dom) > length(d) && substr(dom, length(dom) - length(d)) == "." d))
        return 1
    return 0
  }
  NR == FNR { d = tolower($0); sub(/^@/, "", d); deny[d]; next }
  { if (denied($2)) print "  " $1 " author"; if (denied($3)) print "  " $1 " committer" }
' "$work/domains" "$work/commits" > "$work/bad"

checked="$(grep -c . "$work/commits")"
if [ ! -s "$work/bad" ]; then
  echo "$checked commit(s) checked, none under a denylisted domain."
  exit 0
fi

echo "REFUSED: commits made under a denylisted domain:"
# The commit and the role, never the address: the domain list is secret-held and
# the report is published.
cat "$work/bad"
echo ""
echo "Rewrite the listed commits as the profile identity before pushing - for the"
echo "last one, 'git commit --amend --reset-author'."
exit 1
