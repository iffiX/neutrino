# Python style

Formatting, docstrings, and the internal order of a file. The reasoning about
how to split logic into classes lives in
[../design/class_design.md](../design/class_design.md);
this file is the mechanical rules.

## Example: file internal order and method order

```text
# BAD: imports, then a class, then a constant, then a function, then main() interleaved
# GOOD: imports  ->  file-local constants  ->  functions (public then private)
#       ->  classes (public then private).  No main() in a library file.
```

```python
# BAD — private helper above public API, lambda helper
class XrayConfigRenderer:
    def _build_outbounds(self): ...      # private before public
    def render(self):
        tag = lambda n: f"node_{n}"       # helper lambda

# GOOD — __init__ -> public -> private, named helpers
class XrayConfigRenderer:
    def __init__(self, *, nodes, routing):
        self._nodes = nodes
    def render(self) -> dict: ...         # public first
    def _build_outbounds(self): ...       # private helpers last
    def _node_tag(self, name: str) -> str:  # named, not a lambda
        return f"node_{name}"
```

## File internal order

Within a file, the order is: file-local constants, then functions, then
classes; within each group, public before private. Never interleave imports,
constants, functions, and `main()`. A library file has no `main()` at all (see
[layout_style.md](layout_style.md)).

## Method order within a class

`__init__`, then public methods, then private (`_`-prefixed) helpers.

## Formatting

- black, 88 columns (config in `pyproject.toml`). `black --check` must pass on
  every change.
- Google docstrings, in the shape below.
- No lambdas used merely as helpers — rewrite them as named functions or
  methods.
- No uppercase words for emphasis in prose, comments, or docstrings
  ("BOTH", "ONLY", "EXACTLY", ...). Use plain words or markdown emphasis.
  Acronyms (DNS, TPROXY, SOCKS, JSON, VLESS, WAN, ...) and code identifiers are
  fine.


## Docstrings

A docstring states what the thing is, then documents every parameter in its
own `Args:` entry. Parameter semantics never live in a prose paragraph.

```python
# BAD: parameter semantics buried in prose
def render(self, device=None, mode=None) -> dict:
    """Render the config for this device. With ``device=None`` the hub box is
    rendered, and passing a mode renders as that mode instead of the saved one.
    """

# GOOD: the description holds only what is not tied to one parameter
def render(self, device=None, mode=None) -> dict:
    """Render the config the apply layer writes.

    Args:
        device: The device rendered for, by id; ``None`` renders the hub box.
        mode: The network mode rendered as; ``None`` keeps the saved one.

    Returns:
        The rendered files by path.

    Raises:
        KeyError: If ``device`` names no known device.
    """
```

- Every public function, method and class docstring is Google style: a
  description, then `Args:` with an entry for every parameter, then
  `Returns:`, `Raises:` and `Note:` when they carry a contract, always in that
  order.
- The description holds only behavior not tied to one parameter. Every
  per-parameter fact moves into its `Args:` entry. Redistribute, never delete.
- Constructor parameters are documented under `__init__`'s own `Args:`; the
  class docstring says what one instance is. A dataclass documents its fields
  under `Attributes:` instead.
- `Raises:` names every kind the body raises on purpose and the condition for
  each; which kind that is follows [exception_style.md](exception_style.md).
- A private method gets one line and no sections.
- A module or class brief stays within 5 lines of prose; the structured
  sections do not count. State what the thing is and its one or two defining
  mechanisms, then stop. Details belong on the `Args:` entries or the method
  docstrings.
- The shortest sentence that names the mechanism, the same rule as a comment.
