import type { IconName } from "./components/icon";
import { hasFeature } from "./edition";

/**
 * The sidebar's hub group, in order.
 *
 * The router and the nav read the same list, so a new page cannot appear in
 * one and be missing from the other. The machine group below it is not a
 * list of pages: it is one entry per managed machine, read from the hub
 * (`sidebar_nav.tsx`).
 *
 * A row carries catalog keys rather than sentences, so the nav words itself
 * at render and a language change re-words it.
 */

export interface NavItem {
  path: string;
  labelKey: string;
  icon: IconName;
  descriptionKey: string;
  /** The description where the page holds something else in one network
   * mode, by mode. */
  modeDescriptionKeys?: Record<string, string>;
}

export const NAV_ITEMS: NavItem[] = [
  {
    path: "/",
    labelKey: "ui.nav.dashboard",
    icon: "dashboard",
    // A tree without the proxy has no exits to describe.
    descriptionKey: hasFeature("proxy")
      ? "ui.nav.dashboard_description"
      : "ui.nav.dashboard_description_no_exits",
    modeDescriptionKeys: {
      server: hasFeature("proxy")
        ? "ui.nav.dashboard_description_server"
        : "ui.nav.dashboard_description_server_no_exits",
    },
  },
  {
    path: "/network",
    labelKey: "ui.nav.network",
    icon: "network",
    descriptionKey: "ui.nav.network_description",
    modeDescriptionKeys: {
      server: "ui.nav.network_description_server",
      side_gateway: "ui.nav.network_description_side_gateway",
    },
  },
  {
    path: "/overlay",
    labelKey: "ui.nav.overlay",
    icon: "mesh",
    descriptionKey: "ui.nav.overlay_description",
  },
  // The proxy's page, where the tree carries it.
  ...(hasFeature("proxy")
    ? [
        {
          path: "/proxy",
          labelKey: "ui.nav.proxy",
          icon: "globe" as IconName,
          descriptionKey: "ui.nav.proxy_description",
        },
      ]
    : []),
  {
    path: "/ai",
    labelKey: "ui.nav.ai",
    icon: "sparkles",
    descriptionKey: "ui.nav.ai_description",
  },
  {
    path: "/agents",
    labelKey: "ui.nav.devices",
    icon: "devices",
    descriptionKey: "ui.nav.devices_description",
  },
  {
    path: "/clients",
    labelKey: "ui.nav.clients",
    icon: "laptop",
    descriptionKey: "ui.nav.clients_description",
  },
  {
    path: "/services",
    labelKey: "ui.nav.services",
    icon: "bolt",
    descriptionKey: "ui.nav.services_description",
  },
  {
    path: "/credentials",
    labelKey: "ui.nav.credentials",
    icon: "key",
    descriptionKey: "ui.nav.credentials_description",
  },
  {
    path: "/settings",
    labelKey: "ui.nav.settings",
    icon: "settings",
    descriptionKey: "ui.nav.settings_description",
  },
];
