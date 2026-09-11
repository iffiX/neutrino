import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app";
import { apiGet } from "./api_client";
import { LANGUAGE_DEFAULT, setLanguage } from "./i18n";
import type { PanelLanguage } from "./api_types";

import "./fonts.css";
import "./theme.css";

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

void panelLanguage().then((language) => {
  setLanguage(language);
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
