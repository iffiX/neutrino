import type { DefaultTheme } from "vitepress";

/**
 * The sidebar and the top nav, one set per locale.
 *
 * The two locales carry the same pages in the same order; only the labels and
 * the `/zh-CN/` prefix differ. A page added to one is added to the other.
 */

export const GITHUB_URL = "https://github.com/iffiX/neutrino";

export const sidebarEn: DefaultTheme.SidebarItem[] = [
  {
    text: "Start",
    items: [
      { text: "Overview", link: "/overview" },
      { text: "Quick start", link: "/quick-start" },
    ],
  },
  {
    text: "Hub",
    items: [
      { text: "Install the hub", link: "/hub/install" },
      { text: "Network", link: "/hub/network" },
      { text: "Overlay: NetBird", link: "/hub/overlay-netbird" },
      { text: "Overlay: EasyTier", link: "/hub/overlay-easytier" },
      { text: "Proxy", link: "/hub/proxy" },
      { text: "AI", link: "/hub/ai" },
      { text: "Devices", link: "/hub/devices" },
      { text: "Clients", link: "/hub/clients" },
      { text: "Services", link: "/hub/services" },
      { text: "Terminals", link: "/hub/terminals" },
      { text: "Files", link: "/hub/files" },
      { text: "Samba", link: "/hub/samba" },
      { text: "Gitea", link: "/hub/gitea" },
      { text: "Containers", link: "/hub/containers" },
      { text: "ZFS", link: "/hub/zfs" },
      { text: "Credentials", link: "/hub/credentials" },
      { text: "Settings", link: "/hub/settings" },
      { text: "nhub commands", link: "/hub/cli" },
    ],
  },
  {
    text: "Agent",
    items: [
      { text: "Install the agent", link: "/agent/install" },
      { text: "nagent commands", link: "/agent/cli" },
    ],
  },
  {
    text: "Client",
    items: [
      { text: "Install the client", link: "/client/install" },
      { text: "The window", link: "/client/window" },
      { text: "Web", link: "/client/web" },
      { text: "Ports", link: "/client/ports" },
      { text: "AI", link: "/client/ai" },
      { text: "Files", link: "/client/files" },
      { text: "Remote desktops", link: "/client/remote-desktops" },
      { text: "nclient commands", link: "/client/cli" },
    ],
  },
  {
    text: "Reference",
    items: [
      { text: "Supported platforms", link: "/reference/platforms" },
      { text: "Troubleshooting", link: "/reference/troubleshooting" },
    ],
  },
];

export const sidebarZh: DefaultTheme.SidebarItem[] = [
  {
    text: "开始",
    items: [
      { text: "总览", link: "/zh-CN/overview" },
      { text: "快速上手", link: "/zh-CN/quick-start" },
    ],
  },
  {
    text: "Hub",
    items: [
      { text: "安装 hub", link: "/zh-CN/hub/install" },
      { text: "网络", link: "/zh-CN/hub/network" },
      { text: "虚拟网：NetBird", link: "/zh-CN/hub/overlay-netbird" },
      { text: "虚拟网：EasyTier", link: "/zh-CN/hub/overlay-easytier" },
      { text: "代理", link: "/zh-CN/hub/proxy" },
      { text: "AI", link: "/zh-CN/hub/ai" },
      { text: "设备", link: "/zh-CN/hub/devices" },
      { text: "客户端", link: "/zh-CN/hub/clients" },
      { text: "服务", link: "/zh-CN/hub/services" },
      { text: "终端", link: "/zh-CN/hub/terminals" },
      { text: "文件", link: "/zh-CN/hub/files" },
      { text: "Samba", link: "/zh-CN/hub/samba" },
      { text: "Gitea", link: "/zh-CN/hub/gitea" },
      { text: "容器", link: "/zh-CN/hub/containers" },
      { text: "ZFS", link: "/zh-CN/hub/zfs" },
      { text: "凭据", link: "/zh-CN/hub/credentials" },
      { text: "设置", link: "/zh-CN/hub/settings" },
      { text: "nhub 命令", link: "/zh-CN/hub/cli" },
    ],
  },
  {
    text: "被控端",
    items: [
      { text: "安装被控端", link: "/zh-CN/agent/install" },
      { text: "nagent 命令", link: "/zh-CN/agent/cli" },
    ],
  },
  {
    text: "客户端",
    items: [
      { text: "安装客户端", link: "/zh-CN/client/install" },
      { text: "窗口", link: "/zh-CN/client/window" },
      { text: "网页", link: "/zh-CN/client/web" },
      { text: "端口", link: "/zh-CN/client/ports" },
      { text: "AI", link: "/zh-CN/client/ai" },
      { text: "文件", link: "/zh-CN/client/files" },
      { text: "远程桌面", link: "/zh-CN/client/remote-desktops" },
      { text: "nclient 命令", link: "/zh-CN/client/cli" },
    ],
  },
  {
    text: "参考",
    items: [
      { text: "支持的平台", link: "/zh-CN/reference/platforms" },
      { text: "故障排查", link: "/zh-CN/reference/troubleshooting" },
    ],
  },
];

export const navEn: DefaultTheme.NavItem[] = [
  { text: "Quick start", link: "/quick-start" },
  { text: "Hub", link: "/hub/install" },
  { text: "Client", link: "/client/install" },
  { text: "GitHub", link: GITHUB_URL },
];

export const navZh: DefaultTheme.NavItem[] = [
  { text: "快速上手", link: "/zh-CN/quick-start" },
  { text: "Hub", link: "/zh-CN/hub/install" },
  { text: "客户端", link: "/zh-CN/client/install" },
  { text: "GitHub", link: GITHUB_URL },
];
