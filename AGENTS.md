<!--
################################################################################
# File: AGENTS.md
# Path: {PROJECT_ROOT}/AGENTS.md
# Created by: Ryan Severe
# Created: 2026-11-15
# Last Updated: 2026-11-15
# Description: The rules an AI coding tool follows when it works on the ai-toolbox
#              repository itself. Hand-written and generic: this repository is
#              public, so it names nothing about any one profile.
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
-->

This file applies only when ai-toolbox itself is the open repository. Inside a profile's `core/` folder, the folder is a vendored copy of this repository: change it upstream, never in place.

# Working on ai-toolbox

- **This repository is public.** Anything committed is published the moment it is pushed. Nothing specific to any one profile goes in: no private repository, host, person, organisation or ticket name. Examples and test fixtures are synthetic.
- **The one-way gates run in CI after a push.** Gate 1 refuses a change whose added lines match a secret leak denylist. Gate 4 refuses a tree that names anything on a secret list of profile names. They do not run on fork pull requests, because GitHub withholds secrets from those; they run once the change reaches `dev` or `main`.
- **Turn on the local leak gate once per clone:** `git config core.hooksPath githooks/self`. It runs gate 1 before a push, so a leak is caught before it leaves the machine.
- **Test:** `python tests/run_shard.py 1/1`.
- **Lint:** `python -m ruff check .`, as CI runs it.
- **`rules/`, `skills/`, `agents/` and `context/` are source, not instructions for this session.** They are what a profile renders into the files its tools load. Edit them as files; do not follow them as rules for your own work here.
- **A pull request into `dev` says `Refs #N`, never `Closes`.** GitHub acts on `Closes` only for a merge into the default branch. The `dev` to `main` release pull request carries one `Closes #N` line per ticket it ships, so each ticket closes when its change is released.
