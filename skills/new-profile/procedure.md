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
2. Draft the answers. You may research and draft every answer except identity: the source
   repository, key and owner, the leak-gate lists, and the capability questions (a
   tracker's fields, statuses and access, for example). **Identity is the operator's.** The
   operator always types the commit name and email; never draft, guess or copy them from
   git config into a file.
3. Show each draft answer to the operator with its source (the page, file or command you
   took it from, or "no source: your decision"). Change a draft until the operator
   confirms it. Setup refuses an example value left in place, so never leave one.
4. Write the confirmed answers to a file with no `identity:` key, then run `init` with
   `--answers <file>`. `init` asks identity at the console, then asks for the target
   repositories as folder names beside the profile, then asks the operator to lock the
   push gates. The lock is the operator's consent: never type it for them.
5. `init` then commits the profile, renders it into itself and commits the render. It never
   pushes. Stop when it prints `git push -u origin main`, and leave the push to the
   operator. Without `--answers`, the operator answers setup's questions at the console
   instead. `--setup-only` stops after setup and prints the remaining steps.

---

## Failure modes

- `init` refuses and changes nothing when `core/` or `profile.yaml` already exists or the
  folder is not a git work tree. Do not delete files to get past it; say what it found.
