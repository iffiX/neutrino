# Maintaining the documentation site

`docs/guide/` is a standalone VitePress project. It builds to static HTML, CSS,
JavaScript and a search index that any web server can host.

This page is for whoever maintains the site. It is excluded from the build
(`srcExclude` in `.vitepress/config.mts`), so it never becomes a page.

## Build and preview

Every command runs in `docs/guide/`.

```bash
npm ci
npm run dev
```

`dev` serves the site on 127.0.0.1 and reloads on save. With nvm, run
`nvm install && nvm use` here first; both read `.nvmrc`, which pins Node 24.

```bash
npm run check
npm run build
npm run preview
```

`check` runs prettier, ESLint, TypeScript and the shot check. `build` writes
`.vitepress/dist/`. `preview` serves that directory on
`http://127.0.0.1:4173/`.

Deploying under a repository subpath (no custom domain) needs the same base at
build and preview time:

```bash
NEUTRINO_DOCS_BASE=/neutrino/ npm run build
NEUTRINO_DOCS_BASE=/neutrino/ npm run preview
```

`packaging/build/build_docs.py` runs the same steps the workflow runs:
`npm ci` with `--install`, then `check`, then `build` once for each `--base`.

```bash
python3 ../../packaging/build/build_docs.py --install --base /neutrino/
```

`cleanUrls` is off, so pages keep their `.html` addresses and a static server
needs no rewrite rules.

## Locale layout

English is the root locale; Simplified Chinese lives under `zh-CN/`. The
sidebar follows the panel's own: the hub's pages, then the pages that act on
one managed machine, then the clients, the commands and the reference.

```text
docs/guide/
  index.md                      English home
  overview.md, quick-start.md   Start
  hub/                          install, then one page per page of the panel's
                                Hub group, in its order
  agent/                        terminals, files, modules, and modules/ with
                                one page per module
  client/                       desktop, android
  commands/                     nhub, nagent, nclient
  reference/, protocol/         platforms, troubleshooting, the channel
  zh-CN/                        the same tree in Chinese
  README.md                     this page, excluded from the build
  .vitepress/config.mts         site, locales, search, base path
  .vitepress/navigation.ts      sidebarEn / sidebarZh, navEn / navZh
  .vitepress/theme/             styling on top of the default theme
  .vitepress/prepare_assets.mjs copies and converts images into public/
```

The two locales carry the same paths, the same heading count and the same
screenshot list. A page added to one is added to the other, and to both
sidebars in `navigation.ts`.

Neither language is a translation of the other. Both are written under
[`skills/doc-author/`](../../skills/doc-author/SKILL.md), each from its own
register file.

## Where images come from

`prepare_assets.mjs` runs before `dev` and `build`. It copies:

| Source                                               | Destination     | Referenced as                                                                                           |
| ---------------------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------- |
| `images/icons/neutrino_64.png`, `neutrino_512.png`   | `public/`       | `/neutrino_64.png`                                                                                      |
| `images/guide/` (recursive)                          | `public/guide/` | `/guide/en/<name>.webp`, `/guide/zh/<name>.webp`, `/guide/os/<name>.webp`, `/guide/console/<name>.webp` |
| `images/web/overview_*.svg`, the overview's diagrams | `public/guide/` | `/guide/overview_one_computer.svg`                                                                      |

Every screenshot has an entry in
`packaging/screenshots/shots.json`, and the tool beside it
captures them as png. The script writes each png under `images/guide/` as the
webp of the same name, replacing an older webp. For a table entry with no
image yet, it writes a one-pixel placeholder and prints a warning, so the
build goes on.

`npm run check` runs `check_shots.py`, which fails when a page references an
image the table does not name for that page, or the table names one the page
does not use. Add a screenshot to the table and to both language pages in the
same change. An `os` or `console` entry is one image both language pages
reference, and an entry with `pages` is one image every listed page
references.

The `console` images are pages of the NetBird and EasyTier consoles, taken
from a browser profile kept outside the repository and deleted after the
capture; the
[screenshot tool's README](../../packaging/screenshots/README.md) says how it
is signed in.

Nothing copied into `public/` is committed: `.gitignore` holds
`public/neutrino_64.png`, `public/neutrino_512.png` and `public/guide/`.

## GitHub Pages

`.github/workflows/docs.yml` builds and checks every pull request that
touches `docs/guide/**`, `images/guide/**`, `images/icons/**`, `images/web/**`,
`packaging/screenshots/**`, `packaging/build/build_docs.py` or the workflow
itself, by running `packaging/build/build_docs.py`. It publishes
on a pushed `v*` tag, so the site shows the guide of the newest release.

The three Pages steps (`configure-pages`, `upload-pages-artifact` and the
`deploy` job) run only on a `v*` tag and only when the repository variable
`DOCS_PAGES_ENABLED` is `true`. A run on any other ref builds and checks and
publishes nothing. The `github-pages` environment needs a deployment rule for
`v*` tags in `Settings → Environments`.

The site is published at `https://neutrino.beyond-infinity.top/`: a DNS CNAME
from that name to `iffix.github.io`, and `public/CNAME` carrying the name so
every deploy keeps it. With a custom domain the base path is `/`.

To switch publishing on:

1. `Settings → Pages → Build and deployment → Source`: `GitHub Actions`, and
   `Custom domain`: `neutrino.beyond-infinity.top` with `Enforce HTTPS`.
2. `Settings → Secrets and variables → Actions → Variables`: add
   `DOCS_PAGES_ENABLED` with the value `true`.
3. Run the `docs` workflow on the newest `v*` tag, or push a new one.

The workflow reads the real base path from `configure-pages`, so a repository
subpath and a custom domain both build correctly. The deploy job requests
`pages: write` and `id-token: write`; no personal access token is stored.

## Other static hosts

| Setting      | Value                                               |
| ------------ | --------------------------------------------------- |
| Project root | `docs/guide`                                        |
| Node.js      | `24`                                                |
| Install      | `npm ci`                                            |
| Build        | `npm run build`                                     |
| Output       | `.vitepress/dist`                                   |
| Environment  | `NEUTRINO_DOCS_BASE` when deploying under a subpath |

The host must serve directory indexes and return `404.html` with an HTTP 404
status. Connect the whole repository, not `docs/guide` alone: the build reads
`images/`.
