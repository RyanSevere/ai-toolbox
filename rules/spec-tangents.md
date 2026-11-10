---
id: tangents
tier: 2
scope: "*"
alwaysApply: false
description: >-
  Tangent SPECIFICATION - why a valid finding still needs a verdict before it is
  followed, how to weigh acting now against filing for later, and what naming the
  thread means in practice. Covers the evidence that tooling displaced the work it
  was built to support, the rule against suppressing findings, and why this is a
  shared record rather than something the assistant applies to itself. The binding
  one-line rules are in prescriptions.md. Open this when a rule seems to be asking
  you to withhold something, or when deciding whether a finding is worth following
  now.
---

# Tangents

The problem is not bad tangents. It is **unbounded good ones**.

Every tangent in the week this was written was individually justified. One
glob finding was real, and had it been suppressed the entire rules
mechanism would have silently stopped working. That is what makes this hard:
there is no bad-tangent filter to build, because the tangents are correct.

---

## What actually goes wrong

One week, as it happened:

```
Day 1  An infrastructure upgrade ships two phases
Day 1  A pipeline overhaul spun out to its own doc -> "Design, not started"  [never resumed]
Day 4  An audit -> 46 issues filed
Day 4  The rules repository created to fix what the audit exposed
Day 5  Hooks
Day 6  Context layers, /prime, /sync
Day 7  The rules repository consumes the entire day
```

The rules repository took 26 commits over that span. The repository all of it
was built to support took 6 - every one a rules re-render.

**The tooling displaced the work it was built to support**, and nothing reported
that while it was happening. No step was wrong. The sum was.

---

## Three questions, not one

When something new appears mid-task, only the first of these is reliably
answered today:

1. **Is it valid?** Usually yes, and this is answered well.
2. **Does it have to be now?** Almost never asked.
3. **What is it a tangent from?** Almost never stated.

Question two is the whole point. Question three is what makes returning
possible.

---

## The tangent you wrote yourself

Everything above assumes a finding **arrives**. The harder case is scope that
**grows**, because nothing arrives and so nothing triggers the questions.

Added after exactly that. A ticket said: write the secrets util
in two languages, done when six unit tests pass. Asked where it should live,
the answer proposed a new repository, a packaging exercise in two ecosystems,
and a versioning scheme. All defensible. None of it in the ticket.

**The operator caught it. The rules did not**, because no finding had arrived -
the proposal had simply inflated, one reasonable step at a time.

The check is mechanical and costs nothing:

> Does what I am about to do change the ticket's **exit criteria**?

If yes, it is a different ticket. Say so, file it, and finish the one in hand.
If the answer is unclear, read the exit criteria again - a ticket that does not
state them is the real defect, and that is worth fixing first.

This matters more than the arriving-finding case, because scope growth is
invisible from the inside. Each step follows from the last, nothing is wrong,
and the ticket that unblocked seven issues quietly becomes blocked on learning
a packaging toolchain.

---

## Review feedback is not a work order

A third shape, added after it slipped past both rules above.

The operator said *"just going to do a general review"* and listed four
observations on a file. Editing started immediately. The thread at the time was
a research ticket, and it was abandoned mid-sentence without anyone saying so.

Nothing arrived unbidden, so the first rule did not fire. No scope grew, so the
second did not either. **Feedback was simply read as an instruction.**

It usually is not. A review produces findings, and findings get the same verdict
as any other:

> Valid? Yes. Does it have to be now? No. What is it a tangent from?

The fix costs a sentence: *"Three of those are quick and one needs a decision -
file them and stay on the research, or take them now?"* That is a question the
operator can answer in one word, and it keeps the thread named either way.

**Where the work is genuinely small this still applies.** The edits in that case
took minutes, which is exactly why nobody noticed the thread had been dropped -
a cheap tangent is harder to spot than an expensive one, not easier.

---

## Weighing now against later

| Act on it now | File it and continue |
|---|---|
| It invalidates the work currently in flight | It is independent of the current thread |
| It is a live security or data-loss exposure | It is a correctness or tidiness issue |
| The context to fix it exists **only** right now | It will be equally fixable next week |
| Leaving it makes the current change wrong | Leaving it makes a future change harder |

The glob discovery qualified on row one - it invalidated the thing being built.
Most findings do not, and get treated as though they did.

**When the answer is "later", file it immediately.** Not at the end of the
session, not when the thread closes. That mechanism already works and is why the
backlog is usable; the gap is that nobody asks the question that triggers it.

---

## Naming the thread

Say what is being left, and say it on the way out rather than afterwards:

> That is worth doing and it is not this. Filing it as `proj-24`; still on
> the Phase 8 split.

On return, say what the tangent was a tangent *from*. A stack that is never
popped out loud is a stack nobody remembers pushing.

At the end of a reply, **separate what finishes the original request from what
was found along the way.** Listing both under one heading is what makes a
tangent look like progress on the thing that was asked for.

---

## This is a shared record, not self-discipline

Tangents originate from both sides of the conversation, and the operator's
arrive faster than they can be executed. A rule the assistant applies privately
to its own behaviour therefore solves at most half of it.

What is needed is a **visible, shared statement of the open thread** - one that
either party can point at. That is why the binding rules are about saying things
out loud rather than about internal restraint.

---

## The constraint that outranks everything here

**Never withhold a finding.** Not to protect focus, not to keep a thread tidy,
not because it seems small.

The most valuable discovery of the week this describes was a tangent. A version
of this rule that made the assistant reluctant to surface findings would be
strictly worse than the behaviour it replaced, and it would fail invisibly -
the findings it suppressed would leave no trace at all.

Surface it, weigh it out loud, then either take it or file it. The judgement is
about **sequencing**, never about disclosure.

---

## What this does not ask for

- Not a ban on tangents, or a quota
- Not a depth limit, or a counter that blocks work at some threshold
- Not permission-seeking before every finding
- Not a new document. The thread is named in conversation and the deferral is
  named in an issue, both of which already exist
