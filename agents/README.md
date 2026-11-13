# Agents

An agent withholds a **capability** for an entire session, which is a stronger
control than asking for one in prose. Where a tool's agent hooks are
unavailable or switched off by policy, it is the only such control.

| Mechanism | Enforces by |
|---|---|
| Prescription | Asking |
| Hook | Blocking one action, where the tool runs hooks |
| Agent | Withholding the tool - partially, see below |

---

## Why this matters

"Outline the change and wait for approval", written as prose, can be violated
in any session at any moment, and the only thing preventing it is attention.
An agent with no edit tools makes it structurally impossible: the request
becomes a control rather than staying a request.

---

## Source format

`agents/<name>/definition.md`, named to stay inert. The renderer writes the
live filename per tool.

```yaml
---
name: agent-name
description: When to switch into this agent, in the user's words.
tools: [read, search]
---
```

Two optional keys decide where else a role runs:

- **`sessions:`** names the kinds of session it is rendered for. Absent, it is
  `[interactive]`, rendered to `.github/agents/` and `.claude/agents/`. A role that lists `factory` is
  also rendered, in factory mode, to `factory/rules/<name>.agent.md` on a
  `factory: true` target.
- **`model:`** is one of `sonnet`, `opus`, `haiku`, `fable` or `inherit`, and
  is written into the Claude Code agent file only. Absent, it renders as
  `inherit`, the session's model. Any other value refuses on every target. For
  Claude Code, `tools:` is mapped to its tool names, a tool with no equivalent
  is dropped with a warning, and `agents:` is not rendered (also with a warning).
- **`skills:`** names the factory skills the role is given, each a skill seed
  whose `sessions:` lists `factory`. It is written into the factory agent file
  only, where the harness reads it and grants those skills and no others. A name
  that is not a factory skill refuses on every target.

**A role, not a tone.** An agent that differs from the default only in tone is
a persona, and personas are out - `DECISIONS.md`, "Personas are out; role agents
are allowed". An agent that states a
job, what is expected of it and its pass criteria is a role agent, and is
allowed. The `tools` list is still the strongest part of one: withhold every
tool a requirement can be enforced by withholding, and name in the definition
the requirements that rest on trust instead.

What an agent gives a role that a skill does not: the body is delivered, not
advertised - verified 2026-09-26 by running `auditor` as a subagent and asking
it to quote its own definition, which it did verbatim. Selecting an agent in a
new chat delivers it too - verified 2026-09-28 with `design-partner`, which
quoted its `agent-ready` section word for word and listed edit and terminal
tools for `tools: [read, search, edit, execute, agent]`. One
caveat: it also read its rendered file that turn, so only its own account says
the quote came from the delivered body.

**A name that is not a real tool is silently ignored, not rejected.** VS Code's
documentation states it outright: "If a given tool is not available when using
the custom agent, it is ignored." An agent can therefore ship claiming a
capability it does not have, and nothing reports it. Confirmed empirically
2026-09-22 - see Verified below.

---

## Current agents

| Agent | Removes | Makes structural |
|---|---|---|
| `auditor` | all write capability, and every subagent but `Explore` | An audit cannot modify what it is reviewing |
| `design-partner` | nothing - every limit is trust-based and named in its definition | Nothing; it is a role agent. Its body is delivered rather than advertised |
| `test-writer` | nothing - it needs a terminal to show a test failing first | Nothing; it is a role agent. The `test-provenance` gate is its mechanical backstop |
| `qa` | file edits, tasks, notebooks, and every subagent but `Explore` | The operator's working tree cannot be changed by a review. It mutates code only in a throwaway worktree, which rests on trust |
| `fact-keeper` | edits, terminal, and every subagent but `Explore` | A fact check cannot change the facts. What only a command could settle lands on a could-not-check list |
| `coder` | every subagent but `Explore` | It cannot have a test changed by delegating to the test writer. Every other limit rests on trust |

A profile documents its own agents in a `README.md` beside their seeds.

**A role without `edit` names its terminal tools one by one and carries
`agents: [Explore]`.** Two indirect ways to write were found on 2026-09-29 while
checking the `qa` role. First, the `execute` tool set includes
`createAndRunTask`, which writes `.vscode/tasks.json`, and `runNotebookCell`.
The `qa` agent listed both when asked what it had. Second, per VS Code's
subagent documentation, a subagent called by name runs with that agent's tools,
and leaving out `agents` permits every agent. So `qa` could have handed an edit
to `test-writer`. `tests/test_sync.py` `RenderAgent` holds both rules for every
role. The terminal itself can still write anything, which is why every limit
above that depends on it is described as resting on trust.

`design-partner` replaced `planner`, which withheld every write so planning
could not drift into implementation. For design and refinement work, whose
output is ticket text, that restriction was artificial. The reasoning is in
its definition.

---

## What moves a chat off its agent

Checked 2026-09-29 against the per-request `modeInfo` VS Code keeps in
`chatSessions/<id>.jsonl`. Every typed request in four trial sessions ran as
the selected agent (`isBuiltin: false`). Two things did not:

- **A prompt file with `mode: agent`.** `/prime all` in a `design-partner` chat
  ran as the built-in agent, and so did the next message after it. The switch
  persists, so rendered prompts carry no default `mode`.
- **The "Continue to iterate?" button.** It sends `@agent Continue`, which runs
  that one turn as the built-in agent, without the role's definition. The turn
  after it returns to the selected agent on its own. This comes from VS Code
  and nothing here can change it. So judge any work done in a
  continued turn against the role as though the role were absent, because it
  was. `chat.agent.maxRequests` sets how often the button appears.

A role's restrictions hold only on the turns that run as that role.

---

## Rejected: an agent that checks the assistant's claims

A `verifier` agent existed briefly and was removed. It was meant to
re-run the commands behind claims rather than re-read the prose that made them.

Two reasons it went, the second fatal:

1. It declared `terminal-readonly`, which is not a real tool. The name was
   dropped silently and the agent shipped with no terminal at all, so the one
   thing it existed to do was the one thing it could not do.
2. **It can only check claims someone thought to list.** The prompt naming what
   to verify is written by the same assistant whose blind spots are the
   problem. A claim nobody recognised as a claim is never handed over, and
   those are precisely the ones that turn out false.

Checking AI output with AI inherits the original blind spot. Prefer a control
that does not depend on the unreliable party choosing to invoke it.

---

## Verified

Checked 2026-09-22 against VS Code documentation and by invoking an agent and
asking it to enumerate its own tools.

- **The `tools` restriction is real.** An agent given `[read, search]` came back
  with only read and search tools available. It had no command execution and no
  `tool_search`, so it could not load deferred tools either.
- **Unknown names are dropped in silence.** `terminal-readonly` produced no
  error, no warning, and no terminal.
- **There is no closed list of valid names to validate against.** The field
  accepts built-in tools, tool sets, MCP tools, extension-contributed tools and
  `<server>/*` wildcards, so the valid set depends on the machine. Any
  allowlist written here would produce false rejections and go stale.
- **There is no read-only terminal tool.** An agent either gets full command
  execution or none. "Read-only terminal" cannot be enforced, only requested.

The consequence worth remembering: a `tools` list can quietly grant less than
it appears to, and the failure is invisible from the file. Verify a restriction
by invoking the agent and asking what it actually has - reading the frontmatter
proves nothing.
