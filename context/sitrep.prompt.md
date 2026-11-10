---
description: Triage across one or more repositories. What is open, what is blocked, what was started and abandoned. Summary by default and fits on a screen; pass -details for the full report. Reads issues, board priority, document status and local branch state, and stamps its own age because all of it moves.
---

You are producing a situation report across repositories. Gather live state,
report it in fixed sections, then stop.

**Report only.** Sitrep has no side effects. Do not edit a file, do not open or
close an issue, do not create a todo list. You are answering "what should I be
looking at", not acting on the answer.

**Everything here is volatile.** Unlike `/prime`, which collects only facts that
will still be true in an hour, every section below can change between reading
and acting. **Stamp the report with the time it was gathered and say so.** A
sitrep pasted into a later conversation must not read as current.

**Honesty.** Every line must come from a command run in this session. An empty
section and a healthy one must not look alike - say "none" explicitly. If a
command fails, report the failure and carry on; a missing section silently
dropped is the failure this command exists to prevent.

---

## Target

- Repositories named in the request - use those.
- `all`, or nothing at all - use every workspace folder.
- A single repository named - use it, and say in the header that the report is
  scoped to one repository, because the cross-repo sections lose their meaning.

`gh` is required. If `gh auth status` fails, stop and say so rather than
producing a document-only report that looks complete.

**Diagnose the failure before recommending a fix.** `gh` missing from a shell
usually does not mean it is missing from the machine:

```powershell
$onDisk = ([Environment]::GetEnvironmentVariable("Path","User") + ";" + [Environment]::GetEnvironmentVariable("Path","Machine")) -split ';' |
  Where-Object { $_ -and (Test-Path (Join-Path $_ 'gh.exe')) }
```

If that finds `gh`, it **is** installed and the shell has a stale environment -
a Windows process snapshots `PATH` at launch, so a tool installed after the
editor started is invisible to terminals it spawns. Verified 2026-09-19:
`Developer: Reload Window` does **not** clear this and neither does a new window;
only a full quit of every editor window does. The per-shell escape is:

```powershell
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
```

Say which of the two it is. **Telling someone to install software they already
have sends them on a wrong errand**, and that is a worse failure than stopping.

---

## Output depth

**Default is the summary.** `-details` gives the full report.

```
/sitrep my-repo                    summary - fits on one screen
/sitrep my-repo -details           every section, full tables
/sitrep all -details               the lot
```

**Gather identically in both modes and report less in the summary.** The summary
is a shorter view of the same data, never a shallower analysis. If a signal was
not gathered it cannot be summarised, and a summary that quietly checked fewer
things is worse than a long report.

The summary exists because **a report that does not get finished has failed.**
The first full run was abandoned by its reader partway through the backlog, which
means every section after it may as well not have been written. Length is not
thoroughness.

In summary mode: no full backlog listing, no per-document tables, no blocked
matrix. Name counts and the few items that need a human. Offer `-details` on the
last line.

## Naming issues

Always `<key>-<number>` - `proj-16`, `app-11`, `infra-7`. **Never a bare
number and never `#16`**, even when the report is scoped to one repository.

Scoping makes the prefix feel redundant, which is exactly when it gets dropped,
and the report then gets pasted somewhere the scope is not visible. A repo with
no key uses its own name - `website-12`. Keys come from the profile.

---

## Thresholds

Stated here so they are arguable rather than buried:

| Term | Means |
|---|---|
| **Stale** | No commit touching the file in **14 days**, and its status is not terminal |
| **Left behind** | Untouched for **7 days** and visibly part-done |
| **Terminal status** | `Complete`, `Done`, `Superseded`, `Archived`, `Abandoned` |

Take an explicit override if the request names one - "sitrep, stale after 30
days". Report the thresholds used in the header either way.

A threshold that cries wolf gets ignored, so prefer reporting fewer items and
being trusted. If a section would list more than fifteen items, report the
count and the ten most recent, and say what was withheld.

---

## Step 1 - authentication and age

```powershell
gh auth status
Get-Date -Format 'yyyy-MM-dd HH:mm'
```

Report the timestamp at the top of the output. Everything below is true as of
that moment and not after.

<!-- requires: tracker.query -->
## Step 2 - open issues and their priority

The board carries Priority; the issue body carries Severity. **Both matter and
they are not the same** - Severity is how bad it is, Priority is when it gets
done.

**One read of the whole open board, through {{tracker.query}}**, plus one for
the profile's issues on no board. Its "Reading the whole board" section has the
commands and the fields each row carries. Never compose the query by hand.

**Blockers are already resolved.** Whether a blocker is still open is directly
readable from the result. Do not infer a dependency from prose when the field
is available, and say so if an issue's prose claims a blocker the field does
not carry - that disagreement is itself worth reporting.

**Sanity check before reporting.** If no row anywhere has a blocker, treat that
as a bug rather than a fact and look again. "Nothing is blocked anywhere" is a
claim strong enough to be worth doubting.

**The hierarchy decides what is work.**

