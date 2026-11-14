---
id: response-shape
tier: 2
scope: "*"
alwaysApply: false
description: >-
  Response shape SPECIFICATION - the format every reply takes. Covers the mode
  header, the condensed default shape (summary with pointers, decisions,
  operator steps, recommended next, came up), the full planning and execution
  blocks printed on demand and what each section is for, the
  per-entity ID prefixes the operator answers with, why evidence for and evidence
  against are separate lines, the falsification line and its known weakness, and
  the look-back compliance check that grades the previous reply before this one
  is written. Open it before writing any reply. Not advertised by scope because
  it applies to every turn rather than to a file type, so nothing would trigger
  it; the routing table in prescriptions.md is the only pointer at it.
---

# Response shape

**Status: in use and permanently open to refinement.** There is no
done state for this document. It reaches *good enough that changes are
refinements* and stays there - the same way other long-lived specifications
work. An earlier draft marked itself "reference artifact, not to be changed"
and was wrong within the hour; the marker is gone and will not come back.

Changes land here as they are agreed. The shape was built under a ticket; no
ticket tracks its refinement. **Refinement is not ticketed**: it is one-off work
that continues for as long as the shape is used.

Work with no end state cannot have an exit criterion, and a ticket without one
sits open forever reporting nothing. The document is the record.

Checked by `check_response.py`, which grades structure only and prints what it
cannot judge.

Sections exist because the operator can act on them. Not because a script can
check them. That ordering was the flaw in the previous draft.

---

## Rules that hold regardless of mode

1. **Verify always, print on demand.** Every claim is verified, and the tool call behind it can be named, in every reply, whatever its shape. The shape changes only what is printed: the condensed shape prints a summary with a pointer for each result, and the full shape prints every premise and claim with its evidence for and against. Mode still never reduces obligations; it reorders and renames them.
2. **An empty section is omitted, never padded.** Filler to satisfy a shape is
   the content that gets skipped, and skipping trains skipping. The stated-empty
   exception: Recommended next and Came up with the line `None.`, and a Summary of
   `None this turn.`, are written out, like `## Your premises` with `none new this turn.`
3. **An omitted section is a signal, not a gap.** No `Evidence` on a turn full
   of claims means nothing was checked. That is the reading.
4. **Sub-items are nested list items, not bolded prose and not indented
   lines.** The nesting carries the relationship; a bold lead-in followed by a
   paragraph does not. An item is a top-level `-` bullet starting with its ID,
   and its fields are `-` bullets nested under it. Four leading spaces without
   a bullet is a markdown code block, so an indented item renders as monospace
   and its long lines run off the side. Once, every example below
   was indented that way inside a fence, and a reply that copied one out of the
   fence rendered every section as code. The checker strips leading whitespace and list
   markers before matching an ID, so both forms grade the same. **A section
   title is a markdown heading** - `## Your premises`, not a bare line. The
   checker finds sections by heading, so a reply with bare titles parses to
   zero sections and every one is reported missing. Once, every
   example below showed bare titles, and a reply that followed them failed on
   sections it had - the same trap as the bold IDs in rule 10.
5. **Caps apply where the count is mine to choose, not where the data sets
   it.** Three came-ups, four next steps - overflow named in one line and
   deferred. **Decisions and clarifications have no cap.** How many things
   genuinely need a ruling is a property of the work, and truncating that list
   hides a question rather than answering it.
6. **Mixed is structural, not interleaved.** Planning block complete, rule,
   then execution block complete. Never alternating.
7. **Every claim carries evidence for and evidence against, separately.** A
   single undifferentiated evidence line is the evidence that was gone looking
   for. Splitting it forces the question of what was found on the other side.
8. **Block order is not chronological.** The planning block precedes the
   execution block even when the work happened the other way round. Nobody
   should read sequence into it.
9. **Every entity in the reply carries an ID, not only the ones asking
   something.** The prefix says what kind of thing it is; the counter runs
   per prefix and never restarts within a reply.

   | Prefix | Entity | Block |
   |---|---|---|
   | `P1`, `P2` | A premise - operator's or acted on | both |
   | `C1`, `C2` | A claim of mine | planning |
   | `LA1`, `LA2` | An item under Logic and approach | planning |
   | `DC1`, `DC2` | A decision or clarification. A fork in the road | planning |
   | `A1`, `A2` | An asked-done-result task | execution |
   | `ND1`, `ND2` | Something not done or not checked | execution |
   | `CU1`, `CU2` | Something that came up while doing it | execution |
   | `R1`, `R2` | A recommended next step. Listed, not asked | both |
   | `OS1`, `OS2` | A step only the operator can take | condensed |
   | `Q1`, `Q2` | A question, attached to the item it is about | both |

   **The ID is the default, not a marker of significance.** Earlier drafts
   numbered only questions, decisions and next steps, which made everything
   else unaddressable - the operator could not object to a premise verdict or a
   piece of reasoning without quoting it back in full. The operator may comment
   on any entity in the shape, whether or not it asks anything.

   `Premises acted on` in the execution block shares the `P` counter with
   `Your premises`. They are the same kind of thing and never appear in the
   same block.

   The operator answers with "C2 and R1", never "the second claim" - a
   reference should identify an item without also naming which section it lives
   in.
