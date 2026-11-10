---
id: python
tier: 2
scope: "**/*.py"
alwaysApply: false
description: >-
  Python SPECIFICATION - style, logging, configuration, and error handling.
  Covers type hints and docstring expectations, the per-module logger pattern
  and level semantics, the config.py environment pattern and why secrets are
  excluded from it, and the rule against returning a value that cannot be
  distinguished from a healthy reading. Auto-attaches when writing or reviewing
  Python. The binding one-line rules are in prescriptions.md.
---

# Python

## Style

- Type hints on parameters and returns, Python 3.11+ syntax
- Triple-quoted docstrings on all classes and functions
- Lines under 100 characters
- Imports grouped: standard library, third-party, local
- Module-level constants in `UPPER_SNAKE_CASE`

## Logging

Every module gets a logger:

```python
import logging
logger = logging.getLogger(__name__)
```

Use logging rather than `print` for anything a person might need later.

| Level | Use for |
|---|---|
| `debug` | Execution flow, state transitions, loop detail |
| `info` | Operations started and completed |
| `warning` | Recoverable conditions, retries, fallbacks, deprecated paths |
| `error` | Failures |
| `critical` | Unrecoverable failures |

A `logging_config.py` centralises configuration via `dictConfig`, with a
console handler at the configured level and a file handler at `DEBUG`.

**Never log a secret value.** See Tier 1.

## Configuration

Configurable values belong in a `config.py` reading from the environment, not
hardcoded at the point of use.

```python
import os

ENV = os.getenv('APP_ENV', 'development')
```

Consumers import the resolved names:

```python
from config import SERVICE_HOST, SERVICE_PORT, LOG_LEVEL
```

**Secrets are the exception to the defaults pattern.** A host or a port may
have a sensible default. A password, key, or token may not - it must abort.
`os.getenv('PASSWORD', '')` is the defect this estate keeps rediscovering,
because an empty string passes a truthiness check in some places and fails
silently in others.

```python
SERVICE_HOST = os.getenv('SERVICE_HOST', 'localhost')   # fine

password = os.getenv('SERVICE_PASSWORD')                # required
if not password:
    raise RuntimeError('SERVICE_PASSWORD is not set. Refusing to start.')
```

## Error handling

- No bare `except:` and no `except Exception: pass`.
- **Never return a value that looks like a valid reading when the real answer
  is "I could not find out."** Returning `[]` for both "auth failed" and
  "genuinely empty" is indistinguishable to every caller. Raise, or return a
  result that carries the failure.
- Every outbound network call gets an explicit timeout. A blocking call with no
  timeout on a long-running process hangs forever and looks like a hang, not an
  error.
