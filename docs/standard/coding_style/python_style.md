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
- Google docstrings with explicit `Args:` / `Returns:` / `Raises:`. Prefer
  explicit argument documentation over long paragraphs.
- No lambdas used merely as helpers — rewrite them as named functions or
  methods.
- No uppercase words for emphasis in prose, comments, or docstrings
  ("BOTH", "ONLY", "EXACTLY", ...). Use plain words or markdown emphasis.
  Acronyms (DNS, TPROXY, SOCKS, JSON, VLESS, WAN, ...) and code identifiers are
  fine.
