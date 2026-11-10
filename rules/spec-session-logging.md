---
id: session-logging
tier: 2
scope: "*"
alwaysApply: false
description: >-
  Session logging SPECIFICATION - what belongs in a log and what does not.
  Narrowed to discarded approaches and reversed decisions only.
  Load when an approach has been abandoned or a decision reversed, or when
  resuming work that already has a log. Some repos redirect the destination;
  where a repo names one, that wins. Binding rules are in prescriptions.md.
---

# Session logging

A log records **what was ruled out**. Nothing else.

A ticket records what was decided. A commit records what shipped. Between them
almost everything is already captured, durably and greppably. The gap neither
covers is the path not taken - the approach that was tried, failed, and left no
artifact to explain why it should not be tried again.

Repos may redirect this. A repository may journal active infrastructure work to
a named execution document instead of `session-logs/`. Where a repo states a
destination, that wins.

---

## What this used to be

This once specified a running narrative updated every five
operations, with a nine-section template. That was a manual hedge against
context limits, written before transcripts and session history were dependable.

It did not survive contact. The heaviest week of work under it - 26 commits in
the rules repository alone - produced **no logs at all**, in a period
when the rule was resident in every request. The cost of the narrative competed
directly with the work, and the work won every time.

What did get maintained, without prompting, was tickets and commit messages.
The narrowed rule keeps only the part those two genuinely miss.

## When to write one

When either of these happens:

- **An approach was tried and abandoned.** Record what was attempted, what went
  wrong, and what would have to change for it to be worth trying again.
- **A decision was reversed.** Record what the original premise was and what
  falsified it.

Not for: work that succeeded, progress narration, command transcripts, file
inventories, or anything a ticket or commit message already carries.

If an abandoned approach is worth a ticket, file the ticket instead. A log entry
is for the case where there is nothing left to do - only something not to repeat.

A handoff seed - the note one session leaves for the next - is not a log. It is the
**handoff** skill.

## Contents

```markdown
# {date} - {what was tried}

**Outcome:** abandoned | reversed

## What was attempted
## What went wrong
## What would have to change for this to be worth revisiting
```

Three headings, and the third is the one with value. "We tried X and it failed"
invites someone to try X again; "we tried X, it failed because Y, and it becomes
viable if Y changes" does not.

Record exact error text rather than a paraphrase of it. The paraphrase is what
makes an old log unusable.

## Repository hygiene

Session logs are gitignored. They are working state, not deliverables.

Do **not** create summary markdown files to document changes that were just
made unless asked. A commit message and the diff already say what changed.
