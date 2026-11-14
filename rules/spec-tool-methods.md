---
id: tool-methods
tier: 2
scope: "*"
alwaysApply: false
description: >-
  Tool methods SPECIFICATION - which method does each common job without raising
  an operator approval card or prompt, per tool (Cursor, Copilot in VS Code,
  Claude Code), and the methods that do the same job and raise one. Covers the
  one-command-per-call
  rule, canonical script paths, deleting under scratch/, ordering card-raising
  steps last, and the jobs that are carded by design. Open it before any shell
  command that writes, deletes, or reaches the network.
---

# Tool methods

Every approval card or prompt costs the operator a trip to the keyboard. In a week of
Cursor transcripts, most cards raised through Auto-review were agents doing an allowed
job by a method that is not allowed, or joining an allowlisted command to something
else on one line. Those cards bought nothing - the job had a card-free method.

The allowlist itself is not copied here. It is a fact and it changes, so a profile
may render it from its own source. Cursor's lives in `~/.cursor/permissions.json`;
VS Code's in `chat.tools.terminal.autoApprove`, which a managed policy can lock;
Claude Code's in the `permissions` block of its settings files. Read the file when you
need to know whether a command is on it.

**Claude Code mechanics.** A permission rule matches from the start of a command, so a
command that begins with something else is not covered by a rule for what follows. Rules
are checked deny first, then ask, then allow. Auto mode suspends broad interpreter allow
rules (a blanket allow for `python` or `bash`), so a script run by interpreter can raise a
prompt that a manual mode would not. A `cd` persists between calls only inside the
session's working directories.

---

## One command per call

**Two commands on one line always raise a card, even when both are
allowlisted.** Observed in use. An allowlist entry matches a
call only when the call is that single command, so `;`, `&&`, `||` and a pipe
into anything but a formatter each send the whole call to review.

Run independent commands as parallel calls instead. They cost the same time and
nothing else.

## Card-raising steps go last

Do everything that runs free first - edits, reads, tests, ticket writes -
then the steps that raise a card, together, at the end of the turn. The operator
answers the cards in one sitting, and nothing card-free is waiting behind one.

## Use the canonical path

Run a rendered script by the path it is allowlisted under,
`python .github/scripts/<tool>/<script>.py <verb>`, from the repository root.
These all raised cards for a job that was allowed:

- `python <tool>/<script>.py` - the source path in the profile, not the rendered one
- `python ../<other-repo>/.github/scripts/<tool>/<script>.py` - another repository's copy
- `$T = "..."; python $T` - a variable hides the path, and it is two commands

## The table

| Job | Cursor | Copilot (VS Code) | Claude Code | Raises a card |
|---|---|---|---|---|
| Delete a file or directory under `scratch/` | `cleanup.py --ws <objective> --apply`, once, at the end of the workstream | same | same `cleanup.py` call (verify live) | `Delete` per file; `Remove-Item`; a delete mid-task or per ticket |
| Delete anything outside `scratch/` | `Delete` - a card, deliberately | not confirmed: shell, expect a card | - | - |
| Remove a worktree | inside `scratch/<objective>/`, the same `cleanup.py` call; elsewhere `git worktree remove`, one per call, at the end | same | - | - |
| Create, edit or append to a file | `Write`, `StrReplace` | `createFile`, `editFiles` - not confirmed live | `Write`, `Edit` (verify live) | `Set-Content`, `Out-File`, `python -c "open(...).write(...)"` |
| Back up a file before a batch edit | `Read`, then `Write` the copy to `scratch/` | same | `Read`, then `Write` the copy (verify live) | `Copy-Item` |
| Commit | `git add`, then `git commit`, each its own call | same | `git add`, then `git commit`, each its own call (verify live) | `git hash-object`, `git update-ref`, a hand-rolled commit script |
| Run a long script | `Write` it to `scratch/`, run the file | same | write it to scratch, run the file (verify live) | a multi-line `bash -c @'...'` - the classifier fails on it |

**`Delete` raises a card in Cursor.** Observed, three calls out of three. The transcript does
not record it - that prompt is Cursor's own and leaves no Auto-review marker - so a
transcript count of cards misses every one.

**Scratch is cleaned once per workstream, with one card.** The delete approval is
the last thing done, when the workstream's objective is complete. A workstream's
files live in `scratch/<objective>/`, and that directory is the inventory:
`python .github/scripts/cleanup.py --ws <objective>` lists what it would remove -
files, worktrees, and their branches - and changes nothing. With `--apply` it
removes them all in one call, and refuses the whole run, removing nothing, if a
worktree is dirty or any work is not merged into the remote's default branch. Run
the listing first and put it in front of the operator with the card.

## Carded by design

These raise a card on purpose. Batch them at the end, never chain them, and do
not look for a way around them:

- `git push` to `main`, `HEAD:main`, or with `--force`; any history rewrite -
  `reset --hard`, `rebase`, `--amend`, `filter-branch`
- `sync.py --rollout --push` - it pushes every target's `main`
- deletes outside `scratch/`
- `cleanup.py --apply` - the one end-of-workstream delete
- registering a scheduled task, killing a process by force
