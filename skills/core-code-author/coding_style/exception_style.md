# Exceptions

Which exception a raise site uses, and the one place a package may declare a
kind of its own. The docstring shape that names them lives in
[python_style.md](python_style.md).

## Example

```python
# BAD: a kind invented for one module, named after the subsystem
class VaultError(ValueError):
    """Something the vault refused."""

# BAD: a group base raised bare
raise Exception("no share named media")

# GOOD: Python's own kind says it
raise KeyError(f"no share named {name!r}")

# GOOD: a kind from the package's one table, because the caller acts on it
from neutrino_hub.exceptions import RefusalError

raise RefusalError("vault_locked", params={})
```

## Rules

- Python's own exceptions first. `ValueError` for an argument of the wrong
  value or shape, `TypeError` for the wrong type, `KeyError` or `LookupError`
  for a name that is not there, `IndexError` past the end, `FileNotFoundError`,
  `PermissionError` and the rest of `OSError` for a local file or device,
  `TimeoutError` for a wait that ran out, `ConnectionError` for anything across
  a network, `RuntimeError` for a call in the wrong state, and
  `NotImplementedError` for a case the code does not handle yet. When one of
  these says it, no kind is invented.
- A package declares its own kinds in one module, `<package>/exceptions.py`,
  written before any code that can fail. Never in another module, never per
  subsystem, never in a test.
- A kind of the package's own exists only because a caller acts differently on
  it: a refusal that carries a code and params the API or the page answers
  with, a hub answer the connection loop treats unlike an unreachable hub. If
  every catcher would do the same thing, the detail goes into the message and
  the builtin is raised.
- A kind subclasses the builtin closest to what it is, so `except OSError` and
  `except ValueError` keep meaning what they mean to a caller who does not know
  the package. At most one subclass step below a table kind, and that step is
  also in the table.
- Never raise a group base bare: no `raise Exception(...)`, no
  `raise RuntimeError(...)` where a narrower builtin fits.
- A kind is named after what happened, never after the subsystem:
  `VaultLockedError`, not `VaultError`; `ShareAttachError`, not
  `PlatformError`.
- Every public docstring names each kind it raises under `Raises:` and the
  condition, so a caller reads the contract without reading the body.
- The three packages keep three tables. `hub/neutrino_hub/exceptions.py`,
  `agent/neutrino_agent/exceptions.py` and `client/neutrino_client/exceptions.py`
  never import one another; a kind two packages both need is copied, in the
  same way the wire code is.

## Choosing the kind

At a raise site, ask whether the caller could have avoided this with what it
already had. Yes means the fault is in the code and the kind is `ValueError`,
`TypeError`, `KeyError`, `IndexError` or `RuntimeError`. No means the fault is
outside, in a file, a device, another process or the network, and the kind is
an `OSError`, a `TimeoutError` or a `ConnectionError`.

Then pick the narrowest builtin that fits, and only then the package's own
kind, when a catcher acts on it. If no kind fits, the message needs to be
better, not the table longer.
