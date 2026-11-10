---
description: Load working context for one repository, or for every repository in the workspace, from live state. Nothing here is stored, so nothing here can be stale.
---

You are priming a fresh session. Gather current state, report it compactly, then
stop. Do not begin work and do not propose any.

**Report only.** Priming has no side effects. Do not create a todo list, do not
edit a file, do not open a plan. You are building a picture, not acting on it.

That holds at the end of the report too. **Do not close with an inference.** No
"this suggests", no read on what the active work is, no summary of what it all
means. Those conclusions are the reader's to draw, and one assembled from the
last few commit messages reads like a finding while carrying nothing. Stop after
the last fact.

**Honesty.** Every line you report must come from a command run in this session.
If a step returns nothing, say it returned nothing - an empty section and a
healthy one must not look alike. If a command fails, report the failure rather
than omitting the section.

---

## Blast radius

Prime collects **durable** facts only - things that were true an hour ago and
will still be true in an hour. That is the whole reason its output can be
trusted for the rest of a session without being re-checked.

Collect: branch and tracking state, recent commits, working tree, design-document
status lines, nested `AGENTS.md` traps, run targets.

**Do not collect:** issue state, pull request state, project board state, CI
results, or anything living on a remote host. Those move between the moment they
are read and the moment they are acted on. They belong to `/sitrep`, which is
built to carry its own age. Pulling them in here is exactly how prime would stop
being trustworthy - and widening the target to more repositories does not widen
what may be gathered.

## Target

- A repository named after the command - use that one.
- `all`, or "every", "both", "the workspace" - use every workspace folder.
- Nothing, and the workspace holds one folder - use it.
- Nothing, and the workspace holds several - ask which one, and offer `all` as
  an explicit choice. Do not guess from the open editor.

Where several repositories are in scope the steps below do not change. Keep
each repository's results separate. Never report a fact gathered in one
repository under the name of another.

---

## Collecting - one command

```powershell
python .github/scripts/prime.py "<repo path>" ["<repo path>" ...]
```

Pass the absolute path of every repository in scope, in one call, from any
workspace folder - the script is rendered into every repository at that path.
It resolves a path inside a repository to that repository's root.

**Do not compose the steps by hand.** A hand-assembled command differs from
session to session, so it cannot be allowlisted and cost an approval click per
repository; the script is covered by the existing `python` auto-approval. If
the script is missing, put that under `UNKNOWN` rather than
improvising the commands.

One call is safe where one long hand-built loop was not. Each repository is
isolated: a failure prints `[error]` under that repository, the rest still run,
and the exit code is non-zero. That was the reason for the old
one-repository-at-a-time rule.

Output per repository: `=== REPO <name> (<path>)`, then `[state]`, `[docs]`,
`[traps]` and `[commands]`. `none` under a section means the step ran and found
nothing; `[error]` means it failed. The steps below say what each section is
for and how to report it.

---

## Step 1 - repository state

`[state]` holds `git status -sb`, then the last six commits.

The first line of `git status -sb` carries the branch, its upstream, and any
ahead/behind count. Committed-but-unpushed work is invisible without it, and a
repository sitting on a different branch from its siblings is the most expensive
thing on this list to discover late.

## Step 2 - design documents and their status

The highest-value step. A document with a status line answers "is this done?"
without reading it, and that question has already been got wrong once.

Design documents do not all live in a documents directory. Repositories keep
them at the repository root too, and scanning only the directories reported
`none` for a repository holding work marked **In progress**. Scan both.

Report the path, not the file name. One repository had a `MIGRATION_PLAN.md`
in both `docs/` and `planning-docs/`; by name
alone they are one document reported twice, which is worse than missing it.

`[docs]` lists `<path> | <status>` for every `*.md` directly in `docs/`,
`project-docs/` and `planning-docs/`, and at the root except README, AGENTS,
CHANGELOG and LICENSE. `-` means no `**Status:**` line.

A document carrying a status line is the point of this step. Give those a line
each, status included. For the rest, do not spend a line each saying `-`: name
them on one wrapped line prefixed with their count. They are findable, which is
all that is needed, and eleven of them once buried the two that mattered.

## Step 3 - traps

Nested `AGENTS.md` files record things that are true, not derivable, and
expensive to rediscover. The repository root `AGENTS.md` is generated, and the
script skips it.

`[traps]` lists each nested file's path, then its headings verbatim, indented.
Ignored directories such as `node_modules/` and `scratch/` are left out, and so
are lines inside fenced code blocks.

Report each heading **verbatim**, one line each, with
at most a six-word clause after it. The headings are written as claims and carry
the warning on their own; the detail behind them is why the file exists rather
than something to reproduce here.

If a file has more than six headings, report the first six and state how many
remain. Name the path so it can be opened.

## Step 4 - how to run things

`[commands]` lists `target:` lines for `package.json`, `Makefile`,
`docker-compose.yml`, `pyproject.toml`, `requirements.txt` and any extensionless
`*ctl` command at most three path segments deep, and `scripts:` lines naming
each `package.json`'s scripts to the same depth.

**Do not test the repository root only.** Repositories keep their runnable
project one level down - `<repo>/typescript`, `<repo>/react-app` - and a
root-only check once reported two of them as having no
commands at all while they carried working test suites. Verified 2026-09-21.

Report the script names only, never their contents.

## Step 5 - open issues, only if asked

Skip this by default; it costs several round trips and it is the one step whose
answer decays. Run it when the user says "with issues", and when you do, say
when it was read. Report number, title, and the severity line from the body if
one is present.

---

## Report format

**The first line of the report is exactly `Results from Prime`, on its own.**
Nothing before it. It is not a preamble - it is the marker
`check_response.py` matches to establish that the reply it is grading next turn
is a fixed-format report rather than a shaped reply. Without it the grader
reports three header findings that are artifacts of itself.

Prime does not run the compliance check. It opens a session, so there is
nothing before it to grade.

Then: no preamble, no closing offer of help. Tables over prose.

### One repository

Under 50 lines.

### Several repositories

Lead with a single state table covering every repository at once. A
cross-repository inconsistency - one repo on a different branch, one holding
unpushed commits, one dirty - is visible only in this view, and it is the reason
the multi-repository form exists at all.

| Repo | Branch | Tracking | Tree | Last commit |

Then one block per repository carrying only what the table does not: design
documents, traps, run targets.

Budget 20 lines per repository. If a repository would exceed it, cut the
design-document list to those whose status is not a finished state and say how
many were dropped.

Where a step found nothing for a repository, write `none` on that repository's
line for that step. Do not omit the line and do not collect the omissions into a
footer - an absence noticed three blocks later is an absence not noticed. A
reported `none` means the step ran and found nothing; it must never stand in for
a step that was skipped or that failed.

Truncate each document status to its first sentence or 60 characters,
whichever is shorter. The full text is in the file; this is an index.

```
Results from Prime

REPO       <name> on <branch>, <n> uncommitted
RECENT     <up to 4 commits, one line each>
DOCS       <name> -> <status>, only those with a status line
           <count> more without one
TRAPS      <file>: <heading>
COMMANDS   <how to test, build, deploy>
UNKNOWN    <anything a step failed to establish>
```

Drop a section entirely if it has no content, except `UNKNOWN` - if a step
failed, that must appear.

Stop after the last section. **No closing line.** An earlier version of this
file asked for one naming what the recent commits suggested was in flight, which
contradicted the prohibition above and was removed 2026-09-21 - the first
session to read both flagged the conflict rather than silently picking a side.
