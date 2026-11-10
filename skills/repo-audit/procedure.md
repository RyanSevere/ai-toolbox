---
name: repo-audit
description: >-
  Principal-engineer review of a repository, producing a filed backlog rather
  than a report. Hunts silent false signals and fail-open behaviour rather than
  running a generic quality checklist. Use when the user says any of: "audit
  this repo", "review this codebase", "what's wrong with X", "put your
  principal engineer hat on", "find what's broken", "what should I be worried
  about here", or otherwise wants a considered assessment of a repository's
  real defects. Also use before a repo goes from side project to depended-upon.
---

# Repo audit

Produces GitHub issues. A document nobody actions is not the output.

---

## Set the bar first

The bar differs by what the repo is. Holding a scratch repo to a password
server's standard is how audits become noise nobody acts on.

| State | Bar |
|---|---|
| Deployed, others depend on it | Highest |
| Deployed, sole user | High |
| Early, mostly spec | Foundation only - structure, secrets, config |
| Scratch or reference | Labelling only |

For early repos, explicitly do **not** report missing tests, incomplete
features, TODOs, or absent CI. That is expected and correct at that stage.
Auditing unwritten code is theatre.

---

## What to hunt

The highest-yield category is the **silent false signal**: code that reports
success while doing nothing, or reports nothing while broken.

Proven instances, all found this way:

- A mount declared `:ro` that was read-write because of a stray backslash.
  Compose accepted it, exit 0, no warning.
- A function returning `[]` for auth-failure, HTTP-error and genuinely-empty
  alike, so a dead dashboard rendered identically to an idle one.
- An endpoint that committed a row, failed to send mail, and returned 500
  "Failed to submit request" - reporting failure for work it had done.
- Two files disagreeing about a config path, silently discarding every user
  override.
- A gitignore pattern excluding the directory it was meant to protect, with an
  inactive fix already present and nothing reporting that the fix failed.

Second category: **fail-open**. A missing secret, token, or check resulting in
proceeding rather than aborting.

Third: **can it be restored, and will you know when it breaks.** Untested
backups are hope. Silence from a monitor is ambiguous.

Do not report: no tests, needs more comments, consider type hints, add a
linter. Noise.

---

## Method

1. **Set the bar.** Confirm with the user what the repo is if unclear.
2. **Gather evidence** with a subagent, read-only, with the calibration above
   and an explicit "do not report generic findings" instruction.
3. **Verify every headline claim yourself** before filing. Subagent reports
   routinely contain confident errors. On the last run, a "CRITICAL
   unauthenticated webhook" was a correctly-implemented template with a
   fail-closed guard, and a "stale committed build artifact" was not tracked at
   all. Both would have been embarrassing.
4. **Prove it where provable.** Reproduce the defect in a temp directory rather
   than asserting it. A side-by-side showing `:ro` producing `read_only: true`
   and `:ro\` producing nothing is worth more than any amount of reasoning.
5. **File one issue per defect**, with file:line, the code, why it matters
   operationally, and a proposed fix.
6. **Record dismissals with reasons.** What was checked and found genuinely
   fine matters as much as what was filed. It stops the same thing being
   re-investigated, and it is the only way the audit reads as honest.
7. **Comment rather than contradict.** Where an existing issue disagrees with
   what the code now does, add a comment explaining the divergence. Do not
   silently file a contradicting issue.

---

## Issue quality

- Lead with severity and one line justifying it.
- Evidence before argument. Findings without file:line are useless.
- State what is **not** claimed. "There is no known RCE here; this issue is
  about the consequence of one" prevents an over-reaction.
- Give credit where the code is right. An audit that only lists faults gets
  discounted wholesale.
- Note cross-repo sequencing. Rotating a key before fixing the thing that
  leaks it wastes the rotation.

---

## Outputs

- Filed issues, one per defect
- A verdict table: every finding either FILED or DISMISSED with a reason
- Any cross-repo dependencies between fixes
