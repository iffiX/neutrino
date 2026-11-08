# The panel demo

The panel demo is the page the website serves at `/demo/`: the hub's panel
and the client's phone page side by side, each drawn by its own code over a
fake hub that runs in the browser. `demo/` holds the fake hub, its sample
data, the page around the two frames and the build. The panel's source
stays in `hub/frontend/src/` and the client's page in
`client/desktop/frontend/`, and each build of the demo reads them there.

## What is real code and what is sample data

| Part | Comes from | Changed for the demo |
| --- | --- | --- |
| The panel: pages, components, words, styles | `hub/frontend/src/`, imported by `demo/panel_main.tsx` | `panel_edition.ts` replaces `src/edition.ts`. `panel_transport.ts` serves `fetch` under `/api` and every `WebSocket` from the fake hub. The build drops the MesloLGS font and narrows the panel's phone query. It also drops each Chinese catalog sentence that holds a word the demo never shows. |
| The client's page | `client/desktop/frontend/`: `index.html`, `app.js`, `style.css`, `vendor/` and its two catalogs, copied in at build time. The phone's words come from `client/android/app/src/main/assets/locales/app/`. | `client_bridge.js` replaces the desktop window's pywebview bridge. `client_phone.js`, `client_join.js`, `client_keyboard.js`, `client_viewer.js` and `client_desktop_scene.js` load after `app.js` and replace its functions: the phone's bar, the Join page, the keyboard and the remote desktop viewer. |
| The icons | `images/icons/`, through the panel's two aliases | none |
| The sample data | `demo_hub.ts`, the fake hub's state, routes and sockets; `demo_fixtures.ts`, `demo_network.ts`, `demo_proxy.ts`, `demo_traffic.ts` and `demo_modules.ts`; `demo_client_core.ts`, the client's state document and routes; `demo_shell*.ts`, a shell over a small file tree | Typed by the panel's `hub/frontend/src/api_types.ts`. |
| The page around the frames | `index.html`, `shell_main.ts`, `shell.css`, `demo_words.ts` | The edition switch, and the language and the palette of both frames. `?lang=en` opens the demo in English as the international edition. |

## The build

```bash
cd demo && npm ci           # demo/node_modules, from demo/package-lock.json
cd demo && npm run build    # tsc -p ., then vite build into demo/dist
cd demo && npm run preview  # demo/dist at 127.0.0.1:4780
```

| Rule | Reason |
| --- | --- |
| `demo/` installs its own `node_modules` from `demo/package.json` and `demo/package-lock.json`, and its build runs in `demo/`. Under `hub/` the demo reads the panel's source alone: `src/`, `public/` and `tsconfig.app.json`. | `hub/` holds the hub and its panel alone. |
| One copy of each package runs. `resolve.dedupe` in `demo/vite.config.ts` names every package of the `dependencies` of `demo/package.json`, so a file under `hub/frontend/src/` resolves `react`, `react-dom` and every other package from `demo/node_modules`. `demo/tsconfig.json` points `paths` and `typeRoots` at `demo/node_modules`. | Vite resolves a bare import from the importing file's directory upward. A file under `hub/frontend/src/` reaches `hub/frontend/node_modules` first wherever the panel's packages are installed. React's hooks fail with two copies of React in one page, and the router's context fails with two copies of React Router. |
| `demo/package.json` names each package of `hub/frontend/package.json` but the lint and format tools, in the same section, at the same version. `demo/package-lock.json` holds each package at the version `hub/frontend/package-lock.json` holds. | The demo runs the panel's source on the packages the panel is built with. One version of each package is installed twice, once for each directory. A package the panel adds or moves fails the version check until the demo follows. |
| The build writes `demo/dist/`, which is gitignored. | The hub's packages copy `hub/neutrino_hub` alone, and `demo/` sits outside it. |
| `packaging/build/build_docs.py` runs `npm run build` in `demo/` after the site's check, and its `--install` runs `npm ci` in `docs/` and in `demo/`. It copies `demo/dist` into the site's `demo/` after each `--base` build. | A deploy from a tag holds the demo of that tag. |
| `panel_edition.ts` reaches the Proxy page through the panel's edition table, `hub/frontend/src/edition.ts`. | The mainland tree is this tree with the proxy's files deleted. It keeps `demo/`, and the demo builds there without the Proxy page. |

## The checks

| Check | Catches | Runs |
| --- | --- | --- |
| `tsc -p .`, the first step of `npm run build` | Sample data out of step with the panel's API types: a field the panel adds, renames or drops. The panel's own `tsc -b` passes such a change. | The `demo` job of `ci.yml`, on every push and pull request. `docs.yml`, through `build_docs.py`. |
| `hub/tests/packaging/test_demo_packages.py`, the version check | A package of the panel's that the demo needs, missing from `demo/package.json` or named at another version; a package the panel's `package.json` lacks; an entry of `demo/package-lock.json` at a version the panel's lock does not hold. | The hub's suite, in both trees. |
| `packaging/ci/check_demo.py <folder>`, which opens the built demo in headless Chromium through Playwright, in Chinese as the mainland edition and with `?lang=en` | In each run: a panel page of nine, a tab of the phone's bar or the Proxy page that fails to draw, a Proxy page in the mainland edition, an uncaught exception in either frame, a console error, a file the server lacks. A `client_*.js` that replaces a function of a changed `app.js` wrongly fails here. | The `demo` job of `ci.yml`, on `demo/dist`, with no `hub/frontend/node_modules`. `docs.yml`, on the site's `demo/` before the deploy. |

`docs.yml` runs for a pull request that changes `demo/`,
`hub/frontend/src/`, `client/desktop/frontend/`, the site or its scripts.
