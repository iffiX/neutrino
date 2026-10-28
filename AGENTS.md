# AGENTS.md

Neutrino: a personal developer infrastructure hub on one box — transparent
proxy routing (xray), a FastAPI + React control panel, NetBird remote access,
an AI gateway (CLIProxyAPI), and Gitea, Samba and Podman as modules. The
hub runs on Linux in any network mode, and in server mode also on macOS and
Windows. A device agent under `agent/` reconciles modules on managed LAN
machines.

Ships as three packages and two apps: `neutrino_hub` (`hub/`),
`neutrino_agent` (`agent/`) and `neutrino_client` (`client/desktop/`), and the
Android app (`client/android/`, Kotlin) and the iOS app (`client/ios/`,
Swift, a client with fewer pages and no virtual network). The two apps are
AGPL-3.0; the rest is MIT.

Every agent working here — Claude Code, Codex, Cursor, or otherwise — follows
the standard in [`skills/core-code-author/`](skills/core-code-author/SKILL.md). This file is the
index, not a second copy: **when a rule changes, change it in `skills/core-code-author/`
and leave this pointing at it.**

## Reading order

**Must read before writing any code:**

| Document | What it settles |
| --- | --- |
| [coding_style/layout.md](skills/core-code-author/coding_style/layout.md) | Where a file goes. `under_score` everywhere, no grab-bag dirs, library packages vs. `neutrino_hub/cli/<name>.py`, one `constants.py` per package. |
| [design/architecture.md](skills/core-code-author/design/architecture.md) | `config/` is the only source of truth; render → validate → apply; renderers are pure, appliers touch the system. |
| [coding_style/comment.md](skills/core-code-author/coding_style/comment.md) | A comment names the thing and stops, the sentence shapes, KISS, English only, no narrated reasoning anywhere. |
| [coding_style/exception.md](skills/core-code-author/coding_style/exception.md) | Python's own exceptions first; a package's own kinds live in its one `exceptions.py`; `Raises:` on every public docstring. |
| [agent_work_rule/commit.md](skills/core-code-author/agent_work_rule/commit.md) | Only the user decides a commit happens. One answerable author, no agent `Co-Authored-By`. One line `Section: text` of at most twenty words. |
| [design/files.md](skills/core-code-author/design/files.md) | The five roots an installed hub uses on each system, the one question each answers, and the one Neutrino tree on macOS and Windows. |
| [design/development.md](skills/core-code-author/design/development.md) | Running the hub from a checkout: `--dev` against a root of its own, what it changes on the machine, and why a checkout installs nothing. |
| [design/privilege.md](skills/core-code-author/design/privilege.md) | Why the panel is root, what the unit narrows, why stepping down uses `runuser` and never `sudo`, and what holds on macOS and Windows. |
| [kill_on_sight.md](skills/core-code-author/kill_on_sight.md) | The self-check to run before you say you are done. |

**Selective read — open the one your change touches:**

