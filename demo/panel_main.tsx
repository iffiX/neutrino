import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";

import "../hub/frontend/src/fonts.css";
import "../hub/frontend/src/theme.css";
import "../hub/frontend/src/themes/dark.css";
import "../hub/frontend/src/themes/light.css";

import { AuthProvider } from "../hub/frontend/src/auth_provider";
import { setLanguage } from "../hub/frontend/src/i18n";
import { startPanelIdentityWatch } from "../hub/frontend/src/panel_identity";
import { setThemeChoice } from "../hub/frontend/src/theme";
import type { DemoPanelWindow, DemoWindow } from "./demo_window";
import { DemoPanelRoutes } from "./panel_routes";
import { installDemoTransport } from "./panel_transport";

import "./panel_fit.css";

function startPanel(): void {
  installDemoTransport();

  const container = document.getElementById("root");
  if (container === null) {
    throw new Error("panel.html is missing the #root container");
  }

  const hub = (window.parent as DemoWindow).neutrinoDemoHub;
  setLanguage(hub.language());
  setThemeChoice(hub.theme());
  startPanelIdentityWatch();
  const root = createRoot(container);
  (window as DemoPanelWindow).neutrinoDemoPanelStop = () => root.unmount();
  root.render(
    <StrictMode>
      <HashRouter>
        <AuthProvider>
          <DemoPanelRoutes hub={hub} />
        </AuthProvider>
      </HashRouter>
    </StrictMode>,
  );
}

// The fake hub lives in the top window, so a frame opened alone goes there.
if (window.parent === window) {
  window.location.replace("./");
} else {
  startPanel();
}
