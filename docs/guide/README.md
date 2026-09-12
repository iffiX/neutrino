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

`check` runs prettier, ESLint and TypeScript. `build` writes
`.vitepress/dist/`. `preview` serves that directory on
`http://127.0.0.1:4173/`.

Deploying under a repository subpath (no custom domain) needs the same base at
build and preview time:

```bash
NEUTRINO_DOCS_BASE=/neutrino/ npm run build
NEUTRINO_DOCS_BASE=/neutrino/ npm run preview
```

`cleanUrls` is off, so pages keep their `.html` addresses and a static server
needs no rewrite rules.

## Locale layout

English is the root locale; Simplified Chinese lives under `zh-CN/`. Pages
are grouped by component, and each group runs install, use, commands.

```text
docs/guide/
  index.md                      English home
  overview.md, quick-start.md   Start
  hub/                          install, one page per panel page in sidebar
                                order, cli (nhub)
  agent/                        install, cli (nagent)
  client/                       install, window, one page per client panel,
                                cli (nclient)
  reference/                    platforms, troubleshooting
  zh-CN/                        the same tree in Chinese
  README.md                     this page, excluded from the build
  .vitepress/config.mts         site, locales, search, base path
  .vitepress/navigation.ts      sidebarEn / sidebarZh, navEn / navZh
  .vitepress/theme/             styling on top of the default theme
  .vitepress/prepare_assets.mjs copies images into public/ before a build
```

The two locales carry the same paths, the same heading count and the same
screenshot list. A page added to one is added to the other, and to both
sidebars in `navigation.ts`.

Neither language is a translation of the other. Both are written under
[`skills/doc-author/`](../../skills/doc-author/SKILL.md), each from its own
register file.

## Where images come from

`prepare_assets.mjs` runs before `dev` and `build`. It copies:

| Source                                               | Destination     | Referenced as                                                             |
| ---------------------------------------------------- | --------------- | ------------------------------------------------------------------------- |
| `images/icons/neutrino_64.png`, `neutrino_512.png`   | `public/`       | `/neutrino_64.png`                                                        |
| `images/guide/` (recursive)                          | `public/guide/` | `/guide/en/<name>.webp`, `/guide/zh/<name>.webp`, `/guide/os/<name>.webp` |
| `images/web/architecture.svg`, `architecture_zh.svg` | `public/guide/` | `/guide/architecture.svg`                                                 |

`images/guide/` may not exist in a fresh working copy; the script skips what is
missing rather than failing, and the pages show broken images until the
screenshots land.

Nothing copied into `public/` is committed: `.gitignore` holds
`public/neutrino_64.png`, `public/neutrino_512.png` and `public/guide/`.

## GitHub Pages

`.github/workflows/docs.yml` builds on every pull request and on pushes to
`main` that touch `docs/guide/**`, `images/guide/**`, `images/web/**` or the
workflow itself.

The three Pages steps (`configure-pages`, `upload-pages-artifact` and the
`deploy` job) are gated on the repository variable `DOCS_PAGES_ENABLED`. Until
it is set, `main` still builds and checks, and nothing is published.

The site is published at `https://neutrino.beyond-infinity.top/`: a DNS CNAME
from that name to `iffix.github.io`, and `public/CNAME` carrying the name so
every deploy keeps it. With a custom domain the base path is `/`.

To switch publishing on:

1. `Settings → Pages → Build and deployment → Source`: `GitHub Actions`, and
   `Custom domain`: `neutrino.beyond-infinity.top` with `Enforce HTTPS`.
2. `Settings → Secrets and variables → Actions → Variables`: add
   `DOCS_PAGES_ENABLED` with the value `true`.
3. Re-run the `docs` workflow on `main`.

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
