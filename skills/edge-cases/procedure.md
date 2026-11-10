---
name: edge-cases
description: >-
  Weigh a spec's edge cases one category at a time, with one small prompt per
  category, so nothing in the spec's Edge cases section is taken on trust. Use
  when writing tests from a spec, and before writing any test for a spec's Edge
  cases section.
sessions: [factory]
---

# Edge cases, one category at a time

A small model asked about every kind of edge case at once weighs none of them well. This
skill splits the question into six prompts, one per category the spec gate checks, and
each is read alone.

## Steps

Take the categories in this order. For each one, read its file beside this one, then
nothing else until it is done:

1. `empty-or-missing.md`
2. `boundary-values.md`
3. `malformed-or-wrong-type.md`
4. `a-failed-dependency-or-lookup.md`
5. `duplicates-and-ordering.md`
6. `state-across-runs.md`

For each category:

- Find the spec's line for it under `## Edge cases`. The spec gate has already checked
  that the line exists.
- Ask the file's questions of the spec and of the code it touches.
- For every case the spec's line names, write a test that pins its expected result.
- If the questions turn up a case the spec's line does not name, or the line says
  `N/A:` with a reason that does not hold, do not test a guess. Name it in the result
  block as a proposed ticket, written as a line in the spec's own form.

## Output

Per category: the tests written, by name, and any case named rather than tested.
