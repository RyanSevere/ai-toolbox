<!--
################################################################################
# File: README.md
# Path: {PROJECT_ROOT}/githooks/README.md
# Created by: Ryan Severe
# Created: 2026-10-19
# Last Updated: 2026-11-06
# Description: The gate wireframe - what a gate is, how the pre-push hook runs
#              it, and how a profile declares and enables one. Names no
#              toolchain and no hosting service.
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

# Gates

A gate is one check the pre-push hook runs before a push leaves the machine.
The hook owns no check of its own: it decides which gates run, runs them, and
publishes what they said.

## The contract

- A gate is a `sh` script, `gates/<name>.sh`.
- Its name is lowercase letters, digits and hyphens, starting with a letter or
  digit. The hook refuses any other name in the enabled list rather than
  building a path from it.
- `$1` is the commit being pushed. `$2` is the commit already on the remote,
  all zeros for a new branch. A gate that compares a range needs both; the
  rest ignore them.
- Its standard input is closed, and it runs from the repository root.
- **Exit 0 passes. Any other exit fails, and what it printed is the reason.**
  Say what was found, where, and how to fix it. A gate that fails silently
  gives the person reading the report nothing to act on.
- A gate that cannot carry out its check fails. A missing tool, an unreadable
  declaration or an absent setting is never a pass.

## Where gates come from

- The core's gates live in `githooks/gates/`. A profile adds its own under
  `seeds/githooks/gates/`. A name used by both is refused at render.
- Helpers the gates share live in `lib/`, not `gates/`. A script in `gates/`
  that the enabled list leaves out is reported as a skipped gate.

## Which gates run

- A profile declares every gate on or off in `profile.yaml`, under
  `features: gates:`. `profile.lock` records the operator's consent to those
  flags. Only the consent command changes either: `consent.py --init` once at
  setup, then `consent.py --set <gate>=on|off`, typed at an interactive console.
- The render writes the gates that are on into `.githooks/gates/enabled`. The
  hook runs those, as listed in the commit being pushed, names every gate it
  skips, and refuses the push when the list is missing. Whatever checks the
  report after the push requires the same list.
- In the profile's own repository the hook also refuses a push when
  `profile.lock` and `features:` disagree.
- A new gate has no flag until it is consented, and the render refuses until
  then: a gate nobody switched on is a decision nobody made.

## Per-repository settings

- `.githooks/gate-config` holds `key=value` lines, rendered from the profile.
  Read a key with `gate_config <key>` from `lib/gate_config.sh`, which reads
  the file and never sources it. It fails when the key is absent, and a gate
  must then refuse rather than assume a default.
- Keys: `deploy-branch`, the branch a failing gate blocks; `identity-email`;
  `config-dir`; and `consent-check`, in the profile's repository only.
- Files a repository keeps by hand for its gates live in `config-dir`, the
  profile's `gate_config_dir`. Read them as `$(gate_config config-dir)/<file>`,
  never from a fixed folder.

## Adding a gate

1. Write `seeds/githooks/gates/<name>.sh` in the profile.
2. Test it both ways: it passes on a tree without the problem, and fails on
   the thing it exists to catch.
3. Switch it on with `consent.py --set <name>=on`.
4. Render, and commit `profile.yaml`, `profile.lock` and the rendered list
   together.
