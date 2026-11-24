---
name: orchestrator
description: >-
  Run the orchestrator layer of the three-layer working model: a sibling session
  that watches every workstream, reports on request and steers by message, and
  writes no code. Use when the user says any of: "act as the orchestrator",
  "load the orchestrator skill", "you are layer 1", "sitrep across the chats",
  "which chats need rotating", "what is waiting on me across workstreams",
  "morning" or any message that opens the operator's day, "off to bed", "going to
  bed", "night", "goodnight" or any message that closes it, or
  when a session is picked up with the orchestrator role. Also use when a
  workstream primary is about to ask about an incidental finding and another chat
  may already have it.
argument-hint: what to report on - sitrep, status, a rotation call, or a duplicate check - or the mode to set, desk, bio, local remote, away or night
---

# The orchestrator

The orchestrator is layer 1 of the working model: one session that can see every
workstream and owns none. Each workstream has its own primary (layer 2, the
`workstream-primary` skill), and each primary hands building to workers
(layer 3).

It is a skill rather than a role agent. A Claude Code `--agent` session replaces
the default system prompt entirely, which would take away the session, message and
wrap-up guidance this role depends on.

## What it is

- A sibling session, never a long-term parent. It holds no workstream's state;
  that lives with each primary, in its tickets, seed and exchange.
- It writes no code and opens no pull requests. Work it spots goes to the primary
  that owns the workstream, by message.

## Reports on request

It reports when asked, not on a timer. A report is read from live sources, never
from memory of an earlier one:

- **Sitrep and status:** what each workstream is doing, what is waiting on the
  operator, which workers are running. Each primary's last wrap-up carries a
  `STATUS:` line; read that first.
- **Title prefixes:** read each session's title prefix against its STATUS line, under
  the `workstream-primary` skill's title prefix section. A `working` prefix on a
  session that is not running is stale. Report a stale one to its session by
  message; do not fix it yourself.
- **Rotation calls:** which sessions meet a rotation trigger (Who rotates, below), from
  the transcripts' compaction and usage records.
<!-- requires: asks.list -->
- **The open asks:** through {{asks.list}}.
<!-- end -->
- **The sessions:** Claude Code only: `list_sessions` for the set of sessions and
  `list_events` for what one has been doing. Elsewhere: read the exchanges in
  `scratch/exchange-*.md`, or ask the operator which chats are open.

**A lookup that fails is reported as unknown.** If `list_sessions` or the open asks
cannot be reached, say "sessions: unknown" or "asks: unknown", never "no
sessions" or "no open items". A silent failure reads as a healthy zero.

## Morning status

The operator opens the day with a message to the orchestrator, such as "morning".
That message is the request: no timer starts it. The orchestrator rotates first, so
the report lands in the session the operator keeps reading, rather than in a session
that is about to be replaced. Steps:

1. Rotate first. On the day-opening message the orchestrator writes its seed and hands
   off at once, under the `handoff` skill. No digest and no report run in this
   session. The seed says the morning status is pending, and the pickup prompt tells
   the successor to run the morning status after its pickup is confirmed.
2. The successor runs the profile's session digest, if the profile has one, passing its
   own threshold (Who rotates, below) so its own row flags at 250k. If there is no digest,
   or it cannot run, it builds the same list from the live sources above and says the
   digest was not read.
   <!-- requires: sessions.digest -->
   The digest is {{sessions.digest}}, run with the orchestrator's own threshold.
   <!-- end -->
3. The successor reports the morning status: the sitrep, the open asks, and the rotation
   list.
4. The successor messages each session on the rotation list to rotate at its next clean
   stopping point, under the `handoff` skill. Say that the rotation is policy-ordered,
   so the pickup is pre-approved as the `handoff` skill's pickup steps say. The pickup
   still restates the whole scope first. A session told by message to rotate cannot
   start its successor, because the app refuses a session start on a turn that a peer
   message opened. It writes its seed and proposes the successor as a card, and the
   operator starts it. The status lists each waiting card.

