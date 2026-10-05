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
      { text: "Dashboard", link: "/hub/dashboard" },
      { text: "Network", link: "/hub/network" },
      { text: "Access", link: "/hub/overlay" },
      { text: "SSH Relay", link: "/hub/relay" },
      { text: "Proxy", link: "/hub/proxy" },
      { text: "AI", link: "/hub/ai" },
      { text: "Devices", link: "/hub/devices" },
      { text: "Clients", link: "/hub/clients" },
      { text: "Services", link: "/hub/services" },
      { text: "Credentials", link: "/hub/credentials" },
      { text: "Settings", link: "/hub/settings" },
    ],
  },
  {
    text: "Managed machines",
    items: [
      { text: "Terminals", link: "/agent/terminals" },
      { text: "Files", link: "/agent/files" },
      {
        text: "Modules",
        link: "/agent/modules",
        collapsed: false,
        items: [
          { text: "File share", link: "/agent/modules/shares" },
          { text: "Terminal", link: "/agent/modules/terminal" },
          { text: "Remote desktop", link: "/agent/modules/remote_desktop" },
          { text: "Gitea", link: "/agent/modules/gitea" },
          { text: "Containers", link: "/agent/modules/containers" },
          { text: "ZFS storage", link: "/agent/modules/zfs" },
          { text: "VS Code", link: "/agent/modules/vscode" },
          { text: "code-server", link: "/agent/modules/code_server" },
        ],
      },
    ],
  },
  {
    text: "Clients",
    items: [
      { text: "Desktop client", link: "/client/desktop" },
      { text: "Android app", link: "/client/android" },
    ],
  },
  {
    text: "Commands",
    items: [
      { text: "nhub commands", link: "/commands/nhub" },
      { text: "nagent commands", link: "/commands/nagent" },
      { text: "nclient commands", link: "/commands/nclient" },
    ],
  },
  {
    text: "Reference",
    items: [
      { text: "Supported platforms", link: "/reference/platforms" },
      { text: "Troubleshooting", link: "/reference/troubleshooting" },
      { text: "The channel", link: "/protocol/channel" },
    ],
  },
];

export const sidebarZh: DefaultTheme.SidebarItem[] = [
  {
    text: "开始",
    items: [
      { text: "概述", link: "/zh-CN/overview" },
      { text: "快速上手", link: "/zh-CN/quick-start" },
    ],
  },
  {
    text: "Hub",
    items: [
      { text: "安装 hub", link: "/zh-CN/hub/install" },
      { text: "总览", link: "/zh-CN/hub/dashboard" },
      { text: "网络", link: "/zh-CN/hub/network" },
      { text: "外部访问", link: "/zh-CN/hub/overlay" },
      { text: "SSH 中继", link: "/zh-CN/hub/relay" },
      { text: "代理", link: "/zh-CN/hub/proxy" },
      { text: "AI", link: "/zh-CN/hub/ai" },
      { text: "设备", link: "/zh-CN/hub/devices" },
      { text: "客户端", link: "/zh-CN/hub/clients" },
      { text: "服务", link: "/zh-CN/hub/services" },
      { text: "凭据", link: "/zh-CN/hub/credentials" },
      { text: "设置", link: "/zh-CN/hub/settings" },
    ],
  },
  {
    text: "被控端",
    items: [
      { text: "终端", link: "/zh-CN/agent/terminals" },
      { text: "文件", link: "/zh-CN/agent/files" },
      {
        text: "模块",
        link: "/zh-CN/agent/modules",
        collapsed: false,
        items: [
          { text: "File share", link: "/zh-CN/agent/modules/shares" },
          { text: "Terminal", link: "/zh-CN/agent/modules/terminal" },
          {
            text: "Remote desktop",
            link: "/zh-CN/agent/modules/remote_desktop",
          },
          { text: "Gitea", link: "/zh-CN/agent/modules/gitea" },
          { text: "Containers", link: "/zh-CN/agent/modules/containers" },
          { text: "ZFS storage", link: "/zh-CN/agent/modules/zfs" },
          { text: "VS Code", link: "/zh-CN/agent/modules/vscode" },
          { text: "code-server", link: "/zh-CN/agent/modules/code_server" },
        ],
      },
    ],
  },
  {
    text: "客户端",
    items: [
      { text: "桌面客户端", link: "/zh-CN/client/desktop" },
      { text: "Android 应用", link: "/zh-CN/client/android" },
    ],
  },
  {
    text: "命令",
    items: [
      { text: "nhub 命令", link: "/zh-CN/commands/nhub" },
      { text: "nagent 命令", link: "/zh-CN/commands/nagent" },
      { text: "nclient 命令", link: "/zh-CN/commands/nclient" },
    ],
  },
  {
    text: "参考",
    items: [
      { text: "支持的平台", link: "/zh-CN/reference/platforms" },
      { text: "故障排查", link: "/zh-CN/reference/troubleshooting" },
      { text: "通道", link: "/zh-CN/protocol/channel" },
    ],
  },
];

export const navEn: DefaultTheme.NavItem[] = [
  { text: "Quick start", link: "/quick-start" },
  { text: "Hub", link: "/hub/install" },
  { text: "Clients", link: "/client/desktop" },
  { text: "GitHub", link: GITHUB_URL },
];

export const navZh: DefaultTheme.NavItem[] = [
  { text: "快速上手", link: "/zh-CN/quick-start" },
  { text: "Hub", link: "/zh-CN/hub/install" },
  { text: "客户端", link: "/zh-CN/client/desktop" },
  { text: "GitHub", link: GITHUB_URL },
];
