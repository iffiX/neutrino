import { fileURLToPath } from "node:url";

import { defineConfig, searchForWorkspaceRoot } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI panel that serves `dist/` in production. During `npm run dev`
// Vite proxies both the REST surface and the websockets there so the frontend
// talks to the same origin-relative paths in both modes.
const BACKEND_ORIGIN = "http://127.0.0.1:8080";

// The module glyphs, one file per module, which the panel reads by module
// name through the `@module_icons` alias. The directory sits outside the
// frontend, so the dev server is told it may serve it.
const MODULE_ICONS_DIR = fileURLToPath(
  new URL("../../images/icons/modules", import.meta.url),
);

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@module_icons": MODULE_ICONS_DIR,
    },
  },
  build: {
    // Straight into the package, which is what the panel serves and what the
    // wheel and the deb carry. There is no separate copy step.
    outDir: "../neutrino_hub/data/frontend",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // The charting and terminal libraries dwarf the panel's own code and
        // change only when they are upgraded. Splitting them out keeps the
        // app chunk small enough to re-fetch cheaply after every deploy.
        manualChunks: {
          recharts: ["recharts"],
          xterm: ["@xterm/xterm", "@xterm/addon-fit"],
        },
      },
    },
  },
  server: {
    fs: {
      allow: [searchForWorkspaceRoot(process.cwd()), MODULE_ICONS_DIR],
    },
    proxy: {
      "/api": {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
      },
      "/ws": {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
