import type { IconName } from "./components/icon";

/**
 * The sidebar's contents, in order.
 *
 * The router and the nav read the same list, so a new page cannot appear in
 * one and be missing from the other.
 *
 * Two groups, and the split is the whole shape of the panel. Core is the
 * appliance's reason to exist: move traffic from the LAN, through the proxy,
 * out the WAN, and let its owner see and steer that. Optional is everything
 * the box also happens to host because it is already there and always on — a
 * file share, a git server, a tailnet. Each of those appears only once its
 * service is switched on, so the sidebar stays as short as the appliance
 * actually is rather than advertising what it is not doing.
 */

export type NavGroup = "core" | "optional";

export interface NavItem {
  path: string;
  label: string;
  icon: IconName;
  description: string;
  group: NavGroup;
  /**
   * The service whose presence decides whether this appears. Set only on
   * optional pages; a core page is always there.
   */
  service?: string;
}

export const NAV_ITEMS: NavItem[] = [
  {
    path: "/",
    label: "Dashboard",
    icon: "dashboard",
    description: "Live throughput, exits and DNS",
    group: "core",
  },
  {
    path: "/network",
    label: "Network",
    icon: "network",
    description: "Interface roles, uplinks and DHCP",
    group: "core",
  },
  {
    path: "/proxy",
    label: "Proxy",
    icon: "globe",
    description: "Exit nodes, split routing and DNS",
    group: "core",
  },
  {
    path: "/ai",
    label: "AI",
    icon: "sparkles",
    description: "One endpoint for every AI tool",
    group: "core",
  },
  {
    path: "/devices",
    label: "Devices",
    icon: "devices",
    description: "LAN hosts and remote actions",
    group: "core",
  },
  {
    path: "/credentials",
    label: "Credentials",
    icon: "key",
    description: "SSH keys and AI provider tokens",
    group: "core",
  },
  {
    path: "/modules",
    label: "Modules",
    icon: "services",
    description: "What is installed on the hub",
    group: "core",
  },
  {
    path: "/services",
    label: "Services",
    icon: "bolt",
    description: "What the hub publishes to devices",
    group: "core",
  },
  {
    path: "/settings",
    label: "Settings",
    icon: "settings",
    description: "Password, backup and versions",
    group: "core",
  },
  {
    path: "/terminal",
    label: "Terminal",
    icon: "terminal",
    description: "A shell on the gateway itself",
    group: "core",
  },
  // Named for the service, because that is what the page configures: someone
  // arriving to change a share is looking for samba, not for "Files".
  {
    path: "/netbird",
    label: "NetBird",
    icon: "link",
    description: "Remote access to this gateway",
    group: "optional",
    service: "netbird",
  },
  {
    path: "/samba",
    label: "Samba",
    icon: "hard_drive",
    description: "Shares the box serves over SMB",
    group: "optional",
    service: "samba",
  },
  {
    path: "/containers",
    label: "Containers",
    icon: "cube",
    description: "Containers the box runs through podman",
    group: "optional",
    service: "podman",
  },
  {
    path: "/gitea",
    label: "Gitea",
    icon: "gitea",
    description: "The private git server",
    group: "optional",
    service: "gitea",
  },
  {
    path: "/zfs",
    label: "ZFS",
    icon: "database",
    description: "Pools, datasets and disk health",
    group: "optional",
    service: "zfs",
  },
];

/**
 * The pages to show, given which optional services are switched on.
 *
 * Enabled rather than installed, because samba and gitea arrive with the
 * install and sit there switched off: a page for a service that is not running
 * would only ever report that it is not running.
 *
 * Args:
 *   enabledServices: Names of the optional services enabled on the box.
 *
 * Returns:
 *   Every core page, plus the optional pages whose service is enabled.
 */
export function visibleNavItems(enabledServices: string[]): NavItem[] {
  return NAV_ITEMS.filter(
    (item) =>
      item.service === undefined || enabledServices.includes(item.service),
  );
}

/**
 * The pages of one group, in declared order.
 *
 * Args:
 *   items: The visible pages, from :func:`visibleNavItems`.
 *   group: Which half of the sidebar to take.
 *
 * Returns:
 *   That group's pages, which may be none.
 */
export function navItemsInGroup(items: NavItem[], group: NavGroup): NavItem[] {
  return items.filter((item) => item.group === group);
}
