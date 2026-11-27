# Hooks and checks

Programmatic enforcement of rules that prose cannot guarantee.

A rule written in markdown is a request. This directory holds controls.

---

## Two mechanisms, not one

Checked 2026-09-15 against both vendors' documentation, and again 2026-09-17.

| | Cursor | Copilot / VS Code |
|---|---|---|
| Agent hooks | **Yes** - `.cursor/hooks.json` | **Yes**, since VS Code 1.135 - but see below |

An account policy can force `chat.useHooks` to `false`, and a user setting
cannot override it; "Before building anything agent-hook-shaped" below says
how to check. The VS Code hooks page ("Choose a hook source") says
`chat.useHooks` does not stop the Copilot agent harness loading hooks, so such
a policy may switch off VS Code's own hooks and leave the harness's on. Not
verified.

The distinction matters. "The feature does not exist" and "the feature exists
and is switched off for this account" lead to different decisions: the second
means VS Code hooks would work on a machine signed in without that policy, and
that any design resting on them is portable but not usable where it applies.

**Consequence:** anything that must hold regardless of tool or machine has to
be a **git hook or a CI check**, not an agent hook.

---

## `failClosed` is mandatory

Cursor permission hooks **fail open by default**. From the documentation:

> Crashes, timeouts, and non-zero exit codes other than `2` fail open by
> default: Cursor logs the failure and allows the action through.

A security hook without `failClosed: true` stops guarding the moment it breaks,
silently. That is a silent false signal wearing a safety label. Every
`permission` hook renders with it, and a source cannot set it: the fail mode
comes from `kind:` (see "Tool-neutral schema").

The scripts also deny on unparseable input rather than allowing, for the same
reason.

---

## What is implemented

A profile documents its own hooks in a `README.md` beside their seeds.

### `no-destructive-shell` - agent hook on `shell.before`

A `permission` hook, so it fails closed. Denies the shell commands that discard work, and
the ways round the pre-push gates, so the agent asks the operator first. It is the second layer behind the tool's own
approval prompt and the rule *"Never discard unfamiliar files"*.

Denies five families, with these flag variants:

- `git clean`, unless `-n`, `--dry-run` or a short cluster holding `n` is among its flags.
- `git checkout` with `--` or `.` among its arguments (`git checkout -- src/app.py`, `git checkout .`).
- `git reset --hard`.
- `rm` with a recursive flag: `-r`, `-R`, `-rf`, `-fr`, `-r -f`, `--recursive`.
- `Remove-Item` and its aliases `ri`, `del`, `erase`, `rd`, `rmdir`, and PowerShell's `rm`, with a
  `-Recurse` parameter or any prefix of it (`-r`, `-rec`), in any case.

A sixth family refuses a way round the pre-push gates, so the agent fixes the failing gate or
asks the operator:

- `git push` with `--no-verify` among its arguments. `-n` and `--dry-run` stay allowed.
- `GATE_REPORT_PUSH` set in a segment: `GATE_REPORT_PUSH=...` before a command or after
  `export`, `env GATE_REPORT_PUSH=...`, `$env:GATE_REPORT_PUSH = ...` and `Set-Item
  env:GATE_REPORT_PUSH ...`, in any case.
- `git push` with a global `-c core.hooksPath=...` (or `--config-env=core.hooksPath=...`).
- `git update-ref`, `git tag` or `git push` with an argument containing `gate-report/`, a
  hand-written report ref. Reading one (`ls-remote`, `fetch`, `show`, `for-each-ref`) stays allowed.

A name inside a message or an argument (`git commit -m "never use --no-verify"`, `echo
GATE_REPORT_PUSH=1`) is not an option or an assignment, so it is allowed.

Git's global options (`-C <path>`, `-c <key=value>`, `--git-dir`, `--work-tree`) are
skipped before the subcommand, and `sudo`, `env`, `NAME=value` and a shell keyword
(`if`, `then`, `do`, ...) before the command word.

