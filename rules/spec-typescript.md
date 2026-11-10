---
id: typescript
tier: 2
scope: "**/*.{ts,tsx,js,jsx}"
alwaysApply: false
description: >-
  TypeScript and React SPECIFICATION - component patterns, the per-file logging
  wrapper and its feature flags, build-time secret exposure, UI state honesty,
  CORS and cookie settings. Covers why a build-prefixed variable cannot hold a
  credential regardless of storage, and why a display a person acts on must
  distinguish zero from unknown. Auto-attaches when writing or reviewing
  TypeScript, JavaScript, or React. Binding one-line rules are in
  prescriptions.md.
---

# TypeScript and React

## Patterns

- Functional components
- Extract custom hooks for reusable logic
- Use the logging wrapper in new code from the start

## Logging

Logging is for developers, not production users. Per-file control via feature
flags, with a global level.

```typescript
const log = createLogger('useRecentOnly', {
  enabled: featureDevFlags.enableLogging.useRecentOnly,
  level: config.logging.level,
});

log.debug('Detailed diagnostic');
log.info('Operation completed');
log.warn('Retrying');
log.error('Failed', err);
```

Levels follow `DEBUG < INFO < WARN < ERROR`.

**Add logging for:** complex control flow, async start and completion, error
paths with context, important state transitions.

**Remove logging from:** polling loops and other repeated operations that spam
the console, and verbose debug output in code that has proven stable.

Adoption is incremental. New code uses the wrapper; existing `console.*` calls
stay until a deliberate pass replaces them. There is no requirement to migrate
everything at once.

## Build-time values reach the browser

Anything with a build-tool env prefix is **inlined as a literal string** into
the shipped bundle. This is not a permissions problem and no secrets manager
can fix it.

- Never put an API key, token, or password in a build-time variable.
- Never name a variable in a way that invites someone to. A backend reading a
  frontend-prefixed variable as a fallback keeps that name alive as a
  legitimate-looking place to put a live credential.
- Frontend access to a keyed service goes through a backend proxy that holds
  the key server-side and refuses to proxy without one.

If a variable is loaded into the build environment it is one reference away
from shipping, whether or not anything currently references it.

## Reporting state in a UI

A display that a person acts on must distinguish **"the value is zero"** from
**"I could not find out"**.

- Never render an unreachable data source as a plausible healthy reading.
- Show an explicit unreachable state, not an empty panel and not a blank area.
- Give panels a last-updated indication so stale data is visibly stale.
- Failing over from a live connection to polling is fine; doing so without any
  visible difference is not.

## CORS and cookies

- Restrict origins to the known frontend. Do not default to allowing all
  origins, particularly alongside credentialed requests.
- Auth cookies: `httpOnly`, `secure` in production, an explicit `sameSite`, and
  a bounded lifetime.
