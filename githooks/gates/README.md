<!--
################################################################################
# File: README.md
# Path: {PROJECT_ROOT}/githooks/gates/README.md
# Created by: Ryan Severe
# Created: 2026-11-16
# Last Updated: 2026-11-16
# Description: One line for each generic gate the core ships. The contract a gate
#              meets is in ../README.md.
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

# The core gates

Each is a script in this folder, and each reads only the repository it runs in.

- `dead-variants`: refuses a tracked file named like a leftover copy, such as `x.bak` or `x.old`.
- `eslint`: refuses a push that adds an eslint finding the baseline does not already hold.
- `lockfile`: refuses a `package-lock.json` that npm calls an invalid tree.
- `no-change-docs`: refuses markdown added outside the places documents live.
- `ruff`: refuses a push that adds a ruff finding the baseline does not already hold.
- `run-expressions`: refuses a `${{ }}` expression inside a workflow `run:` script.
- `secret-defaults`: refuses a default value on a secret-named variable in compose, YAML or env-example files.
- `secret-scan`: refuses added lines that carry a credential shape.
- `self-render`: in a profile's source repository, refuses rendered copies that differ from what the source renders.
- `shellcheck`: refuses a push that adds a ShellCheck finding the baseline does not already hold.
- `test-orphans`: refuses a test file no declared test root covers, and a root that covers nothing.
- `test-provenance`: reports an edited assertion beside a source change; never blocks.
- `tests`: runs each test command the repository declares in `test-roots`.
- `typecheck`: refuses TypeScript no tsconfig covers, then type-checks each project.

A profile adds gates of its own under `seeds/githooks/gates/`, and switches each
on with `consent.py --set <name>=on`.