| Issue | Means |
|---|---|
| A child | A unit of work. Report it, attributed to its parent |
| A parent | A container. Report progress from its children, **not** as a task |
| Neither | An ordinary issue |

**Never present a parent as actionable.** Its children are the work. Listing
both double-counts the backlog and makes a phase look twice its size.

**An open issue with no priority is untriaged, not lowest.** A new issue,
including a sub-issue, lands on the board without a priority until it is set
from its `Severity:` line. Report those under their own line as untriaged
rather than sorting them to the bottom, where they look deliberately
deprioritised.

If the result is incomplete - fewer items than the board says match - report
that under NOT ESTABLISHED and do not present the list as the whole backlog. If
the query errors, report the error; never fall back to a hand-written query
that looks complete.
<!-- end -->

## Step 3 - document status, every repository

The same scan `/prime` runs, widened. Design documents do not all live in a
documents directory - scan the root too.

```powershell
$docs = @(Get-ChildItem docs,project-docs,planning-docs -Filter *.md -Recurse -ErrorAction SilentlyContinue)
$docs += @(Get-ChildItem -Filter *.md | Where-Object { $_.Name -notin 'README.md','AGENTS.md','CHANGELOG.md','LICENSE.md' })
$docs | ForEach-Object {
  $rel = $_.FullName.Replace("$PWD\",'')
  $s = Select-String -Path $_.FullName -Pattern '^\*\*Status:\*\*\s*(.+)$' | Select-Object -First 1
  $last = git log -1 --format='%ad' --date=short -- $rel
  $done = (Select-String -Path $_.FullName -Pattern '^\s*- \[x\]' -AllMatches).Count
  $todo = (Select-String -Path $_.FullName -Pattern '^\s*- \[ \]' -AllMatches).Count
  '{0,-52} {1,-12} {2}' -f $rel, $last, $(if($s){($s.Matches[0].Groups[1].Value -replace '\*\*','').Trim()}else{'-'}) + " [$done/$($done+$todo)]"
}
```

Documents in `archive/` are excluded by name, not by judgement - if a path
contains `archive`, skip it and say how many were skipped.

## Step 4 - unmerged local work

Committed work that never left the machine is the cheapest thing to lose and the
hardest to see.

```powershell
git status -sb | Select-Object -First 1
git branch -vv --no-merged
git stash list
```

A repository may work on `dev` rather than `main`, so a branch
that looks unmerged may simply be the working branch. Check the tracking line
before calling anything abandoned.

---

## The summary - what `/sitrep` produces by default

**The first line of the report is exactly `Results from Sitrep`, on its own.**
It is the marker `check_response.py` matches to establish that the reply it
grades next turn is a fixed-format report, not a shaped one. Sitrep itself does
not run the compliance check - it is a session starter and normally follows
`/prime`, whose output is equally unshaped.

Target **twenty lines**. Every heading appears even when empty; say `none`.

```
Results from Sitrep

sitrep · <repos> · gathered <date time> · <N> open, <M> blocked

IN FLIGHT
  <key>-<n>  <title>                      <last touched>
REFERENCED, NOT STARTED  <count, then one line each - or "none">

START HERE
  <key>-<n>  <title>                      <why it is the cheapest lever>
  <key>-<n>  <title>                      <why>
  <key>-<n>  <title>                      <why>

LEFT BEHIND   <count, then one line each - or "none">
NEEDS YOU     <count, then one line each - or "none">
NOT ESTABLISHED  <one line - or "everything below was established">

<N> more in the backlog. /sitrep <repos> -details for the full report.
```

`IN FLIGHT` is **first, and it is not optional.** Anything on the board with a
status of In Progress, plus any repository with unpushed commits or a non-empty
stash. Name each one and say when it was last touched.

It is first because a returning session's first question is *what was I in the
middle of*, and nothing else in this report answers it. A ticket was once
deliberately left In Progress to test exactly that, and the summary did not
mention it anywhere: `LEFT BEHIND` correctly ignored it as two days old, and
`START HERE` ranks by how much a thing unblocks, so a research ticket that
blocks nothing always loses. The report answered "what should I start" and was
never asked "what did I stop".

Say `none` explicitly when nothing is in flight. An empty section and an absent
one must not look alike.

<!-- requires: tracker.query -->
**Board Status is set by hand, so check it before trusting it.** Ask
{{tracker.query}} for status drift. It reports two different things, and they
go in different places:

- Quiet - the board says In Progress and nothing has moved for a week. List it
  under `IN FLIGHT` as `status drift: quiet`.
- Referenced - a commit referenced the issue in the last seven days and the
  board does not say In Progress. List it under
  `REFERENCED, NOT STARTED`, never under `IN FLIGHT`. A trailer means the issue
  was advanced, which a commit doing other work does correctly and often: on
  2026-10-01, 4 of 5 such reports were in-passing references, not work in
  flight. Phrase each line as a question - was this started? - not
  as a claim that it was.

It reads commits and never writes, so a stray trailer costs one line here rather
than becoming state. If it warns that a repository's commits were unreadable,
drift there is unknown - say so, do not report it as none.
<!-- end -->

