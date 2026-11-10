---
id: testing
tier: 2
scope: "*"
alwaysApply: false
description: >-
  Testing SPECIFICATION - test-first for complex work, and why an assistant must
  not edit a test to make its own code pass. Load before implementing anything
  substantial, or when a test is failing and changing the test looks like the
  fix. Binding rules are in prescriptions.md.
---

# Testing

Promoted from a single repository. The token-budget and session-type
material that accompanied it was dropped - see the end of this file.

---

## Tests are written before the implementation, for complex work

Not for everything. For work where "done" is arguable, the test is what makes it
decidable.

Writing the test first forces the requirement to be stated before the solution
exists, which is the only moment it can be stated honestly. Afterwards the test
describes what was built rather than what was wanted, and the two are not
reliably the same thing.

## A test is a contract the assistant may not renegotiate

**Do not edit a test so that your own implementation passes.** This is the rule
the rest of the file exists to support.

When a test fails, exactly one of these is true:

| | Then |
|---|---|
| The implementation is wrong | Fix the implementation |
| The test encodes a genuine design error | **Say so and stop.** Changing it needs the operator's explicit agreement |

There is no third case where quietly adjusting the assertion is correct. An
assistant that can move the goalposts is not being measured by anything.

This applies to deletion and to skipping. Marking a test `skip` to get a green
run is the same act with better manners.

## What to cover

- **Unit** - individual functions, including the boundary values
- **Integration** - the seams, which is where the defects in this estate have
  actually been
- **Failure paths** - null, missing, malformed, and unreachable-dependency

The failure paths matter most here. The recurring defect across this estate is
not a wrong calculation; it is something reporting success while doing nothing,
which only a failure-path test catches.

## Verify the test can fail

A test that has never failed has not been shown to test anything. Before
trusting a new test, make it fail once - break the implementation, or write it
before the implementation exists and watch it go red.

A live example of why: a repository's `npm test` named its test files
explicitly, so a new test file was silently never run. The suite was green and
measuring nothing.

## Provenance: written ahead, or written after

A passing test says nothing about when it was written. One written before the
code encodes intent; one written after, by reading the code, records what the
code already does. Both are legitimate. The second must not read as the first.

`.githooks/lib/provenance.py` makes the difference visible:

- **On every push, reported and never blocking:** the `test-provenance` gate
  flags a commit that edits an existing assertion and changes non-test source in
  the same commit. That is the shape of changing a test to fit the code. It also
  counts tests added, and `Intent:` / `Characterisation:` markers.
- **On demand:** `python .githooks/lib/provenance.py classify --range BASE..HEAD`
  runs the Python tests the range added against the source as it was at `BASE`.
  Passing there means **characterisation**; failing there means **written
  ahead** of the code. Too slow for every push, so it runs when
  asked.

A flagged commit is not a violation. It is the question the section above says
to stop and ask.

## Mark where each test's intent came from

The first line of a test's docstring, or its first comment line if it has no
docstring, names the source:

- `Intent: <source>` - the test encodes something wanted before the code
  existed. The source is an operator quote, a ticket line, or a document line
  with its path.
- `Characterisation: <why>` - the test was picked after reading the code and
  records what the code already does. Say why that behaviour is worth pinning.

The core's own tests are the one exception: their intent comes from the core's
`DECISIONS.md` and the rule text, so they state the wanted behaviour without a
per-test pointer.

The same in Python and TypeScript:

```python
def test_a_baseline_only_shrinks(self):
    """Intent: DECISIONS.md, lint baselines - a baseline only shrinks."""
```

```typescript
it('rejects an empty secret', () => {
  // Intent: prescriptions.md - an empty secret is as dangerous as a missing one.
```

**Every session writes them, not only the test-writer agent.** The provenance
counts above are only as good as how widely the markers are used. A test with
neither marker is not wrong, but it cannot be counted. A characterisation test
without its marker reads as intent, which is the failure this section exists to
prevent.

## What was deliberately not promoted

The source material also specified hard token budgets per session, a taxonomy of
session types, and four numbered rollback levels.

Dropped. The token limits were written against context windows several times
smaller than current ones and were never enforceable by the assistant. The
session taxonomy described a way of working that was not adopted. Git already
provides rollback, and a numbered ceremony around it added nothing.