**How it reads a command.** Not a regex over the line: a quote-aware scan that finds the
segments and judges each by its leading words. Quoted text, a PowerShell here-string
(`@'...'@`, `@"..."@`) and a bash heredoc body are not scanned, so `git commit -m "git
reset --hard was the fix"` and a commit message that opens a line with `rm -rf build` are
allowed. Segments split at `;`, `&&`, `||`, `|`, `&`, a newline, `(`, `)` and a backtick, so a
destructive segment anywhere in the line denies; a backtick before a newline is PowerShell's
line continuation and joins the lines. The same payload carries either shell's syntax, so
the scan accepts both quoting styles. A quote, here-string or heredoc that never closes
denies, naming that the command could not be read: a command that cannot be split may hide a
destructive segment.

**Scratch exemption.** A recursive delete is allowed when every target is a literal path
that resolves, against the payload's `cwd`, strictly inside `<repository root>/scratch/`.
The repository root is the nearest folder at or above `cwd` that holds `.git`. A variable, a
glob, `{}`, `~`, `..` out of `scratch/`, `scratch/` itself, a target-less delete, a `cwd` that
is absent, relative or in no repository, or a pattern parameter (`-Include`, `-Filter`, ...)
denies. The exemption covers deletes only; the git families are never exempt.

The deny's message names the matched command and says to ask the operator. Allowed:
everything else, including `rm file.txt`, `git checkout main`, `git reset --soft`, and
`Remove-Item file.txt`. `AI_TOOLBOX_HOOKS=off` allows everything.

**Known gaps** (a general shell parser is a separate piece of work): a command run through
another interpreter (`bash -c`, `pwsh -Command`, `cmd /c rd /s`); `xargs rm`; `find -delete`;
a script that deletes; a command substitution inside a double-quoted string; a bash line
continuation (backslash then newline), which reads as two segments; a Windows path in double
quotes that ends in a backslash (`"C:\dir\"`), which POSIX quoting reads as an escaped quote,
so the rest of the line is read as quoted and a later segment can be missed, or the command
denies as unreadable. `git restore`, `git checkout -f`, `git stash drop` and `git stash clear`
are not covered.

**Not yet verified live.** Library tests feed it Cursor's and Claude Code's payload shapes.
It renders for Cursor only; no adapter registers it in Claude Code yet.

### `no-generated-edits` - agent hook on `file.write.before`

A `permission` hook, so it fails closed. Denies an agent write to a file that carries the
generated-file stamp, because the next render overwrites the edit and the pre-push
self-render gate catches it only after the session has built on it.

**How it decides.** It resolves the payload's `path` (absolute, or against `cwd`), allows a
path that does not exist (a new file), and reads the file's first 40 lines, the window the
gate reads, as UTF-8 with replacement. It denies when they hold the *whole* stamp,
`generated from <source>[@<sha>] - edit the source, not this file`. The opening alone is
not enough: the example profile quotes `generated from <repo>@<sha>` in a comment, and
`sync.STAMP_RE` would deny an edit to that source file. The hook carries its own pattern,
because a rendered hook cannot import `sync.py`, and a test ties it to `sync.stamp()` in both
forms. The deny names the file and the stamp's source repository, says the file is overwritten
at the next render, and says to edit the source there and re-render. It does not map a
rendered file back to the source file it came from.

**Denied as unreadable:** an empty or non-text path, a directory, a read that raises, and a
relative path when the payload has no usable `cwd`. A file that is not UTF-8 is decoded with
replacement, so a binary file with no stamp is allowed. A file with two stamps is denied once,
naming the first. `AI_TOOLBOX_HOOKS=off` allows everything.

**Not covered:** a shell write to a stamped file (that is command-line parsing), deleting a
stamped file, and Claude Code's `NotebookEdit`, whose path key is `notebook_path`.

**Not yet verified live.** Claude Code is covered by tests that feed its documented
`PreToolUse` payload, and the hook is not registered there yet. For Cursor, the key that
holds a `Write`'s target path is not documented: the library reads `tool_input.file_path`
provisionally, and a captured `preToolUse` payload for an agent file edit must confirm that
key, and that an edit of an existing file reports the tool name `Write`, before the hook is
enabled anywhere. If either is wrong, every agent `Write` in a repository with hooks on is
denied for the missing field.

### `session-start` - agent hook on `session.start`, Claude Code only

