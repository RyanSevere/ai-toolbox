---
name: new-profile
description: >-
  Stand up a new profile repository from a released core with toolboxctl init.
  Use when the user says any of: "stand up a new profile", "bootstrap a
  profile", "create a new profile repo", "set up a profile from the core", or
  otherwise wants an empty repository turned into a profile that vendors the
  core.
---

# New profile

The procedure is `docs/runbooks/RUNBOOK-NEW-PROFILE.md`. Follow it step by step; do not
paraphrase it from memory.

---

## Preconditions

- An empty private repository can be created (no README, license or .gitignore: setup
  refuses anything but `.git` and `core`).
- The core repository and a release tag that carries `init` are known.

---

## Steps

1. Read the runbook and run its steps in order, each in the shell and folder it names.
2. `init` asks setup's questions at the console. **The operator answers them**; do not
   invent identity or answers. If the operator supplies an answers file, pass it with
   `--answers`.
3. Stop after the render for the operator to review before the commit and push.

---

## Failure modes

- `init` refuses and changes nothing when `core/` or `profile.yaml` already exists or the
  folder is not a git work tree. Do not delete files to get past it; say what it found.
