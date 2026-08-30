# Architecture

The load-bearing structural principles of this repo.

## The two-tier principle: library vs. scripts

Reusable logic lives in purely functional library packages. All execution
verbosity lives in `neutrino_hub/cli/`. This is not a formatting preference; it lets the
same rendering logic drive both the web panel and the command-line tools without
duplication, and keeps every library unit-testable with no daemon running.

- Library packages (`neutrino_hub/modules/<name>/`, `neutrino_hub/system/`, `neutrino_hub/web/`, `neutrino_hub/utils/`)
  expose composable functions and classes with explicit constructor keywords.
  No `main()`, no `argparse`, no wiring-config classes.
- Each tool is a `neutrino_hub/cli/<name>.py` that wires the libraries together with
  plain-variable config sections. The three tools are `scripts/install/main.py`,
  `scripts/render_all/main.py`, and `scripts/web/main.py`.

The mechanical placement rules are in
[../coding_style/layout_style.md](../coding_style/layout_style.md).

## config/ is the single source of truth

Everything the gateway does is a function of the JSON files under `config/`.
State flows one way:

```
config/<module>/*.json  ->  render (pure library)  ->  /etc/neutrino/generated/*
                        ->  validate  ->  apply (systemctl / nft / ip)
```

- The web backend and `scripts/render_all/main.py` drive the exact same
  pipeline. A change made in the panel is a write to `config/` followed by a
  render+apply; there is no second path that edits `/etc` by hand.
- Backing up `config/` (and restoring it on a fresh machine) reproduces the
  whole appliance. Nothing load-bearing lives only in `/etc` or in a daemon's
  memory.
- Because `config/` is the contract, `config/<module>/<name>.example.json` is
  committed and documents every field; the real file may be `.gitignore`d for
  secrets. See [config.md](../misc/config.md).

## Render and apply are separate layers

Keep system effects out of the rendering logic. A renderer is a pure function
from `config/` data to a generated artifact (a dict, a string, a file); it never
runs `systemctl`, `nft`, or `ip`. A thin apply layer validates the artifact and
then touches the system.

```text
# BAD — renderer shells out; impossible to test without root and a live nft
class RouterNftRenderer:
    def render(self):
        ruleset = self._build_ruleset()
        subprocess.run(["nft", "-f", "-"], input=ruleset)   # effect inside render

# GOOD — render is pure; apply validates then applies
class RouterNftRenderer:
    def render(self) -> str:            # pure: config -> ruleset text
        return self._build_ruleset()
modules/router/routes.py  ->  RouterRulesetApplier.apply(ruleset)   # nft -c then nft -f
```

Litmus test: if you deleted systemd and nft tomorrow, every renderer should
still import, run, and pass its tests unchanged. If it would not, an effect has
leaked into the rendering layer.

## The web backend runs as root, and that is a boundary, not a habit

`neutrino_web.service` runs as root because it must edit nftables, restart
services, and scan the LAN. That privilege is the reason the panel binds only to
the LAN and NetBird interfaces (enforced again by the nftables input chain)
and sits behind an argon2id password. Do not spread root-requiring calls through
the codebase: they live in the `neutrino_hub/system/` and `*/ops`/`apply` layers behind
named operations, so the surface that needs privilege is small and auditable. If
this ever becomes multi-user or WAN-exposed, split the privileged helper out
then — the apply layer is already the seam to split on.
