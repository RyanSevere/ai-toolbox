---
description: Render the profile into a consuming repository. Dry run first, write only after explicit confirmation.
---

Render the profile repository's source into a consuming repository.

**Target.** If the user named a repository, use it. If not, ask. Do not infer
from the open editor. This writes files into a repository, and writing into the
wrong one is not obvious afterwards.

**Never write without showing the dry run first and getting explicit
confirmation.** `--write` is not the default for a reason.

The render map, the frontmatter translation, the stamp format and the Tier 3
boundary are **not repeated here** - they live in `skills/sync-rules/procedure.md`,
which is canonical. Open it if a question comes up that the steps below do not
answer.

---

## Step 1 - check both trees are safe to write into

`sync.py` overwrites generated files without asking, and does not inspect the
target's working tree. Uncommitted edits to a generated file are lost silently.

```powershell
git -C <root>/<target> status --porcelain -- AGENTS.md .github .cursor
```

Anything listed there is about to be overwritten. Say so plainly and stop until
the user decides. An empty result means safe to proceed.

**The profile repository is itself a render target.** Every run also writes this repo's own
`AGENTS.md`, `.github/` and `.cursor/`, so those are overwritten too - the check
above covers the target only. The source tree must additionally be *committed*,
not merely clean of generated-file edits, or sync refuses in step 2.

## Step 2 - dry run

```powershell
python core/sync.py --profile . <target>
```

Run from the profile repository's root. Targets are resolved as siblings on disk;
`--root` is only needed when they are not.

Expect one of these, and report which:

| Outcome | Meaning |
|---|---|
| `[OK] up to date` | Nothing to do. Stop here |
| `N would change, M would be removed` | Proceed to step 3 |
| `Source tree is dirty` | The profile repository has uncommitted changes. It refuses so the stamp cannot point at a SHA lacking the content. Tell the user to commit |
| `Local and origin have diverged` | Reconcile by hand. Do not guess a side |
| `Could not reach origin` | Offline. `--no-fetch` renders from local HEAD and may be stale - only with the user's agreement |

`[INFO] pulled N commit(s) from origin` is normal. If it then aborts saying
`sync.py` or `profile.yaml` was updated, just run the command again - the first
process was running the old code.

## Step 3 - report, then ask

State, in this order:

- source SHA and target
- how many files change, and how many would be **removed** as orphans
- the resident footprint line, and how it compares to before if a previous
  number is known
- any file whose removal looks surprising
- any `[WARN] hand-written file(s) in rendered directories` block, in full

An orphan removal is the one thing worth pausing on. It means a rule was
renamed or descoped, and the old copy is being deleted. That is usually correct
and occasionally not.

The `[WARN]` block is the opposite case: files sync will **never** touch,
sitting where it renders. On a first render they are usually the repo's old
hand-written rules, and they keep loading alongside the new ones until someone
removes them.

Then ask whether to write. Do not assume.

## Step 4 - write, on confirmation only

```powershell
python core/sync.py --profile . <target> --write
```

Then show `git -C <root>/<target> status --porcelain` so the user sees exactly
what landed. Do not commit it - that is theirs to decide.

---

Report what the commands returned. If a step produced no output, say so rather
than moving on quietly - an empty result and a skipped step must not look the
same.
