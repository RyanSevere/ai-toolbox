---
name: spec-gate
description: >-
  Check a spec - a ticket body or a factory SPEC.md - against the spec format
  before anyone builds from it, and refuse it naming every rule it breaks.
  Use when the user says any of: "is this ready for an agent", "mark it ready for an
  agent", "check the spec", "gate this spec", "will the factory take this", "write a
  SPEC.md", or before marking any ticket ready for an agent to build. Also use when
  writing or reviewing a factory subject's SPEC.md, and when a factory
  tests night refuses a spec.
argument-hint: the ticket or the SPEC.md path
sessions: [interactive, factory]
---

# Gating a spec

A spec is what a coder - often a small model - builds from without asking. Anything it
leaves open gets decided by whoever reads it, and a small model decides by guessing.
This skill holds one format for both kinds of spec, and a checker that refuses a spec
not in it.

**The checker checks shape, not sense.** "Boundary values: N/A: none" passes it. It
makes a vague spec more expensive to write, never impossible. Passing it is the floor
for calling a spec ready, not the bar.

## The format

Required sections, as `##` headings, each once:

| Section | Holds |
|---|---|
| **Severity** | Tickets only. The first line: a level and why |
| `## Problem` | What is wrong or missing, with at least one `path:line` |
| `## Decided` | The design, ruled. Nothing here is open. `## Fix` is accepted instead |
| `## Touches` | Every file the change edits or adds, with its functions and one line on the change. Nothing outside it may change. There is at least one top-level bullet, and each starts with exactly one backticked path, then prose: ``- `report.py`: `count`, raises on a failed lookup`` |
| `## Edge cases` | One line per category below |
| `## Done when` | Each item an outcome with `Checked by:` and the test or gate that proves it |
| `## Verify` | Which tests fail before the change and pass after it |
| `## Verification class` | Exactly `gated` or `needs-live-host` |
| `## Escalate when` | The condition on which the coder stops and asks rather than guessing |
| `## Out of scope` | The non-goals |
| `## Open questions` | Exactly `None.` |
| **Found** | Tickets only. A date and where. The note leads with the date - `**Found:** 2026-11-08, ...` or `**Found** 2026-11-08, ...` - and closes the body; a line that only starts with the word "Found" is section content and is checked |

Other sections - `## Steps`, `## Design` - are allowed and not checked.

Ticket mode is a body convention, not a tracker feature: it adds two required parts to
the format above, a **Severity** first line and a dated **Found** note. The checker
takes the mode as `--mode ticket` or `--mode spec`, and never guesses it from the body.

The edge-case categories, each a case with its expected result, or `N/A:` and why:

```markdown
- Empty or missing: ...
- Boundary values: ...
- Malformed or wrong type: ...
- A failed dependency or lookup: ...    (never reads as a healthy result)
- Duplicates and ordering: ...
- State across runs: ...
```

## Running it

`spec_gate.py` sits beside this file and needs only the standard library.

```powershell
python <this skill's folder>/spec_gate.py --mode ticket scratch/body-123.md
python <this skill's folder>/spec_gate.py --mode spec SPEC.md
```

| Exit | Means |
|---|---|
| 0 | Passed |
| 1 | Refused. One `refused: <rule>: <detail>` line per broken rule, all of them |
| 2 | Could not check - the file is missing, unreadable or not UTF-8. **Never a pass** |

The rules: `missing-section`, `duplicate-section`, `empty-section`, `placeholder`
(`TBD`, `TODO`, a bare `?` or `...`, outside backticks), `problem-pointer`,
`touches-format` (a top-level `## Touches` bullet that does not start with exactly one
backticked path, or a section with no top-level bullet at all), `done-when-unchecked`, `edge-case-missing`, `edge-case-no-reason`,
`verification-class`, `open-questions`, and in ticket mode `severity` and `found`.

## Before marking a ticket ready for an agent

1. Write the body to `scratch/` and run the checker on it in ticket mode.
2. Fix every refusal in the body. Do not argue with the checker in a comment - if a
   rule is wrong for this ticket, say so to the operator and stop.
3. Write the body through the profile's ticket-edit operation, read it back, and only
   then apply the profile's readiness label. A `gated` spec is ready for an agent. A
   `needs-live-host` spec is not: the factory's best output for it is a pull request
   plus a command list for the operator.

A ticket marked ready before this skill existed is not grandfathered while it is open:
run it, and fix the body before it is picked up.

## In the factory

The harness runs the rendered copy on a subject's `SPEC.md` in spec mode before a tests
night starts, and treats exit 1 and exit 2 alike as a refusal. A role
does not run it.

## Failure modes

- **Passing a hollow spec.** Every section present, every line saying nothing. The
  checker cannot see this; reading the spec as the coder would is the only check.
- **Treating exit 2 as "nothing wrong".** It means the checker never saw the spec.
- **Editing the spec to satisfy the checker by deleting content.** An `N/A:` with a
  reason that does not hold is worse than the refusal it silenced.
