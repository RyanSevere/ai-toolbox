---
name: handoff
description: >-
  Write or pick up a handoff seed - the note one session leaves so another session,
  tool or AI service can continue a workstream without the conversation that built
  it. Use when the user says any of: "hand this off", "write a seed", "write a
  handoff", "new chat for this", "I'm switching to X", "pick up where that left
  off", "read the seed", or when a session is about to end mid-workstream - context
  degrading, the compliance arrears cap reached, a service's usage running out.
  Also use when a scratch/<objective>/handoff.md file exists for the work in front of you, and
  when the operator declares a workstream's objective complete - its scratch cleanup
  is the last step.
argument-hint: write or pick up, and the workstream - a milestone, goal, ticket set or repo
---

# Handing off a workstream

A seed exists so the next reader - another chat, another tool, another AI service -
can act correctly without the transcript. It is not a record. It is read once,
confirmed with the operator, marked picked up, and removed with its workstream.

A seed passes a workstream from one session to the next. Chats that are live at the
same time coordinate through an exchange log instead - the `exchange` skill.

The first seed this was written from listed its tickets by hand and missed four of
them, while a milestone on GitHub held all fifteen in order (2026-10-09). The rule
that follows from it: **state comes from a live query, never from memory.**

## Writing a seed

### Before writing

1. **Record every finding first.** Anything that exists only in the conversation
   goes to a ticket, a document or the code now. A seed is spent at pickup and
   removed with the workstream, so a finding that lives only there is lost - `AGENTS.md`: "A finding that exists
   only in the transcript is not recorded."
2. **Name the workstream.** The area of work the operator gave this session - a
   milestone, a goal, a ticket set, a repository. If it has none of these, say so
   in the seed; "no grouping" and "grouping not mentioned" must not look alike.
3. **Name its directory.** Every workstream owns `scratch/<objective>/` - its
   top-level objective in kebab case, agreed with the operator when the workstream
   started. The seed carries it, so the next session writes into the
   same directory and the end-of-objective cleanup finds everything. A workstream
   that never agreed one proposes it now, before the seed is written.

### Where

`scratch/<objective>/handoff.md` in the repository the work lives in. `scratch/` is
gitignored everywhere, the workstream's own directory keeps parallel sessions'
seeds from colliding, and the end-of-objective cleanup removes the seed with
everything else. Work spanning
repositories gets one seed, in the repository the operator opened it from, naming
the others.

### What it holds

Fixed sections, in this order. An empty one says `none`, never disappears.

```markdown
# Handoff - <workstream>

## Written
<date and time>, by <tool or service>. Parent transcript: <id, or none>.
Repositories in scope: <list>.
Workstream directory: `scratch/<objective>/`, in each repository in scope.

## First, before acting
- Specs to read in full, by path.
- Checks to run at the start of every reply, with the command.
- Conduct that differs from the default for this workstream.

## Scope
The workstream as the operator gave it, in their priority order.
Standing rulings, each quoted with its date.

## Live state - re-run these before acting
<command>
<its output, with the time it was read>

## In flight
Uncommitted work and where it sits. A step started and not finished.
Blockers, and who each one waits on.

## Next, in order

## Waiting on the operator
Questions asked and not answered, each with the context needed to answer it.

## Not yours
Files in scratch/ that belong to other workstreams. Leave them.
```

**Live state is commands, not lists.** Paste each command's output with the time it
was read, and tell the reader to run it again. In every case, per repository:
`git status -sb` and `git log --oneline origin/main..`.

<!-- requires: tracker.query -->
The tickets, chosen by the workstream, through {{tracker.query}}:

| Workstream | Query |
|---|---|
| A milestone | Every issue in the milestone, open and closed, in this repository |
| A goal - spans repositories | Every issue under the goal, open and closed, across repositories |
| A ticket set with neither | Each named issue, open or closed |

Write the query so it resolves the repository when it runs, and the same line is
correct in every repository and in any clone of the core.
<!-- end -->

Never write a repository or owner into the seed as a constant where a command can
work it out.

**Tool-neutral.** The reader may be a different tool or AI service from the writer.
Plain markdown; every tool-specific step names its generic equivalent ("the
look-back check: `python .github/scripts/responses/check_response.py --previous`,
which detects the tool"); no machine paths, store ids or account tokens.

### Then, the pickup prompt - always

**A handoff is not finished until the pickup prompt is in chat.** Every handoff ends
with it, whether or not the operator asks: filled in from this template, in a fenced
block so it copies in one action, as the last thing in the reply. It goes in chat, not
in the seed: the seed is spent at pickup, and the prompt is only the way in.

```
Pick up the <workstream> workstream in <repository>, on branch <branch>. Read <seed path>
in full and follow the handoff skill's "Picking up a seed" steps: do what its "First,
before acting" section says, re-run every Live state command and say where the fresh
output differs from the pasted one, re-ask anything under "Waiting on the operator", then
confirm the scope and the next step - <first item under Next, in order> - with me before
acting. Mark the seed picked up once I confirm.
```

It carries nothing but those fields. Anything else belongs in the seed, which is the
source; state copied into the prompt goes stale the way a hand-listed ticket set does.
Session-specific conduct - "refine tickets only, no code" - goes in the seed's
`First, before acting`.

## Picking up a seed

1. Read it in full before acting.
2. Run every command under `Live state` again. Where the fresh output disagrees with
   the pasted one, the fresh output wins - say what changed.
3. Do what `First, before acting` says.
4. Confirm the pickup with the operator - what you understood the scope and the next
   step to be. Questions under `Waiting on the operator` are re-asked, not assumed
   answered.
5. Write into the seed's workstream directory, worktrees included. A file this
   session makes anywhere else in `scratch/` is one the cleanup will not find.
6. Once the operator confirms, make the seed's first line
   `Picked up <date and time>, by <tool or service>.` - an edit, not a delete. A seed
   carrying that line is spent: a later session reads it as history, never as a
   workstream to take. It goes with the directory's cleanup. Leave `Not yours` alone.

## Closing a workstream

When the operator declares the objective complete, and not before - not when a
ticket closes, not mid-task:

1. Run `python .github/scripts/cleanup.py --ws <objective>` in each repository in
   scope. It lists the directory's files, its worktrees and their branches, and
   changes nothing. Anything it refuses - a dirty worktree, work not merged into the
   remote's default branch - is resolved with the operator first.
2. Put the listing in front of the operator, then run the same command with
   `--apply` as the last step of the session. One call, one card, per repository.

## Failure modes

- **A hand-listed ticket set.** It is complete only on the day it is written, and
  wrong silently after. Use the query.
- **A seed not marked at pickup.** Two sessions reading one seed each believe they
  own the workstream. Mark it picked up on confirmation.
- **Findings moved into the seed instead of out of the conversation.** The seed is
  removed with the workstream; the finding goes with it.
- **A seed with no pickup prompt.** The operator has to write the way in by hand, and
  a hand-written prompt drops the steps that make the pickup safe.
