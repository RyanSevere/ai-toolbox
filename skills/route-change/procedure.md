---
name: route-change
description: >-
  Decide whether a change to rule source belongs in the core or in a profile, name
  the repository and the reason in one line before anything is written, and audit a
  profile's seeds for items that read as core. Use when the user says any of: "is
  this core or profile", "where does this change go", "does this go to ai-toolbox",
  "audit the profile for core items", or before any edit to rule source - rules,
  specs, agents, skills, hooks, context - in either repository.
argument-hint: the change in one sentence, or "audit" and the profile
---

# Routing a change to the core or a profile

Every change to rule source lands in the core or in a profile. The line between
them is "The boundary" in the core's `DECISIONS.md` (ai-toolbox), with its
three-step test and worked cases. This skill applies that test and carries only its
own steps. It keeps no state.

## Route a change

1. **Say what the change is** in one sentence, and which files it would touch.
2. **Not rule source?** A change that touches no rule source, such as a typo in a
   README, gets the verdict `not routed: no rule source`. Write nothing more.
3. **Apply the test in "The boundary", in its order.** The first step that matches
   decides, so one change gets one verdict. Do not add a rule of your own. If the
   change fits none of the steps cleanly, or fits two, stop and report it.
4. **A change that is mostly mechanism with one profile value splits.** It never
   goes wholly to one side. Name what goes to each.
5. **Give the verdict as one line, before anything is written:**
   `route: core|profile|split - <reason>`
   For a split, the reason names the core part and the profile data.

## After the verdict

- **Profile:** edit the profile.
- **Core:** the work is done in the core and reaches the profile by a vendored
  release. Find the profile's own rule for core work, in its `AGENTS.md` or
  equivalent, and follow it. If you cannot find that rule, say so and stop. Never
  guess where core work goes.
- **Split:** do the core part by the core's route and the data part by the
  profile's route, as separate changes.

## Audit a profile

The audit is output, not a move.

1. Read the profile's `seeds/`, one item at a time.
2. Run the test over each item, in order.
3. Post one line per item that reads as core:
   `<path> - core|split - <reason>`
   Items that route to the profile are not listed.
4. Move nothing. Each move is filed as its own ticket, after the operator has
   reviewed the list.
