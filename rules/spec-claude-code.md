---
id: claude-code
tier: 2
scope: "*"
alwaysApply: true
tools: [claude]
description: >-
  Claude Code working practices - what applies only in a Claude Code session: the
  reply marker, the UI that is not used, the workspace, the main session and its
  subagents, commits, and settings files. Rendered to Claude Code only, and resident
  in every session, so it stays short.
---

# Claude Code

Applies only in Claude Code. The shared rules cover everything else.

## Reply layout

- One final shaped reply per turn. Open it with this line, alone on its own line:

```
=== REPLY STARTS HERE ===
```

- Everything before the marker is progress. Between tool calls, a progress note is one line.
- The Stop hook and the response check read from the last marker line. A reply with no marker is graded whole and flagged.

## Only what is mirrored remotely

If a UI is not mirrored in the remote session, do not use it.

- The desktop app's next-step question box is not used. Its turn wrap-up carries a recap only.
- A question the operator may answer later goes to the profile's async channel, not to a prompt that waits in one session.

## Workspace

- One workspace per session, opened in the repository the session mostly writes to.
- A step that reads or writes outside it raises a prompt. Name the step before the turn reaches it, and run those steps last.

## Main session and subagents

- The main session designs, decides, drafts for review and verifies.
- Subagents execute settled plans. Each brief carries the files, the commands and the done-checks.
- A worker never pushes and never opens a pull request, and it leaves no background process running.

## Commits

- No `Co-Authored-By` or any other identity trailer. The commit identity gate refuses them.

## Settings

- The user-level `~/.claude/settings.json` is the operator's to write. The auto-mode classifier refuses an agent's write to it.
- The classifier refuses a force push too. A branch that needs a rewrite goes up as a new branch and a new pull request.
