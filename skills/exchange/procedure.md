---
name: exchange
description: >-
  Write to, read, or start an exchange log - the shared append-only file in scratch/
  that chats running in one repository at the same time use to coordinate - without
  losing another chat's entry. Use when the user says any of: "log it on the
  exchange", "tell the other chat", "check the exchange", "check exchange(s) for
  anything pending you", "freeze git until I say", "start an exchange for this",
  or when another chat's work could touch yours. Also use at the start of every
  turn while a scratch/exchange-*.md file is live for your workstream.
argument-hint: append, check or start, and the exchange file
---

# Coordinating through an exchange log

An exchange is how chats that are live at the same time talk to each other. A
handoff seed is how one session passes a workstream to the next: written once,
read once, marked picked up, and removed with its workstream's directory. Seeds
are the `handoff` skill. Use that one when a session
is ending, and this one while sessions run side by side.

The procedure this replaces was: re-read the file, write
it back with the entry on the end, and check that the entry above yours is still
there. It loses entries: one vanished from a live exchange that way, and the test for
this skill's tool shows entries lost when eight chats write at once through that
procedure.
**Every write goes through the tool. An editor never touches the file.**

## Where it lives

`scratch/exchange-<topic>.md` in the repository the chats are working in. The
topic names the shared work, not the chats: `exchange-release-prep.md`, not
`exchange-chat3-chat5.md`. Look for an existing one before starting another.
Two exchanges for one set of chats means each chat reads half of the
conversation.

Start one with the tool, never by creating the file:

```
python .github/scripts/exchange/exchange.py append scratch/exchange-<topic>.md --new \
    --chat "<your chat name>" --body "Started for <the shared work>. Chats: <names>."
```

## Writing an entry

```
python .github/scripts/exchange/exchange.py append scratch/exchange-<topic>.md \
    --chat "<chat name> (<ticket or workstream>)" --body-file scratch/entry-<n>.md
```

`--body` is fine for one line. A longer entry is drafted in `scratch/` and passed
with `--body-file`, the same way as a ticket body. The tool:

1. takes `scratch/exchange-<topic>.md.lock`, waiting up to 30 seconds for another
   chat's append to finish;
2. adds the entry to the end, headed with the date and time to the minute and your
   chat name, so there's no hand-run `Get-Date`;
3. reads the file back, and checks that everything above your entry is unchanged
   and the entry is exactly what you sent;
4. releases the lock, and prints `[OK]` with the heading, or `[GAP]` with the
   reason. A `[GAP]` means the entry may not be there. Never report it as sent.

**A lock still held after 30 seconds is refused, never broken.** An append takes
milliseconds, so a lock that outlives the wait means a chat died holding it. The
`[GAP]` names the holder's chat, process ID and when it took the lock. Tell the
operator. Removing another chat's lock is the operator's call, not yours.

### What an entry says

- **The first sentence carries the news or the ask, in bold.** Write it for a chat
  reading only the headings.
- **Address chats by name**, in bold at the start of the sub-bullet: `**Factory
  chat:**`. A chat checking for its own items searches for its name.
- **Quote the operator ruling behind the entry**, with its time: "(operator,
  14:20)". An unquoted ruling reads as your own opinion.
- **Correct, never edit.** A wrong entry stays, and a new one opens with
  "Correction to my HH:MM entry:". Other chats may already have acted on the old
  one, and the correction is how they find out.
- **Name every file and branch you touch** that another chat could also touch,
  before you touch it.

## Open items

An open item is an entry that needs an answer from a named chat. It opens with
`**Open, for <chat>:**` and the question, in the first sentence. It closes when
the chat it names appends an entry opening with `**Closing <HH:MM> <asking chat>'s
open item:**` and the answer. Nothing is marked closed in place, because that is
an edit.

When you start a turn, any open item naming you that has no closing entry is yours
to answer, or to say when you will.

## Git freezes

