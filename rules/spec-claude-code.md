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
- In the Summary, leave a blank line between topics. Bold is subtle in the terminal, so the gap does the separating.
- The Stop hook and the response check read from the last marker line. A reply with no marker is graded whole and flagged.

## Only what is mirrored remotely

If a UI is not mirrored in the remote session, do not use it.

- The desktop app's next-step question box is not used. Its turn wrap-up carries a recap only.
- A question the operator may answer later goes to the profile's async channel, not to a prompt that waits in one session.

## Workspace

- One workspace per session, opened in the repository the session mostly writes to. Work on the core also holds the profile repository, for its tools and records.
- A step that reads or writes outside it raises a prompt. Name the step before the turn reaches it, and run those steps last.
- With more than one repository in the workspace, a `cd` into any of them carries over to the next call. So every command names its folder (`git -C <path>`, or an explicit change of directory in the same call), and never relies on where the last call left the shell.

## Handing off

- In the desktop app, once the seed is written:
  1. Start the next session with the app's session tool, using the pickup prompt as its prompt and the same workspace folders. The prompt carries this session's id.
  2. The new session detaches itself first, so archiving this one does not archive it. If the app refuses because the operator moved it in the sidebar, it says so, and this session asks the operator before archiving.
  3. When the operator confirms the pickup, the new session messages this session. If the message fails, it tells the operator this one is still open, never that it was archived.
  4. On that message, this session checks with `get_session` that the new one is top level, then archives itself with no ask: the confirmation approves it. If it is not top level, ask the operator.
- Outside the desktop app, end with the pickup prompt in chat, as the handoff skill says.
- On the first use, check that the new session received the prompt and the folders, and report it if not.

## Tangents

- A tangent is work outside the current task: a finding, a side question, a fix noticed in passing. Name it, then give it a session of its own, rather than following it here.
- In the desktop app, start a linked session with the app's session tool, or propose one for the operator to start. Give it a brief that stands on its own: the files, what done looks like, and what this session found. Then carry on with this session's task.
- Outside the desktop app, record the tangent as the tangents rule says, and carry on.
- A quick check, a read or a one-line fix that serves the current task is not a tangent. Do it here.

## Main session and subagents

- The main session designs, decides, drafts for review and verifies.
- Subagents execute settled plans. Each brief carries the files, the commands and the done-checks.
- A worker never pushes and never opens a pull request, and it leaves no background process running.

## Commits

- No `Co-Authored-By` or any other identity trailer. The commit identity gate refuses them.

## Settings

- The user-level `~/.claude/settings.json` is the operator's to write. The auto-mode classifier refuses an agent's write to it.
- The classifier refuses a force push too. A branch that needs a rewrite goes up as a new branch and a new pull request.
