# Decisions

Why the core is built the way it is. Each entry records a choice and the
alternatives it ruled out, so that they are not proposed again. A profile keeps
its own decisions file for the specifics behind these: who ruled, when, and on
which ticket.

---

## Evidence

### A resident, loaded rule can still be broken

The always-resident prescriptions say never to state a fact about a repo without
opening the file. In the first repository to receive the rendered rules, with
those rules loaded and in context, an assistant asserted from memory how a
service's accounts were provisioned. It was false, one command would have
settled it, and the claim reached a committed README before a person caught it.

That separates two failure modes that are easy to conflate:

| Mode | Fixed by |
|---|---|
| Rules not present | Rendering them everywhere |
| Rules present, loaded, not followed | Not rendering - verification |

**More surface is not more safety.** Widening distribution extends a mechanism
that has visibly failed at full coverage. Verification comes before reach.

### Hand-written derivable facts go stale immediately

The corrected README carried a table of which accounts reconcile - a derived
fact written down, wrong again the next time one changes. It was replaced with
the command that produces it, plus the interpretation that does not follow from
the output. **An enumeration is derivable; what it means is judgement.** Write
the second, derive the first.

---

## Rules and rendering

### Resident line count is a validation signal, not a goal

The resident footprint exists to catch a design that claims to be conditional
while being resident. It is not a target. **Do not make changes for the purpose
of keeping the number down.** Moving content somewhere it is never read improves
the metric and degrades the rules. If a rule must be resident to work - one that
has to fire before work begins cannot be one that is looked up first - it is
resident and the number goes up.

### Only `**` attaches. Every other scope is advertisement

Tested in Copilot and Cursor against a throwaway fixture, each rule body
demanding a unique nonce be echoed back.

| Scope | Body reaches the model |
|---|---|
| `applyTo: '**'` / `alwaysApply: true` | Yes, every request |
| `**/*.py`, `**/*.{ts,tsx}`, directory globs | **No. Never, in either tool** |

Copilot's debug export shows the roles are distinct: a glob-scoped file appears
as a file name plus its description - an advertisement - and only `**` appears
as an attachment carrying the body. Opening a matching file first changes
nothing, which rules out task-scoped loading. Both tools agree.

**Consequence:** the language specs are advertised, never resident.
Registration was once mistaken for loading; they are different events.

**Globs stay.** `scope` still decides where a spec renders, so stripping it
would make the specs less reachable, not more. It also records intent, and both
vendors document glob attachment as intended behaviour, so anything already in
place becomes live if they fix it.

**Known risk:** everything outside the prescriptions is read only when an agent
chooses to open it. The routing table says so rather than implying otherwise.

### Reading a file already normalises line endings - do not "fix" it

A CRLF bug was reported in the renderer and did not exist. `Path.read_text`
opens in universal-newline mode, so a rendered file read back from a Windows
working tree compares equal to freshly rendered content, and the comparison in
`emit` is already correct. Established by test, not by reasoning - the
reasoning is what produced the false report. A second normalisation pass risks
breaking a comparison that works.

### The prescriptions are duplicated into every repo on purpose

`AGENTS.md` is the only cross-vendor surface, and it is per repository.
Generated, SHA-stamped, CI-verified duplication is a build artifact, not the
defect the core exists to fix; the defect was unmanaged duplication. It also
means the prescriptions need no editor-specific sync: git is the cross-machine
mechanism.

### The render is not the guarantee; the check is

A pull-based render alone lets a repository fall behind silently, which is the
original problem at a slower tempo. The check that compares the stamped SHA
against the source's head is what makes drift loud.

### A repository's own instructions are never generated

Each repository's hand-owned instruction file stays hand-owned, and the renderer
never writes it. If generated and hand-written content mix in one file, the
generated files stop being trustworthy and the whole mechanism decays.

### Rendered Cursor output is tracked

`.cursor/` was once untracked wholesale on the grounds that rendered output does
not belong in a repository. It was never applied consistently - rendered
`.github/` output stayed committed - and it cost three things: a fresh clone had
no Cursor rules until someone rendered, the drift check could not see Cursor at
all, and rendered agent hooks would have shipped the same gap.

Tracked: `.cursor/rules/`, `.cursor/skills/`, `.cursor/hooks/` and
`.cursor/hooks.json`. Everything else under `.cursor/` stays ignored, because
Cursor writes machine and credential state there - `mcp.json` is where an MCP
token lives. `ensure_cursor_tracked` writes that allowlist into every target. A
re-include beneath a blanket directory ignore cannot work, because git never
descends into an excluded directory.

**Rejected: a per-clone switch for each tool's output.**

- Output for one tool is inert in every other. Only Cursor reads `.cursor/`, and
  only Copilot reads `.github/instructions/`.
- A switch in the renderer is worse than none. CI checks the tracked set for
  drift, so a rollout from a clone with a tool switched off commits stale output
  and turns CI red.
- A switch that changed hook behaviour would let an agent disable its own guard
  with one `git config` line.

Which tools a repository receives at all is a committed, per-target choice in
the profile, not a per-clone one.

### The profile's own render stamps no SHA

