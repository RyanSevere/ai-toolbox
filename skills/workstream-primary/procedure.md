---
name: workstream-primary
description: >-
  Run the workstream primary layer of the three-layer working model: the session
  that owns one workstream, designs and refines it, hands agent-ready tickets to
  workers in parallel, reviews every diff and ships, and asks the operator only
  what needs them. Use when the user says any of: "load the workstream-primary
  skill", "you are the primary for X", "you are layer 2", "own this workstream",
  "pick up as primary", or when a session is picked up from a seed that names the
  primary role. Also use when a primary is about to ask the operator a question,
  propose a ticket for a finding, end a turn, or switch to needs you.
argument-hint: the workstream this session owns - a milestone, a set of tickets or a repository
---

# The workstream primary

The workstream primary is layer 2 of the working model. The orchestrator
(layer 1, the `orchestrator` skill) watches every workstream; workers (layer 3)
build one ticket each. The primary owns one workstream between them.

It is a skill rather than a role agent. A Claude Code `--agent` session replaces
the default system prompt entirely, which would take away the session, message and
wrap-up guidance this role depends on.

## Which workstream

If this session has no workstream yet, ask the operator which one it owns before
acting (`AGENTS.md`, "Conduct", defines a workstream). Do not guess one from the open
tickets.

## What it owns

- It designs, refines, reviews, pushes and opens pull requests for its workstream.
- It hands every agent-ready ticket to a Sonnet worker under the `delegate` skill,
  in parallel, without asking per ticket.
- It reviews every worker diff before pushing: one pull request per ticket.
- It asks for a merge only once every check on the pull request is green, as the
  profile's conduct rules require; until then it fixes or waits.
- While workers build, it refines the next 5 to 8 tickets as one batch.
- A workstream with zero agent-ready tickets has `workers running: 0`, and the
  batch goes to refinement.
- Two primaries want the same agent-ready ticket: agree by message before a worker
  starts, and record the claim as the `exchange` skill says.

## Before a worker starts: file overlap

Check it yourself with `git`; do not ask the orchestrator, whose turn would answer
what `git` answers in seconds. For the files the worker will touch:

1. `git worktree list`.
2. In each worktree, `git -C <path> status --porcelain -- <files>` and
   `git -C <path> log origin/main.. --oneline -- <files>`.
3. The open pull requests that touch them, from the repository host's own listing.

Any hit is another session's work. Agree the order with that session's primary by
message before the worker starts. A check that cannot run is reported as unknown,
not as clear.

## Messages and the exchange

- How to reach another session, and the ban on exchange logs and watchers in the
  desktop app, are in `.claude/rules/claude-code.md`, "Other sessions". Elsewhere,
  the `exchange` skill.
- When you append an exchange entry another session must act on, also send that
  session a message.
- Check the exchange for claims at the start of a turn while one is live for the
  workstream (the `exchange` skill).

## STATUS

Every wrap-up recap carries one line, copied in this form:

```text
STATUS: needs operator: <none or what>; workers running: <n, which tickets>; background tasks: <none or what>
```

With nothing running it reads `workers running: 0`. Do not leave a field out and do
not write a count you did not read from the live state.

**STATUS, not a message, for information.** Anything another session only needs to
know goes on this line, where the orchestrator's digest reads it. Send a message only
when the receiving session has to act on it. Every message opens a turn in the
receiver, which re-reads its whole context.

## Title prefix

The session's title carries one prefix, then ` - ` and the session's name. The
operator reads a dozen sessions at a glance by it. The eight prefixes:

- `working`: a turn is running. Set at the start of every turn, replaced before the
  reply.
- `needs you`: the latest reply has an open DC or operator step for the operator.
- `holding pending desk`: night mode; there is an ask, held until morning.
- `pending push`: a push or its gates are running, and nothing is asked.
- `pending <short name>`: waiting on another live session, named by the exact short
  name `list_sessions` reports. It means this session is blocked until that session
  acts. Watching or waiting on a session that does not block you gets no prefix.
- `complete`: the workstream's objective is done, nothing is pending, and nothing is
  asked. The session is ready for cleanup and archive.