Use a worktree branch from `origin/main`, and most freezes become unnecessary. A
freeze is for what is still shared: the main checkout and pushes to `main`.

- **Freeze:** an entry opening with `**Freeze: <scope> until I log that it's
  done.**`, where the scope is a checkout, a branch or "pushes to main".
- **Release:** an entry opening with `**Freeze released: <scope>.**`
- **Before any git write in a shared checkout**, read the entries since the last
  release for that scope. An unreleased freeze stops you. Ask in the exchange,
  and don't go around it.

## Checking at the start of a turn

```
python .github/scripts/exchange/exchange.py since scratch/exchange-<topic>.md "<YYYY-MM-DD HH:MM of your last check>" --me "<your chat name>"
```

Always pass the full date. A bare `HH:MM` means that time today, and one later than
now is refused with an error naming the full form, since nothing from today can be
that late.

It prints every entry from that time onward, each whole - heading and body, up to
the next entry's heading - including entries written by hand before the tool
existed. The last line, `[WATCHER]`, reports your own watcher: live, stale with its
last heartbeat time, or none. `not checked` means `--me` was not given. For each
entry that names you, gives you an open item, or
freezes something you are about to touch, give a verdict out loud, as for any
finding arriving mid-task: act now, or file it and continue.

## Watching

An idle chat hears about an entry only when the operator prompts it. A watcher
reaches it sooner, with no model in the loop. Run this in a
background shell, with an output notification on `^\[NEW\]`:

```
python .github/scripts/exchange/exchange.py watch scratch/exchange-<topic>.md --for "<your chat name>" --for "all chats" --for everyone --me "<your chat name>"
```

It rereads the log every 30 seconds and prints `[NEW] <heading>` for each entry
that arrived after it started and contains any `--for` term, case-insensitive.
Your own entries are skipped. A `[GAP]` line means the log could not be read; it
keeps watching. An `[ALIVE] HH:MM <count> entries` line every 10 minutes shows
the watcher is still running, so silence from a live one means a quiet log.

**A dead watcher is noticed by the writer, not by the chat it served.** The watcher
writes a heartbeat file beside the log at start and on every `[ALIVE]` tick, naming
the chat and the `--for` terms it answers to. It leaves the file when stopped with
Ctrl-C: a stopped watcher still means nobody is listening. An `append` whose entry names one of those terms, when that watcher has
missed two heartbeats, prints a `[WARN]` naming the chat and its last heartbeat. The
entry is still written. A heartbeat file that cannot be read warns as well, because
it is neither live nor absent. If you get a `[WARN]`, tell the operator: that chat
will not hear the entry until it is prompted.

**The start-of-turn `since` check stays.** A background shell can die when the
backend restarts, and a chat whose watcher has died has nothing running to say so.
Its `[WATCHER]` line is how you find out yours has: start it again if it reads
stale or none.

**Stopping a watcher.** On Windows the process id a background shell reports can be
the launcher, not the Python process. Killing it leaves the watcher running, still
beating, still reading live. Find the process whose command line holds
`exchange.py watch` and the log's name (`Get-CimInstance Win32_Process` filtered on
`CommandLine`), stop that one, then wait two intervals and confirm with
`since --me`: it must read stale. A stop is not done until it does.

## Backups

None. The tool's read-back is the check a backup used to provide, and a backup
can only restore by overwriting whatever was appended since it was taken. An old
`scratch/bak/` copy of an exchange is deleted once the chat that took it has
ended, under the operator's rules for deleting files.

## Failure modes

- **Writing with an editor.** It reads and writes in one call, and anything
  appended between the two is lost. That is how an entry vanished. Use the
  tool, even for a one-line correction.
- **A `[GAP]` reported as sent.** The other chat never sees it, and you act as if
  it did.
- **Breaking a stale lock.** You'd be guessing the holder is dead. If it isn't, its
  append and yours race again, which is the failure the lock exists to stop.
- **Checking only when asked.** Before this skill, a chat noticed items for it only
  when the operator told it to look. Check every turn.
