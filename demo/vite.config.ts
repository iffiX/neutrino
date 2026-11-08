import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import type { Plugin } from "vite";
import react from "@vitejs/plugin-react";

// The demo's build. It writes a folder of static files for any static host. The
// panel is built from `hub/frontend/src/`, and the client page is copied as it
// is. The panel's own build reads nothing here.

function here(relative: string): string {
  return fileURLToPath(new URL(relative, import.meta.url));
}

const DEMO_DIR = here(".");
const OUT_DIR = here("./dist");
const PUBLIC_DIR = here("../hub/frontend/public");
const MODULE_ICONS_DIR = here("../images/icons/modules");
const HUB_ICONS_DIR = here("../images/icons/neutrino_hub");
const CLIENT_DIR = here("../client/desktop/frontend/");
const PHONE_WORDS_DIR = here(
  "../client/android/app/src/main/assets/locales/app/",
);
const EDITION_REPLACEMENT = here("./panel_edition.ts");
const PREVIEW_PORT = 4780;

// The client page's files, the terminal fonts left out.
const CLIENT_FILES = [
  "app.js",
  "style.css",
  "vendor/xterm.js",
  "vendor/xterm.css",
  "vendor/addon-fit.js",
];
const DEMO_CLIENT_FILES = [
  "client_bridge.js",
  "client_desktop_scene.js",
  "client_join.js",
  "client_keyboard.js",
  "client_phone.css",
  "client_phone.js",
  "client_viewer.css",
  "client_viewer.js",
];
const CLIENT_LANGUAGES = ["en", "zh-CN"];
const CLIENT_WORDS_ELEMENT = '<script id="words" type="application/json">{}';

// The sidebar stays down to a phone's width. A half of a wide window is portrait
// and would draw the bottom bar.
const PANEL_NARROW_QUERY =
  "@media (max-aspect-ratio: 1 / 1), (max-width: 880px)";
const DEMO_NARROW_QUERY = "@media (max-width: 640px)";

// The words the demo never shows. A catalog sentence holding one is dropped and
// falls back to English, except those reworded here and those only the
// international edition draws.
const BANNED_WORDS = /VPN|翻墙|收费|会员|代理|福瑞|内网穿透|青龙/;
const INTERNATIONAL_KEYS =
  /^(ui\.proxy\.|ui\.nav\.proxy$|ui\.shell\.chip_proxy$|ui\.dashboard\.(scope_proxied|tile_proxy_exits)$|ui\.network\.upstream_hint$|code\.(no_exit_node_enabled|policy_route_|tun_|xray_))/;
const CATALOG_REWORDED: Record<string, string> = {
  "ui.list.empty": "没有条目。",
  "ui.network.exposure_hint":
    "哪些网段的主机能连到中枢自己的端口：面板的 HTTP 和 HTTPS、连接端口、DNS。SSH 等不归中枢的服务由系统防火墙管。",
};

/** Puts the demo's edition table in place of `hub/frontend/src/edition.ts`. */
function demoEdition(): Plugin {
  return {
    name: "demo_edition",
    enforce: "pre",
    resolveId(source, importer) {
      const isPanelImport =
        importer !== undefined && importer.includes("/hub/frontend/src/");
      return isPanelImport && /\/edition$/.test(source)
        ? EDITION_REPLACEMENT
        : null;
    },
  };
}

/** Rewrites what the panel's CSS needs for the demo. */
function panelStyles(): Plugin {
  return {
    name: "demo_panel_styles",
    enforce: "pre",
    transform(code, id) {
      if (!id.endsWith(".css") || !id.includes("/hub/frontend/src/")) {
        return null;
      }
      return code
        .replace(/@font-face\s*{[^}]*MesloLGS[^}]*}/g, "")
        .replaceAll(PANEL_NARROW_QUERY, DEMO_NARROW_QUERY);
    },
  };
}

/** Takes the banned words out of the panel's Chinese catalog. */
function panelCatalog(): Plugin {
  return {
    name: "demo_panel_catalog",
    enforce: "pre",
    transform(code, id) {
      if (!/\/src\/locales\/zh-CN\/[a-z_]+\.json$/.test(id)) {
        return null;
      }
      const words = JSON.parse(code) as Record<string, string>;
      const kept = Object.entries(words)
        .map(([key, word]) => [key, CATALOG_REWORDED[key] ?? word] as const)
        .filter(
          ([key, word]) =>
            INTERNATIONAL_KEYS.test(key) || !BANNED_WORDS.test(word),
        );
      return JSON.stringify(Object.fromEntries(kept));
    },
  };
}

