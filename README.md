<!--
################################################################################
# File: README.md
# Path: {PROJECT_ROOT}/README.md
# Created by: Ryan Severe
# Created: 2026-11-08
# Last Updated: 2026-11-20
# Description: The front page of the ai-toolbox repository - what it is for,
#              how to start a profile, how to ask for a change, a map of the
#              repository, and how to install and test it. The design material
#              lives in docs/DESIGN.md.
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

# ai-toolbox

A generic core for managing the rules, skills and git gates that AI coding
tools read. You write the rules once, in one place. The core renders them into
the files each tool loads, in every repository you point it at, and stamps each
file with the commit it came from.

It is for anyone who keeps `AGENTS.md`, `.github/` for GitHub Copilot or
`.cursor/` for Cursor by hand in several repositories. Those copies drift: one
repository gets a fix the others never see, and nothing says which is current.
Here there is one source. A drift check (`sync.py --check`) re-renders it and
compares the result with what is committed, so a stale or hand-edited file is
reported rather than discovered later.

The core is public and generic. Everything specific to you lives in a private
profile repository that vendors a pinned copy of the core.

## Quickstart

To start a profile, follow
[the new-profile runbook](docs/runbooks/RUNBOOK-NEW-PROFILE.md).

`examples/profile` is a starting point to copy, not a profile that renders as it
stands. A render needs the push gates locked first, and only the profile's owner
can lock them, by typing `yes` at a console. So the example ships with no lock, and
the runbook covers locking a copy of it before the first render.

## Updating a profile

Inside a profile, run `python core/toolboxctl.py check` to see whether a newer
release exists, then `python core/toolboxctl.py update` to preview it and keep
it after you type yes. The other subcommands are in [the design notes](docs/DESIGN.md).

## Rules by pull

A profile can let each repository pull its rules itself, instead of pushing them
to every repository in one rollout. The profile marks a release by tagging a
commit; each repository renders the newest tag when asked.

**Setting up.** In `profile.yaml`, set `rollout.release_tag` to a glob that names
the release tags, for example `rules-*`. Set `rules.profile-path` once per
machine, to the profile checkout:

```
git config --global rules.profile-path <path to the profile>
```

**Tagging a release.** `python core/sync.py --print-source-sha` prints the full
40-character sha of the commit a render stamps. It writes nothing. Tag that
commit. `--pull` picks the newest tag by creation date, and the push check
(below) picks it by name, so tag names must sort by date: start them with the
date, as in `rules-2026-11-15`. The profile checkout needs the tags fetched.

**Pulling.** In the repository to update, run `python <profile>/core/sync.py --pull`.

- The repository is found by its `origin` URL: its last path segment, without
  `.git`, must equal exactly one target's `remote` (default: the target's name).
  The folder must be named for that target.
- The newest release is checked out in a temporary worktree of the profile, so
  the profile's own working tree is never touched, and rendered by that
  release's own `sync.py`.
- The result is one commit on the current branch, `Sync rules: <tag>`. Nothing
  is pushed. A repository already at the release prints `already current` and
  commits nothing.
- It refuses on uncommitted changes, a detached HEAD, an unset or wrong
  `rules.profile-path`, a missing `rollout.release_tag`, no tag matching it, or
  no single matching target.

**Gate-config keys.** A profile that sets `rollout.release_tag` also renders two
lines into every repository's `.githooks/gate-config`: `profile-remote=<url>`,
the profile repository's own `origin` URL at render time, and
`release-tag=<glob>`. A profile without the setting renders neither, and a
profile with it but no `origin` refuses to render.

**Freshness at push.** Opt-in: only a gate-config with a `release-tag` line is
checked, so a repository whose profile does not use release tags is never held.
The pre-push hook reads the newest release tag from `profile-remote` with
`git ls-remote` (20 second limit), and compares it with the sha in the stamp on
line 1 of the gate-config.

| Outcome | On the deploy branch | On any other branch |
|---|---|---|
| Current | silent | silent |
| Behind, or the stamp matches no release | refuses, naming the `--pull` command | one warning line |
| Cannot tell (no network, no `profile-remote`, an unreadable stamp, no tag, a timeout) | refuses: "cannot tell whether the rules are current" | one warning line |

A stamp with no sha (the profile's own repository) skips the check. Unknown is
never read as current. Nothing is cached.

**Urgent releases.** `python core/sync.py --rollout <subject> --push --parallel N`
pushes `N` repositories at once for that run, instead of `rollout.parallel`. It
neither probes nor stores anything. How a profile marks a release urgent is the
profile's own procedure.

## Asking for a core change

A profile never edits its `core/`; a change is made here and released. Open an
issue with the [core-request template](.github/ISSUE_TEMPLATE/core-request.md).
This repository is public, so the issue must name nothing of your own.

## Repository map

"Rendered" means `sync.py` reads the folder and renders from it.

| Path | What it holds | Rendered |
|---|---|---|
| `actions/` | Workflow actions, such as the gate report. | Yes |
| `agents/` | Agent role definitions. | Yes |
| `capabilities/` | Capability files: the setup questions a profile answers. | Yes |
| `context/` | Prompt and context files, such as `/prime`. | Yes |
| `docs/` | Design notes and runbooks. | No |
| `examples/` | The example profile to copy. | No |
| `exchange/` | The exchange tool and its script. | Yes |
| `githooks/` | Generic push gates and the one-way gates. | Yes |
| `hooks/` | Agent hooks. | Yes |
| `patterns/` | Canonical code that gets copied between repositories. | No |
| `responses/` | Response-shape checks, one module per tool. | Yes |
| `rules/` | The rules, with their tier in front matter. | Yes |
| `skills/` | Skills. | Yes |
| `tests/` | The test suite and its runner. | No |
| `workflows/` | GitHub Actions workflow files. | Yes |
| `cleanup.py` | Removes what a finished workstream owns in `scratch/`. | Yes, as `.github/scripts/cleanup.py` |
| `consent.py` | Writes gate flags after a typed yes. | No |
| `gate_lists.py` | Builds the one-way gates' pattern files from a profile. | No |
| `prime.py` | Collects repository facts for `/prime`. | Yes, as `.github/scripts/prime.py` |
| `setup_profile.py` | Creates or updates a profile from the example. | No |
| `sync.py` | The renderer and drift check. | Is the renderer |
| `toolboxctl.py` | A profile's entry point: version, check, update. | No |
| `vendor.py` | Fetches and pins the core into a profile. | No |

## Install and test

You need git, Python 3.11 or newer, and PyYAML:

```
python -m pip install -r requirements.txt
python tests/run_shard.py 1/1
python -m ruff check .
```

`tests/run_shard.py` runs shard `K` of `N` of the suite; `1/1` is all of it.
Ruff is the linter CI runs.

## Contributing

Work happens on `dev`. A release is a change to the `VERSION` file in a pull
request from `dev` to `main`; on merge, a workflow on `main` tags `vX.Y.Z`
(`.github/workflows/release.yml`). That tag is what a profile's `toolboxctl.py`
reads, so a release is the only way a change reaches a profile.

## Licence

MIT. See `LICENSE`.

## Design

How it works, and why: [docs/DESIGN.md](docs/DESIGN.md). Decisions are in
[DECISIONS.md](DECISIONS.md).