| Document | Open it when |
| --- | --- |
| [coding_style/naming.md](skills/core-code-author/coding_style/naming.md) | Naming anything: `is_`/`has_` bools, constant prefixes, banned terms. |
| [coding_style/python.md](skills/core-code-author/coding_style/python.md) | Writing Python: file and method order, black, Google docstrings. |
| [coding_style/typescript.md](skills/core-code-author/coding_style/typescript.md) | Touching `hub/frontend/`: no `any`, `import type`, API types mirror the backend models. |
| [coding_style/kotlin.md](skills/core-code-author/coding_style/kotlin.md) | Touching `client/android/`: PascalCase files, ktlint, one `Exceptions.kt`, refusals as sealed results, no `!!`. |
| [coding_style/swift.md](skills/core-code-author/coding_style/swift.md) | Touching `client/ios/`: PascalCase files, swift-format, one `Error` enum per target, no force unwrap. |
| [coding_style/go.md](skills/core-code-author/coding_style/go.md) | Touching `transport/` or `agent/sshserver/`: gofmt and vet, lowercase package directories, one `errors.go` per package, errors wrapped with `%w`, no panic, every goroutine owned by a context. |
| [design/protocol.md](skills/core-code-author/design/protocol.md) | Adding or renaming any endpoint, frame, kind or code: the three ports, path rules and the verb table, refusals as `{code, params}`, every route, the channel's frames, kinds and sections, versioning by protocol number. |
| [design/transport.md](skills/core-code-author/design/transport.md) | Touching `transport/`, the agent port, or anything a client or a Web share reaches through it: the doors the first bytes pick, the member header and its per-hub magic, the knock and the handshake, the guest path of a Web share, what each link holds, TCP first, the stream layer and its timings, the ways the port is reached, what the hub spends before admission and the limits on it, admission and the binding, an agent of 0.5, the local channel between each transport and its Python, and why the hub relays every stream; each design with its reason. |
| [design/web_share.md](skills/core-code-author/design/web_share.md) | Touching `share_page/` or what a Web share's visitor sees: the files and the sites, the connection and its timeouts, the app in the page, what the page keeps, and the four screens. |
| [design/hub_components/network.md](skills/core-code-author/design/hub_components/network.md) | Touching the router layer: the three engines the hub drives, which modes own a machine's network and which touch nothing, server mode and the system firewall on macOS and Windows, and why it does not build on NetworkManager. |
| [design/hub_components/proxy.md](skills/core-code-author/design/hub_components/proxy.md) | Touching the proxy: the scopes and what each diverts, exit selection, where every lookup resolves, what an overlay member can do, the consequences of a dead exit. |
| [design/hub_components/ai.md](skills/core-code-author/design/hub_components/ai.md) | Touching the AI gateway: how a request routes, the gateway-owned model namespace, what each AI panel surface owns, metering. |
| [design/agent.md](skills/core-code-author/design/agent.md) | Touching the agent: the hub and root as its only authorities, the four module states and `want`, the root-only control socket, the platform layer for Linux, Windows and macOS. |
| [design/agent/module_template.md](skills/core-code-author/design/agent/module_template.md) | Touching any device module: the kinds by how a module runs and each `runner`, the run and the publish of a program run as an account, the hub side, what a module owns and what `modules/shared/` holds, icons, the disk layout. |
| [design/agent/module_install.md](skills/core-code-author/design/agent/module_install.md) | Touching how software reaches a machine: the manifest and its platform entries, the five install methods (`agent`, `builtin`, `system`, `hub`, `container`), artifacts and digests, every download's sources, the source sets and how one source is chosen, the one presence check, module versions, what an uninstall removes. |
| [design/agent/modules/](skills/core-code-author/design/agent/modules/) | Touching one device module: one page per module (`terminal.md`, `remote_desktop.md`, `file_share.md`, `gitea.md`, `containers.md`, `vscode.md`, `code_server.md`, `cloudcli.md`, `codeg.md`, `siyuan.md`, `hermes_webui.md`, `ayakaleaf.md`), and [design/agent/ai_tools.md](skills/core-code-author/design/agent/ai_tools.md) beside them for the machine's AI tools setting. |
| [design/tests.md](skills/core-code-author/design/tests.md) | Writing or moving any test: the seven blocks (agent / client / hub / go / android / ios / integration), the mirror rule, what each area pins, what a change owes. |
| [design/visual.md](skills/core-code-author/design/visual.md) | Touching panel CSS: what the accent and the glow may mean, button tiers, frames. |
| [design/ui_behavior.md](skills/core-code-author/design/ui_behavior.md) | Touching panel pages or components: which idiom a screen reuses, per-panel apply bars, effect timing, ask before inventing an interaction. |
| [design/client.md](skills/core-code-author/design/client.md) | Touching any client (`client/desktop`, `client/android`, `client/ios`): the one state document, the layout, the button rule, refresh, and every page's state machines; the three clients change together. |
| [design/class_design.md](skills/core-code-author/design/class_design.md) | Adding a class: one concept per class, explicit `__init__` kwargs. |
| [design/class_hierarchy.md](skills/core-code-author/design/class_hierarchy.md) | Naming a class: the per-package `<Domain><Thing><Role>` families. |
| [design/repository_tree.md](skills/core-code-author/design/repository_tree.md) | Adding a directory to the source tree, or unsure what an existing one is for. |
| [misc/config.md](skills/core-code-author/misc/config.md) | Touching `config/`: which files are secrets, how examples map to real ones. |
| [misc/operations.md](skills/core-code-author/misc/operations.md) | Verifying an install, or running the appliance. |
| [doc-author/](skills/doc-author/SKILL.md) | Writing any `.md`: the gate before drafting, the kind of page, the rules and budgets, each language's register, the checklist after. |
| [design/min_support.md](skills/core-code-author/design/min_support.md) | Changing a dependency, a build container, or a `Depends` or `Requires` line: the glibc floor of each package and what sets it, the versions the hub, the agent and the client require of the system, and how a build holds the floor. |
| [agent_work_rule/release.md](skills/core-code-author/agent_work_rule/release.md) | Cutting a release: the tag, the changelog prefixes, and which package each platform installs. |

