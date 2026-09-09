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
 */

export type NavGroup = "hub" | "agent";

export interface NavItem {
  path: string;
  label: string;
  icon: IconName;
  description: string;
  group: NavGroup;
}

export const NAV_ITEMS: NavItem[] = [
  {
    path: "/",
    label: "Dashboard",
    icon: "dashboard",
    description: "Live throughput, exits and DNS",
    group: "hub",
  },
  {
    path: "/network",
    label: "Network",
    icon: "network",
    description: "Interface roles, uplinks and DHCP",
    group: "hub",
  },
  {
    path: "/overlay",
    label: "Overlay",
    icon: "mesh",
    description: "Remote access to this gateway",
    group: "hub",
  },
  {
    path: "/proxy",
    label: "Proxy",
    icon: "globe",
    description: "Exit nodes, split routing and DNS",
    group: "hub",
  },
  {
    path: "/ai",
    label: "AI",
    icon: "sparkles",
    description: "One endpoint for every AI tool",
    group: "hub",
  },
  {
    path: "/devices",
    label: "Devices",
    icon: "devices",
    description: "LAN hosts and remote actions",
    group: "hub",
  },
  {
    path: "/clients",
    label: "Clients",
    icon: "laptop",
    description: "Machines that reach the hub as clients",
    group: "hub",
  },
  {
    path: "/services",
    label: "Services",
    icon: "bolt",
    description: "What the hub publishes to devices",
    group: "hub",
  },
  {
    path: "/credentials",
    label: "Credentials",
    icon: "key",
    description: "SSH keys and AI provider tokens",
    group: "hub",
  },
  {
    path: "/settings",
    label: "Settings",
    icon: "settings",
    description: "Password, backup and versions",
    group: "hub",
  },
  {
    path: "/terminals",
    label: "Terminals",
    icon: "terminal",
    description: "A shell on a managed machine",
    group: "agent",
  },
  {
    path: "/files",
    label: "Files",
    icon: "folder",
    description: "Browse and move files on a machine",
    group: "agent",
  },
  {
    path: "/samba",
    label: "Samba",
    icon: "hard_drive",
    description: "Shares a machine serves over SMB",
    group: "agent",
  },
  {
    path: "/gitea",
    label: "Gitea",
    icon: "gitea",
    description: "The private git server",
    group: "agent",
  },
  {
    path: "/containers",
    label: "Containers",
    icon: "cube",
    description: "Containers a machine runs through podman",
    group: "agent",
  },
  {
    path: "/zfs",
    label: "ZFS",
    icon: "database",
    description: "Pools, datasets and disk health",
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
