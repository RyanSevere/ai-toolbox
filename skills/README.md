# Skills

Skills are **procedures invoked by intent**. Rules are **constraints applied by
scope**. Keep them separate.

| | Rules (`rules/`) | Skills (`skills/`) |
|---|---|---|
| Nature | constraints | procedures |
| Triggered by | file scope, or always | what the user asked for |
| Shape | "always do X" | inputs, steps, outputs |
| Loaded | passively | on match |

---

## Schema

Source files are named `procedure.md` so the source tree stays inert. The renderer
writes them out as `SKILL.md` in the target.

```yaml
---
name: skill-name
description: >-
  What it does. Then the trigger contract: "Use when the user says any of:
  <literal phrases>", or otherwise wants <outcome>.
---
```

Two required keys. `name` matches the directory. **`description` is machine-facing** -
it is the routing interface, not a caption. Write it for the router that has to
decide whether to load this skill, which means naming the literal phrases a
person would actually type.

Body carries the procedure: preconditions, steps, outputs, failure modes.

**`sessions:` is optional** and names the kinds of session the skill is rendered
for, as on an agent seed. Absent, it is `[interactive]`: the skill renders to
`.cursor/skills/`, `.github/skills/` and `.claude/skills/` and nowhere else. A skill that lists
`factory` also renders to `factory/skills/<name>/` on a `factory: true` target,
in factory mode, and reaches a role only if that role's agent seed lists it under
`skills:`. A skill without `interactive` is not rendered for interactive tools at
all. Never under `.agents/skills/`: OpenCode loads that folder even with project
config disabled, so a skill there would reach a headless role.

---

## Composition

Skills may dispatch to other skills. A front-door skill classifies the request
and routes to a specialist rather than handling everything itself. Prefer that
over one skill with six branches.

---

## What belongs here

A procedure that gets re-explained from scratch each time it comes up. If a
sequence of steps has been walked through more than twice, it is skill-shaped.

Not everything is. A skill for something done once is overhead.

---

## Current skills

| Skill | Covers |
|---|---|
| `repo-audit` | Principal-engineer review of a repo, producing filed issues |
| `sync-rules` | Render a profile's rules into a consuming repo |
| `handoff` | Write or pick up the note one session leaves so another can continue the work |
| `spec-gate` | Check an agent-ready ticket or a factory `SPEC.md` against the spec format, refusing every rule it breaks |
| `exchange` | Coordinate chats live in one repository at once through an exchange log, appending through a locked tool so no entry is lost |

A profile documents its own skills in a `README.md` beside their seeds.