An `observer` with `tools: [claude]`. On every session start, hooks on or off, it adds an
orientation to the session's context, through Claude Code's `SessionStart` output
(`hookSpecificOutput.additionalContext`). The response-shape rule renders on demand, so a
fresh session would not otherwise have it before its first reply. The text is up to three
lines, joined in this order into one string:

1. **Off line**, only when `AI_TOOLBOX_HOOKS=off`: "Agent hooks are OFF on this machine:
   AI_TOOLBOX_HOOKS=off is set, so no hook guards this session. Clear it to turn them back on."
2. **Shape line**, only when `.github/rules/response-shape.md` exists under the payload's
   `cwd`: read that file before the first reply, and at the start of every turn run
   `python .github/scripts/responses/check_response.py --previous` from the repository root
   and fix what it reports.
3. **Role line**, always: if the session's instructions name a role skill, load it before
   acting and do the steps it says belong on the first tool call.

A payload with no `cwd`, a `cwd` that is not a string, does not exist or is not a directory,
or a filesystem error while checking for the rule file, leaves out the shape line: the hook
never guesses the path. A repository without the rule (a target that excludes it) also gets
no shape line. Input it cannot read, or a tool other than Claude Code, writes nothing and
exits 0. It is the one hook that runs while the switch is off; see "The off switch". Cursor
is not covered.

### `write-observer` - agent hook on `file.write.after`, Claude Code only

An `observer` with `tools: [claude]`, run after `Write` and `Edit` (`PostToolUse`). When the
file the agent just wrote holds a credential shape, it adds a warning to the session's context
(`hookSpecificOutput.additionalContext`) naming the file, the line and the shape, never the
matched text. It never blocks: the write has already happened.

**Same shapes as the push gate.** The shapes live in one file, `githooks/lib/secret_shapes.py`,
which renders to each target's `.githooks/lib/`. The hook resolves the repository root from the
payload's `cwd` (`git rev-parse --show-toplevel`, else the nearest folder above it with `.git`),
loads `<root>/.githooks/lib/secret_shapes.py` by path and scans the file's lines with its
`find`. The shapes are a private key header, a bare 32-hex token, and an env-style `NAME=value`
where `NAME` ends in `KEY`, `TOKEN`, `SECRET`, `PASSWORD` or `PASSWD` and the value is long and
not a placeholder. A line carrying `secret-scan: allow` is skipped. The same module reads
`path:line: text` lines on stdin and prints `path:line: <shape>`, exiting 1 on any hit, so a
shell gate can use it too.

**Silent when:** the file is missing, a directory or unreadable; the repository has no rendered
`.githooks/lib/secret_shapes.py`; the module raises; the input cannot be read; the tool is not
Claude Code; or `AI_TOOLBOX_HOOKS=off`. It exits 0 in every case. Cursor is not covered.

### `response-check` - agent hook on `turn.end`, Claude Code only

An `observer` with `tools: [claude]`, run when a turn ends (`Stop`). It hands the hook payload
to the rendered response checker, `.github/scripts/responses/check_response.py --stop`, found
by walking up from the hook's own folder to the nearest ancestor that holds it. A reply that
fails the response shape is sent back once: the checker's findings go to stderr and the hook
exits 2. A second try (`stop_hook_active` true) is reported and never sent back again.

**It never blocks on its own failure.** With no rendered checker above the hook, a checker that
crashes or times out, or `AI_TOOLBOX_HOOKS=off`, it exits 0; the first three print why the reply
was not graded. Cursor is not covered.

### `title-prefix` - agent hook on `turn.end`, Claude Code only

An `observer` with `tools: [claude]`, run when a turn ends (`Stop`). It reads the session's
latest `set_session_title` call for `"self"` from the transcript, takes the status prefix (the
title up to the first ` - `), and grades it against the reply by the rule its vocabulary gives
that prefix:

- `ask`: the reply must carry an open ask, a line after the last reply marker, outside fenced
  code blocks, that opens with a `DC<n>`, `Q<n>` or `OS<n>` item ID, under any heading.
- `no-ask`: it must not.
- `unchecked`: it is not graded. A title that matches no entry is not graded either.

A stale prefix is sent back once: the reason goes to stderr and the hook exits 2. A second try
(`stop_hook_active` true) is reported and never sent back again.