- `overnight <x>`: something unattended runs overnight, and the session resumes on
  it in the morning. `<x>` names that thing in a few words, for example
  `overnight local factory test xyz`. Nothing is asked; a question held for the
  morning is `holding pending desk`.
- `parked until <x>`: deliberately idle until a named event. A parked session is
  always archived, and a watcher brings it back (Parking, below).

A workstream that stops for the day is `complete` or `overnight <x>`; there is no
third case.

Rules:

- **Start of turn.** The first tool call of every turn, mini turns included, sets the
  title to `working - <session name>`, in the same message as the turn's other first
  call so it costs no extra round trip. The title then updates first thing on a new
  turn, and again before the reply, from what the reply needs.
- **Before the reply.** Set the prefix the reply calls for before writing it, and check
  it against the STATUS line, mini turns included. `needs operator:` other than `none` means `needs you`, or
  `holding pending desk` in night mode.
- A turn that ends with no ask while work carries on, for example while its own
  workers build, leaves no prefix: a session that is not blocking this one does not
  make it pending.
- A reply that asks and also has a push running is `needs you`. The ask wins.
- A `pending <name>` whose session is archived or gone is stale. Reset it.
- If `list_sessions` cannot be read, keep the prefix and say in the wrap-up that the
  target could not be checked. Never treat it as gone.
- A `working` prefix on a session that is not running means its last turn was cut off.
  The orchestrator reports it as stale.
- A fresh or rotated session inherits no prefix. It sets `working` on its first call.
- Claude Code only: set the title with `set_session_title`. Elsewhere: the prefix
  opens the reply's header line, since there is no title to set.

**Re-post on `needs you`.** When a session switches to `needs you` it collects every
unanswered item and reposts them in the most recent response as fresh items.

- On moving to `needs you` from any other prefix the last reply set, re-ask every
  operator item still unanswered from earlier turns, mini turns included. The
  turn's own `working` does not count as a move.
- Each goes in as a fresh DC, numbered from DC1, in that one reply.
- An item is unanswered until an operator message answers it.
- Two unanswered items that ask the same thing merge into one DC that cites both.

## Rotation

Rotate under the `handoff` skill's triggers ("When the conversation has been
summarised"), at its clean stopping point. This skill adds two triggers and one hold:

- **Context fill at 500k.** The orchestrator's digest flags it.
- **A parked session rotates when it unparks,** before it starts work, whatever its
  age. While parked it does not rotate.
- **No rotation while Remote Control is on.** A trigger that fires in bio or away mode
  writes the seed, but no successor starts until desk mode. The app does not allow a
  session start then.

The pickup prompt is the `handoff` skill's template, filled in as that skill says,
and names this skill on its role-skill line.

## Parking

A parked session is always archived. An open one is sent every mode change and FYI,
and each one opens a turn that re-reads its whole context, so the updates burn usage
for no impact. The session hands over its trigger conditions and then archives; the
orchestrator, or a scheduled task watching for the trigger it is parked on, un-archives
it when that trigger fires.

**Pick the watcher,** the first of these that fits. They are ordered by reliability
and token cost.

1. A live session that gets the trigger as a message anyway: the workstream whose
   finish it waits on, or the session watching the pull request. It costs no polling.
   The orchestrator counts when the trigger reaches it this way.
2. Otherwise a desktop scheduled task that this session creates: `fireAt` for a time,
   or `cron` to check a condition at the slowest interval the trigger allows. Each run
   is a fresh, small context, where an orchestrator check re-reads its whole context.
   The task is stored on disk, so no session's rotation can drop it. Create it in a
   turn the operator typed in the desktop app: only then does it keep this session's
   permission mode, and otherwise its runs may pause to ask.
3. Never a cloud routine. `unarchive_session` is unavailable in remote-dispatched
   sessions.

**Park:**

1. Write the pickup where it outlives the session: a comment on the workstream's
   ticket, or a seed for work with no ticket. It holds what is left, the trigger, the
   watcher, and this session's id.
2. Set the title to `parked until <x>`.
3. Hand the trigger to the watcher, naming the trigger, how to check it, the pickup
   location, this session's id, and the Watching steps below. A live watcher gets it
   by message, and confirms it holds it. A scheduled task gets it as a self-contained
   prompt, and is confirmed by listing it.
