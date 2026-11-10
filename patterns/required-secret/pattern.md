# Required secret

A secret that is absent must abort. There is no correct fallback value.

**Three confirmed instances in one set of repositories.** Every
one passed review, because a default value looks like defensive programming
rather than the removal of a control.

---

## The rule beneath the rule

Test **falsy, not null**. An empty string is as dangerous as an unset variable
and usually more so, because it passes an existence check and fails a
comparison. `??` and `os.getenv(name, '')` both let an empty value through.

---

## TypeScript / Node

```typescript
function requireEnv(name: string): string {
  const value = process.env[name];
  // Falsy rather than nullish: an empty value is as dangerous as a missing one.
  if (!value) {
    throw new Error(
      `${name} is not set. Refusing to start rather than signing tokens with a fallback secret.`,
    );
  }
  return value;
}

const JWT_SECRET = requireEnv("JWT_SECRET");
```

**Load-bearing:** `!value` rather than `value == null`. **Load-bearing:** the
throw is at module scope, so the process cannot reach a request handler.

## Python

```python
password = os.getenv('SERVICE_PASSWORD')
if not password:
    raise RuntimeError('SERVICE_PASSWORD is not set. Refusing to start.')
```

With pydantic settings, omit the default entirely - absence becomes a
`ValidationError` at startup and needs no extra code:

```python
class Settings(BaseSettings):
    secret_key: str            # no default: absence must abort
    service_host: str = "localhost"   # not a secret, default is fine
```

**Known wrong:** `secret_key: str = "change-me-in-production"`, signing OAuth
state tokens. A
published signing key defeats the CSRF protection the state parameter exists to
provide, and it fails silently and successfully.

## Docker Compose

```yaml
    environment:
      # Substituted so compose fails before replacing containers; env_file is not validated.
      - JWT_SECRET=${JWT_SECRET:?JWT_SECRET must be set in .env}
      - OPTIONAL_API_KEY=${OPTIONAL_API_KEY:-}
```

**Load-bearing:** `:?` not `:-`. The first aborts; the second substitutes.
Non-secrets may use `:-`.

**Load-bearing:** secrets belong in the `environment:` block, not only in
`env_file`. Compose does not validate `env_file` contents, so a `:?` guard
there never fires.

## Bash

```bash
if [ -z "${WEBHOOK_SECRET:-}" ]; then
  log "Error: WEBHOOK_SECRET is not set. Refusing to start."
  exit 1
fi
```

**Load-bearing:** `exit 1`. See `patterns/webhook-entrypoint` for what happens
when this becomes a warning.

---

## Non-secrets are different

A host, a port, a retention window, a log level - these may have sensible
defaults and usually should. The distinction is whether an attacker benefits
from knowing the default value. For a credential, key, token, or signing secret,
they always do.