**The vocabulary** is `prefixes.yaml`, rendered beside `hook.py`. The core ships a default of
eight entries (`needs you`, `holding pending desk`, `pending push`, `pending <name>`,
`complete`, `overnight <x>`, `parked until <x>`, `working`). An entry is `prefix` and `rule`, or
`label`, `pattern` (a regular expression matched against the whole prefix, case-insensitively)
and `rule`; the first entry that matches wins.

**A profile overrides it with the `title_prefixes` key** in its profile file, a list of entries
in that same shape. When the key is present it replaces the default whole, and sync renders it
as the target's `prefixes.yaml`; when it is absent the core's default renders. Sync refuses a
profile file whose list is empty or whose entry is not exactly `prefix` and `rule` or `label`,
`pattern` and `rule`, whose rule is none of the three, or whose pattern is not a regular
expression, naming the entry. There is no file-level override: a profile seed whose name
matches a core hook is refused.

**It never blocks on its own failure.** An unreadable payload or transcript, a missing or
unusable `prefixes.yaml`, or `AI_TOOLBOX_HOOKS=off` exits 0; the first three print why the
title was not graded. Cursor is not covered.

### `no-shell-file-edits` - Cursor hook, not shipped

**Not rendered.** In Cursor it denied every agent `git commit` with "Blocked:
shell redirection writing to .", and fighting it cost more than it guarded.
Its `hook.yaml` is deleted, so `sync.py` renders nothing for it; `hook.py` and
its tests stay for the fix. The rule it enforced is prose again.

`beforeShellExecution`. Denies commands that edit a file in place, so edits go
through tooling that produces a reviewable diff.

Blocks: `sed -i`, `perl -i`, `ruby -i`, `truncate`, `ed -s`, shell redirection
into a real path, `tee` to a real path, and the PowerShell writers `Set-Content`,
`Add-Content`, `Out-File`, and `New-Item` with `-Value`, to a real path.

Allows: `/dev/null`, `$null`, `/tmp/...`, `.log` / `.tmp` / `.out` / `.bak`
targets, file descriptor redirects, `New-Item` without `-Value`, and everything
that is not a write. PowerShell aliases (`sc`, `ac`) are not matched - `sc` is
also `sc.exe` in Windows PowerShell 5.1.

Source was `hooks/no-shell-file-edits/hook.yaml`. `sync.py` merges every
`hook.yaml` into the target's `.cursor/hooks.json`, with `failClosed` from its
`kind:`, and refuses to overwrite a `hooks.json` it did not write.
Off by default: a target opts in with `hooks: true` in its profile. One broken
fail-closed guard once denied every shell command, the compliance check
included, and only deleting `hooks.json` and reloading the window recovered.

Unit-tested 2026-09-15, 14/14 cases, no false positives on `git status`,
`docker ps 2>/dev/null`, `npm test > /tmp/results.log`, or `tee /tmp/debug.log`.
Malformed input denies. Those tests handed `main()` a string, so they never saw
real stdin: the first live run, 2026-10-09 on Windows, denied every command as
unparseable. The cause was very probably, not provably, Cursor sending hook payloads on Windows prefixed with a UTF-8 byte-order mark (`EF BB BF`). Scripts reading from `sys.stdin` using `json.load()` crashed because the standard decoder did not strip the BOM. Both hooks now read bytes and decode with `utf-8-sig`, and `tests/test_hooks.py` `HookInput` feeds them bytes.

Enforces: *"Never edit a file by running a terminal command unless asked to."*

### `no-secret-defaults` - git hook and CI check

**Not** an agent hook. It must catch every commit, including ones made without
an assistant, which is where two of the three known instances came from.

Flags a secret given a fallback: JS/TS `??` and `||`, Python `getenv` /
`environ.get` defaults, typed field defaults, and `${SECRET:-default}` in shell
or Compose.

Deliberately does **not** flag:

- `${VAR:?message}` - the correct required form
- `${API_KEY:-}` - empty passthrough where the consumer validates
- Non-secret defaults such as a host, port, or timezone

An empty Python default **is** flagged. `os.getenv('PASSWORD', '')` is one of the
known instances, and an empty secret is as dangerous as a
missing one.

Escape hatch: `no-secret-defaults: allow` on the line.

