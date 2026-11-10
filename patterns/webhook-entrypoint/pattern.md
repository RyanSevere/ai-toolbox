# Webhook entrypoint

Injects a shared secret into an `adnanh/webhook` hooks file at container start,
so the committed configuration holds a placeholder rather than a credential.

**This is the pattern that produced the sharpest defect of the audit that
started this directory.** Copy from here.

---

## Canonical implementation

```sh
#!/bin/sh
set -e

HOOKS_SRC="/config/hooks.json"
HOOKS_RESOLVED="/tmp/hooks-resolved.json"

if [ ! -f "$HOOKS_SRC" ]; then
  log "Error: $HOOKS_SRC not found"
  exit 1
fi

for f in /config/*.sh; do [ -f "$f" ] && chmod +x "$f"; done

if [ -z "${WEBHOOK_SECRET:-}" ]; then
  log "Error: WEBHOOK_SECRET is not set. Refusing to start."
  log "An empty secret templates an empty match value, which any request satisfies."
  exit 1
fi

jq --arg s "${WEBHOOK_SECRET:-}" '
  map(
    if .id == "redeploy-stack" then
      .["trigger-rule"].match["value"] = $s
    else
      .
    end
  )
' "$HOOKS_SRC" > "$HOOKS_RESOLVED"

exec /usr/bin/webhook.real "$@"
```

---

## Load-bearing lines

### `exit 1` on an empty secret

**Without it the endpoint is unauthenticated.** `jq --arg s ""` writes
`"value": ""` into the trigger rule. adnanh/webhook matches by value equality,
so any request with an empty or absent header satisfies it and executes the
command.

**Keep the second log line.** It is not commentary - it is the only thing that
explains why the guard cannot be softened. It was deleted along with the guard
in the one repo that got this wrong.

### The committed `hooks.json` holds `"value": ""`

This looks alarming on inspection and is correct. It is a template. The empty
value never reaches the running webhook because the entrypoint refuses to start
before substitution can happen with an empty secret.

An audit will flag this as a critical finding. It is not, **provided the guard
above is present.** The two must be read together.

### `webhook.real`

The Dockerfile moves the real binary aside and installs this script at
`/usr/bin/webhook`, so the shim always runs even when the container's entrypoint
is overridden:

```dockerfile
RUN mv /usr/bin/webhook /usr/bin/webhook.real
COPY entrypoint-webhook.sh /usr/bin/webhook
```

**Without this**, a compose `entrypoint:` override bypasses the guard entirely.

### `-hooks` points at the resolved file

```yaml
command: ["-verbose", "-hooks=/tmp/hooks-resolved.json", "-hotreload"]
```

**Without this** the substitution is pointless - the webhook reads the template
with its empty match value. Verify this line whenever the entrypoint changes.

---

## Known wrong

A copy that warns instead:

```sh
if [ -z "${WEBHOOK_SECRET:-}" ]; then
  log "Warning: WEBHOOK_SECRET is empty"
fi
```

Warns and continues. Everything else in the file was copied faithfully, so it
reviews as correct. `.env.example` ships `WEBHOOK_SECRET=` empty, meaning the
documented setup path produces an unauthenticated remote command trigger.

---

## Review checklist

When reviewing any copy of this pattern, check all four in order. Three
correct out of four is not a partial pass - the guard alone determines whether
the endpoint is authenticated.

1. Empty secret causes `exit 1`, not a warning
2. The explanatory log line is present
3. The binary is shimmed, not merely wrapped
4. `-hooks` points at the resolved path
