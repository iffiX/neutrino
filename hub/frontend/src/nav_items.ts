import type { IconName } from "./components/icon";

/**
 * The sidebar's contents, in order.
 *
 * The router and the nav read the same list, so a new page cannot appear in
 * one and be missing from the other.
 *
 * Two groups, and the split is who the page acts on. Hub is the box itself:
 * the network it routes, the proxy it runs, the devices and clients it
 * knows. Agent is what the hub drives on a machine running the agent —
 * itself included, since the hub box is one of them. Every page is always
 * listed: a page whose module is on no machine still says so, which is worth
 * more than a rail that changes shape underneath somebody.
 *
 * A row carries catalog keys rather than sentences, so the nav words itself
 * at render and a language change re-words it.
 */

export type NavGroup = "hub" | "agent";

export interface NavItem {
  path: string;
  labelKey: string;
  icon: IconName;
  descriptionKey: string;
  group: NavGroup;
}

export const NAV_ITEMS: NavItem[] = [
  {
    path: "/",
    labelKey: "ui.nav.dashboard",
    icon: "dashboard",
    descriptionKey: "ui.nav.dashboard_description",
    group: "hub",
  },
  {
    path: "/network",
    labelKey: "ui.nav.network",
    icon: "network",
    descriptionKey: "ui.nav.network_description",
    group: "hub",
  },
  {
    path: "/overlay",
    labelKey: "ui.nav.overlay",
    icon: "mesh",
    descriptionKey: "ui.nav.overlay_description",
    group: "hub",
  },
  {
    path: "/proxy",
    labelKey: "ui.nav.proxy",
    icon: "globe",
    descriptionKey: "ui.nav.proxy_description",
    group: "hub",
  },
  {
    path: "/ai",
    labelKey: "ui.nav.ai",
    icon: "sparkles",
    descriptionKey: "ui.nav.ai_description",
    group: "hub",
  },
  {
    path: "/devices",
    labelKey: "ui.nav.devices",
    icon: "devices",
    descriptionKey: "ui.nav.devices_description",
    group: "hub",
  },
  {
    path: "/clients",
    labelKey: "ui.nav.clients",
    icon: "laptop",
    descriptionKey: "ui.nav.clients_description",
    group: "hub",
  },
  {
    path: "/services",
    labelKey: "ui.nav.services",
    icon: "bolt",
    descriptionKey: "ui.nav.services_description",
    group: "hub",
  },
  {
    path: "/credentials",
    labelKey: "ui.nav.credentials",
    icon: "key",
    descriptionKey: "ui.nav.credentials_description",
    group: "hub",
  },
  {
    path: "/settings",
    labelKey: "ui.nav.settings",
    icon: "settings",
    descriptionKey: "ui.nav.settings_description",
    group: "hub",
  },
  {
    path: "/terminals",
    labelKey: "ui.nav.terminals",
    icon: "terminal",
    descriptionKey: "ui.nav.terminals_description",
    group: "agent",
  },
  {
    path: "/files",
    labelKey: "ui.nav.files",
    icon: "folder",
    descriptionKey: "ui.nav.files_description",
    group: "agent",
  },
  {
    path: "/samba",
    labelKey: "ui.nav.samba",
    icon: "hard_drive",
    descriptionKey: "ui.nav.samba_description",
    group: "agent",
  },
  {
    path: "/gitea",
    labelKey: "ui.nav.gitea",
    icon: "gitea",
    descriptionKey: "ui.nav.gitea_description",
    group: "agent",
  },
  {
    path: "/containers",
    labelKey: "ui.nav.containers",
    icon: "cube",
    descriptionKey: "ui.nav.containers_description",
    group: "agent",
  },
  {
    path: "/zfs",
    labelKey: "ui.nav.zfs",
    icon: "database",
    descriptionKey: "ui.nav.zfs_description",
    group: "agent",
  },
];

/**
 * The pages of one group, in declared order.
 *
 * Args:
 *   group: Which half of the sidebar to take.
 *
 * Returns:
 *   That group's pages.
 */
export function navItemsInGroup(group: NavGroup): NavItem[] {
  return NAV_ITEMS.filter((item) => item.group === group);
}
