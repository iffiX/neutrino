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
      { text: "Quick start", link: "/quick-start" },
      { text: "Overview", link: "/overview" },
    ],
  },
  {
    text: "Guides",
    items: [
      { text: "Network modes", link: "/network-modes" },
      { text: "Overlay with NetBird", link: "/overlay-netbird" },
      { text: "Overlay with EasyTier", link: "/overlay-easytier" },
      { text: "Proxy", link: "/proxy" },
      { text: "AI gateway", link: "/ai-gateway" },
      { text: "Devices and remote desktop", link: "/devices-remote-desktop" },
      { text: "Shares and services", link: "/shares-services" },
      { text: "Clients", link: "/clients" },
      { text: "Backup and restore", link: "/backup-restore" },
      { text: "Upgrade and reset", link: "/upgrade-reset" },
    ],
  },
  {
    text: "Reference",
    items: [
      { text: "CLI", link: "/cli" },
      { text: "Troubleshooting", link: "/troubleshooting" },
    ],
  },
];

export const sidebarZh: DefaultTheme.SidebarItem[] = [
  {
    text: "开始",
    items: [
      { text: "快速上手", link: "/zh-CN/quick-start" },
      { text: "总览", link: "/zh-CN/overview" },
    ],
  },
  {
    text: "指南",
    items: [
      { text: "网络模式", link: "/zh-CN/network-modes" },
      { text: "用 NetBird 组网", link: "/zh-CN/overlay-netbird" },
      { text: "用 EasyTier 组网", link: "/zh-CN/overlay-easytier" },
      { text: "代理", link: "/zh-CN/proxy" },
      { text: "AI 网关", link: "/zh-CN/ai-gateway" },
      { text: "设备与远程桌面", link: "/zh-CN/devices-remote-desktop" },
      { text: "共享与服务", link: "/zh-CN/shares-services" },
      { text: "客户端", link: "/zh-CN/clients" },
      { text: "备份与恢复", link: "/zh-CN/backup-restore" },
      { text: "升级与重置", link: "/zh-CN/upgrade-reset" },
    ],
  },
  {
    text: "参考",
    items: [
      { text: "命令行", link: "/zh-CN/cli" },
      { text: "故障排查", link: "/zh-CN/troubleshooting" },
    ],
  },
];

export const navEn: DefaultTheme.NavItem[] = [
  { text: "Quick start", link: "/quick-start" },
  { text: "Guides", link: "/network-modes" },
  { text: "CLI", link: "/cli" },
  { text: "GitHub", link: GITHUB_URL },
];

export const navZh: DefaultTheme.NavItem[] = [
  { text: "快速上手", link: "/zh-CN/quick-start" },
  { text: "指南", link: "/zh-CN/network-modes" },
  { text: "命令行", link: "/zh-CN/cli" },
  { text: "GitHub", link: GITHUB_URL },
];