## Commands

```bash
pip install -e "hub[dev]"            # nhub, black, pytest, pytest-cov, detect-secrets
pip install -e agent                 # nagent
pip install -e client/desktop        # nclient

black --check hub agent client packaging  # REQUIRED before every commit
nhub scan-secrets                    # REQUIRED before every commit
cd hub && pytest -q                  # hub tests
cd agent && pytest -q                # agent tests
cd client/desktop && pytest -q       # desktop client tests
cd transport && go vet ./... && go test -race ./...   # the transport
cd agent/sshserver && go vet ./... && go test -race ./...  # the agent's SSH server
cd client/android && ./gradlew test lint   # Android app tests and lint
cd client/ios && xcodegen generate && xcodebuild test -scheme Neutrino \
    -destination 'platform=iOS Simulator,name=iPhone 16'
                                     # iOS app tests, on macOS

cd hub/frontend && npx prettier --check src && npx eslint src --max-warnings 0
cd hub/frontend && npm run build     # REQUIRED after frontend changes
                                     # builds into neutrino_hub/data/frontend/

nhub apply --dry-run                 # render everything, no effects
sudo systemctl restart neutrino_hub_web  # deploy the panel on an installed box
```

The secret scan is a gate, not advice. A finding is either real and removed, or
safe and marked `scan: allow` on its line. Never narrow a rule to silence it.

## Config

`config/<module>/*.json` is the only source of truth. Every change is a write
there, then render → validate → apply; the panel and `nhub apply` drive
the same pipeline, and nothing hand-edits `/etc`. Real files holding secrets are
`.gitignore`d with a committed `<name>.example.json` beside them. Backing up
`config/` reproduces the appliance. Details: [misc/config.md](skills/core-code-author/misc/config.md).

## Architecture

