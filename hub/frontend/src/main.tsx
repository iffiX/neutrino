import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app";
import { apiGet } from "./api_client";
import { LANGUAGE_DEFAULT, setLanguage } from "./i18n";
import { THEME_DEFAULT, setThemeChoice } from "./theme";
import type { PanelDisplay } from "./api_types";

import "./fonts.css";
import "./theme.css";
import "./themes/dark.css";
import "./themes/light.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("index.html is missing the #root container");
}

/**
 * The language and the palette the box holds, or English and dark.
 *
 * Read before the first render, from the one route that answers without a
 * session. A login card drawn in the other palette is a flash a session
 * arrives too late to prevent. The wizard's own server has no such route, so
 * a first run is in English until its first screen says otherwise.
 */
async function panelDisplay(): Promise<PanelDisplay> {
  try {
    return await apiGet<PanelDisplay>("/hub/display");
  } catch {
    return { language: LANGUAGE_DEFAULT, theme: THEME_DEFAULT };
  }
}

void panelDisplay().then(({ language, theme }) => {
  setLanguage(language);
  setThemeChoice(theme);
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
