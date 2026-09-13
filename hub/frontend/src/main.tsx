import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app";
import { apiGet } from "./api_client";
import { LANGUAGE_DEFAULT, setLanguage } from "./i18n";
import { THEME_DEFAULT, setThemeChoice } from "./theme";
import type { PanelLanguage, PanelTheme } from "./api_types";

import "./fonts.css";
import "./theme.css";
import "./themes/dark.css";
import "./themes/light.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("index.html is missing the #root container");
}

/**
 * The language the box holds, or English.
 *
 * Read before the first render, from the one route that answers without a
 * session. The wizard's own server has no such route, so a first run is in
 * English until its first screen says otherwise.
 */
async function panelLanguage(): Promise<string> {
  try {
    return (await apiGet<PanelLanguage>("/language")).language;
  } catch {
    return LANGUAGE_DEFAULT;
  }
}

/**
 * The theme the box holds, or dark.
 *
 * Read beside the language, and for the same reason: a login card drawn in
 * the other palette is a flash a session arrives too late to prevent.
 */
async function panelTheme(): Promise<string> {
  try {
    return (await apiGet<PanelTheme>("/theme")).theme;
  } catch {
    return THEME_DEFAULT;
  }
}

void Promise.all([panelLanguage(), panelTheme()]).then(([language, theme]) => {
  setLanguage(language);
  setThemeChoice(theme);
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
