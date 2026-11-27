---
id: planning
tier: 2
scope: "**/{docs,project-docs,planning-docs}/**"
alwaysApply: false
description: >-
  Planning SPECIFICATION - what belongs in a design document and what belongs in
  a ticket, and the short design review run before tickets are marked
  agent-ready. Load when writing or reviewing a plan or design document, or when
  asked whether a design is ready to build. Do not load for small single-file
  changes; the spec says so itself and applying it there is how planning
  documents stop being read. Also says where runbooks live - docs/runbooks/ -
  and that this spec does not apply to them.
---

# Planning

## Documents plan; tickets track

A plan document and an issue are not two places to put the same thing. They
fail differently, and that is what decides which one a given sentence belongs
in.

| | Goes stale | Belongs in |
|---|---|---|
| Design, rationale, rejected alternatives | No | **A document** |
| Status, next steps, blockers, phase state | Yes | **An issue** |

The asymmetry that matters: **only an issue's state is maintained by the act of
working.** Closing it is part of doing the work. A status line in a document is
maintained only by someone remembering to go and edit it, which is a separate
act that competes with the work and loses.

### This has cost real time twice

- A correct `SMTP_` / `MAIL_` diagnosis written into a planning document and
  marked BLOCKING. Unactioned for five months. It was never unknown - it was
  unfindable.
- A design document correctly reading "Design, not started" while both
  participants in a session failed to locate it.

Neither was a recording failure. Both were a **wrong container** failure -
status placed somewhere with no mechanism to surface it.

### This is not a reason to stop writing design documents

It is a division of labour, not a demotion. A document carrying design and
linking to issues for status is the target. A backlog with no written reasoning
behind it is worse than a stale document, because the reasoning is gone rather
than merely out of date.

When a document is mostly tracking, convert the tracking to issues and let the
document become the decision archive it was always better at being.

---

For multi-step work: plan, get approval, then implement.

A plan document lives in `docs/` or `project-docs/`, following whatever the repo already does.

## Runbooks

Runbooks live in `docs/runbooks/`, named `RUNBOOK-<SUBJECT>.md`, with supporting
files in `docs/runbooks/<subject>/`. A runbook is a procedure, not a plan: the rest
of this spec does not apply to it. Existing runbooks elsewhere move as their own
repository's work.

---

## Design review

**Tickets are not marked agent-ready until the design has been reviewed.** Run it
before marking them, and again whenever the design changes substantially.

The spec gate checks the ticket: its required sections, its acceptance criteria,
and its testing approach. This review does not repeat that. It covers only what
the spec gate does not check:

- **Rollback:** which changes are reversible, and how each is reversed.
- **Dependency ordering:** what must land first, and what can run in parallel.
- **Resource and timeline reality:** whether the work fits the time, tools and
  capacity it has.

Record the outcome as a comment on the ticket, with the date. Do not record it in a
document.

---

## Scale the ceremony

This protocol is for genuinely multi-step work. A single-file fix does not need
a design review or a plan document. Applying the full framework to small changes is how planning
documents become something people stop reading.

The test: **would losing this conversation cost more than writing the document
costs?** If not, skip it.