10. **Every question attaches to the item it is about.** A question separated
    from its context is unanswerable without reconstructing that context, and
    reconstruction is a cost the operator should never have to pay.

    The standalone `Decisions and clarifications` section survives for exactly
    two cases:
    - **(a)** the question spans several items - common, and most often
      meta-level in planning;
    - **(b)** the question has to be answered before any item can exist, so
      there is nothing yet to attach it to - rare.

    Prompted by a one-line recommendation the operator could not rule on,
    because the context needed to answer it was three sections away.

    **An item that raises something actionable carries the question itself.**
    A bug found, a gap noticed, an option spotted - if there is any chance you
    want it acted on, the question belongs on that item. Writing it up as a
    recommendation or a decision further down is the same failure as (a) and
    (b) not applying, arrived at by a different route. Added after
    a found bug was reported as an item and its "shall I fix it?" appeared
    three sections later as a recommendation.

    **A pointer to a question is not a question.** "Q1 attached below" written
    under an item, with the question itself in the Decisions section, is the
    defect wearing the fix's clothing. Attached to the reply but not to the
    entity does not count.

    **An attached question is not bolded, and not indented past its neighbours.**
    The `Q<n>` prefix is what makes it findable; bold adds nothing. The checker
    finds an item by its ID - `P`, `C`, `LA`, `DC`, `A`, `ND`, `CU` or `R` at the
    start of a line - and deliberately not by `Q`, so a question line stays
    attached to the item above it. It once found items by bold
    instead, while every example in this document used unbolded IDs; replies
    that followed the examples parsed to zero items and passed on the header
    alone for a full day. A bolded question was read as a claim with no verdict,
    no evidence and no falsifier - five findings generated by text that follows
    this rule. The ID is what makes it stand out; bold does not, and bold is
    what the checker tripped on.

    **Indenting it further is worse than bolding it.** Four spaces in markdown
    is a code block, so an indented question renders as one long unwrapped line
    that runs off the side and cannot be read. Write it as
    a plain list item beside the item's other lines - same level, no bold, `Q<n>`
    first.

    **In the condensed shape the same rule holds, with different homes.** (Operator
    ruling 2026-11-13.) A `DC` carries its own context in its `Use case:`
    line, so it is never a pointer to the Summary. A standalone `Q` states in the
    same entry what it is about and what the ask is. A `Came up while doing it`
    item is informative by default; **one that needs the operator to rule carries a
    nested `Q<n>` line, and an item with no `Q` is read as informative.** The
    `Q` is how the operator tells "needs a ruling" from "FYI" without reading the
    item. The checker does not test this: whether a `CU` needs a ruling is a
    judgement it cannot make, so the reviewer reads for it.
11. **A question goes where the context that answers it is.** This is not a
    rule about restating versus referencing. It is about distance.

    The failure is asking for a decision somewhere other than beside the thing
    that would let it be made. An ID does not repair that: by the time a reader
    reaches `R3`, which points at `ND2`, which points at `C5`, the context that
    made `C5` meaningful is gone and they are reconstructing it from three
    scattered pieces. The issue is not restating; it is moving the question away
    from the context needed to answer it.

    So an ID is a handle for the operator to point at an item. It is not a
    substitute for putting a question next to the reason it is being asked.
    Where an item genuinely needs a fact established elsewhere in the reply,
    bring the fact to the question rather than sending the reader to it.

    **A cross-reference is allowed when it names context, not an ID.** On a
    mixed turn the execution block's `Premises acted on` would otherwise repeat
    the planning block's `Your premises` verbatim. One line resolves it -
    provided that line says *where the content is* in words, not by pointing at
    an identifier.

    Acceptable: "Both premises acted on this turn are in `Your premises` above."
    Not acceptable: "See P1 and P2."

    **In the condensed shape the premises and claims are not in the reply, so a
    question cannot point at them.** What a ruling depends on is stated in the
    `DC`, `Q` or `CU` itself, in words. A pointer to the ledger file does not
    count as context: the operator does not read it in the moment.
12. **Emoji are barred from documentation, not from chat.** The rule exists
    because display systems render them badly. Chat is not one of those
    systems, so the compliance check does not test for them - it was producing
    false positives on box-drawing characters in pasted terminal output.
13. **An approved action is never a recommendation. Do it.** Re-listing
    something the operator approved in their previous message as a next step is
    asking for permission already granted, and it puts the work back on the
    person who already did their part.
14. **A proposed design change carries an approval question or it is not a
    proposal.** Stating an improvement as an observation and then building it
    means the operator agreed by not objecting, which is not agreement. Two
    design changes once went in this way and were approved after the
    fact - luck, not process.
15. **A change made mid-turn is reported in the turn that made it.** A fix
    applied between two tool calls, with only its result surfacing, is invisible
    work - the operator sees a passing check and not the edit that produced it.
    Name the change, then name what verified it, and never present the second
    without the first.
16. **Anything re-surfaced from an earlier turn goes in `## You missed this`,
    directly under the header, and every entry there is a `Q<n>` line.** An
    item the operator did not answer was probably missed, not declined, so it
    comes back loud, above the planning block, not as a quiet line near the end.
    Each entry says what it is and what the ask is, and carries a `Q<n>` from this
    reply's counter, so it can be answered as "Q1". It is new to this reply, and
    its original ID from the earlier turn is stale. The checker flags any entry
    in that section, or under a "Still open" heading, that does not start with
    `Q<n>`, so the operator has a key to answer by. The section existed for four days only in the
    assistant's memory, unwritten here, so it was improvised every time, and a
    ticket approval sat unanswered for six turns under an entry with no ID.

---

## Header

Always present, always three lines or fewer.

```
Mode: Planning | Execution | Planning + Execution
Needs from you: 2 decisions, 1 clarification        (or: nothing, informational)
Changed: 3 files in example-repo, committed         (or: nothing)
```

The `Needs from you` line is triage only. It says how much judgement this reply
costs before any of it is read. It is not a summary and cannot be acted on
alone.

**The compliance verdict is not here.** It was, briefly. A header is written
before the body exists, so a compliance line in it could only describe intent.
It goes immediately above or below the header instead, reporting the **previous**
reply - see Compliance.

---

## Condensed shape

The default. Operator rulings of 2026-11-08, 2026-11-10, 2026-11-12 and
2026-11-13. The operator reads the decisions and the next steps about nine times in
ten and mostly takes the recommended option; the full blocks are paid for in
every reply and mostly unread. The shape exists to make agents show their work,
to show when a context has grown so large it is dropping things, and to say what
the operator has to do. The condensed shape keeps all three.

In this order:

- **The header**, unchanged, with the compliance line beside it. `Needs from you`
  counts decisions, questions and operator steps.
- **`## Summary`**: one paragraph of prose - no blank line inside it, no list
  bullets. It says what happened this turn. Every result it claims carries an
  inline pointer: a `path:line`, a backticked command or its output, a URL, or a
  quotation. The checker requires at least one pointer in the paragraph, which is
  the floor, not the obligation. A reply that claims no result writes the single
  line `None this turn.`