/** A nested catalog's sentences by dotted key, as the phone app reads it. */
function flattened(
  node: Record<string, unknown>,
  prefix = "",
): Record<string, string> {
  const words: Record<string, string> = {};
  for (const [name, value] of Object.entries(node)) {
    const key = prefix === "" ? name : `${prefix}.${name}`;
    if (typeof value === "string") {
      words[key] = value;
    } else {
      Object.assign(words, flattened(value as Record<string, unknown>, key));
    }
  }
  return words;
}

function readJson(path: string): Record<string, unknown> {
  return JSON.parse(readFileSync(path, "utf-8")) as Record<string, unknown>;
}

/**
 * The demo's packages. Each resolves from `demo/node_modules`, for a demo file
 * and for a file of the panel's source alike.
 */
function demoPackages(): string[] {
  const manifest = readJson(`${DEMO_DIR}package.json`);
  return Object.keys(manifest.dependencies as Record<string, string>);
}

function clientPage(): string {
  const demoWords = readJson(`${DEMO_DIR}client_words.json`);
  const catalogs = Object.fromEntries(
    CLIENT_LANGUAGES.map((language) => [
      language,
      {
        ...readJson(`${CLIENT_DIR}locales/${language}.json`),
        ...flattened(readJson(`${PHONE_WORDS_DIR}${language}.json`)),
        ...(demoWords[language] as Record<string, string>),
      },
    ]),
  );
  const words = JSON.stringify(catalogs).replaceAll("</", "<\\/");
  const opening = CLIENT_WORDS_ELEMENT.slice(0, -2);
  return readFileSync(`${CLIENT_DIR}index.html`, "utf-8")
    .replace('lang="en" data-theme="dark"', 'lang="zh-CN" data-theme="light"')
    .replace(CLIENT_WORDS_ELEMENT, `${opening}${words}`)
    .replace(
      '<link rel="stylesheet" href="style.css">',
      '<link rel="stylesheet" href="style.css">\n<link rel="stylesheet" href="client_phone.css">\n<link rel="stylesheet" href="client_viewer.css">',
    )
    .replace(
      '<script src="app.js"></script>',
      '<script src="client_bridge.js"></script>\n<script src="app.js"></script>\n<script src="client_keyboard.js"></script>\n<script src="client_phone.js"></script>\n<script src="client_join.js"></script>\n<script src="client_desktop_scene.js"></script>\n<script src="client_viewer.js"></script>\n<script>openTab = "apps";</script>',
    );
}

/** Copies the client page into `client/`, its bridge and phone CSS beside it. */
function clientFiles(): Plugin {
  return {
    name: "demo_client_files",
    generateBundle() {
      for (const name of CLIENT_FILES) {
        this.emitFile({
          type: "asset",
          fileName: `client/${name}`,
          source: readFileSync(`${CLIENT_DIR}${name}`),
        });
      }
      for (const name of DEMO_CLIENT_FILES) {
        this.emitFile({
          type: "asset",
          fileName: `client/${name}`,
          source: readFileSync(`${DEMO_DIR}${name}`),
        });
      }
      this.emitFile({
        type: "asset",
        fileName: "client/index.html",
        source: clientPage(),
      });
    },
  };
}

export default defineConfig({
  root: DEMO_DIR,
  base: "./",
  publicDir: PUBLIC_DIR,
  plugins: [
    demoEdition(),
    panelStyles(),
    panelCatalog(),
    react(),
    clientFiles(),
  ],
  resolve: {
    alias: {
      "@module_icons": MODULE_ICONS_DIR,
      "@hub_icons": HUB_ICONS_DIR,
    },
    dedupe: demoPackages(),
  },
  build: {
    outDir: OUT_DIR,
    emptyOutDir: true,
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      input: {
        index: `${DEMO_DIR}index.html`,
        panel: `${DEMO_DIR}panel.html`,
      },
      output: {
        manualChunks: {
          recharts: ["recharts"],
          xterm: ["@xterm/xterm", "@xterm/addon-fit"],
        },
      },
    },
  },
  preview: {
    port: PREVIEW_PORT,
  },
});
