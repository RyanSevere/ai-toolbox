---
id: shell
tier: 2
scope: "**/*.sh"
alwaysApply: false
description: >-
  Shell SPECIFICATION - safety flags, idempotency, honest reporting, input
  validation. Covers why all three of set -euo pipefail are needed rather than
  -e alone, the sudo test pattern for root-owned files that a readability test
  silently fails, verifying an outcome rather than trusting an exit code,
  validating every externally supplied value, and the ShellCheck findings worth
  acting on. Auto-attaches when writing or reviewing shell. Binding one-line
  rules are in prescriptions.md.
---

# Shell

## Safety flags

```bash
set -euo pipefail
```

All three, not just `-e`. Several scripts in this estate use `set -e` alone,
which means an unset variable expands to nothing and the script carries on with
a wrong value. In a VPN pause or resume path, that is how a tunnel silently
stays down.

`-o pipefail` matters wherever a pipeline's first command can fail; without it
the exit status is the last command's, which is usually `0`.

**Documented exception:** a library sourced by other scripts may legitimately
omit these, because they leak into the caller's shell. Where that is the case,
say so in a comment at the top with the reason.

## Idempotency

Scripts must be safe to run repeatedly. Check state before changing it.

```bash
if ! id service_user &>/dev/null; then
    sudo useradd -r service_user
fi

if systemctl is-active --quiet service_name 2>/dev/null; then
    sudo systemctl restart service_name
else
    sudo systemctl start service_name
fi
```

## Reading files that root owns

```bash
[ -r "$root_only_file" ]        # always false for the invoking user
sudo test -f "$root_only_file"  # correct
```

A readability test on a root-owned file silently reports "missing" to a
non-root caller. This has caused real defects here.

## Reporting

- **Verify before declaring success.** A command exiting `0` frequently means
  "the request was accepted", not "the outcome happened". Check the outcome.
- **Never print a success message on a path that did not do the work.** If a
  fallback ran, say which path ran.
- **Surface failures somewhere a person sees them.** A log file on a machine
  nobody logs into is not a notification.

## Input validation

Validate any externally supplied value before it reaches a filesystem path or a
command, not after:

```bash
if [[ ! "$NAME" =~ ^[a-z0-9_-]+$ ]]; then
    echo "[ERROR] Invalid name: $NAME"
    exit 1
fi
```

Validate **every** such value. Validating one and forgetting its neighbour is
the common shape of this bug.

Parse JSON with `jq`, not with `sed` or a regex. Greedy matching silently
selects the last occurrence rather than the first, and payloads often embed
user-authored strings.

## ShellCheck

Worth running. `SC2155` alone would have caught a real dispatcher bug here that
passed syntax checking and manual testing while being completely broken:

```bash
local stack="$1" cli="$STACKS_DIR/$stack/${stack}ctl.sh"
```

`local` expands all arguments before assigning any, so `$stack` resolved to the
caller's scope.
