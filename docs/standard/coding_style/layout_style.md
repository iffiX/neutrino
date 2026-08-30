# Layout

Where files and directories go. These are hard rules, not preferences.

## Example: library must not carry execution

```text
# BAD — main()/argparse buried in a library module, config class, hyphen dir
modules/xray/
├── render-config.py          # hyphen dir/file; script logic inside a library pkg
│     def main():
│         p = argparse.ArgumentParser(); ...        # execution verbosity in library
│     class RenderConfig:                           # config class for wiring
│         listen_port = 12345
│     if __name__ == "__main__": main()

# GOOD — library is pure functions/classes; execution lives in scripts/
modules/xray/config_renderer.py
      class XrayConfigRenderer:                       # explicit kwargs, no main()
          def __init__(self, *, nodes, routing): ...
scripts/render_all/main.py
      # --- config ---
      GENERATED_DIR = "/etc/neutrino/generated"       # plain module constant
      def main() -> None:                             # the only place main() lives
          args = argparse.ArgumentParser()...
```

## Rules

- All source directories and files use `under_score` — never hyphens, never
  camelCase, never PascalCase for directories. No exceptions.
- A directory name states a role, not a grab-bag: `modules/xray/`,
  `modules/router/`, `neutrino_hub/system/`. Do not create `utils2/`, `misc/`, `helpers/`, `common/`,
  `stuff/`, `new/`, or `tmp/` as source directories, and never name a directory
  after a person.
- One cohesive concept is one module named after it; a reader guesses the
  contents from the filename. No `utils.py` / `helpers.py` / `misc.py` dumping
  grounds inside a package. `neutrino_hub/utils/` is the one shared-primitive package, and
  even there each module owns one concept (`json_file.py`, `subprocess_run.py`),
  never a `helpers.py`.

## The two-tier split (no exceptions)

Library packages are purely functional. All execution verbosity lives in
`neutrino_hub/cli/`.

- Library packages (`neutrino_hub/modules/<name>/`, `neutrino_hub/system/`, `neutrino_hub/web/`, `neutrino_hub/utils/`)
  contain no `main()`, no `argparse`, no `if __name__ == "__main__"`, and no
  wiring-config classes. Every tunable is an explicit constructor keyword or a
  value read from `config/`.
- `neutrino_hub/cli/` holds one directory per tool, each with a `main.py` whose tunables
  are plain variables in commented config sections. The three tools are
  `scripts/install/main.py` (idempotent bootstrap), `scripts/render_all/main.py`
  (render + validate + apply every generated config from `config/`), and
  `scripts/web/main.py` (the uvicorn entry point).
- A new tool is a new `scripts/<name>/` directory, never a flag bolted onto an
  unrelated script.

The rationale (why the render libraries never touch the system, why applying is
its own layer) lives in
[../design/architecture.md](../design/architecture.md).

## `config/` is data, not code

Every module's runtime configuration lives under `config/<module>/` as JSON, the
single source of truth (see
[../design/architecture.md](../design/architecture.md)).
Real files carrying secrets (node passwords, admin hash, device SSH keys) are
`.gitignore`d; a committed `<name>.example.json` documents every field. Library
code reads `config/` through `utils/json_file.py`; it never hardcodes what
belongs in `config/`.

## Constants have one home per package

Non-configurable constants (fwmark values, table names, socket paths, prefixes)
live in one `constants.py` per package. Never scatter them across modules, never
redefine the same value in two files. Values a user changes at runtime belong in
`config/`, not `constants.py`.

```text
# BAD — magic numbers / per-module constants scattered
# nft_renderer.py
FWMARK_PROXY = 0x1
# routes.py
FWMARK_PROXY = 0x1          # redefined, drifts

# GOOD — modules/router/constants.py owns them, others import
from modules.router.constants import ROUTER_FWMARK_PROXY
```

## Packages and `__init__.py`

- Library packages have `__init__.py` (`modules/` and every
  `neutrino_hub/modules/<name>/`, `neutrino_hub/system/`, `neutrino_hub/web/`, `neutrino_hub/utils/`).
- `neutrino_hub/cli/` has none. It and every subdirectory are PEP 420 implicit namespace
  packages. Sourcing `set_env.sh` puts the repo root on `PYTHONPATH` (required
  for every run), so `nhub render` still resolves
  `from modules.xray.config_renderer import XrayConfigRenderer` with zero `__init__.py`
  under `neutrino_hub/cli/`.
