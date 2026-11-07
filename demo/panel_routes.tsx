import { useEffect, useState } from "react";

import { AuthenticatedRoutes } from "../hub/frontend/src/authenticated_routes";
import { setLanguage } from "../hub/frontend/src/i18n";
import { setThemeChoice } from "../hub/frontend/src/theme";
import type { DemoHub } from "./demo_hub";

const SETTINGS_ROUTE = "#/settings";

interface DemoPanelRoutesProps {
  hub: DemoHub;
}

/**
 * The panel's routes, following the top window's overwrites of the language
 * and the palette. The settings page seeds its pickers once, so an overwrite
 * mounts it again.
 */
export function DemoPanelRoutes({ hub }: DemoPanelRoutesProps) {
  const [settingsMount, setSettingsMount] = useState(0);

  useEffect(
    () =>
      hub.onDisplayOverwrite(() => {
        setLanguage(hub.language());
        setThemeChoice(hub.theme());
        if (window.location.hash.startsWith(SETTINGS_ROUTE)) {
          setSettingsMount((count) => count + 1);
        }
      }),
    [hub],
  );

  return <AuthenticatedRoutes key={settingsMount} />;
}
