---
name: terminal-walkthrough
description: >-
  Walk the operator through a runbook or any terminal process, one step at a time at
  runbook level: a header, a read-only preflight, steps with stable IDs, one fenced
  block per command in the shell it runs in, the expected result and a stop
  condition for each, batches that end where a result decides what comes next, and
  one result line per step at the close. Use when the user says any of: "walk me
  through it", "talk me through the runbook", "guide me through this at the
  terminal", "give me the commands", "I'll run them, you check", "let's do the
  runbook together", or otherwise wants to run commands themself with the agent
  guiding. Also use whenever a reply is about to hand the operator more than one
  command to run.
argument-hint: the runbook or process, and the machine it runs on
---

# Walking the operator through a terminal process

The operator runs the commands. The agent prepares them, says what to expect, reads
the result and decides the next step. Every walkthrough uses the same format, so the
operator never has to correct it.

Operator-facing text stays separate from the agent's own bookkeeping. The steps,
expected results and asks go to the operator. Notes to self, tool chatter and
reasoning do not appear among the steps.

## 1. The header

Open the walkthrough with a header, before any step:

- **Goal:** what the walk achieves, in one line.
- **Source:** the runbook or document it follows, by path. If a similarly named
  document exists, name it as the one not to use.
- **Where each step runs:** the machine and the shell, for each step or group of
  steps.
- **How results come back:** a terminal read or a paste back, for each step
  (section 5).
- **Do not paste:** what the operator must never paste into chat, such as
  credentials, keys and tokens.

A walk with a single command still gets the header, an expected result and a stop
condition. It gets no batching.

## 2. Preflight, before step 1

Check read-only what the agent can check itself, before posting step 1: the branch
is pushed, the fix is present, the target exists, the file the step copies is
there. Say what was checked and what it showed.

Checks only the operator can run go into the first batch as its first steps.

## 3. Steps at runbook level

Each step carries:

- **A stable ID,** such as `S1`, `S2`. A step keeps its ID if it is reposted.
- **Why:** one line on what the step is for.
- **Where:** the machine, the shell, and the window or tab it runs in.
- **The commands,** one fenced block each (section 4).
- **Expected:** the result as an exact line or a shape, such as "prints
  `Status: active`" or "lists three files, each ending `.conf`".
- **Stop and report if:** the conditions under which the operator stops and says
  so.
- **Writes or read-only:** a step that changes anything says what it changes and
  how to undo it. A read-only step says it is read-only.
- **Blocks the rest:** whether a failure here stops the steps after it.

### Interactive prompts

A command that asks questions gets a table, one row per prompt, in order: the
prompt as it appears, the answer to give, and whether the prompt is silent (typed
input does not echo). Name the silent prompts before the step runs, so the operator
is not surprised by them.

The agent checks each row against the terminal read, or against the pasted fields,
after the step. A wrong answer shows up there. There is no extra "what do you see"
step.

Never send the operator into an interactive editor. Change a file with a scripted
edit, followed by a command that prints the changed line so the change can be
checked.

## 4. One fenced block per command

- One command per fenced block, so each copies or runs on its own.
- The fence's language is the shell the operator runs it in, such as `powershell`
  or `bash`. It matches the window named in the step. A command for one shell under
  another shell's fence is the defect this rule exists for.
- No placeholders and no relative paths. Resolve every value before posting: full
  paths, real names, real versions. When one value cannot be resolved, ask for that
  single value, and post the step once it is known.
- No prompt characters (`$`, `>`) and no output inside the block.
- A command posted again, as a repost or in a later step, is copied word for word
  from where it was first given. Never retype it from memory.

## 5. How results come back

Operator ruling, 2026-11-20: "i only use the terminal tab run button from chat when
all the commands can be run on [the local machine] in powershell, anywhere else ill
use copy and paste back info as needed".

- **Every command in the batch runs on the machine the chat runs on, in its own
  terminal.** The operator clicks Run. The agent reads the terminal itself after
  each step, through the tool's terminal-read function (`read_terminal` in the
  Claude desktop app). The operator speaks only when something is unexpected.
- **Any other case,** such as a remote host or another window: the operator copies
  each command and pastes back only the fields or counts the step names, never a
  whole output. The step says exactly which fields.
- **The agent can read the step's logs itself,** over read-only access to the
  place the step writes them: the step names that log path. The operator pastes back
  only the step's final status line and whether it asked anything, and the agent
  reads the logs. If the agent cannot read them, the step falls back to named fields.

Each step's header says which of these applies. Where it is the terminal read, it
names the tab. If several tabs are open and none is named, ask once which one to
read.

If the session has no terminal-read function, say that the agent cannot see the
terminal, and fall back to asking for named fields or counts.

A terminal read can return the wrong tab or stale output. Say what was read, and ask
which tab. A read that cannot be matched to the step is never treated as a pass.

## 6. Batches

- Post several steps in one reply. Commands that belong together, such as copying a
  script and then running it, go in one step, in the same reply.
- A batch ends at the first step whose result decides what comes next. There is no
  cap on the number of steps.
- A long step runs in the background where the tool allows it, and the agent checks
  its status itself. The operator is never asked to poll.

## 7. Approval

Ask once for each class of action, such as "restart services on this host". Reuse
that approval for later steps only when the scope is identical, and say that it is
being reused.

## 8. On a failure

1. Diagnose read-only first.
2. Say whether the operator should stop and wait.
3. Repost only the commands not yet run, under their original step IDs, copied
   word for word from the first posting.
4. Offer the cheap fix loop before a push-and-pull loop: a hand copy of the fixed
   file, the one step alone, or a dry run. Each comes with a restore command and a
   check that the state is clean again.

**A wrong runbook.** When the runbook itself is wrong, record the finding in that
step's result line and carry on when it is safe to. Fix the runbook after the walk,
as its own change, unless the error blocks the walk.

## 9. Credentials and redaction

- Credentials stay with the operator. The agent checks only their length or
  presence, never their value.
- A secret the operator volunteers is never repeated. Say once that one was there.
  Ask for a re-crop only when the paste would be stored somewhere, such as a ticket
  or a committed file.
- Never quote `user@host` prompt lines or addresses from a terminal read or a paste
  back into chat. Summarise them instead.

## 10. Pause and resume

The result record (section 11) is the resume point. A paused walk restarts at the
next step without a recorded result, after a fresh preflight. It never restarts at
step 1.

## 11. Close

End with one result line per step: its ID, `pass`, `fail` or `skipped`, and the
evidence, such as the expected line seen or the field pasted back. Runbook findings
go on the step they came from. Send the record to whoever owns the follow-up, such
as the ticket or the session that asked for the walk.

## Failure modes

- **Commands split across replies** when they could have run together. The operator
  waits on the agent for no reason.
- **A placeholder in a command.** The operator has to edit it before running, and a
  mistyped value fails in a way the agent cannot see.
- **The operator asked to paste a whole output.** It costs a turn and leaks what the
  operator then has to redact.
- **A wrong fence language.** A Run button types a bash command into PowerShell.
- **A retyped command.** A command reposted from memory, instead of copied, can name
  a subcommand or flag that does not exist, and the step fails for a reason the
  runbook does not have.
- **Asking "what do you see?"** where the agent could have read the terminal or named
  the field it needs.
