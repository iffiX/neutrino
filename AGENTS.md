# AGENTS.md

Neutrino: a personal developer infrastructure hub on one box — transparent
proxy routing (xray), a FastAPI + React control panel, NetBird remote access,
an AI gateway (CLIProxyAPI), and Gitea, Samba, Podman and ZFS as modules. A
device agent under `agent/` reconciles modules on managed LAN machines.

Ships as two packages: `neutrino_hub` (this tree) and `neutrino_agent`
(`agent/`).

Every agent working here — Claude Code, Codex, Cursor, or otherwise — follows
the standard in [`docs/standard/`](docs/standard/README.md). This file is the
index, not a second copy: **when a rule changes, change it in `docs/standard/`
and leave this pointing at it.**

## Reading order

**Must read before writing any code:**

| Document | What it settles |
| --- | --- |
| [coding_style/layout_style.md](docs/standard/coding_style/layout_style.md) | Where a file goes. `under_score` everywhere, no grab-bag dirs, library packages vs. `neutrino_hub/cli/<name>.py`, one `constants.py` per package. |
| [design/architecture.md](docs/standard/design/architecture.md) | `config/` is the only source of truth; render → validate → apply; renderers are pure, appliers touch the system. |
| [coding_style/comment_style.md](docs/standard/coding_style/comment_style.md) | KISS, English only, no narrated reasoning anywhere, commit message shape. |
| [agent_work_rule/commit.md](docs/standard/agent_work_rule/commit.md) | Only the user decides a commit happens. One answerable author, no agent `Co-Authored-By`. |
| [design/files.md](docs/standard/design/files.md) | The five roots an installed hub uses, and the one question each answers. |
| [design/install_and_dev.md](docs/standard/design/install_and_dev.md) | Who installs what: the package's dependencies, what `nhub setup` may do, and how `--dev` differs. |
| [design/privilege.md](docs/standard/design/privilege.md) | Why the panel is root, what the unit narrows, and why stepping down uses `runuser` and never `sudo`. |
| [kill_on_sight.md](docs/standard/kill_on_sight.md) | The self-check to run before you say you are done. |

**Selective read — open the one your change touches:**

| Document | Open it when |
| --- | --- |
| [coding_style/naming_style.md](docs/standard/coding_style/naming_style.md) | Naming anything: `is_`/`has_` bools, constant prefixes, banned terms. |
| [coding_style/python_style.md](docs/standard/coding_style/python_style.md) | Writing Python: file and method order, black, Google docstrings. |
| [coding_style/typescript_style.md](docs/standard/coding_style/typescript_style.md) | Touching `hub/frontend/`: no `any`, `import type`, API types mirror the backend models. |
| [design/api.md](docs/standard/design/api.md) | Adding or renaming a panel endpoint: `/api/<module>`, plural sub-resources, when a verb is allowed. |
| [design/network.md](docs/standard/design/network.md) | Touching the router layer: the three engines the hub drives, which modes own a machine's network and which touch nothing, and why it does not build on NetworkManager. |
| [design/agent.md](docs/standard/design/agent.md) | Touching the hub↔agent channel: the two ports, the pinned identity, tickets and tokens, the failure states, version sync. |
| [design/visual.md](docs/standard/design/visual.md) | Touching panel CSS: what the accent and the glow may mean, button tiers, frames. |
| [design/class_design.md](docs/standard/design/class_design.md) | Adding a class: one concept per class, explicit `__init__` kwargs. |
| [design/class_hierarchy.md](docs/standard/design/class_hierarchy.md) | Naming a class: the per-package `<Domain><Thing><Role>` families. |
| [design/repository_tree.md](docs/standard/design/repository_tree.md) | Adding a directory to the source tree, or unsure what an existing one is for. |
| [misc/config.md](docs/standard/misc/config.md) | Touching `config/`: which files are secrets, how examples map to real ones. |
| [misc/operations.md](docs/standard/misc/operations.md) | Verifying an install, or running the appliance. |
| [doc_style/](docs/standard/doc_style/README.md) | Writing any `.md`: which of the three kinds you are writing, and how each is worded. |
| [agent_work_rule/release.md](docs/standard/agent_work_rule/release.md) | Cutting a release: the tag, the changelog prefixes, and which package each platform installs. |

## Commands

