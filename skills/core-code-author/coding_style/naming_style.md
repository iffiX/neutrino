# Naming

How to name identifiers so an outside reviewer understands each one without
context. The philosophy behind class names (tree-like semantic hierarchies, the
`<Domain><Thing><Role>` family) lives in
[../design/class_hierarchy.md](../design/class_hierarchy.md);
this file is the mechanical surface rules.

## Example: booleans

```python
# BAD
def valid(node): ...            # returns bool but reads like a getter
reachable = check(host)         # noun, unclear it is a bool
def enabled(self): return ...   # ambiguous

# GOOD
def is_valid(node) -> bool: ...
is_reachable: bool = check(host)
def is_enabled(self) -> bool: ...   # can_/should_ allowed where they read better
```

## Rules

- Booleans use an `is_` / `has_` prefix. This applies to variables, attributes,
  functions that return a bool, dataclass fields, Pydantic model fields, and the
  JSON keys in `config/` (`is_enabled`, `is_geoip_split_enabled`,
  `has_reality`). `can_` / `should_` are allowed where they read more naturally,
  but `is_` / `has_` are the defaults.
- Modules are reviewer-legible: guess the contents from the name
  (`nft_renderer.py`, `wake_on_lan.py`, `stats_client.py`). Avoid opaque names
  (`loader.py`, `manager.py`, `handler.py`).
- Constants use a package prefix that names their domain — `XRAY_` in
  `modules/xray/constants.py`, `ROUTER_` in `modules/router/constants.py`,
  `SAMBA_` in `modules/samba/constants.py`, `SYSTEM_` in
  `system/constants.py`, `WEB_` in `neutrino_hub/web/constants.py`. All caps with
  underscores.
- No misleading terms: no "DB" for something that is not a database, no `env`
  for an environment-variable dict when it is really something else, no
  abbreviation that collides with another concept. Say the concrete role
  (`self._nft_renderer`, `self._ssh`), not a vague one (`self._mgr`).

## Files and directories

Files and directories use `under_score` (see [layout_style.md](layout_style.md)). A filename
names the one concept the module owns. This holds for TypeScript too — a React
component file is `nodes_page.tsx`, not `NodesPage.tsx` (the component *inside*
is still `NodesPage`); see
[typescript_style.md](typescript_style.md).