**Decided 2026-11-09.** Operator ruling. It replaces the 2026-11-08 direction of one stamp index.

Every rendered file used to carry `generated from <source>@<sha>`. Two branches that each changed any source input re-stamped every rendered file with a different SHA, so each merge of main conflicted on about 118 files, and on nothing else. Nothing reads that SHA back. Every reader tests only whether a stamp is present, and the drift check compares whole files. So the profile's own render now writes `generated from <source> - edit the source, not this file`, which is the same on every branch. A consuming repository's render keeps the SHA, because that stamp is the only record of which source version the repository holds, and a consuming repository never self-renders.

Rejected:

- **One stamp index.** It shrinks the conflict from about 118 files to one, but that one file still changes on both branches, so GitHub still marks the PR CONFLICTING. The cost was always the round trip of re-merging and pushing, not the number of files, and one conflicting file costs that round trip as surely as 118 do.
- **A merge driver.** It lives in local git config, and GitHub's mergeability check never runs it.
- **A `sync.py` merge subcommand.** It doesn't help a merge in the GitHub web UI, and it's one more command to remember.
- **Self-render on main after merge.** It moves rendering into CI and works against the pre-push `self-render` gate, whose job is to keep a branch's output current.

The cost that's left: an aggregated rendered file, such as `AGENTS.md`'s tables or `repos.json`, can merge cleanly as text and still differ from a fresh render of the merged sources. The drift check on the push to main catches that, and one self-render fixes it.

---

## Agents

### Personas are out; role agents are allowed

A persona - an agent that changes only tone - was tried and caused more problems
than it solved. A persona is out, permanently.

- A **role agent** states a job, what is expected of it, and its pass criteria.
  Allowed.
- Where a requirement can be enforced by withholding a tool, withhold it. Where
  it cannot, the definition names which requirements rest on trust.
- A role agent complements mechanical checks, never replaces them. Checking AI
  output with AI keeps its blind spots - see the rejected `verifier` in
  `agents/README.md`.

An earlier form of this rule said every agent must remove or constrain a
capability. That generalised from the tone-only case to every agent, and a role
spec plus a tool restriction is a working agent that it would have ruled out.

---

## The core and its profiles

### The boundary

**The bar for the core is relevance and portability.** Someone else must be
able to use it, or take it elsewhere, with nothing irrelevant to them in it: no
work data, no build context - machine, accounts, how one person separates work
from personal - and nothing specific to one profile. Method, vocabulary and
generic rationale stay.

**Core:** the renderer and its tests, and the profile *schema*, not its
content. The rules, specs, agents and skills that describe method, with
provenance moved to the profile. The response checker, the gate runner and its
libraries, and the agent hooks. `patterns/`, as generic patterns.

**Profile:** the estate map, the profile's content, ticket tooling, every
specific gate, the CI layer, skills and agents tied to particular hosts or
services, any work/personal boundary rules, and the header art as a
requirement.

**Rejected: ticket tooling as core**, with or without its triage scheme moved to
configuration. Anything more than a loose wireframe of general concepts bleeds
one tracker's shape into every profile. A profile may need Jira by API, Jira by
MCP, ServiceNow, or something not yet known, so the core carries a wireframe of
concepts only - `capabilities/tracker.yaml`.

**Rejected: the gates as profile-only, with the core carrying a written
wireframe.** Proposed on the premise that the gates were CI jobs. They are git
pre-push hooks, which every profile shares. The runner is core and every gate is
profile, and gates carry feature flags set only by the operator or at setup, as
committed profile data. The exception is the one-way gates: core mechanism,
profile data.

**Rejected for provenance: keeping it in the core, or deleting it.** Kept, it
carries build context and one profile's specifics into the core. Deleted, the
reasoning for why each rule exists is lost. So the reasoning is here, and the
specifics are in the profile.

### The core runs without profile code

The renderer loads a profile module only when the flag needing it is used, and
refuses in one line when that module is absent. Profiles supply scripts,
workflows and actions as seed kinds, merged like every other kind.

Two things stay out of the core's first version because they are built around
one operator's setup: a phone-driven approval queue, and an unattended build
harness's rules. A generic version of either may come to the core later,
written here fresh rather than pushed from a profile.

File headers in the core keep their author's signature. The art is not a
requirement for any other profile. The core is MIT-licensed.

### A profile pins the core by a vendored copy

The core is vendored into a profile as a copy with a SHA stamp, fetched by the
renderer. There is no git path from a profile back to the core, so "never
pushes upstream" holds by construction. It matches the render stamp, and the
pinned SHA is checkable in CI.

- **Rejected: a clone with an `upstream` remote and the push URL disabled.**
  Core and profile share one tree, every update is a merge, and the push block
  is a gate rather than an absence.
- **Rejected: a git submodule.** A clean pin, but a push from inside the
  submodule still reaches the core.
- **Not argued for: a pip package.** A version pin rather than a SHA.

A no-upstream-push gate is kept regardless, as a backstop for a remote added by
hand.

### Core work happens in the core repository, released by tag

Once a profile vendors the core, its `core/` is a read-only copy, the same way
rendered repositories consume rules and edit none of them. Core work goes to the
core repository.

