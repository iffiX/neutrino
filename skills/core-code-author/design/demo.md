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
cd hub/frontend && npm run demo:build    # tsc -p ../../demo, then vite build
cd hub/frontend && npm run demo:preview  # demo/dist at 127.0.0.1:4780
```

| Rule | Reason |
| --- | --- |
| The build runs in `hub/frontend` with its `node_modules`. `demo/vite.config.ts` loads the React plugin from there. Its plugin resolves a bare import in a demo file as a file in `hub/frontend/src/` resolves it. React and React DOM point at `hub/frontend/node_modules`. `demo/tsconfig.json` extends the panel's `tsconfig.app.json` and points `paths` and `typeRoots` at the same `node_modules`. | The panel and the demo share one copy of every package, in `hub/frontend/node_modules`. Node resolves the config's own imports from `demo/`. The React plugin resolves React and React DOM from Vite's root, `demo/`, to keep one copy of each. |
| The build writes `demo/dist/`, which is gitignored. | The hub's packages copy `hub/neutrino_hub` alone, and `demo/` sits outside it. |
| `packaging/build/build_docs.py` runs `npm run demo:build` after the site's check. It copies `demo/dist` into the site's `demo/` after each `--base` build. | A deploy from a tag holds the demo of that tag. |
| `panel_edition.ts` reaches the Proxy page through the panel's edition table, `hub/frontend/src/edition.ts`. | The mainland tree is this tree with the proxy's files deleted. It keeps `demo/`, and the demo builds there without the Proxy page. |

## The two checks

| Check | Catches | Runs |
| --- | --- | --- |
| `tsc -p ../../demo`, the first step of `npm run demo:build` | Sample data out of step with the panel's API types: a field the panel adds, renames or drops. The panel's own `tsc -b` passes such a change. | The `demo` job of `ci.yml`, on every push and pull request. `docs.yml`, through `build_docs.py`. |
| `packaging/ci/check_demo.py <folder>`, which opens the built demo in headless Chromium through Playwright, in Chinese as the mainland edition and with `?lang=en` | In each run: a panel page of nine, a tab of the phone's bar or the Proxy page that fails to draw, a Proxy page in the mainland edition, an uncaught exception in either frame, a console error, a file the server lacks. A `client_*.js` that replaces a function of a changed `app.js` wrongly fails here. | The `demo` job of `ci.yml`, on `demo/dist`. `docs.yml`, on the site's `demo/` before the deploy. |

`docs.yml` runs for a pull request that changes `demo/`,
`hub/frontend/src/`, `client/desktop/frontend/`, the site or its scripts.
