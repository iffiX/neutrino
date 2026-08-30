import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI panel that serves `dist/` in production. During `npm run dev`
// Vite proxies both the REST surface and the websockets there so the frontend
// talks to the same origin-relative paths in both modes.
const BACKEND_ORIGIN = "http://127.0.0.1:8080";

export default defineConfig({
  plugins: [react()],
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