- **`## Logic and approach`**, required when the Mode contains Planning (Planning,
  or Planning + Execution), optional otherwise: the reasoning behind an approach,
  in `LA` items with a verdict, as in the full shape. Operator ruling 2026-11-13:
  on design messages it is the most useful section, so the condensed shape keeps
  it. It sits after the Summary and before the decisions it leads to. Writing it
  does not make the reply full.
  The checker fails a Planning reply that omits it, even when the reply did not
  need it. That is deliberate (operator, 2026-11-13): the agent sees the
  finding, judges whether it was right, and may leave the reply uncorrected if it
  was not. An unchecked requirement would be dropped without anyone noticing.
- **`## Decisions and clarifications`**, only when there is something to ask. `DC`
  items and standalone `Q` items. Each carries the full context needed to answer it
  in place, because the premises and claims it would once have been attached to
  are no longer printed. Each `DC` keeps its `Use case:` line and marks exactly one
  option `(recommended)`.
- **`## Operator steps`**, only when the operator has something to do: run a
  command, review a page, paste a result back. Items are `OS1`, `OS2`, and so on.
- **`## Recommended next`**: the work that comes next - not things for the
  operator to do. An item may depend on an operator step ("once OS1's output is
  back, decide whether X is viable"). `R` items, cap 4, or the single prose line
  `None.`
- **`## Came up while doing it`**: what was found along the way. `CU` items, cap
  3, or the single prose line `None.`
- The queue line where one applies. It is not checked.

Recommended next and Came up are both required, so an omitted section and an
empty one never look alike. A nested line never starts with an ID-like token:
options are `a.`, `b.`, because the checker reads any line opening with an ID as a
new item.

### The full shape, on demand

The planning and execution blocks below, printed as they always were. They are
owed when:

- the operator asks for it ("expand"); or
- the reply proposes a state change the operator has not already approved. That is
  the agent's judgement, and the checker cannot detect it.

### Inferring the shape

There is no marker to forget. A reply containing any heading from this set is
graded as full: Your premises, My claims, Recommendations, Asked done result,
Premises acted on, Not done not checked. Any other reply is graded as condensed.
Logic and approach, Decisions and clarifications, Operator steps, Recommended
next and Came up are left out because both shapes use them.

A reply graded as full gets the full checks, unchanged, so a half-opened block -
a lone `## My claims` - fails on the sections its mode requires. A reply graded as
condensed gets the condensed checks and none of the mode-required sections. The
header checks, the item-ID check and the caps apply to both.

| Condition | Finding |
|---|---|
| `## Summary` absent | `condensed: section missing: summary` |
| `## Recommended next` absent | `condensed: section missing: recommendednext` |
| `## Came up while doing it` absent | `condensed: section missing: cameupwhiledoingit` |
| Mode contains Planning and `## Logic and approach` absent | `condensed: section missing for planning mode: logicandapproach` |
| Summary has no paragraph, or more than one | `summary: <n> paragraphs, exactly 1 allowed` |
| Summary carries no pointer and is not exactly `None this turn.` | `summary: no pointer a reader could follow` |
| Recommended next or Came up has no item and no `None.` line | `<section>: empty - list an item or write 'None.'` |

In both shapes every `DC` item marks exactly one option `(recommended)`, on any of
its lines, case-insensitive. Otherwise it fails with `decisions: '<title>' marks
<n> options recommended, exactly one is required`. The `Recommendation:` line in
the full shape is the reasoning and is not counted.

The grade line names the inferred shape: `previous reply: mode=<mode> |
shape=<full|condensed> | <n> chars | <n> sections`.

---

## "aria"

- "aria", as an explicit one-word reply, takes every option marked `(recommended)`
  in the immediately previous reply, and nothing else.
- It is never a silent default. A reply that is not exactly "aria" (case and
  trailing punctuation aside) is not one.
- It approves a recommended option that is a write only if that reply printed the
  plan, which under the trigger above means it was in the full shape.
- Queue items are unchanged: their verdict is the queue service's to judge.

---

## Planning block

### 1. Your premises

Every factual claim in the request, or that the work rests on. **This section
is the reason the shape changed.** Nothing previously forced the operator's own
statements to be checked.

Two kinds of premise, checked differently:

- **A factual claim** is checked against the world. Verdict comes from evidence.
- **A ruling** is a decision, and cannot be true or false. It is checked for
  **consistency with rulings already in force.** Treating a ruling as a factual
  claim is a category error; skipping it entirely is how two rulings end up
  contradicting each other with nobody noticing.

```markdown
## Your premises
- P1 "the alerting ticket is proj-35" [factual]
  - Verdict: confirmed
  - Evidence for: `gh issue view 35 --repo owner/repo` -> "Alerting is pure noise: every alert is now deleted unread"
  - Evidence against: none found
  - Looked for it: yes - checked the title matched the subject
- P2 "decisions and clarifications get no cap" [ruling]
  - Consistent with: the data-drives-it principle; the use-case requirement that makes each item answerable
  - In tension with: "one thread at a time"; the four-item ceiling on next steps
  - Resolution needed: whether the header count is sufficient mitigation
- P3 "DECISIONS.md was dead" [factual]
  - Verdict: contradicted
  - Evidence for: none found
  - Evidence against: DECISIONS.md:41, last entry 2026-09-15, referenced by three current rules
  - Looked for it: yes
```

Verdict values: `confirmed`, `contradicted`, `not checked`. **`not checked` is
a first-class verdict, not a failure to fill the section in.** A premise acted
on without verification must be visible as such.

If there are none: the `## Your premises` heading with one line under it,
`none new this turn.` Stated, not omitted -
"I checked and found nothing to challenge" and "I did not check" must not look
alike.

### 2. My claims

```markdown
## My claims
- C1 All seven repos rendered clean
  - Verdict: confirmed
  - Evidence for: <pasted per-repo output, exit codes included>
  - Evidence against: none - no repo reported [ERROR] or a non-zero exit
  - Would have falsified it: a non-zero exit or an [ERROR] line from sync.py
  - Looked for it: yes, exit code captured per repo
- C2 The verifier agent has no terminal
  - Verdict: confirmed
  - Evidence for: <agent's own tool enumeration, no execution tool present>
  - Evidence against: none
  - Would have falsified it: the agent returning command output
  - Looked for it: yes, that was the test
- C3 Transcripts are written for every session
  - Verdict: not checked
  - Evidence for: none
  - Evidence against: none
  - Would have falsified it: a dated listing of the transcripts directory
  - Looked for it: no
```

**An empty `Evidence for` on a claim whose verdict is not `not checked` is a
contradiction, and the most valuable thing the shape catches.** It is also
mechanically detectable, which makes it the strongest requirement here.

**Evidence that is present but unfollowable is the next weakest point, and it
is checked too.** The side of the evidence that carries a verdict - `Evidence
for` on `confirmed`, `Evidence against` on `contradicted` - must hold at least
one pointer a reader could follow without trusting the writer:

| Pointer | Looks like |
|---|---|
| A file location | `tickets/collect.py:201`, `context/sitrep.prompt.md:125-126` |
| A command run this turn, or its output | a backticked span with a space in it - `gh issue view 3 --repo ...`, `open issues checked: 99` |
| A URL that was fetched | `https://...` |
| A quotation | the operator's words, or a line of a file or body, in double quotes |

A bare identifier in backticks - `tickets/collect.py` - is not a pointer. It
names a thing without saying where in it to look.

Added after three false claims in one session, each with an `Evidence for` line
that was a summary with nothing behind it. The first proposal allowed only
`path:line`, and was rejected as too narrow: evidence also comes from a terminal
command, a web search, or a quotation.

**This checks presence, not truth.** A cited line never opened passes. What it
buys is that fabrication now costs one followable link, which the operator can
follow, rather than a paragraph they have to take on trust.

The falsification line exists because supporting evidence for one's own claim is
the evidence one went looking for. Naming what would have broken the claim, and
whether that was actually sought, is a question that is hard to answer
dishonestly without noticing. **Its weakness is that the falsifier is chosen by
the same party** - naming a weak falsifier passes the check. That is how a
bypassed tool gets past it: a hand-rolled query produces real output, and the
catch depends on naming the sanctioned tool as the falsifier.

### 3. Logic and approach

**Always present in planning mode.** Planning is weighing something by
definition - if nothing is being weighed, the turn is not a planning turn and
the mode label is wrong. This section is also the home for reasoning that is
neither a claim nor a premise, which the previous draft had nowhere to put.

```markdown
## Logic and approach
- LA1 A standalone "not checked" section, separate from claim verdicts
  - For: the negative space is where three of four original failures sat
  - Against: it can only be populated with gaps already thought of, and a gap thought of can be stated as a claim with verdict "not checked" instead
  - Verdict: rejected - folded into claim verdicts, see below
- LA2 Mode label gives the compliance script a discriminator
  - For: trivially parseable, cheap
  - Against: only if modes differ in obligations, which rule 1 forbids
  - Verdict: holds, but buys less than it first appeared
```

### 4. Rejected: a standalone "not checked" section

Recorded rather than deleted, because it will be proposed again.

Draft 1 carried a `Not checked` section listing what went unexamined. The
operator's objection was that it duplicates the `Looked for it` line in the
claims sections. **The objection is correct and the section is gone.**

The argument that killed it: a standalone section can only ever be populated
with gaps that were already thought of - and any gap thought of can be written
as a claim with verdict `not checked`, where it sits next to its evidence and
its falsifier. A section that exists to catch what was not thought of will be
filled only with what was thought of, so it is structurally self-defeating.

What replaces it, and does the job better:

- `not checked` is a first-class verdict on any premise or claim.
- `Evidence for` and `Evidence against` are separate, so an empty side is
  visible rather than averaged away.
- `Looked for it: no` states the absence next to the specific claim it applies
  to, rather than in a list at a distance from it.

The execution block keeps `Not done, not checked`, which is **not** the same
thing: it covers tasks that were asked for and not completed, which are not
claims and have no other home.

### 5. Decisions and clarifications

Repeats per item. **No cap** - the count is set by the work, not by a number
chosen in advance. Truncating this list hides a question rather than answering
it. The header's `Needs from you` line carries the triage signal instead, which
is why that line matters more once the cap is gone.

Ambiguity in the request lands here as a clarification rather than needing its
own section.

```markdown
## Decisions and clarifications
- DC1 Should the compliance script fail a turn, or only report it?
  - Use case: this decides whether a failing check blocks the reply or just annotates it, which changes what you do when it fires
  - Options:
    - a. Report only - annotation in Evidence, reply posts regardless
    - b. Fail loudly - reply carries a visible FAILED banner
  - Recommendation: (b), because a quiet annotation is skippable and the whole point is that degradation should be loud
  - Would change my answer: if false positives turn out common, a banner becomes noise and trains you to ignore it
```

The use-case line is what makes the question answerable without domain
knowledge. It is the fix for the problem that an inventory of what the operator
knows cannot be built.

**A `DC` item carries no `Q` line.** The item *is* the question - that is what
the prefix means. Adding a `Q<n>` underneath restates it in fewer words and
invites the operator to answer the thinner copy.

`Q` exists for a question raised by an item that is **not** a decision - a
premise, a claim, a came-up, a next step. Those have their own subject and the
question has to be attached to them explicitly. A decision needs no such
attachment because it has no other subject.

**A `DC` item that only points at a question asked elsewhere must not be
written at all.** Same turn, same ruling: a `DC1` reading "`Q1` is attached to
`P6` above" carries nothing. The question is already where its evidence is,
which is correct; the `DC` entry adds a second place to look and no content.
This is the mirror of "a pointer to a question is not a question" in rule 10 -
there the pointer stood in for the question, here it stands beside it, and both
cost the reader a lookup that returns nothing. Where a question is attached to
the item that raised it, that is the whole record of it. Do not index it.

### 6. Recommendations

Things suggested that need no decision now.

```markdown
## Recommendations
- R1 Run the falsification test before writing the script
  - Reasoning: it is the difference between a control and a ritual
  - Evidence: none - this is judgement
```

---

## Execution block

### 1. Asked, done, result

Repeats per task.

```markdown
## Asked, done, result
- A1 Fix proj-36, the auditor terminal contradiction
  - Done: replaced the Terminal use section with No terminal; rendered to all seven repos
  - How: sync.py --write per target, then git commit with a Refs trailer
  - Result: confirmed present in every repo
  - Evidence: <pasted per-repo check>
  - Autonomy: proceeded without asking - the defect and the fix were both objectively checkable and required no invention
```

**`How` is not optional and it is not decoration.** Where a skill, script or
documented procedure exists for the thing being done, name the one that was
used. Where none was used, say so and say why.

This exists because the estate has spent real effort converging work onto
enforced paths - a sanctioned ticket tool for issues, `sync.py` for rendering,
a deploy script for production - and the whole value of that convergence
evaporates silently if something hand-rolls the same operation. A hand-rolled
`gh` call and the script produce the same visible outcome and a different
amount of guarantee. Naming the method is what makes the difference legible
without reading the transcript.

```markdown
  - How: ad hoc API call - the ticket tool has no status operation, which is the subject of a filed issue
```

That line is a finding, not an apology. An ad-hoc path named out loud is how
the gap gets a ticket instead of becoming habit.

The autonomy line makes the conditional-autonomy rule auditable. It currently
gets applied silently, which means a wrong call is invisible.

### 2. Premises acted on

**Execution mode keeps premise-checking.** Execution is where instructions
carry facts, and acting on a wrong fact produces the wrong thing built
correctly - the characteristic execution failure.

```markdown
## Premises acted on
- P1 "the alerting ticket is proj-35" [factual]
  - Verdict: confirmed
  - Evidence for: `gh issue view 35` -> title matches the alerting subject
  - Evidence against: none found
  - Looked for it: yes, before commenting
- P2 "this work is refinement, no ticket needed" [ruling]
  - Consistent with: documents plan, tickets track - work with no end state has no exit criterion
  - In tension with: nothing in force
```

**The `[factual]` / `[ruling]` tag is required here exactly as it is in the
planning block.** This section was previously shown without it, and the
consequence was not cosmetic: the ruling exemption keys off the tag, so an
untagged ruling acted on during execution was graded as a factual claim and
failed on evidence it cannot have. Three findings, all describing the grader
rather than the reply. Observed in the turn that recorded this rule.

A recurring finding that is always wrong is how a guard gets removed for
working, which is the failure this document names two sections above.

**Required whenever the execution block is present, and the check is right to
demand it.** It was briefly dropped because it kept appearing as a finding; the
finding was correct and the section was simply not being written. A guard that
gets removed because it keeps firing is a guard removed for working.

If a turn genuinely relied on no fact from the operator, say so in one line
rather than omitting the section - "none, the instruction carried no facts to
check" and the absence of checking are different states and must not look
alike.

### 3. Not done, not checked

```markdown
## Not done, not checked
- ND1 The compliance script - blocked on the shape ruling
- ND2 Whether the rendered auditor file parses as a valid agent - not tested
```

### 4. Came up while doing it

Repeats, maximum three.

```markdown
## Came up while doing it
- CU1 The auditor has the same fake-capability defect as the verifier
  - Why it needs you: deciding whether to grant execution or delete the instruction changes what the agent can be used for
  - If ignored: the agent keeps describing checks it cannot perform
```

### 5. Recommended next

```markdown
## Recommended next
- R1 proj-37, the undocumented --ready flag
  - Reasoning: small, unblocked, and the only remaining ticket in this repository before the next one's queue
  - Evidence: none - ordering judgement
```

---

## Mixed

Planning block in full. Horizontal rule. Execution block in full. No
interleaving - the reader should be able to stop at the rule and have a
complete thought.

Each block keeps its own `Decisions and clarifications` and its own
recommendations list. **The blocks stack; they do not merge.**

### Rejected: one shared decisions section at the bottom of a mixed turn

Recorded rather than deleted, because the argument for it is a good one and it
will be proposed again.

It was ruled in once and retracted the same day, on this objection:

> mixed is literally stacking one on top the other trying to change that makes
> compliance harder to validate

The case for merging was real: everything the operator has to act on ends up in
one place, and a mixed turn with two decision sections makes them check both
before knowing what is being asked. The case against is stronger. `Mixed` is
defined as two complete blocks stacked, and a section that belongs to neither
block has no owner - a checker cannot tell whether a missing planning decision
is absent or has been folded downward, so the section stops being verifiable at
exactly the point it matters. A shape that is harder to check is worse than a
shape that is slightly harder to read, because the reading problem is visible
and the checking problem is not.

The reading problem it was trying to solve is real and stays unsolved. The
header's `Needs from you` line is the mitigation: it carries the total count
across both blocks, so nothing is discovered only by reading to the end.

---

## Compliance: a look back, not a footer

**The check runs first thing in a turn, against the previous reply, and its
output shapes the reply being written.**

It has been in two wrong places already. As a header item it described intent,
because the body did not exist yet. As an end-of-turn footer it described
finished text correctly - and was **completely non-actionable**, arriving after
everything it graded had already been read and often already acted on. A
verdict the reader cannot do anything with is decoration.

Running it at the front makes every finding into work:

- A claim graded as having no evidence gets the evidence, or gets retracted.
- Something approved on the strength of a claim that turns out unsupported is
  **halted rather than continued**, and the approval is re-sought.
- A question answered against a wrong premise is re-asked with the premise
  corrected.
- A missing section is filled in this reply rather than noted as absent in the
  last one.

The verdict is reported near the top of the new reply, with the terminal call
that produced it immediately visible. **The terminal call is the link.** Nothing
is pasted, transcribed, or written to a file and copied back - VS Code renders
that block from the actual process, so it cannot be authored, shortened or
softened.

```
Compliance (previous reply): FAIL - 2 findings, both addressed below
```

A reply with no compliance line did not run the check. That absence is the
signal.

**The compliance section carries two results, and shows both.** (Operator ruling
2026-11-13.) The condensed reply no longer prints premises, claims or
evidence; they go to a ledger file the check also reads. So the section reports
the chat reply and the file separately - the reply's result with its findings,
then the file's result:

```
Compliance (previous reply): PASS
Ledger file: not checked - no ledger exists yet
```

Either line dropping out of the section is the signal, as an absent compliance
line is. The checker prints the second line itself, after `Compliance:`, and
reads `not checked` rather than `PASS` until the ledger is built: an unchecked
file must never read as a passing one.

### Four verdicts, and one of them is only ever the result of a failed attempt

The compliance line is mandatory and says exactly one of these:

| Verdict | Means |
|---|---|
| `PASS` | The script ran and the previous reply is well-formed. Never that it is correct |
| `FAIL` | The script ran and found findings. They are addressed in this reply, not noted for later |
| `NOT APPLICABLE` | The previous reply was `/prime` or `/sitrep` output, **or there is no previous reply** because this is the first of the session, **or the slice was cut short** by a message sent mid-turn, so it is narration from a turn that carried on. A completed run, not a skip - the script prints which case it found |
| `UNAVAILABLE` | The script is not in this workspace |

**The first reply of a session still runs the check.** It is not exempt by
reasoning. Added after a first reply in a workspace with no script
wrote "no previous assistant reply, and the script is not present, so the
verdict would be `UNAVAILABLE` regardless" - two predictions and no attempt.
The script now distinguishes the two ways of finding nothing to grade:

- **No earlier turn in the transcript** - `NOT APPLICABLE`, exit 4. Correct and
  expected on a first reply. In Cursor the first reply finds no transcript at all,
  because Cursor writes one when a turn ends. That reads as a first reply only for
  an id from `CURSOR_CONVERSATION_ID`, where this workspace's transcript folder
  already holds other chats; anything else stays `UNKNOWN`.
- **An earlier turn that produced no text** - `UNKNOWN`, exit 3. A turn was
  interrupted before it replied. Not a pass, and worth saying so, but nothing
  was skipped either: that reply does not exist to grade.

Both once printed the same `UNKNOWN`, so a first reply and a
broken session looked alike.

**`UNAVAILABLE` is legitimate only as the output of a run that was actually
attempted, with the failing command visible exactly as a pass shows its
command.** Never "there is no script here, so I skipped it" - that is a claim
about the workspace made without looking, and it is the shape of excuse that
spreads. Predicting the absence and observing it are different acts and must
not produce the same line.

This is what keeps the check from quietly lapsing where it does exist. The
script is rendered into every repo in the manifest, so in this estate
`UNAVAILABLE` is **impossible by construction**. Seeing it in a personal repo is
not permission to continue - it is a defect report, meaning either the render
broke or the repo is behind on rules, and both are worth stopping for.

Outside the estate - a repository the rules do not render into, a bare
checkout - `UNAVAILABLE` is the correct and only answer, and the shape is
self-enforced from there. The
obligations do not change. Nothing in this document is conditional on the script
existing; the script only tells you when you failed to meet them.

### One run, and what it grades

**Look-back runs up to three times per turn.** The two-run cap belonged to the
write-check-fix loop that the reframe removed. The text being graded is already
posted, so a re-run cannot revise it; the cap of three is there so a re-run after
a fix, or to see the result again, is not refused (it was one, and kept
refusing a check the operator wanted - ruling 2026-11-13). The in-flight
mode keeps its cap of two for the rare case where it is used at all.

**Grading starts at the header block and covers the whole reply from there** -
every message block of the previous turn, including anything written after a
tool call, because a trailing block is still something the operator read and can
still contain an unsupported claim.

**What counts as the reply depends on the tool**, so each tool has its own
adapter under `.github/scripts/responses/` beside a shared shape core.
Copilot writes a reply as message blocks, and all of them are
graded. Cursor writes a turn as one stream of progress notes between tool calls,
ending in the reply, so its **last text block** is graded. A turn a background
task opens in Cursor is graded like any other. It owes no recap of the reply
before it, but its reply is one the operator reads and often answers, so it
carries the shape. An earlier version of this paragraph exempted those turns, and the look-back then graded
nothing, or an older reply, for full replies written in them. Cursor also writes a
turn to its transcript only when it ends, so in-flight mode is refused there.

Claude Code writes each content block to its transcript as it is produced, so
in-flight mode works there. A turn opens at an operator prompt, or at a background
task's notification, which is graded like any other turn; tool results, attachments
and a message sent mid-turn stay inside the current turn. The reply is the turn's
text from the line `=== REPLY STARTS HERE ===` (the adapter's `REPLY_MARKER`) to the
end of the turn, across text blocks. A turn with no marker line is graded on its
text after its last tool call, with one extra finding, `reply marker missing`. A
turn with no `end_turn` text was interrupted or is still being written, and the
look-back skips it.

**A Cursor transcript can lag the turn that reads it.** The check always runs
inside a turn that has started, so the file should end at that turn's message. If
any `turn_ended` record follows the last message - the last record, or one before
an aborted turn's orphan assistant record - reading it would take the
previous turn for this one: grade the reply two back, or count the previous turn's
run as this turn's and refuse. The script re-reads for up to five seconds, then
prints `BEHIND`, exit 3, records no run, and asks for a re-run. Added after a
look-back refused a turn's only run.

**Anything before the header is not graded.** A lead-in sentence ahead of a tool
call is not shaped, so checking it would invent failures against a section
structure it was never meant to have.

**Run it as `python .github/scripts/responses/check_response.py --previous`
from the repository root.** It works out which tool is running from a marker
only that tool sets, and refuses rather than guessing when it finds none or
several; `--tool` overrides. In Claude Code the marker is `CLAUDECODE=1`, and
that is the whole command: `CLAUDE_CODE_SESSION_ID` is the transcript's name, found
at `~/.claude/projects/<project folder>/<session id>.jsonl` (`--session` overrides
it). In Cursor that is the whole command:
`CURSOR_CONVERSATION_ID` is the transcript's name. In Copilot add
`--session <id>`, where `<id>` is the last path segment of the
`VSCODE_TARGET_SESSION_LOG` template variable every Copilot session is handed -
`.../debug-logs/acc1384d-...` gives `acc1384d-...` - and it is the transcript's
filename. The script is rendered into every repo in the manifest, so the path is
correct wherever you are.

**Without a session identity the script refuses with `UNKNOWN`** - in Copilot
`--session` or `--nonce`, in Cursor `CURSOR_CONVERSATION_ID`, in Claude Code
`CLAUDE_CODE_SESSION_ID`. A session id found in two project folders is refused
too. It used to
grade the newest transcript across every workspace, which is whichever session
wrote last. Once, a parallel session in the same workspace graded a
session's reply in another workspace instead of its own, and reported the result
as its own verdict. A guess that is usually right is the defect,
not the fallback.

- **`--nonce <token>`** is for a tool that supplies no session id. Put a fresh
  token in the command; the script finds the one recent transcript that recorded
  it. A token found in two transcripts identifies nothing and is refused.
- **`--transcript <path>`** is for test fixtures only.
- Every run prints `transcript: <workspace>/<session>.jsonl` first. A verdict that
  does not say what it graded cannot be checked.

**An interrupted or checkpoint-abandoned turn is skipped, not graded.** It has no
reply, and any run of the checker inside it was never seen, so it neither counts as
grading the reply before it nor stops the arrears walk. A restore once
left exactly such a turn, the walk stopped on it, and the look-back returned
`UNKNOWN` for a reply that existed.

In Cursor, the turn's first `turn_ended` record decides whether it was
interrupted: any status other than `success` means it was. The first, because a
finished turn is often followed by a stray abort record, and an aborted one by an
orphan assistant record whose text is narration.

There is a near-miss file beside the transcript. VS Code also writes
`*/GitHub.copilot-chat/debug-logs/<session-id>/main.jsonl` - the directory the
session id comes from - which holds a `session_start` record and no replies. Pass
the **id**, never that file's path. Pointed at it via `--transcript`, the script
returns `UNKNOWN: no reply text found to grade`, which is indistinguishable from a
genuinely empty session. Verified 2026-09-24: that mistake produced a reported
finding that the transcript process was dead, while the real transcript was
213 KB and grading fine.

### Session starters are outside the shape, and say so in their first line

`/prime` and `/sitrep` produce fixed-format reports. Neither carries a shape
header and neither should - `prime.prompt.md` bars a preamble and a closing
line, and `sitrep.prompt.md` fixes its section order. Graded as ordinary
replies they fail on three header findings that are artifacts of the grader,
not defects in the report.

**A prime or sitrep turn does not run the check.** They are session starters. Prime opens a session, so there is nothing before it
to grade; sitrep normally runs directly after prime, so the only thing before it
is a prime report. Not applicable, rather than skipped. The distinction matters
because a skip is a decision and this is not one.

**The turn after one of them does run the check**, and needs to know what it is
looking at. Each report therefore opens with one plain-text line:

```
Results from Prime
Results from Sitrep
```

That string is the whole mechanism. `check_response.py` matches it on the first
non-empty line of the graded text and returns a specific result naming the
command:

```
NOT APPLICABLE: previous reply was Sitrep output - a fixed-format report that
carries no shape header by design. Nothing to grade.
This is a completed run, not a skip. The next reply is graded normally.
```

**It is neither a pass nor a fail, and it has its own exit code.** A pass would
be a healthy reading of text that was never examined, which is the defect this
estate treats as the serious one. A fail would train the operator to discount
fails. It is a run with valid output that lets the agent neither skip nor
take a wrong pass or fail.

The marker line is in the report rather than inferred from the transcript
because the transcript cannot carry it. Verified 2026-09-23: when `/prime` opens
a session its `user.message` record is never written - a session with two user
turns recorded exactly one, and the file begins `session.start` followed
directly by `assistant.message`. Any detector reading the previous user message
would work for sitrep and fail silently for prime.

**Consequence, and it is now covered:** running `/sitrep` in the middle of a
session leaves the ordinary reply before it ungraded *at the time*. The arrears
walk below collects it on the next run, so the reply is graded late rather than
never. This paragraph said the opposite when the exemption was written an hour
earlier, before the arrears rule existed.

### A skipped check is collected by the next run

When a look-back check is skipped, the next run grades it as well as the most
recent reply.

A skip is invisible from the turn that skipped it - there is no later moment at
which that reply gets looked at, so it simply never happens. The run now walks
backwards and grades **the previous reply plus every earlier reply whose turn
never invoked the check**, stopping at the first reply that was graded.

This is mechanical, not honour-based. Reply *j* is graded during turn *j+1*, and
tool invocations are recorded in the transcript with their full command text, so
whether a turn ran the check is directly readable. A command that was recorded but
never ran - denied, rejected, cancelled - graded nothing, so in Cursor a past turn
counts as having run the check only if the run ledger saw it deliver a verdict.
Turns older than the ledger's first entry, or any turn when the ledger is unreadable,
fall back to the command text.
**Skipping therefore defers
the finding rather than escaping it** - which is the point. It does not make the
run compulsory; nothing available here can. It makes skipping pointless.

Each reply is reported under its own label, with the arrears named in the first
line:

```
run 1 of 3 | grading 2 reply(s), 1 in arrears - their turn never ran the check

previous reply: mode=execution | shape=full | 113 chars | 1 sections
Compliance: FAIL - 1 finding(s)
  - section missing for execution mode: premisesactedon

1 turn(s) back, UNGRADED: mode=execution | shape=full | 96 chars | 1 sections
Compliance: FAIL - 2 finding(s)
  - header: 'Changed' line missing
  - section missing for execution mode: premisesactedon
```

**The walk is capped at five replies** and says so when it stops there, because
the alternative is that the first run of a long ungraded session grades all of
it. A truncated walk states that the replies beyond the cap are not covered and
will not be collected later - an arrears mechanism that quietly forgets is worse
than one that never existed.

The cap was chosen by the assistant rather than ruled. The response to it:

> if you start skipping the check that many times in a row its a good indicator
> your context has become corrupt and start a new chat

So **hitting the cap is a signal about the session, not a limit to work around.**
Five consecutive turns that each declined to run a one-command check is not a
scheduling accident; it is the same degradation the shape exists to catch,
showing up in the behaviour rather than in the text. The response is a new
session, not a higher cap.

### A FAIL is the point, not a problem

A fail is acceptable: it shows the failures, how they bear on the answers the
operator just gave, and lets behaviour change accordingly. That keeps it
actionable rather than informational.

An earlier proposal had a FAIL interrupt the reply - stop everything, re-seek
approval. That was rejected and the rejection is the better call: an interrupt
halts the work, where this redirects it. The findings arrive before the next
reply is written, so they change what gets written rather than describing what
already was.

### Why this works at all

Verified 2026-09-22: **the transcript is flushed live, mid-turn.** A marker
string written into a reply was already on disk when a terminal call three lines
later went looking for it, with the file's modification time equal to the clock.

So the check needs nothing handed to it. The reply hands itself over by being
written. The script reads the current `messageId`, joins its fragments, and
checks the text that is already in front of the reader.

### How it fails, and the only thing that prevents it

**Observed twice: the check did not run, because the reply ended
first.**

Nothing forces a turn to continue after a block of text. A reply that reads as
finished invites stopping, and a long, complete, well-shaped reply reads as
finished more strongly than a short one. Ending on a sentence that *announces*
the check - "running it now" - is the worst case: it is a natural full stop
wearing the costume of an action.

The rule that follows, and it is the whole mitigation:

- **Never announce a tool call in prose. Call it.**
- **The compliance run is the first thing in the turn, before any of the reply is
  written.** Its findings shape what follows. A run that happens later has
  nothing left to change.
- **The run is never skipped, and a reason for skipping it is a factual claim.**
  One reply skipped the check and said it was at its run limit. It
  had not run at all that turn. A false claim used to justify skipping the one
  control is the defect this document exists for, arriving in its own enforcement.

This is honour-based in a way the run cap is not, and nothing enforces it yet -
no hook runs the check, though Cursor runs project hooks. What it has
instead is that **it fails visibly**: a reply with no compliance line did not
run the check, and that absence is obvious at a glance.

Two consequences:

- The checked text **cannot be retracted.** Whatever the script read is already
  posted.
- Anything written after the check runs is unchecked, including the verdict line
  itself. That is correct - a checker that graded its own output would be the
  self-certifying problem this whole document exists to avoid.

### Three runs in look-back, two in the vestigial in-flight mode

With the move to look-back, the old run count no longer applies: the check
grades the previous reply only, and may run up to three times per turn.

**Look-back runs up to three times.** The text being graded is already posted,
so a re-run cannot start a check-and-revise loop; the write-check-fix loop that
needed two runs is gone. One run per turn was the first cut and kept refusing
a re-run that was legitimate (`PREVIOUS_RUN_LIMIT` in `check_response.py`).

**A run that produced no verdict does not count.** An `UNKNOWN` used to spend
the turn's one run, so fixing its cause and re-running was refused and the turn
ended ungraded. The transcript records every run as a success whatever its exit
code, so the script keeps its own per-turn tally of verdictless runs in the
temp directory and subtracts it. An unreadable tally counts as zero, which
restores the old limit rather than widening it.

**In look-back, a run counts only once its verdict has reached a terminal.**
Three successful runs per turn; a run that errors or is cancelled may be re-run to
complete and does not count.

A reply that day piped the check through `Select-Object -First 4`, cut off the
verdict line, and could not re-run. So each look-back run records `started` in
its temp-directory ledger, and `delivered` only after its verdict was printed
with stdout on a terminal. A crash, a cancellation, an `UNKNOWN`, or piped or
captured output leaves a start with no delivery, and the re-run is free. An
unreadable ledger falls back to counting every run. The in-flight mode keeps
the verdictless tally above, because a free re-run there would reopen the
check-and-revise loop that its cap exists to stop.

The earlier two-run cap came from a different ruling under the footer design:

> 2 runs max. if second fails it has to be written regardless.

Its reasoning still holds wherever a check-and-revise loop exists - an uncapped
loop burns tokens grinding toward a passing shape instead of shipping something
the operator can react to, and **a visible FAIL is more useful than an expensive
PASS.** The in-flight mode retains it. That mode is vestigial; nothing currently
calls for it.

**The cap enforces itself.** Tool invocations are recorded in the transcript
with their full command text, so the script counts its own prior runs since the
last user message and refuses another. This is mechanical rather than
honour-based, which matters because the party expected to stop is the party
whose self-restraint is the subject of this ticket.

**PASS therefore means "passes now", not "passed first time."** That is
deliberate. A reply that corrected itself before the operator read it is the
outcome wanted, and counting attempts would add a number that invites
over-reading.

---

## What a script can and cannot check

Mechanically decidable:

- Header present, mode declared, counts in the header match the blocks
- Required sections present for the declared mode, including `Logic and
  approach` on every planning turn
- Came-up and next-step counts against caps (decisions are uncapped)
- `Evidence for` and `Evidence against` both present on every claim and premise
- **A claim with a verdict other than `not checked` and an empty `Evidence for`**
  - the single highest-value mechanical check in the shape
- `Evidence for` containing a fenced block or a `path:line` where the verdict is
  `confirmed`
- Every claim carrying a falsification line and a `Looked for it` line
- Every decision item carrying a use-case line, and exactly one `(recommended)` option
- Every premise tagged `[factual]` or `[ruling]`
- In the condensed shape: Summary, Recommended next and Came up present; the Summary
  one paragraph with at least one pointer, or exactly `None this turn.`; the two
  closing sections holding an item or `None.`

**Not decidable, and the script must say so in its own output:**

- Whether a reply proposes a state change the operator has not approved, and so owes
  the full shape
- Whether each result in the Summary has its own pointer

- Whether evidence actually supports the claim it sits under
- Whether a stated verdict is correct
- Whether the falsifier named is the *strong* one or a convenient weak one
- Whether a use case is real
- Whether reasoning is sound

Roughly sixty percent of the shape is verifiable. A passing check means the
reply is *well-formed*, never that it is *right*, and any output implying
otherwise is the healthy-reading failure this estate treats as a defect.
