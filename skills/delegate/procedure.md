---
name: delegate
description: >-
  Hand a settled piece of work to a subagent and take back a result you can trust:
  when to delegate, which model, the brief, the stop rules, and the review before
  anything ships. Use when the user says any of: "give that to a sub-agent", "have a
  worker build it", "delegate this", "spin off a worker", or when a settled plan is
  bigger than a few tool calls, or a read-only search would pull large files into the
  main session's context.
argument-hint: the settled work, and where it is specified
---

# Delegating to a subagent

The main session designs, decides, drafts for the operator's review and verifies.
A subagent executes a plan that is already settled, or does research too large to
read in the main session. Its report is all the main session takes back, so the
brief decides the quality and the review decides whether it ships.

## When to delegate

- **Delegate:** a settled build, a batch of tool-driven writes (ticket posts,
  renders, commits in one worktree), a test run, or read-only research over many
  files or a long page. The win is largest when the reading is large and the report
  is small.
- **Keep:** anything that needs a decision, anything that needs this conversation's
  context to judge, and anything a few tool calls settle - a brief costs more than
  that.
- **Model:** the cheaper model for execution and bounded research; the main model
  for anything the operator will rely on without re-reading, such as a handoff seed
  or a spec.

## The brief

Write it to a file in the workstream's scratch directory, so it can be reviewed and
reused, and pass the path. It carries:

1. **Spec:** the ticket or document that is binding, and which of its sections.
2. **Where:** the exact worktree and branch, and "work only here".
3. **Hard rules:** never push, never open a pull request, never merge; edit files
   with edit tools only - no heredocs, no `python -c` writes; one command per call;
   no background process left running; the profile's commit rules (trailers,
   identity); in a public repository, no profile names anywhere, and synthetic
   fixtures only.
4. **Build steps**, in order, with the decisions already made. Anything left open is
   a stop condition, not a choice for the worker.
5. **Tests:** one failing-then-passing test per behaviour. **Paste the failing run;
   a report without it is incomplete.** Name the suite command, minus anything that
   cannot run locally, and name CI as the run of record for that part. Run locally
   any linter the consuming profile gates on.
6. **Stop and report:** on the spec's escalation conditions, and on any design
   question the brief does not answer.
7. **Report:** commits, before and after test lines, one line per step, every
   deviation, the diff stat - under a word cap.

## Review before anything ships

The worker's report is a claim. Before pushing:

- Read the diff of the logic that matters, not just the stat.
- Search the diff for names the repository must not carry; check commit trailers and
  author.
- Check the merge against the current base, and whether a release is in flight on it.
- Spot-check the report's pointers and numbers; re-run one test or the live behaviour
  yourself where that is cheap.
- Name every deviation the worker reported, and either accept it out loud or fix it.

Only the main session pushes, opens the pull request and reports to the operator.

## Failure modes

- **A brief that carries a mistake.** A wrong rule in the brief is copied into every
  commit. Check the brief against the profile's gates before dispatch.
- **"Tests pass" with no failing run.** A test never seen failing may test nothing.
- **A stalled background run.** Stop the worker, then check for leftover processes.
- **A report read in part.** It is the only thing that comes back. Read it whole, and
  ask again rather than infer.