The core keeps strict `dev` and `main` branches. Work lands on `dev`; a release
is a pull request to `main` and a `vX.Y.Z` tag. Profiles update by choice:
`toolboxctl check` lists newer tags, and `toolboxctl update` vendors one.
Nothing updates on its own.

**Rejected: offline vendoring from a downloaded archive.** Every place a copy is
expected to live can reach GitHub. If one cannot, that is solved when it exists.

**Rejected: continuing core work in a profile and carrying each change across.**
Every core change would need its own transfer.

### Parent-folder Cursor workspaces are not supported

A Cursor window opened at the folder holding every clone has no `AGENTS.md` or
`.cursor/rules/` of its own, and rules reach a session only through the
repositories open in it. Multi-root workspaces, with each repository added
directly, are the supported shape.

**Rejected: a resident rule set in the parent folder.** The folder is not a
repository, so nothing versions or drift-checks the copy.

**Rejected for now: a Cursor plugin.** It would reach every workspace, but adds
a delivery mechanism to fix a shape nobody uses.

---

## Agent hooks

### A tool-neutral schema, and the off switch

Which hooks ship is in `hooks/README.md`; this records why the schema is the
shape it is. It is tool-neutral so one source extends to tools beyond Cursor and
VS Code. A hook declares `run:` as an argument list, `kind:` permission or
observer, and a neutral event. One adapter per tool renders it, and a shared
library normalises the payload at run time.

**Rejected: denying writes outside the workspace or to the system temp
directory.** The write half is checkable, but a shell redirect to the temp
directory needs command-line parsing, the class of check that broke the
shell-file-edit hook.

**Rejected: a `command:` string.** Quoting it per shell has to be solved per
machine, and a bare `{` reads as a YAML mapping. An argument list leaves quoting
to the adapter, and the Copilot harness takes one natively.

**Rejected: a per-hook `fail:` field.** The fail mode was wanted tool-neutral,
which `kind:` also gives, and a mode derived from the kind of hook cannot be set
wrong.

**Rejected: refusing permission hooks for Copilot**, whose timeouts fail open
for every event. That leaves nothing guarded. A guard that fails open only on
timeout still guards every call that finishes, so the gap is stated wherever the
hook renders instead.

**Rejected: skipping a hook silently for a tool that lacks its event.** That
renders as guarded with nothing guarding. It is refused at render, unless the
hook's `tools:` leaves the tool out.

**Rejected: a committed Copilot hooks file naming a bare `python`.** A bare
`python3` once resolved to a shim and took every hook down. The file is local
per machine, like `.cursor/hooks.json`.

**Rejected: an off switch read by the renderer at render time.** An agent can
run the renderer from a shell with the variable unset and change the state.
Read at run time, the switch follows the tool's environment, and the
session-start hook, which runs regardless, makes a switched-off machine
visible.

---

## Skills and their tools

### The exchange lock is never broken by an agent

Several chats working in one repository at once coordinate through an append-only
log. A write takes a lock file by exclusive create, appends, and reads the log back
to check that everything above the new entry is unchanged. A lock still held after
the wait is refused with its holder named. An agent never removes it.

An append takes milliseconds, so a lock that outlives the wait usually means its
writer died. An agent cannot tell that from a writer that is only slow, and removing
a live writer's lock lets two appends race, which is the loss the lock exists to
stop. Removing it is a person's decision.

**Rejected: breaking a lock after a timeout.** It guesses that the holder is dead.
If it is not, the two appends race again.

**Rejected: writing the log with an editor tool.** A read followed by a write loses
an entry appended between the two, and every write must go through the tool.

**Rejected: keeping a backup of the log.** A backup can only restore by overwriting
whatever was appended since it was taken. The tool's read-back is the check a backup
used to provide.

### The spec gate checks shape, not sense

The gate refuses a spec that lacks a required section, repeats one, leaves one empty,
leaves a placeholder, cites no `path:line`, or names an edge-case category with
neither a case nor `N/A` and a reason. It cannot judge whether what is written is
true: "Boundary values: N/A: none" passes. That is the design. The gate makes a vague
spec more expensive to write and never impossible, and passing it is the floor for
calling a spec ready, not the bar. A spec the gate could not read exits with its own
code and is never reported as a pass.

### Cleanup refuses rather than discards

A workstream's files live in `scratch/<objective>/`, and that directory is the
inventory. The cleanup tool lists what it would remove - files, worktrees and the
branches they hold - and changes nothing. With `--apply` it removes them in one call.

It refuses the whole run, removing nothing, when any worktree is dirty, when any
work is not merged into the remote's default branch, when the default branch cannot
be determined, when the name is not kebab case or resolves outside `scratch/`, or
when it is run from inside the directory it would remove. Local `main` ahead of the
remote is unshipped work, so merged means merged into the remote ref. An unreadable
status or an unknown default branch is a refusal, never a clean result.

**Rejected: deleting files one at a time.** Each delete is its own approval card. One
call at the end of the workstream is one card.

**Rejected: assuming the default branch.** A guess decides what counts as merged,
and a wrong guess discards work.
