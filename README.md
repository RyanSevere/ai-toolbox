<!--
################################################################################
# File: README.md
# Path: {PROJECT_ROOT}/README.md
# Created by: Ryan Severe
# Created: 2026-11-08
# Last Updated: 2026-11-13
# Description: The front page of the ai-toolbox repository - what the core is,
#              how a private profile builds on it, how to run it, and what the
#              one-way gates are for.
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

## The problem

AI coding tools each read their own files: `AGENTS.md`, `.github/` for GitHub
Copilot, `.cursor/` for Cursor. If you keep these by hand in every repository,
the copies drift. One repository gets a fix the others never see, and nothing
says which copy is current.

This core keeps one source and renders the per-tool files from it. Each
rendered file carries a stamp:

```
<!-- generated from <source>@<sha> - edit the source, not this file -->
```

The profile's own render carries no SHA, because a SHA there is rewritten in every
rendered file whenever any source input changes, and two branches that each change one
would conflict on every file:

```
<!-- generated from <source> - edit the source, not this file -->
```

A drift check (`sync.py --check`) re-renders the source and compares it with
what is committed, so a stale or hand-edited file is reported rather than
discovered later.

## Design

### Seeds and rendered output

A seed is a source file: a rule, a skill, a context file, an agent, a hook. It
sits in a `seeds/` folder (or, for the core's own, in `rules/`, `skills/` and
so on) and no tool loads it from there. The rendered output is what tools load:
`AGENTS.md`, `.github/instructions/`, `.github/rules/`, `.github/skills/`,
`.cursor/rules/`, `.cursor/skills/`, `.claude/rules/`, `.claude/skills/`,
`.claude/agents/`, `.githooks/` and the rest. You edit seeds.
You never edit rendered files; the next render overwrites them.

### The core and a profile

The core, this repository, is generic. It holds the renderer, a set of rules,
the gate scripts and the tooling around them, and names nothing about any one
person or organisation.

A profile is everything specific to you, kept in its own private repository:

- `profile.yaml`, which names the repositories to render into, the commit
  identity, which rules each gets, and the gate flags.
- Its own seeds, for rules and skills the core does not carry.
- A vendored copy of this core under `core/`, pinned to a release tag.

The profile never holds a live link to the core. It holds a copy of one
release, with a `core/VENDORED` file recording the source, tag, commit and a
hash of the bytes. `core/` is never edited in place: a changed byte is refused.
To change the core, change it here and release it.

### Updating a profile

Run `python core/toolboxctl.py <subcommand>` inside the profile:

| Subcommand | What it does |
|---|---|
| `version` | Prints the source, tag and commit `core/VENDORED` records. Reads only. |
| `check` | Verifies `core/` against `VENDORED`, then lists newer releases. Changes nothing. |
| `update [vX.Y.Z]` | Replaces `core/` with the newest or a named release, previews the render, and keeps it only after you type yes. Otherwise restores `core/` from git. It commits and renders nothing. |
| `flags` | Changes gate flags through `consent.py`, after a typed yes. |
| `setup` | Creates or updates the profile through `setup_profile.py`. |

## Tiers

Rules are sorted into tiers, and the tier is a field in each rule's front
matter (`tier: 1` or `tier: 2`).

- Tier 1 rules are the ones that would still be true in a repository that does
  not exist yet. None of them names a language, a path or a project.
- Tier 2 rules are those that name a language, a path or a project, such as
  the Python, shell and TypeScript rules.
- Tier 3 is hand-owned. The renderer never writes it, because mixing generated
  and hand-written text in one file is how a rendering scheme stops being
  trusted. The files it refuses to overwrite include `README.md` and
  `.github/copilot-instructions.md`.

A profile chooses which rules each target receives with the `tier1` and
`tier2` lists under `defaults:` in `profile.yaml`; a target can drop rules with
`exclude:`. The core documents no further tier semantics than these.

## Profiles

### `examples/profile`

A complete profile with every top-level key the core accepts and invented
values: `source`, `identity`, `not_onboarded`, `defaults`, `rollout`,
`actions`, `gate_config_dir`, `features`, `capabilities`, `answers` and
`targets`. Each key has a comment saying what it is for. The renderer refuses a
key outside that set. Copy it as the start of your own.

### `setup_profile.py`

