---
id: planning
tier: 2
scope: "**/{docs,project-docs,planning-docs}/**"
alwaysApply: false
description: >-
  Planning SPECIFICATION - living plan document structure and the review gate
  that must pass before implementation starts, including the twelve categories
  a plan must address or explicitly mark N/A. Load when writing, reviewing, or
  updating a plan or design document, or when asked whether a plan is ready to
  implement. Do not load for small single-file changes; the spec says so itself
  and applying it there is how planning documents stop being read. Also says where
  runbooks live - docs/runbooks/ - and that this spec does not apply to them.
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

For multi-step work: plan, get approval, then implement. The plan is a living
document, not a one-off artifact.

Lives in `docs/` or `project-docs/`, following whatever the repo already does.

## Runbooks

Runbooks live in `docs/runbooks/`, named `RUNBOOK-<SUBJECT>.md`, with supporting
files in `docs/runbooks/<subject>/`. A runbook is a procedure, not a plan: the rest
of this spec does not apply to it. Existing runbooks elsewhere move as their own
repository's work.

---

## Living plan documents

Create one for multi-phase features, migrations, significant refactors, and
troubleshooting that spans sessions.

Core sections:

| Section | Purpose |
|---|---|
| Decision Ledger | Locked decisions, to stop scope creep |
| Work Tracking | Planned vs actual vs current |
| Change Log | Modifications, timestamped |
| Variance Log | Where reality diverged from the plan |
| Issue Resolution | Problems hit and how they were settled |
| Scope Evolution | Additions and requirement changes |
| Testing Results | Validation outcomes |

Update **before** each phase starts, when implementation deviates, at
milestones, when scope grows, and after implementation with what was learned.

The living document is the single source of truth for status and decision
history. If it disagrees with a chat transcript, the document wins.

---

## Review gate

**Implementation does not start until the plan has been reviewed and the review
is recorded in the Change Log.**

Run it per phase, and again whenever the plan changes substantially.

### Checklist

- [ ] Plan validated against the actual codebase, not against assumptions
- [ ] Assumptions checked; divergences recorded in the Variance Log
- [ ] Unknowns each resolved, deferred with a reason, or accepted as risk
- [ ] Implementation risks and mitigations documented
- [ ] Acceptance criteria defined per phase - explicit pass and fail
- [ ] Testing approach defined
- [ ] Blocking issues resolved, or deferred with explicit rationale
- [ ] Review completion recorded with a timestamp

### Categories to address

Address each, or state "N/A" with a reason. Missing categories mean the plan is
not ready.

**Analysis:** assumptions; gaps; unknowns; unclear requirements.

**Implementation:** dependencies and ordering, including what can run in
parallel; integration points and data formats at boundaries; validation
strategy and what distinguishes success from failure; rollback, and which
changes are reversible.

**Quality and risk:** edge cases and malformed input; resource and timeline
reality; user and data impact during transition; acceptance criteria and how
the original problem is verified solved.

---

## Scale the ceremony

This protocol is for genuinely multi-step work. A single-file fix does not need
a Decision Ledger. Applying the full framework to small changes is how planning
documents become something people stop reading.

The test: **would losing this conversation cost more than writing the document
costs?** If not, skip it.
