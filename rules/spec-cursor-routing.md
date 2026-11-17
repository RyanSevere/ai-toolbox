---
id: cursor-routing
tier: 1
scope: "*"
alwaysApply: true
tools: [cursor]
description: >-
  The routing line that opens every reply in Cursor, telling the operator whether
  to stay in this chat or switch to another. Rendered to Cursor only.
---

# Routing line

Open every reply with one routing line, before anything else:

- `STAY HERE` when the reply asks the operator anything: a decision, an approval
  or a step to take.
- `SWITCH TO <chat>` only when it asks nothing, naming the chat that needs the
  operator next. With no chat waiting, `SWITCH TO any`.
