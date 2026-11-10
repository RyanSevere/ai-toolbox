---
name: sync-rules
description: >-
  Render a profile's rule source into a consuming repository's per-tool formats
  and stamp the result with the source SHA. Use when the user says any of:
  "sync the rules", "update the AI rules in X", "roll the rules out", "this
  repo is behind on rules", or when a repo's drift check has gone red. Also use
  after editing any rule seed - the source change is not live anywhere until
  this runs.
---

# Sync rules

Renders source to targets. **The sync is not the guarantee - the drift check
is.** Running this without the check in place just moves the drift problem to a
slower tempo.

---

## Preconditions

- `profile.yaml` has an entry for the target repo
- Target repo has a clean working tree
- Source repo is at a committed SHA (never render from a dirty tree)

---

## Render map

| Source | Target | Notes |
|---|---|---|
| `prescriptions.md` | `AGENTS.md` | Always-on. Cross-vendor |
| `spec-*.md` where scope is file-type | `.github/instructions/<id>.instructions.md` + `.cursor/rules/<id>.mdc` | Frontmatter translated |
| `spec-*.md` where scope is a subtree | `<subtree>/AGENTS.md` | Prefer this - no glob dialect involved |
| `skills/*/SKILL.md` | `.cursor/skills/<name>/SKILL.md` | Copied, not translated |

Frontmatter translation:

| Source | Copilot | Cursor |
|---|---|---|
| `scope: "**/*.py"` | `applyTo: '**/*.py'` | `globs: **/*.py` |
| `scope: "*"`, `alwaysApply: true` | `applyTo: '**'` | `alwaysApply: true` |

Body text is copied unchanged. This is a frontmatter translation, not a content
transformation.

---

## Hard boundary

**Never write `.github/copilot-instructions.md`.** That file is Tier 3,
hand-owned, and describes the repo rather than the conventions. If generated
and hand-written content mix in one file, the generated files stop being
trustworthy and the whole mechanism decays.

`README.md` is on the same refusal list in `sync.py`, for the same reason.

Respect `exclude:` in the profile. A target can decline a convention it rejects,
such as `file-headers`.

---

## Stamp

Every generated file gets, as the first line after frontmatter:

```markdown
<!-- generated from <source>@<sha> - edit the source, not this file -->
```