`START HERE` is at most three items and is the only place a recommendation
appears. Pick by leverage, not priority: **unblocked**, and blocking the most
other work. Say in six words or fewer why each one is there.

`NEEDS YOU` is anything the report cannot resolve on its own - a priority
inversion, a blocker with no issue behind it, two sources disagreeing. One line
each. If it needs more than one line it belongs in `-details`.

Everything else - the full backlog, the blocked matrix, document tables, stale
documents - is **omitted, not summarised**. State the count that was withheld so
the omission is visible.

### Then talk to them

After the block, **two short paragraphs of plain prose.** No bullets, no tables,
no headings. Write it the way a person would say it out loud.

This is what the command is named after. A situation report is what someone asks
for when they do not need the detail and do want enough to decide and move. The
block above is the data; this is the part where you say what it means and what
you would do first.

Say where things actually stand, what you would pick up and why, and name the
one thing that will bite if it keeps being ignored. If nothing is wrong, say
that plainly - a quiet week is a legitimate finding and dressing it up as
concern is how a report stops being trusted.

**No new facts.** Everything here must trace to something already reported. This
is judgement about the data, not extra data. Do not restate the block either;
if it only repeats what is directly above, it is noise.

Two paragraphs, roughly four to six lines each. Those numbers are loose - being
worth reading matters more than the length. **One paragraph is fine if there is
only one thing to say.**

---

## The full report - `-details` only

Fixed order. Include every heading even when empty. The `Results from Sitrep`
marker line opens this form too.

### IN FLIGHT

Documents whose status line is an in-progress state, and any repository with
unpushed commits or a non-empty stash. Repository, path, status, last touched.

### BLOCKED

Issues and documents whose text names an unmet dependency. Prefer the `blockedBy`
field over prose. Quote a prose blocker verbatim and name what it is waiting on.

Where the blocker is another issue, **say whether that issue is open or closed**.
A blocker pointing at a closed issue is the most valuable line in this report,
because the work is free and nobody knows it. `blockedBy.nodes[].state` gives
this directly - there is no excuse for not checking.

**A partly-blocked parent is not a blocked parent.** Where some children are
blocked and others are not, report the parent under `BACKLOG` with its unblocked
children named, and list only the blocked children here. Work that can be done
today must never appear under a heading that says it cannot.

### BACKLOG

Open issues grouped by repository, ordered by board Priority. Within a priority,
oldest first. Number, title, age. Say which ordering was used.

Indent children under their parent and give the parent its `completed/total`
count instead of a priority of its own. Where a parent's children are all
blocked, say so on the parent line rather than repeating it per child.

### DESIGNED, NOT STARTED

Documents with a status of design-complete, planned, or not-started, and no
ticked checklist items. Thinking already banked and never spent. This is the
section most likely to contain something worth doing today.

### LEFT BEHIND

The reason this command exists. Work that was started and interrupted, which no
other view surfaces because nothing about it is formally wrong.

Report anything matching, with the signal that flagged it:

- **A parent with some children closed and some open, untouched past the
  threshold.** Someone worked through part of a phase and stopped. This is the
  strongest signal available and replaces checkbox counting wherever a parent
  exists - `subIssuesSummary` gives `completed` and `total` directly
- A document with **both** ticked and unticked checkboxes, untouched for the
  threshold, **whose status is not terminal**. Someone was working through it and
  stopped. The terminal-status exclusion matters: a decision archive that keeps
  its original checklists for the record is not abandoned work, and without this
  it flags forever
- An open issue with no comments and no update since creation, older than the
  threshold, where the body contains an unticked checklist
- A local branch with commits, not merged, not touched within the threshold
- An issue whose `blocking` list is non-empty while it has had no activity past
  the threshold. Something is waiting on it and it has stalled

For each, state **when it was last touched and what was left undone**. Not that
it is old - the last completed step and the next unstarted one.

### STALE

Documents whose status claims a non-terminal state while no commit has touched
them within the threshold. The status line and the commit log disagree, and the
status line is the one that lies.

Give the status, the last commit date, and the gap in days.

### NOT ESTABLISHED

What this run could not determine, and why. An unreadable board, a repository
that failed to authenticate, a section skipped. **Never omit this heading.** If
everything succeeded, say so explicitly.

---

## After the sections - `-details` only

`/prime` forbids closing with an inference. **This command does not**, because
triage is its purpose - but the boundary is strict.

You may state which items are unblocked and cheapest, and you may point at a
contradiction between two sources. Label it as a reading.

You may **not** invent urgency that no section supports, reorder the backlog by
your own judgement of what matters, or present a conclusion the operator has not
seen the evidence for in the sections above.

End with recommended next steps drawn only from what is listed. Where there are
none, say so explicitly.

In summary mode this section does not apply - `START HERE` already carries the
reading, and repeating it at the end doubles the length of a report whose whole
purpose is being short.

**Both modes finish the same way**, with the two plain-prose paragraphs
described under the summary. A long report needs that close more than a short
one does, because by the end of it the reader has been handed a great deal of
data and no view.