Tested against real code from the backlog - 6 findings, zero false positives,
zero false negatives.

Install as `.git/hooks/pre-commit`:

```bash
#!/bin/sh
python3 scripts/no-secret-defaults/check.py || exit 1
```

And in CI with `--all`.

---

## What does not belong here

**Anything requiring judgement.** A hook that blocks a legitimate action is
worse than a rule occasionally forgotten, because the workaround becomes
turning hooks off.

Worked example. A prescription says *never state a fact about a repo without
opening the file*. It was resident, loaded, and violated - a false claim about
how a service's accounts were provisioned reached a committed README and a
closed issue.
Could a hook have caught it?

Only by tracking every entity named in a session and blocking any write
asserting something about an entity no command had returned. That would have
fired here. It would also fire constantly on ordinary prose, and be disabled
within a day.

**The durable fix was structural**: stop writing facts that a command already
produces. The README now names the command that lists the accounts and says
how to read its output, instead of listing them. A statement that does not
exist cannot be wrong.

That is the dividing line. Enforce the mechanical. For the rest, remove the
class of statement that can be wrong.

---

## Not yet built

**No-emoji.** Already enforced by lint in some repos. Consolidating into one
checker would remove the per-repo scripts.

---

## Before building anything agent-hook-shaped

Check whether hooks are available at all on the machine in question:

```
Ctrl+Shift+P  ->  Developer: Policy Diagnostics
```

Look for `ChatHooks` / `chat.useHooks`. If it is listed under **Applied Policy**,
agent hooks are off and cannot be turned on locally.

This is worth one command before any design work, because a policy delivered
through the signed-in account leaves **no local artifact** - not in the registry,
not in `managed-settings.json`, not on disk anywhere. Checking those three places
returns clean and reads as permission. It is not.

## Agent hook design (Cursor)

This applies specifically to the `.cursor/hooks.json` implementation.

### The BOM requirement
Cursor sends hook payloads on Windows prefixed with a UTF-8 byte-order mark (`EF BB BF`).
Scripts reading from `sys.stdin` using `json.load()` will crash because the standard `utf-8` decoder (or the default locale code page) does not strip the BOM, rendering the JSON unparseable.

**The fix:** Read the bytes and decode with `utf-8-sig` before parsing. This was very probably the cause of the outage in which the hooks denied every shell command because their parser broke - sufficient to explain it, not proven.

### The interpreter is per machine
A `hook.yaml`'s `run:` opens with `{python}`, quoted in the YAML because a bare `{` starts a mapping. `sync.py` fills it with the interpreter running `sync.py`, absolute and quoted: `& "<python>" ...` on Windows, where Cursor runs hooks through PowerShell, and `'<python>' ...` elsewhere. A bare `python`, `python3` or `py` is refused: once a Windows checkout's first `python3` was an extensionless `sh` shim, no hook could start, and every shell command was denied. A render from inside a virtual environment is refused, and so is one from WSL into a Windows folder under `/mnt/<drive>/`.

So `.cursor/hooks.json` names one machine's interpreter. It is ignored and untracked in every target, and `--check` never compares it; the scripts under `.cursor/hooks/` stay tracked. Each machine renders its own with `sync.py --write` (`--self --write` in the profile repository).

**After pulling the commit that untracked it,** git deletes `.cursor/hooks.json` from the working tree, and no hook runs until the next render. Re-run `sync.py --write` there.

**When a hook stops launching** - every shell command denied with "returned no output" - the interpreter it names has moved or gone. Re-run `sync.py --write` with the interpreter you want, or delete `.cursor/hooks.json` and reload the window to run without hooks until you do.

### Every write launch-checks the interpreter first
Before `sync.py --write` writes `.cursor/hooks.json`, it runs each hook's rendered interpreter with `-c pass` in place of the script, under the shell Cursor will use: `powershell.exe` on Windows, and `pwsh` as well when it is installed, because Cursor does not say which PowerShell it runs; `sh` elsewhere. Each launch has a timeout. Every `--write` re-checks, including one that changes nothing, so re-running it re-verifies a machine whose interpreter has since moved. `--check` writes nothing, so it runs no launch, and with hooks off there is no `hooks.json` to check.

