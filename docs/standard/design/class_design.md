# Class design

How to decompose logic into classes. This is judgment, not surface formatting;
the mechanical method order lives in
[../coding_style/python_style.md](../coding_style/python_style.md).

## Example: one cohesive concept, one class

```python
# BAD — opaque name, generated artifact and system effect fused, config split
#       across a data class plus a renderer plus an applier for one concept
class Manager:                                   # opaque, not navigable
    def run(self):
        self.cfg = XrayCfg(...)                  # config object as public API
        subprocess.run(["systemctl", "restart", "neutrino_hub_xray"])   # effect fused in

# GOOD — one cohesive renderer, clear __init__ kwargs, no system effect
class XrayConfigRenderer:                   # inbounds, outbounds, routing in one
    def __init__(self, *, nodes, routing):
        self._nodes = nodes
        self._routing = routing
    def render(self) -> dict: ...           # pure config -> dict
    def _build_outbounds(self): ...
```

## Rules

- One cohesive concept is one class. Do not shatter a single concept into a
  config class plus a data class plus a renderer plus an applier. The full xray
  config — inbounds, outbounds, balancer, observatory, routing — is rendered by
  one `XrayConfigRenderer`. Applying it (validate + restart) is a *different*
  concept and belongs in `xray/apply.py`, not because of formatting but because
  rendering is pure and applying has effects (see
  [architecture.md](architecture.md)).
- Prefer explicit `__init__` keyword arguments over config objects. The values
  come from `config/`, parsed once into small dataclasses at the edge, then
  passed as explicit kwargs — not threaded around as one opaque config bag.
- When a framework demands a config object, build it privately inside
  `__init__`. It must not be the public API.
- Before adding a class, check whether it shares one cohesive role with an
  existing class and merge if so.

Class naming (the tree-like semantic hierarchy, the `<Domain><Thing><Role>`
family) is covered in [class_hierarchy.md](class_hierarchy.md).