The profile repository's own render has no `@<sha>`: `<!-- generated from <source> - edit the
source, not this file -->`. A target keeps the SHA, because it records which source version
the target holds. Anything that tests for a stamp accepts both.

---

## Steps

1. Read `profile.yaml`; resolve which rules the target receives.
2. Confirm the source tree is clean; capture the SHA.
3. Render each rule to each target format.
4. Write, stamping each file.
5. Show the diff. Rendering one target never commits; review and commit by hand.
6. Confirm the drift check exists in the target repo; if not, add it.

---

## Rolling out to every target

`python core/sync.py --profile . --rollout "<subject>" [--push] [--break-lock]` renders and
commits every target in `profile.yaml` not marked `skip:`, in one run.

It refuses the whole run, before any target is touched, if:

- the profile repository is dirty, or ahead of `origin/main`. A stamp has to name a commit
  that other clones and the drift checks can see.
- the profile repository has its own render pending. Run `python core/sync.py --profile . --self --write`, then commit
  and push first. Otherwise targets receive rules the profile repository is not yet following.
- `--push` is given and `shellcheck` is not on `PATH`. Every pre-push gate
  needs it, and a stale shell `PATH` is the usual cause.
- `--push` is given and `git config rollout.parallel` holds anything but a
  whole number from 1 to 16.
- another rollout holds `scratch/rollout.lock`. The refusal prints the holder's
  pid and subject. A lock is stale after 1 hour from its start, or 20 minutes
  with no heartbeat. Both limits are provisional. `--break-lock` removes a lock
  of any age.

It skips a target, reports it as failed, and continues with the next one, if
that target:

- is dirty,
- is not on its manifest `branch` (default `main`), or
- has a changed path after rendering that is outside the plan, is not a removed
  orphan, and is not `.gitignore`. Nothing is committed in that case, and the
  rendered files are left in place for review.
- has its own `.gitignore` hiding a file the render wrote, so that file would
  never be committed. `.cursor/` is exempt, because it is ignored by design.
  A Python `lib/` rule once hid `.githooks/lib/` this way.

Each target gets one commit: `Sync rules: <subject>`, with the body
`From <source>@<sha>.` **Pushing is opt-in.** Without `--push`, commits stay
local, so you can review them in every repo before anything leaves the machine.
With `--push`, success means the remote has the commit (`@{u}..HEAD` is empty),
not just that `git push` exited 0.

**Pushes run side by side.** Rendering and committing take seconds and run one
target at a time. Pushing runs each target's pre-push gates, which takes
minutes, so pushes run in parallel. The number at once is `git config
rollout.parallel` in the profile clone. The first `--push` on a machine sets it
from a read-only look at the cores and memory, allowing 4 cores and 8 GiB per
push - a provisional budget. Where those cannot be read, it uses
`rollout.parallel_default` from `profile.yaml`, which is 3. Set the git config
by hand to override it, or unset it to probe again.

**Checking a machine's capacity.** Run `python core/sync.py --profile . --probe-capacity`. It
prints the cores, the memory, what the probe would choose, and what is stored,
and it writes nothing. Run it on a new machine, or after a hardware change,
before unsetting `rollout.parallel`. Do not reproduce the probe in a one-off
command - this is the sanctioned way to run it.

**Why a rollout push is fast.** A rollout commit changes only stamped output,
plus `.gitignore`. A profile's test and typecheck gates can see that from the
pushed range and skip, because none of that output is code their checks read.
What still guards it: the lint gates check the changed rendered files, the
profile repository's own push already ran its tests over the same content, and the Rules drift check compares
every stamped file with a fresh render, so a hand edit disguised by a stamp is
caught. Any unstamped file in the range makes both gates run in full.

Output is one line per target, then `ROLLOUT COMPLETE: <n> ok, <m> failed`.
The exit code is non-zero if any target failed.

**How a pushed rollout is verified.** With `--push`, once every push has
finished, the rollout runs `gh workflow run rules-drift.yml` and prints
`drift check triggered: <url>` just before the `ROLLOUT COMPLETE` line. The
all-targets job runs only when dispatched this way, or by hand. On the profile
repository's push before a rollout, every target is one render behind by
design, so a run on that push could only report a guaranteed failure. If `gh`
is missing or the trigger fails, the rollout prints `[WARN] drift check not
triggered: <why>` and its exit code is unchanged; trigger it by hand. Nothing
checks a target between rollouts yet.

---

## Drift check

One workflow per consuming repo, distinguishing two failures:

| Condition | Meaning |
|---|---|
| content differs from a re-render at the stamped SHA | someone edited a generated file |
| stamped SHA is behind the source's HEAD | repo needs a sync |

Fail the first. Warn or fail the second, operator's choice.

---

## Report resident footprint

After each run, report the number of always-resident instruction lines in the
target repo - `AGENTS.md` plus `.github/copilot-instructions.md` plus any
nested `AGENTS.md` on the path being worked in.

**This measures residency, not quality.** Line count says nothing about whether
the rules are any good, and a repo can have a small footprint and terrible
rules. It is tracked for one narrow reason: resident lines are paid for in
every session forever, so the number should be known and should not creep. Do
not present it as a quality score or a target to minimise for its own sake.

---

## Failure modes

- **Rendered but check not added.** The repo silently falls behind again. The
  check is the point.
- **Hand-written rules already in the target's rendered directories.** Sync
  reports them as `[WARN]` and never deletes them - it did not create them. On
  a first render they are usually the repo's previous rules, and both sets keep
  loading until someone reconciles by hand. Watch for `alwaysApply: true` among
  them; that one is in force whether or not anybody remembers it.
- **Glob semantics differ between tools.** Unverified. Until confirmed, prefer
  subtree scoping via nested `AGENTS.md`, which involves no glob at all.
- **Target had local edits to a generated file.** Do not overwrite silently.
  Surface the diff and ask - the local edit may be a rule worth promoting to
  source.
