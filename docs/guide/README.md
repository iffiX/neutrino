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

Deploying under a repository subpath needs the same base at build and preview
time:

```bash
NEUTRINO_DOCS_BASE=/neutrino/ npm run build
NEUTRINO_DOCS_BASE=/neutrino/ npm run preview
```

`cleanUrls` is off, so pages keep their `.html` addresses and a static server
needs no rewrite rules.

## Locale layout

English is the root locale; Simplified Chinese lives under `zh-CN/`.

```text
docs/guide/
  index.md                      English home
  <page>.md                     English pages
  zh-CN/index.md                Chinese home
  zh-CN/<page>.md               Chinese pages
  README.md                     this page, excluded from the build
  .vitepress/config.mts         site, locales, search, base path
  .vitepress/navigation.ts      sidebarEn / sidebarZh, navEn / navZh
  .vitepress/theme/             styling on top of the default theme
  .vitepress/prepare_assets.mjs copies images into public/ before a build
```

The two locales carry the same filenames, the same heading count and the same
screenshot list. A page added to one is added to the other, and to both
sidebars in `navigation.ts`.

Neither language is a translation of the other. English follows the Google
developer documentation style guide, Chinese follows 中文文案排版指北.

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

To switch publishing on:

1. `Settings → Pages → Build and deployment → Source`: `GitHub Actions`.
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