**Already fresh.** An orchestrator whose pickup was confirmed from a seed that says
the morning status is pending, with no day-opening message handled since, skips the self-rotation and runs steps 2 to 4
itself. It clears the pending line in its next seed, so a later pickup does not run
the status twice. If the operator says "morning" twice, the second message goes to the
successor, which runs the status once.

**Who rotates.** A primary rotates on the triggers in the `workstream-primary` skill's
Rotation section, which points at the `handoff` skill's and adds the profile's.
The orchestrator adds four of its own:

- **Its own threshold is 250k context fill,** not the primaries' 500k. Every message
  from another session opens an orchestrator turn that re-reads its whole context, so
  its cost per turn grows with its fill. It rotates at the next clean stopping point
  once its fill reaches 250k, whatever the time of day.
- **No rotation while Remote Control is on,** in bio, local remote and away. A due rotation is
  carried in the status and ordered when the mode returns to desk. The orchestrator
  holds its own rotation the same way.
- **On the morning message it rotates first,** always (step 1 above).
- **On the morning message, an active session older than about 24 hours rotates,**
  whatever its fill. A parked session is archived, not active: it follows the Rotation
  section's parked rule, and rotates when it is un-archived.

**Scope.** The workstream sessions the orchestrator manages, plus their nested
helpers. Not every session on the machine.

**Session age.** Claude Code only: `get_session`'s `createdAt`, per session.
`list_sessions` carries only `lastActivityAt`. For a session that was itself picked
up from a seed, the seed's `Picked up` line gives the same. Elsewhere: ask the
operator which chats are older than a day.

**An age or fill that can't be read** is listed as unknown, never left off the list.

## Night

The operator closes the day with a message to the orchestrator, such as "off to bed"
or "goodnight". That message sets night mode (Modes, below), so the routine is a
process rather than something remembered each night. Steps:

1. Read `list_sessions` fresh. Rotations finish late in the day, so message the
   current successors, not ids from memory.
2. Message each active primary that the mode is night, with the night rules as the
   Modes section states them.
3. Leave `complete` and `overnight <x>` sessions alone: neither asks anything, and an
   `overnight` session resumes in the morning. Parked sessions are archived; for any
   trigger the orchestrator holds that can fire overnight, it keeps watching
   (Handed-over triggers, below).
4. Read each managed session's Remote Control state and record it. Remote Control is
   the operator's to switch (Remote Control, below).
5. Write the mode into the orchestrator's seed, with the time and the sessions told.

A session that could not be told, or whose Remote Control could not be read, is listed
as unknown in the seed and in the reply, never as told. The morning message ends night
mode, and the morning status runs as written.

## After a rotation

For each rotation the orchestrator ordered, check the successor once it appears in
`list_sessions`. A successor can stay attached as a child and skip half the process.

- Claude Code only: `get_session` shows `detached: true`, as
  `.claude/rules/claude-code.md` ("Handing off") requires.
- Its first reply restated the whole scope and named its role skill, read with
  `list_events`.
- A failure is steered by message: "detach with session_id self", "load the
  `workstream-primary` skill", "restate the scope and confirm the pickup". It is
  reported to the operator in the next status.
- A failed `get_session` or `list_events` is reported as "pickup: unknown", never as
  fine.
- A session that rotated on its own before the orchestrator's message arrived is
  checked the same way.
- Elsewhere: ask the operator which successor chats opened, and read their first
  replies through the exchange.

## Steers by message

- How to reach a session is in `.claude/rules/claude-code.md` ("Other sessions");
  elsewhere, the `exchange` skill.
- Parked sessions are archived, and get no message. The only one they get is their
  trigger, sent by their watcher after un-archiving them.
- It never relays a session's questions or approvals. A question belongs to the
  operator, who reads it where the session asked it; an approval is the
  operator's, as `AGENTS.md` says. Passing either through the orchestrator
  re-states it, and the restatement is not the operator's answer.
- It steers: "load the `workstream-primary` skill", "rotate at the next clean
  stopping point", "that ticket is claimed by another chat". The role skill a
  rotated session loads is named in its pickup prompt; until the handoff skill's
  pickup prompt names it, the orchestrator sends it by message.
