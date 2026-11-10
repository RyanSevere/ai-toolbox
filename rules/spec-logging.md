---
id: logging
tier: 2
scope: "*"
alwaysApply: false
description: >-
  Logging SPECIFICATION - structured log format, required fields, and what a log
  line must never contain. Covers the JSON Lines format used for durable logs
  across Python, Node and shell, and the distinction between a durable log and
  terminal chatter. Load when adding logging to anything, or when deciding
  whether an output stream needs to be structured. Binding rules are in
  prescriptions.md.
---

# Logging

Promoted from a single repository, where it was scoped to one repo and one
orchestrator. The format was never specific to that repository; only the
migration plan was.

---

## Durable logs are structured

A **durable** log is one that is written to a file and read later by someone
diagnosing a problem they did not watch happen. Those get structure.

Terminal output a person is watching in real time does not. Do not convert
`echo "starting"` into JSON.

Use `.log` as the extension and **one JSON object per line** - JSON Lines, not
a JSON array. An array cannot be appended to without rewriting it, and cannot
be read by `tail`.

## Required fields

| Field | Always | Why |
|---|---|---|
| `Time` | Yes | ISO 8601 with timezone. A local-time log from a machine in another zone is unreadable |
| `Level` | Yes | `DEBUG` / `INFO` / `WARN` / `ERROR` |
| `Message` | Yes | The human-readable sentence |
| `File`, `Function`, `Line` | From application code | Omit for shell, where they are noise |

Additional fields are free-form. Prefer a field over interpolating a value into
`Message`, because a field can be filtered and a sentence cannot.

## What a log line must never contain

- **A secret, at any level.** Not in `DEBUG`, not "temporarily". This is in
  `prescriptions.md` because it is absolute.
- **A value that reads as healthy when the real answer is unknown.** `0` and
  `null` are not the same as "the lookup failed", and a dashboard cannot tell
  them apart afterwards.

## Per-language

Python and TypeScript have their own conventions on top of this - the
per-module logger pattern and the per-file logging wrapper with feature flags.
Those live in `spec-python` and `spec-typescript`. This file is the format
underneath both.

Shell scripts write durable logs through the repo's logging helper where one
exists. Where none exists, a plain timestamped line is acceptable - structure
matters most where something machine-reads it.

## Migration

Incremental. A repo does not stop working because an old log line is
unstructured.

Apply this to new logging surfaces and to any surface being touched anyway. Do
not open a pull request that only reformats log lines; the diff is large, the
risk is real, and the benefit arrives only when something is being diagnosed.