```bash
pip install -e "hub[dev]"            # nhub, black, pytest, detect-secrets
pip install -e agent                 # nagent

black --check hub agent              # REQUIRED before every commit
nhub scan-secrets                    # REQUIRED before every commit
cd hub && pytest -q                  # hub tests
cd agent && pytest -q                # agent tests

cd hub/frontend && npx prettier --check src && npx eslint src --max-warnings 0
cd hub/frontend && npm run build     # REQUIRED after frontend changes
                                     # builds into neutrino_hub/data/frontend/

nhub apply --dry-run                 # render everything, no effects
sudo systemctl restart neutrino_web  # deploy the panel
```

The secret scan is a gate, not advice. A finding is either real and removed, or
safe and marked `scan: allow` on its line. Never narrow a rule to silence it.

## Config

`config/<module>/*.json` is the only source of truth. Every change is a write
there, then render → validate → apply; the panel and `nhub apply` drive
the same pipeline, and nothing hand-edits `/etc`. Real files holding secrets are
`.gitignore`d with a committed `<name>.example.json` beside them. Backing up
`config/` reproduces the appliance. Details: [misc/config.md](docs/standard/misc/config.md).

## Architecture

```
hub/
  neutrino_hub/       The hub package. One top-level name, so nothing it
                      installs can collide in site-packages.
    modules/<name>/   One feature module each: config.py / renderer.py /
                      ops.py / constants.py / provisioner.py. Pure library.
    system/           Wrappers around OS invocations.
    utils/            Generic helpers shared by every package.
    web/              FastAPI panel: routers/, auth, models.
    cli/              Every entry point behind `nhub`.
    data/             Ships inside the package: services/ unit templates,
                      manifests/ the device software catalog, examples/ the
                      committed *.example.json, frontend/ the built panel,
                      resources/ the icons.
  frontend/           React + TypeScript source. Builds into data/frontend/.
  tests/
agent/
  neutrino_agent/     The device agent. Pure standard library, no dependencies.
  tests/
config/               Source of truth at runtime. Real files gitignored.
                      /etc/neutrino/config once installed.
docs/standard/        This standard. The single source of truth for rules.
images/               Source artwork and README screenshots. Ships nowhere.
```

Do not put `main()`, `argparse`, or wiring-config classes in a library
module — execution lives in `neutrino_hub/cli/<name>.py`, and each of those is
a subcommand of `nhub`.
Full tree: [design/repository_tree.md](docs/standard/design/repository_tree.md).

## Conventions that bite

These are the ones agents get wrong most often. Each is spelled out with
examples in the document named beside it.

- **Renderers are pure.** No `systemctl`, `nft` or `ip` in a renderer; effects
  belong in the apply layer. Do not break the `config/ → render → apply`
  separation. ([design/architecture.md](docs/standard/design/architecture.md))
- **Bools read as questions.** `is_` / `has_` on variables, attributes,
  Pydantic fields, `config/` JSON keys and TypeScript fields alike.
  ([coding_style/naming_style.md](docs/standard/coding_style/naming_style.md))
- **No narrated reasoning.** Not in comments, docstrings, UI copy, or error
  messages. Rationale goes in `docs/`.
  ([coding_style/comment_style.md](docs/standard/coding_style/comment_style.md))
- **English only**, including when translating comments you find.
  ([coding_style/comment_style.md](docs/standard/coding_style/comment_style.md))
- **Smallest change that works.** No restructuring you were not asked for, no
  layer for a case nobody has.
  ([coding_style/comment_style.md](docs/standard/coding_style/comment_style.md))
- **A reset hands the network back before it replaces `config/`, and takes no
  address off anything.** `config/` is the only record of which interfaces had
  units on them, and an interface losing its address mid-reset drops the
  session that asked for it.
  ([design/network.md](docs/standard/design/network.md))
- **Never commit unasked.** When work looks done, ask. A commit is a finished,
  tested feature. ([agent_work_rule/commit.md](docs/standard/agent_work_rule/commit.md))
- **`sudo` never appears in the hub's own code.** The panel is already root, so
  reaching a service account is `runuser -u <account> --`; sudo refuses to run
  under the unit's `NoNewPrivileges`.
  ([design/privilege.md](docs/standard/design/privilege.md))
- **Documents open with a definition and never end with a summary.** No
  "it should be noted", no recap section, no explaining what the reader knows.
  ([doc_style/README.md](docs/standard/doc_style/README.md))