**When it refuses,** it names the command, the shell, the exit code and the output, and writes nothing in that repository - the existing `hooks.json` stays as it was. It never tries a fix. Run the named command by hand under the named shell to see why, then re-run `sync.py --write` with an interpreter that starts.

A hook whose `run:` does not open with `{python}` has no rendered interpreter to probe. It is printed as `not launch-checked` and rendered anyway.

## Claude Code adapter

When `hooks: true` and `claude` is among the profile's tools, `sync.py` renders `.claude/settings.json`: the hook entries, and the profile's permission rules (see the core `README.md`, "Claude Code settings"). The file is committed and `--check` compares it, because it names no machine. It carries a top-level `_generated` key, and a `.claude/settings.json` without that key is hand-written, so sync refuses to overwrite it. Move its entries to the gitignored `.claude/settings.local.json`, which Claude Code merges in. The scripts and `lib/` render under `.claude/hooks/`.

- **`{hooks}` in `run:`** is each adapter's own scripts folder: `.cursor/hooks` for Cursor, `${CLAUDE_PROJECT_DIR}/.claude/hooks` for Claude Code. Cursor still accepts a literal `.cursor/hooks/` path, because profiles carry one. The Claude Code adapter refuses an argument that starts with `.cursor/`, naming the file and asking for `{hooks}`.
- **The command** is `python "${CLAUDE_PROJECT_DIR}/.claude/hooks/<name>/<script>" <args> --tool claude`. The double quotes let the shell expand the variable. Hooks run under bash, so arguments are quoted for it.
- **The interpreter rule.** `{python}` renders as bare `python`, resolved from `PATH` on each machine, because a committed file cannot name one machine's interpreter. The Cursor adapter's refusal of a bare interpreter is unchanged. A Linux machine that ships only `python3` (Debian, for one) needs a `python` on `PATH`, for example from the `python-is-python3` package. Without it no hook can launch, and every permission hook blocks its tool.
- **The launch probe.** Before `--write` writes a `.claude/settings.json` that has hook entries, it runs `python -c pass` the way Claude Code launches a hook: through `bash -c` on Windows (refusing, with the reason, when `bash` is not on `PATH`), through `sh -c` elsewhere, with a timeout. On a failure it refuses, writes nothing, and names the command, the shell, the exit code and the output. `--check` runs no probe.
- **Events** map as `session.start` to `SessionStart`, `shell.before` to `PreToolUse` on `Bash|PowerShell`, `file.write.before` to `PreToolUse` on `Write|Edit`, `file.write.after` to `PostToolUse` on `Write|Edit`, and `turn.end` to `Stop`. There is no `reply.after`, so a hook on it must leave `claude` out with `tools:`.
- **Fail mode.** A `permission` hook gets `"onFailure": "block"`, so a hook that cannot run blocks the action; an `observer` gets none. Entries with the same event and matcher share one matcher group, in hook-name order.

## Tool-neutral schema

The rationale and rejected options are in `DECISIONS.md`, "A tool-neutral
schema, and the off switch". Every `hook.yaml` is in this shape, and the old
`command:` / `failClosed:` keys are refused by name. The Cursor and Claude Code
adapters render; Copilot's and OpenCode's are not built yet.

```yaml
event: shell.before
kind: permission
run: ["{python}", "{hooks}/<name>/hook.py", "--owner", "{owner}"]
timeout: 10
tools: [cursor, copilot]   # optional; default is every adapter
```

- **`run:` is an argument list.** Each tool's adapter quotes it: Cursor joins it for
  the machine's hook shell, as it does for `{python}`; the Copilot
  harness takes it as `exec` + `args`, with no shell.
  Cursor's join leaves an argument bare when it is only letters, digits and
  `_ . / : = + -`; anything else is single-quoted, PowerShell doubling a quote and
  POSIX as `shlex.quote`. So a plain hook renders the same command it did before.
- **`kind:` sets the fail mode.** A `permission` hook fails closed, an `observer`
  fails open. There is no per-hook override. Cursor's entry carries `failClosed`
  either way, `false` written out for an observer.
- **Events are neutral**, mapped by each adapter:

| Neutral | Cursor | Copilot harness |
|---|---|---|
| `session.start` | `sessionStart` | `sessionStart` |
| `shell.before` | `beforeShellExecution` | `preToolUse`, tool `bash` / `powershell` |
| `file.write.before` | `preToolUse`, matcher `Write` | `preToolUse`, tool `edit` / `create` |
| `file.write.after` | `afterFileEdit` | `postToolUse` |
| `reply.after` | `afterAgentResponse` | none documented |
| `turn.end` | `stop` | `agentStop` |

  A hook whose event a targeted tool lacks is refused at render, unless its `tools:`
  leaves that tool out. A silent skip would render as guarded with nothing guarding.
  `tools:` defaults to every tool in the table, so a `reply.after` hook must say
  `tools: [cursor]`. Copilot's column is in `sync.py` as validation only until
  its adapter is built.

  **Not verified live:** Cursor's `Write` matcher on `preToolUse`. It renders per the
  table, and `no-generated-edits` is the hook that uses it; its first live run checks it.
- **A shared runtime library**, `hooks/lib/hookio.py`, rendered to
  `.cursor/hooks/lib/` whenever any hook renders. A hook puts the folder beside its
  own on `sys.path` and calls `run_permission(name, event, decide)` or
  `run_observer(name, event, observe)` (whose `observe` may return a warning), or, for a hook that only reports the off switch,
  `run_notice(name, event, notice)`. The library reads stdin as bytes (BOM and
  UTF-16 handled), hands the hook a neutral payload - `event`, the event's fields
  (`command` and `cwd` for `shell.before`, `path` and `cwd` for `file.write.before`),
  `model`, `model_id`, `model_params`, and `raw` - and writes the tool's output. `session.start` has no fields
beyond those. An
  absent optional field is `None`; an absent required one (`command`, `path`) is not
  passed on. Input it cannot parse denies a permission hook and is skipped by an
  observer. `shell.before`'s, `file.write.before`'s and, for Claude Code only,
  `file.write.after`'s fields are mapped; each other event's are mapped when its first hook
  lands.
  `no-shell-file-edits` keeps its own reader until it is fixed.
- **An observer may return a warning.** `observe` returns `None` to say nothing, or text that
  `run_observer` writes through a per-tool table (`OBSERVER_WRITERS`). It reaches the agent
  where the tool supports it: for Claude Code, `hookSpecificOutput.additionalContext` under the
  event's own name (`file.write.after` is `PostToolUse`). It is never a block. A tool with no
  entry (Cursor) gets nothing, and the off switch silences it before the hook reads anything.
- **The tool is an argument of the hook's command line**, `--tool <name>` or
  `--tool=<name>`, passed by the adapter that renders the hook. The library keeps a
  table per tool of where each neutral field sits in the payload and how a verdict is
  written; a new tool is a new table entry. The Cursor adapter appends `--tool cursor`
  to every `run:`. With no `--tool` the library behaves as Cursor, so a hook rendered
  before the argument existed keeps working until it is re-rendered.

  | Tool | `command` | `cwd` | Allow | Deny |
  |---|---|---|---|---|
  | `cursor` | top-level `command` | top-level `cwd` | `{"permission": "allow"}` | `{"permission": "deny", "user_message": ..., "agent_message": ...}` |
  | `claude` | `tool_input.command` | top-level `cwd` | no output, exit 0 (Claude Code's normal permission flow decides) | `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": <agent message>}}`, exit 0 |

  For `file.write.before` the neutral fields are `path` and `cwd`:

  | Tool | `path` | `cwd` |
  |---|---|---|
  | `cursor` | `tool_input.file_path` - **unverified**: Cursor documents no key for a `Write`'s target, so this is Claude Code's, until a captured `preToolUse` payload confirms or corrects it | top-level `cwd` |
  | `claude` | `tool_input.file_path`, absolute, for `Write` and `Edit` | top-level `cwd` |

  `file.write.after` has the same two fields for `claude`, from the `PostToolUse` payload, which
  carries the same `tool_input`. Cursor's are not mapped.

  Claude Code's shapes are from its hooks documentation (`PreToolUse` on the `Bash`,
  `Write` and `Edit` tools), and seen live (see "Live checks, Claude Code"). A required field that is absent, or a
  `tool_input` that is not an object, denies a permission hook with a message naming
  the field, and skips an observer. An empty-string command is a command. An unknown
  tool has no verdict shape, so a permission hook denies it by exit code 2 with the
  reason on stderr, which blocks in every tool; an observer is skipped.
