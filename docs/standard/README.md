# neutrino engineering standard

This is the canonical engineering standard for the `neutrino` repository. It is
the single source of truth. Every human and every AI coding agent working in
this repo (Claude Code, Codex, Cursor, or otherwise) follows it.

Read this file first, then open the pillar relevant to your change.

## Why this exists

`neutrino` is a personal developer infrastructure hub, worked on by its owner
and by several AI agents. The code spans a few distinct worlds — xray config
generation, nftables/routing, a FastAPI backend, a React frontend, systemd
deployment, and a device agent that has to run on whatever Python a machine
happens to have — and it has to stay calm, consistent, and reviewer-legible no
matter which part or which agent touched it. This document makes the
conventions explicit so nobody drifts.

## The five pillars, and a shelf of reference

1. **Coding style** — the mechanical surface rules. Where files go, how things
   are named, how a file is laid out and formatted.
   - [coding_style/layout_style.md](coding_style/layout_style.md) — directory layout, the
     underscore rule, the library-vs-`neutrino_hub/cli/` split, `config/` as data,
     `constants.py`, and why `neutrino_hub/cli/` has no `__init__.py`.
   - [coding_style/naming_style.md](coding_style/naming_style.md) — identifiers: module
     legibility, `is_`/`has_` bools, constant prefixes, banned terms.
   - [coding_style/python_style.md](coding_style/python_style.md) — file
     internal order, method order, black, Google docstrings, no helper lambdas,
     no shouting caps.
   - [coding_style/comment_style.md](coding_style/comment_style.md) — comments,
     UI copy and commit messages: state the fact, no narrated reasoning.
   - [coding_style/typescript_style.md](coding_style/typescript_style.md) — the
     React + TypeScript frontend: prettier/eslint, under_score files, no `any`,
     component order.

2. **Documentation style** — how the three kinds of document in this repo are
   written, in English and in Chinese. Grounded in a full-text study of the
   Xray-core documentation (106 Chinese pages, 107 English), so the rules come
   with measured frequencies, quoted passages and reusable sentence templates
   rather than opinions.
   - [doc_style/README.md](doc_style/README.md) — which kind is which and where
     the boundary runs; the rules all three obey (open with a definition, never
     summarise, the filler word list that measures zero, say what is not true);
     the three warning levels and their ratio; what differs between writing
     Chinese and English.
   - [doc_style/technical_guide_style.md](doc_style/technical_guide_style.md) —
     reference pages: page shape, the six-step field entry, types written as
     literal unions, defaults that say what they do, answering "what if I leave
     it out", counter-examples on the boundary, skeleton code, and the template
     table.
   - [doc_style/usage_guide_style.md](doc_style/usage_guide_style.md) — guides:
     the three reader levels and stating which one you are, why sentence length
     does not change but person does, one command per block for beginners,
     runnable configurations, translating config into a sentence, handing off
     instead of half-teaching.
   - [doc_style/development_guide_style.md](doc_style/development_guide_style.md)
     — guides for people changing the code: commands marked REQUIRED, inline
     directory maps, stating a rule once and pointing at it thereafter, where
     first person is allowed, and how much personality is too much.

3. **Design philosophy** — how to decompose and name for mature software
   engineering. Judgment, not surface.
   - [design/class_design.md](design/class_design.md) —
     cohesion, one concept per class, explicit `__init__` kwargs over config
     objects.
   - [design/class_hierarchy.md](design/class_hierarchy.md)
     — tree-like semantic class names and the per-package `<Domain><Thing><Role>`
     families.
   - [design/architecture.md](design/architecture.md) —
     the two-tier library-vs-`neutrino_hub/cli/` principle, `config/` as the single
     source of truth, and the render-vs-apply separation.
   - [design/repository_tree.md](design/repository_tree.md) — what each
     top-level directory of the source tree is for, and why it is shaped that
     way.
   - [design/files.md](design/files.md) — where an installed hub puts things:
     five roots, and the one question each of them answers.
   - [design/install_and_dev.md](design/install_and_dev.md) — who installs what:
     the package, `nhub setup`, and the panel; and what `--dev` does
     differently against a root of its own.
   - [design/api.md](design/api.md) — how the panel's endpoints are named
     and organised: one module one prefix, what the bare prefix means, and
     when an operation may be a verb.
   - [design/network.md](design/network.md) — the three engines the hub drives
     instead of a network manager, which modes own a machine's network and
     which touch nothing at all, and what was measured on each distribution.
   - [design/visual.md](design/visual.md) — what the accent, the glow and the
     colours are each allowed to mean in the panel, the three button tiers,
     frames and live sections.
   - [design/privilege.md](design/privilege.md) — why the panel runs as root, what the
     systemd unit narrows and what it deliberately does not, and the rule that
     stepping down to a service account uses `runuser` rather than `sudo`.

4. **Agent work rules** — how work enters the repository, as opposed to what
   the code looks like.
   - [agent_work_rule/commit.md](agent_work_rule/commit.md) — one author, who
     is answerable for the change; one sentence of at most 30 words; no agent
     co-author trailers.
   - [agent_work_rule/release.md](agent_work_rule/release.md) — one tag builds
     both packages; hub and agent share a version with no compatibility
     window; changelog lines are `feature:` / `fix:` / `docs:` and nothing
     else; which file each platform installs.

5. **Hygiene** — the anti-patterns to remove on sight.
   - [kill_on_sight.md](kill_on_sight.md) — self-check this before you finish.

6. **Misc** — reference material that is not a rule.
   - [misc/config.md](misc/config.md) — how `config/` works: which files are
     secrets, how the example files map to the real ones, and the first-run
     and backup flow.
   - [misc/operations.md](misc/operations.md) — verifying an install and
     running the appliance day to day.

## How this standard reaches every agent

The detail lives here, in `docs/standard/`, exactly once.

- `AGENTS.md` (repo root) is the index every agent reads: what this repo is,
  the commands, the tree, and a table pointing at the document that settles
  each question. It states no rule it does not link to.
- `CLAUDE.md` is one line, `@AGENTS.md`, so Claude Code reads the same index
  rather than a second copy that can drift.

If you change a rule, change it here. `AGENTS.md` only points.

## How to use it

- Writing or moving code: read the relevant pillar first, then match the
  bad → good example at the top of each detail doc.
- Before you finish: run through [kill_on_sight.md](kill_on_sight.md).
- `black --check` must pass on every Python change; `prettier --check` and
  `eslint` must pass on every frontend change.