```
hub/
  neutrino_hub/       The hub package. One top-level name, so nothing it
                      installs can collide in site-packages.
    modules/<name>/   One feature module each: config.py / renderer.py /
                      ops.py / constants.py / provisioner.py. Pure library.
    system/           Wrappers around OS invocations.
    platforms/        What differs between Linux, macOS and Windows: the
                      roots, the process controller, the firewall.
    utils/            Generic helpers shared by every package.
    web/              FastAPI panel: routers/, auth, models.
    cli/              Every entry point behind `nhub`.
    data/             Ships inside the package: services/ unit templates,
                      manifests/ the device software catalog, examples/ the
                      committed *.example.json, frontend/ the built panel,
                      resources/ the icons copied in at build time.
  frontend/           React + TypeScript source. Builds into data/frontend/.
  tests/
agent/
  neutrino_agent/     The device agent: Linux, Windows, macOS; root,
                      headless. Pure standard
                      library, no dependencies.
    modules/<name>/   One device module each; modules/shared/ what every
                      module runner shares: the package and unpack
                      machinery, the account service layer, the forwarder.
  sshserver/          The agent's own SSH server, a Go module of its own.
  tests/
transport/            The Go module of the channel the hub, the agent and
                      the clients carry: the knock, the Noise handshake,
                      the yamux sessions, the relay, the local channel,
                      and the WebRTC gate of a Web share's guests.
client/
  desktop/
    neutrino_client/  The client: a person's session on Linux, Windows or
                      macOS; a tray and a window.
    frontend/         The client window's page: plain HTML/CSS/JS, no toolchain.
    packaging/        deb and rpm builds of the compiled client, and the
                      payload every package stages.
    tests/
  android/            The Android app: Gradle, Kotlin, Jetpack Compose.
                      AGPL-3.0.
  ios/                The iOS app: XcodeGen, Swift, SwiftUI. AGPL-3.0.
share_page/           The page a Web share link opens in a visitor's
                      browser: plain JavaScript, hosted as static files.
packaging/            build/ one script per release target, shared/ what
                      they share, ci/ the post-install checks, install/ the
                      one-command install scripts, lab/ the VM lab,
                      integration/ the suite that runs on a box.
config/               Source of truth at runtime. Real files gitignored.
                      /etc/neutrino/hub once installed.
skills/core-code-author/        This standard. The single source of truth for rules.
skills/doc-author/              How every .md is written: the gate, the page kinds,
                      the two registers, the checklist.
images/               Source artwork and README screenshots. Ships nowhere
                      directly — packaging copies images/icons in at build
                      time.
```

Do not put `main()`, `argparse`, or wiring-config classes in a library
module — execution lives in `neutrino_hub/cli/<name>.py`, and each of those is
a subcommand of `nhub`.
Full tree: [design/repository_tree.md](skills/core-code-author/design/repository_tree.md).

## Conventions that bite

These are the ones agents get wrong most often. Each is spelled out with
examples in the document named beside it.

- **Renderers are pure.** No `systemctl`, `nft` or `ip` in a renderer; effects
  belong in the apply layer. Do not break the `config/ → render → apply`
  separation. ([design/architecture.md](skills/core-code-author/design/architecture.md))
- **Bools read as questions.** `is_` / `has_` on variables, attributes,
  Pydantic fields, `config/` JSON keys and TypeScript fields alike.
  ([coding_style/naming.md](skills/core-code-author/coding_style/naming.md))
- **No narrated reasoning.** Not in comments, docstrings, UI copy, or error
  messages. Rationale goes in `docs/`.
  ([coding_style/comment.md](skills/core-code-author/coding_style/comment.md))
- **One exceptions table per package.** A raise site uses Python's own kind
  when one says it; a kind of the package's own is declared in
  `<package>/exceptions.py` and nowhere else, and every public docstring
  carries `Raises:`.
  ([coding_style/exception.md](skills/core-code-author/coding_style/exception.md))
- **English only**, including when translating comments you find.
  ([coding_style/comment.md](skills/core-code-author/coding_style/comment.md))
- **Smallest change that works.** No restructuring you were not asked for, no
  layer for a case nobody has.
  ([coding_style/comment.md](skills/core-code-author/coding_style/comment.md))
- **A reset hands the network back before it replaces `config/`, and takes no
  address off anything.** `config/` is the only record of which interfaces had
  units on them, and an interface losing its address mid-reset drops the
  session that asked for it.
  ([design/hub_components/network.md](skills/core-code-author/design/hub_components/network.md))
- **Never commit unasked.** When work looks done, ask. A commit is a finished,
  tested feature. ([agent_work_rule/commit.md](skills/core-code-author/agent_work_rule/commit.md))
- **`sudo` never appears in the hub's own code.** The panel is already root, so
  reaching a service account is `runuser -u <account> --`; sudo refuses to run
  under the unit's `NoNewPrivileges`.
  ([design/privilege.md](skills/core-code-author/design/privilege.md))
- **Documents open with a definition and never end with a summary.** No
  "note that", no recap section, no em dash inside a sentence, no verb a
  machine does not perform. ([doc-author/SKILL.md](skills/doc-author/SKILL.md))