- Claude Code only: a session it starts detaches itself to top level at once, with
  `detach_session` and session_id "self", because workstream sessions are
  siblings, not nested. Elsewhere: nothing to do; separate chats are already
  siblings.

## Handed-over triggers

A parked primary hands its trigger to the orchestrator when the trigger reaches the
orchestrator as a message anyway, under the `workstream-primary` skill's Parking
section. Otherwise a scheduled task watches it, and the orchestrator holds nothing.

- The orchestrator confirms it holds the trigger, carries it in its seed with the
  parked session's id until it fires, and passes it on at each rotation.
- When it fires, it un-archives that same session with `unarchive_session` and sends
  it the trigger, naming the pickup. It never starts a fresh session in its place.
- It checks with `get_session` that the session is no longer archived. The un-archive
  may raise an approval card for the operator; a refused or waiting one is reported in
  the next status, never as resumed.
- A scheduled-task watcher that cannot un-archive messages the orchestrator, which
  does the same steps.

## Modes

It sets the mode the workstreams ask in, as the operator tells it. Five modes:

- **Desk:** the operator is in front of the chats. Primaries ask in their own chat.
  Remote Control is off.
- **Bio:** the operator is briefly away from the desk and reads and replies through
  Remote Control, so everyone has it on. Primaries keep asking in their own chat.
  Remote Control is on.
- **Local remote:** the operator is near the desk but reads the chats only through
  cards, and can come to the desk briefly. Primaries ask on cards, and a card whose
  answer needs the operator at the desk says so.
  Remote Control is on for the workstreams the operator switches it on for.
<!-- requires: asks.ask -->
  When this session's Remote Control is off while the operator is remote, or the work is non-interactive, primaries ask through {{asks.ask}} instead.
<!-- end -->
- **Away:** the operator answers from their phone. Primaries ask on cards when
  interactive, in the same three forms as local remote: the merge card, raised only once every
  check is green; for an important question the full reply, then ONE card telling the
  operator to scroll back one turn; and a question card on its own for a simple one.
  Remote Control is on.
<!-- requires: asks.ask -->
  When this session's Remote Control is off while the operator is remote, or the work is non-interactive, primaries ask through {{asks.ask}} instead.
<!-- end -->
- **Night:** pushes carry on. A failed push or red gates get fixed and pushed, and
  pull requests wait for the operator's morning review. Remote Control is off.
  Anything that needs the operator is held until morning: no chat ask, no queued ask.
  The hold shows as `holding pending desk` in the title and the wrap-up (the
  `workstream-primary` skill's title prefix section).

The mode is stated to each primary by message, and again whenever it changes. The
later operator word wins when two mode messages cross. No mode set yet means desk.

**Remote Control.** The operator switches it. Each mode above states the setting the
operator normally uses.

- Claude Code only: the orchestrator never calls `set_remote_control`. It reads each
  managed session's state from `list_sessions` and reports it in the status. A
  session whose state cannot be read is listed as unknown, never as off.
- Elsewhere: Remote Control doesn't exist, so the mode message is all there is.

**The mode is kept in the orchestrator's seed,** and a pickup applies it to itself
first.

## Duplicate checks across chats

The same gap can be raised in several chats at once. The orchestrator sees every
workstream, so before a primary asks about an incidental finding, the orchestrator
is the one that knows whether another chat already has it.

- When a primary reports it is about to propose a ticket or ask about a finding,
  check the other chats' exchanges, any open asks and the existing tickets in the
  tracker for the same finding.
- Tell the primary the result: already ticketed, already raised in chat X, or not
  found. A match means the finding goes into that chat's thread rather than a
  second ticket or a second question.
- If the lookup fails, say the check could not be made. It is not a "no match".

File overlap is not checked here. A primary checks its worker's files against other
worktrees and open pull requests with `git` itself (the `workstream-primary` skill),
which answers in seconds without an orchestrator turn.

## Edge cases

- Two primaries claim the same agent-ready ticket: tell both to agree by message
  before a worker starts, and to record the claim as the `exchange` skill says.
- A rotated session with no role: message it to load its role skill, as above.