- **Copilot's timeouts fail open for every event**, permission hooks included. Its
  permission hooks render anyway, and each rendered entry and this file say so: a
  guard that fails open only on timeout still guards every call that finishes.
- **Copilot's rendered file under `.github/hooks/` is local per machine**, ignored
  and untracked, for the same reason as `.cursor/hooks.json`.

### The off switch
`AI_TOOLBOX_HOOKS=off`, set at setup as a user environment variable. The shared
library reads it at run time: a permission hook allows and an observer does nothing.
The value is trimmed and case-folded, and anything but `off` leaves hooks on.
Built in `hookio.py`.

Set or clear it with `python setup_profile.py --hooks off` (or `--hooks on`; from a
profile, `toolboxctl setup --hooks off`). That does only the machine switch: no profile
questions and no `profile.yaml` write. It prints what it will write, and writes only
after a typed `yes`.

- **Windows:** `AI_TOOLBOX_HOOKS=off` as a string value in `HKCU\Environment`, then a
  `WM_SETTINGCHANGE` broadcast so newly started processes see it. `--hooks on` deletes
  the value. A failed broadcast only warns.
- **Linux and other POSIX:** a marked block in `~/.profile`, created if missing and
  written once however often it runs. `--hooks on` removes the block and leaves the rest
  of the file as it was.

  ```sh
  # >>> ai-toolbox hooks switch >>>
  export AI_TOOLBOX_HOOKS=off
  # <<< ai-toolbox hooks switch <<<
  ```

  Setup refuses, and writes nothing, when a login shell would not read `~/.profile`:
  a `~/.bash_profile` or `~/.bash_login` that does not source it, or a zsh login shell.
  It names the reason and the line to add by hand (`export AI_TOOLBOX_HOOKS=off`, to
  that file or to `~/.zprofile`).
- **Restart the tool** after either change: a running process keeps the environment it
  started with. On Linux, start it from a new login shell.

Hooks still render, so running `sync.py` cannot change the state, and a hook process
inherits the tool's environment rather than the agent shell's. Neither tool documents
the second; it is checked live for Claude Code (see "Live checks, Claude Code").

**`session-start` is the one hook that still runs while the switch is off.** It enters the
library through `run_notice`, which the switch does not gate, and it is meant only for a hook
whose job is to report the switch. Every other hook goes quiet when the switch is off, so
without it nothing would tell a session that its guards are off. It tells the session the
hooks are off, and the prime report carries the same line.

### Live checks, Claude Code

Recorded with Claude Code 2.1.325. The runs were headless (`claude -p`), in a profile repository whose committed `.claude/settings.json` registers `session-start`, `no-destructive-shell`, `no-raw-gh` and `no-generated-edits`. Each was run against a control: the same steps with the switch unset.

| Check | Windows 11 | Linux (Debian, under WSL) |
|---|---|---|
| A bare `gh` call is denied by `no-raw-gh`; the passthrough script is not | pass, 2026-11-16 | pass, 2026-11-16 |
| `no-destructive-shell` denies `git reset --hard` and `git checkout -- .`; `no-generated-edits` denies an edit to a stamped file and allows its source | pass, 2026-11-16 | `no-destructive-shell` pass, 2026-11-16 |
| `sed -i`: no rendered hook guards it; it is carried with `no-shell-file-edits` | not applicable | not applicable |
| `AI_TOOLBOX_HOOKS=off`: `session-start` shows the line, the guards stop denying, prime shows the line | pass, 2026-11-16 | pass, 2026-11-16 |
| The hook inherits the tool's environment: the agent shell clears the variable in the same command, and the guard still stays quiet | pass, 2026-11-16 | pass, 2026-11-16 |

A permission rule is separate from a hook. A `deny` rule for a command still applies while the switch is off. In a folder whose trust prompt was never accepted, a project's `allow` rules were not applied, but its `deny` rules and hooks were (Linux, 2026-11-16; cause inferred, not confirmed).
