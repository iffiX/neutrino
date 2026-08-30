# Class hierarchy and naming

Class names must form a tree-like, semantically meaningful structure that a
human can navigate from the name alone. This is the design counterpart to the
mechanical identifier rules in
[../coding_style/naming_style.md](../coding_style/naming_style.md).

## Example

```python
# BAD — opaque, non-navigable
class Manager: ...
class Handler: ...
class ConfigThing: ...

# GOOD — reads as Domain -> Thing -> Role
class XrayConfigRenderer: ...    # Xray -> Config -> Renderer
class RouterNftRenderer: ...     # Router -> Nft -> Renderer
class DeviceSshOperator: ...     # Device -> Ssh -> Operator
```

## Rules

- Class names form tree-like hierarchies: a domain, then a thing, then a role
  (`Xray` -> `Config` -> `Renderer` => `XrayConfigRenderer`). A reader navigates
  the hierarchy from the name.
- Each library package owns a domain prefix and keeps to one family:
  - `modules/xray/` — `XrayConfigRenderer`, `XrayNodeConfig`,
    `XrayStatsClient`, `XrayConfigApplier`.
  - `modules/router/` — `RouterNftRenderer`, `RouterDnsmasqRenderer`,
    `RouterRulesetApplier`, `RouterWanStatus`.
  - `modules/samba/` — `SambaConfigRenderer`, `SambaConfigApplier`,
    `SambaUserManager`, `SambaStatusReader`.
  - `neutrino_hub/system/` — `SystemdServiceController`, `LocalShellSession`,
    `VnstatHistoryReader`.
  Do not introduce a parallel name for a concept that already has one in its
  family.
- Roles are consistent across families: a pure config-to-artifact class is a
  `Renderer`, the class that validates-and-applies it is an `Applier`, a class
  that drives an external tool is an `Operator` or `Controller`, a read-only
  probe is a `Status` or `Reader`.
- Constants for a family use the domain prefix (`XRAY_`, `ROUTER_`, `SAMBA_`, `SYSTEM_`,
  `WEB_`) and live in that package's `constants.py`.

When a genuinely new family appears, propose the name rather than inventing one
silently — consistency beats brevity.