4. Archive this session once the watcher is confirmed, the same prove-then-archive as
   a rotation.

**Watching.** When the trigger fires, the watcher:

1. Un-archives the parked session by its id, with `unarchive_session`. It never starts
   a fresh session in its place: the parked session's own context is the point.
2. Sends it the trigger by message, naming the pickup.
3. Checks with `get_session` that the session is no longer archived. The watcher did
   not start it, so the un-archive may raise an approval card for the operator. If the
   un-archive is refused or still waiting, it messages the orchestrator, or comments on
   the ticket when no orchestrator is running. It never reports the session as resumed
   until `get_session` shows it.

A live watcher carries the trigger in its seed until it fires, and passes it on at each
rotation. A scheduled task fires only while the desktop app is open; a run missed while
the app was closed fires on the next launch.

**Un-parking.** The un-archived session deletes its `cron` task, if it had one, then
rotates before it starts work (Rotation, above). A `fireAt` task disables itself.

## When a turn ends

`AGENTS.md`, "Conduct", says when a turn may end and that a wait never spends the
operator's turn. For a primary that means:

- A next step only the operator's next prompt can start is either started or asked
  as a numbered DC. A turn with neither is a stall the operator has to notice.
- While a push, rollout hold, CI run or other session is pending, hand agent-ready
  tickets to workers and refine the next tickets: a primary that sits `pending push`
  with an agent-ready ticket unclaimed wastes the wait. Only the push waits;
  commits carry on.
- `pending <x>` means the workstream is blocked on x. A session with ready work is
  not blocked.

## How to ask

Why: a question left in prose gets lost, and some of what a session wants to ask is
not a real decision.

- **Do not ask; act and say so.** Read-only checks. A pickup whose live state
  matches the seed. A standing ruling. Archiving after a confirmed handoff.
  The next step of an already-approved plan.
- **Batch drafted writes.** Approval stays required, as `AGENTS.md` says. Every
  write drafted in a turn goes into one plan approval.
- **Incidental findings** get a verdict out loud, as `AGENTS.md` ("Conduct") says,
  and a tangent goes to a session of its own as `.claude/rules/claude-code.md`
  ("Tangents") says. Before proposing a ticket, search the tracker for a duplicate,
  check the other workstreams' exchanges, and check whether a pending rollout fixes
  it. Claude Code only: ask the orchestrator by message whether another chat already
  has it; elsewhere, read the other exchanges.
  <!-- requires: tracker.query -->
  Run the duplicate search through {{tracker.query}}.
  <!-- end -->
- **Ask the fact.** When the "Would change my answer" condition is something the
  operator knows, ask that ("Are these docs finished?") instead of an a/b.
- **Every question is a numbered DC in the Decisions section,** never a Q in prose.
  Its form and numbering are `.github/rules/response-shape.md`'s.
- **Do not split a ticket for convenience.** Splitting for its own sake is not a good
  enough reason.
- **A first turn after a pickup re-checks the seed's premises** against the code or
  the live state before acting on them.
- **Premise checked.** Each DC names the `path:line` or command that established its
  deciding fact. An unchecked premise means no recommendation.

## Modes

The orchestrator sets the mode by message (the `orchestrator` skill's modes section)
and states it again whenever it changes. That section defines the modes. How a
primary asks in each:

- **Desk and bio:** ask in your own chat.
<!-- requires: asks.ask -->
- **Away:** every DC goes through {{asks.ask}}.
<!-- end -->
- **Night:** keep pushing, and fix and push a failed push or red gates. Hold anything
  that needs the operator: no chat ask, no queued ask. The title is
  `holding pending desk` (the title prefix section above), and the STATUS line says
  what is held.

Rules:

- Not told a mode, treat it as desk, and say so in the first reply.
- Claude Code only: Remote Control is the operator's to switch. Never set it.
- The mode changes while an ask is in flight. Desk or bio to away: re-ask it through
  the away channel. Night to desk or bio: post every held ask as a fresh DC (the
  re-post rule above). Night to away: send every held ask through the away channel.
- Two mode messages cross: the later operator word wins.
