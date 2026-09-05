# Kill on sight

The hygiene checklist. Run through it before you finish any change; remove these
the moment you see them.

- **Helper lambdas.** A lambda used merely as a helper — flatten it into a named
  function or a class method. See
  [coding_style/python_style.md](coding_style/python_style.md).
- **Speckled classes.** One cohesive concept shattered into a config class plus
  a data class plus a renderer plus an applier. Merge into one cohesive class
  with clear `__init__` kwargs (rendering and applying are genuinely separate
  concepts, though — do not fuse those). See
  [design/class_design.md](design/class_design.md).
- **Opaque names.** Non-semantic class or module names (`Manager`, `Handler`,
  `loader.py`, `config_thing.py`) that a reviewer cannot decode from the name
  alone. See
  [design/class_hierarchy.md](design/class_hierarchy.md)
  and [coding_style/naming_style.md](coding_style/naming_style.md).
- **Grab-bag directories.** `utils2/`, `misc/`, `helpers/`, `common/` as source
  directories, or `helpers.py` / `misc.py` dumping grounds inside a package. See
  [coding_style/layout_style.md](coding_style/layout_style.md).
- **Execution in a library.** `main()`, `argparse`, `if __name__ == "__main__"`,
  or a wiring-config class inside a library package. It belongs in `neutrino_hub/cli/`.
  See [design/architecture.md](design/architecture.md).
- **System effects in a renderer.** `systemctl`, `nft`, `ip`, or any subprocess
  with an effect inside a `*_renderer.py` or any `render()` method. Rendering is
  pure; effects live in the apply/routes/services layer. See
  [design/architecture.md](design/architecture.md).
- **Hand-editing `/etc`.** Writing a generated file (`/var/lib/neutrino/generated/`,
  a dnsmasq configuration, an nft ruleset) from anywhere other than a renderer +
  apply. The only source of truth is `config/`; everything downstream is
  regenerated, never hand-patched.
- **Secrets in git.** A real node password, admin hash, session secret, or
  device SSH key committed instead of living in a `.gitignore`d config file with
  a committed `.example.json`. See [config.md](misc/config.md).
- **Scattered constants.** The same value defined in more than one module
  instead of one `constants.py`, or a user-tunable value hardcoded in a library
  instead of read from `config/`.
- **Bools without `is_` / `has_`.** A boolean named like a noun or a getter, in
  Python or in a `config/` JSON key or a TypeScript field.
- **Shouting caps.** Uppercase words for emphasis in comments, docstrings, or
  prose.
- **`any` in TypeScript.** Reach for `unknown` and narrow, or write the real
  type. See [coding_style/typescript_style.md](coding_style/typescript_style.md).
- **black / prettier / eslint not run.** `black --check` must pass on Python;
  `prettier --check` and `eslint` must pass on the frontend.
- **Unasked survival machinery.** Persistence, reconciliation, or migration
  added on nobody's request so state outlives a restart, reinstall, or
  upgrade of an unreleased version. Before release, a clean reconfigure or a
  reinstall is the recovery path; released versions get migration design when
  the user asks for it. Never mixed into a commit that was asked to do
  something else.

- A comment, hint, or error message that narrates reasoning instead of
  stating the fact — see coding_style/comment_style.md.
