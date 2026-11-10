---
id: estate
tier: 1
scope: "*"
alwaysApply: true
description: >-
  What each repository in this profile is for. Purpose only - never where
  something runs or what it currently contains; those change, purpose does not.
---

# Estate

Rendered only into targets with `estate: true`. Replace the table with your own
repositories.

## What each repo is for

| Repo | Purpose |
|---|---|
| `example-app` | The application this profile exists to support |
| `example-scratch` | Experiments that may be thrown away |
| `example-profile` | This profile: renders the rules into every other repo, itself included |

If a repository is open that is not listed above, say so before proceeding
rather than inferring its purpose.

## Referring to an issue

Use `<key>-<number>`, with the keys from `profile.yaml`.

<!-- KEYS -->

A repo with no key uses its own name. Bare numbers are ambiguous across repos.
