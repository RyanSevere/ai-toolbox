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

**Generated files are read-only.** Refuse edits to any file carrying the
`generated from <source>` stamp and point at the source instead. Protects the
mechanism from its most likely decay path. Needs `preToolUse` with a `Write`
matcher, which is untested here.

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

## Tool-neutral schema

The rationale and rejected options are in `DECISIONS.md`, "A tool-neutral
schema, and the off switch". Every `hook.yaml` is in this shape, and the old
`command:` / `failClosed:` keys are refused by name. Only the Cursor adapter
renders; Copilot's and OpenCode's are not built yet.

```yaml
event: shell.before
kind: permission
run: ["{python}", ".cursor/hooks/<name>/hook.py", "--owner", "{owner}"]
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
  table and is checked by the first hook that uses it.
- **A shared runtime library**, `hooks/lib/hookio.py`, rendered to
  `.cursor/hooks/lib/` whenever any hook renders. A hook puts the folder beside its
  own on `sys.path` and calls `run_permission(name, event, decide)` or
  `run_observer(name, event, observe)`. The library reads stdin as bytes (BOM and
  UTF-16 handled), hands the hook a neutral payload - `event`, the event's fields
  (`command` and `cwd` for `shell.before`), `model`, `model_id`, `model_params`,
  and `raw` - and writes Cursor's output. An absent field is `None`. Input it
  cannot parse denies a permission hook and is skipped by an observer. Only
  `shell.before`'s fields are mapped; each other event's are mapped when its first
  hook is seen live. `no-shell-file-edits` keeps its own reader until it is fixed.
- **Copilot's timeouts fail open for every event**, permission hooks included. Its
  permission hooks render anyway, and each rendered entry and this file say so: a
  guard that fails open only on timeout still guards every call that finishes.
- **Copilot's rendered file under `.github/hooks/` is local per machine**, ignored
  and untracked, for the same reason as `.cursor/hooks.json`.

### The off switch
`AI_TOOLBOX_HOOKS=off`, set at setup as a user environment variable. The shared
library reads it at run time: a permission hook allows and an observer does nothing.
The value is trimmed and case-folded, and anything but `off` leaves hooks on.
Built in `hookio.py`. Setting it at setup, and the `session.start` line, are
separate work.
Hooks still render, so running `sync.py` cannot change the state, and a hook process
inherits the tool's environment rather than the agent shell's - the second is
documented for neither tool and is the first thing the build checks live. The
`session.start` hook runs regardless and tells the session the hooks are off, and
the prime report carries the same line.