`python setup_profile.py --profile <folder>` creates a profile from the
example, asks each capability file's setup questions (or reads the answers
from `--answers <file>`), hands the gate flags to the consent command, shows a
diff before a re-run writes anything, and ends with a dry-run render that names
what was dropped and what is still to build. Inside a profile,
`toolboxctl.py setup` runs the same thing.

### `toolboxctl.py`

The profile's entry point, described above. It refuses to run unless
`core/VENDORED` exists, so it belongs to a profile that vendors the core, not
to a clone of this repository.

### `vendor.py`

Fetches and pins the core. A version is a `vX.Y.Z` release tag; a full 40
character commit SHA is also accepted, but then `toolboxctl.py update` cannot
tell which release is newer. The source is validated before it reaches a URL,
the new core is built beside the old one and checked, and only then swapped
in. A `core/` with local edits is never overwritten.

### `consent.py`

Gate flags live in `profile.yaml` under `features:` and are mirrored in
`profile.lock`. Only `consent.py` writes either, and only after you type yes at
an interactive console within two minutes. `sync.py` and the pre-push hook
refuse to run when the two disagree, naming the flag.

```
python core/consent.py --profile . --init
python core/consent.py --profile . --set <gate>=on|off
python core/consent.py --profile . --check
```

The prompt reads the terminal itself, never standard input, so piped or
scripted input is refused.

## One-way gates

A profile is private and the core is public. The scripts in `githooks/one-way/`
keep the profile's material out of the core. Each reads a list the profile
supplies and reports where it found a match, never what it matched.

| Gate | Script | What it refuses |
|---|---|---|
| 1 | `leak-denylist.sh PATTERNS LOCAL_SHA REMOTE_SHA` | A push whose added lines contain any string on the profile's denylist: repository names, private address prefixes, employer strings. |
| 2 | `no-core-remote.sh CORE_URL PUSH_URL` | A push whose remote is the core repository, whatever URL form names it. A backstop: a vendored profile has no such remote by construction. |
| 3 | `author-domains.sh DOMAINS LOCAL_SHA REMOTE_SHA` | A push carrying any commit authored or committed under a denylisted domain or its subdomains. Names the commit, never the address. |
| 4 | `core-names-no-profile.sh NAMES TREE` | A core tree in which any file names a profile from the supplied list. It scans a given tree, because in a profile the core is a directory inside it. |

The limit is stated plainly: these catch identifiers, not ideas. A list of
names finds a name. It does not find a private design described in new words.
The gates are a net for the mistakes that are easy to make, not a substitute
for reading what you are about to publish.

This repository's own CI runs gates 1 and 4 from the repository secrets
`LEAK_DENYLIST` and `CORE_NAMES` (`.github/workflows/one-way-gates.yml`). It
does not run them on fork pull requests, because GitHub withholds secrets from
those. They run once the change reaches `dev` or `main`.

## Running it

You need Python 3.11 or newer, PyYAML
(`pip install pyyaml`), and git.

Run the tests:

```
python tests/run_shard.py 1/1
```

`tests/run_shard.py` finds the tests next to itself and runs shard `K` of `N`;
`1/1` is the whole suite.

Preview what the example profile renders, without writing anything:

```
python sync.py --profile examples/profile --self --no-fetch
```

Without `--write` this is a dry run. Do not add `--write` in a clone of this
repository. A write also sets the repository's local git identity and edits
its `.gitignore`.

To use it for real:

1. Copy `examples/profile` into a new private repository, or create one with
   `python setup_profile.py --profile <folder>`.
2. From a clone of this repository, vendor the core into it:
   `python sync.py --vendor-core <owner>/ai-toolbox@vX.Y.Z --profile <path to your repository>`
   This writes `core/` and `core/VENDORED`. Commit `core/` as one change.
3. From the profile's root, render as a dry run, then write:

```
python core/sync.py --profile .
python core/sync.py --profile . --write
```

If the profile ships any gate, set the gate flags first with
`python core/consent.py --profile . --init`. Once a gate exists, `sync.py`
refuses to render without a `profile.lock` that matches `profile.yaml`.

## Contributing

Work happens on `dev`. A release is a change to the `VERSION` file in a pull
request from `dev` to `main`; on merge, a workflow on `main` tags `vX.Y.Z`
(`.github/workflows/release.yml`). That tag is what a profile's `toolboxctl.py`
reads, so a release is the only way a change reaches a profile.

## Licence

MIT. See `LICENSE`.
