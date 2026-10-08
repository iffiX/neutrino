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
    collapsed: false,
    items: [
      { text: "Overview", link: "/overview" },
      {
        text: "Quick start",
        collapsed: false,
        items: [
          {
            text: "Step zero: install, join, reach it from outside",
            link: "/quick-start",
          },
          {
            text: "Your AI session on the phone",
            link: "/quick-start/cloudcli",
          },
          {
            text: "AI tools share the hub's gateway",
            link: "/quick-start/ai_gateway",
          },
          { text: "A remote editor", link: "/quick-start/vscode" },
          { text: "Terminal", link: "/quick-start/terminal" },
          { text: "Remote desktop", link: "/quick-start/remote_desktop" },
          { text: "Share and mount files", link: "/quick-start/files" },
        ],
      },
      {
        text: "Install",
        collapsed: true,
        items: [
          { text: "Install the hub", link: "/install/hub" },
          { text: "Install an agent", link: "/install/agent" },
          { text: "Install a client", link: "/install/client" },
        ],
      },
      { text: "Security", link: "/security" },
      { text: "Uninstall", link: "/uninstall" },
    ],
  },
  {
    text: "Advanced scenarios",
    collapsed: false,
    items: [
      { text: "Choose a way in", link: "/scenarios/choose_a_way_in" },
      {
        text: "One client, several hubs",
        link: "/scenarios/one_client_several_hubs",
      },
      {
        text: "One laptop, every machine",
        link: "/scenarios/one_laptop_every_machine",
      },
      {
        text: "Reach home through your own VPS",
        link: "/scenarios/vps_relay",
      },
      {
        text: "Make the hub a router or side gateway",
        link: "/scenarios/router_or_gateway",
      },
      { text: "Make a machine a NAS", link: "/scenarios/nas" },
      {
        text: "Devices without an agent, over NetBird",
        link: "/scenarios/netbird_lan_routes",
      },
      {
        text: "Devices without an agent, over EasyTier",
        link: "/scenarios/easytier_lan_routes",
      },
    ],
  },
  {
    text: "Hub",
    collapsed: true,
    items: [
      { text: "Dashboard", link: "/hub/dashboard" },
      { text: "Network", link: "/hub/network" },
      {
        text: "Access",
        link: "/hub/overlay",
        collapsed: false,
        items: [
          { text: "SSH Relay", link: "/hub/relay" },
          { text: "NetBird", link: "/hub/netbird" },
          { text: "EasyTier", link: "/hub/easytier" },
        ],
      },
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
    collapsed: true,
    items: [
      { text: "Terminals", link: "/agent/terminals" },
      { text: "Files", link: "/agent/files" },
      {
        text: "Modules",
        link: "/agent/modules",
        collapsed: false,
        items: [
          { text: "AI tools", link: "/agent/modules/ai_tools" },
          { text: "File share", link: "/agent/modules/shares" },
          { text: "Terminal", link: "/agent/modules/terminal" },
          { text: "Remote desktop", link: "/agent/modules/remote_desktop" },
          { text: "Gitea", link: "/agent/modules/gitea" },
          { text: "VS Code", link: "/agent/modules/vscode" },
          { text: "code-server", link: "/agent/modules/code_server" },
          { text: "CloudCLI", link: "/agent/modules/cloudcli" },
          { text: "Containers", link: "/agent/modules/containers" },
          { text: "ZFS storage", link: "/agent/modules/zfs" },
        ],
      },
    ],
  },
  {
    text: "Clients",
    collapsed: true,
    items: [
      { text: "Desktop client", link: "/client/desktop" },
      { text: "Android app", link: "/client/android" },
    ],
  },
  {
    text: "Commands",
    collapsed: true,
    items: [
      { text: "nhub commands", link: "/commands/nhub" },
      { text: "nagent commands", link: "/commands/nagent" },
      { text: "nclient commands", link: "/commands/nclient" },
    ],
  },
  {
    text: "Reference",
    collapsed: true,
    items: [
      { text: "Supported platforms", link: "/reference/platforms" },
      { text: "Troubleshooting", link: "/reference/troubleshooting" },
      { text: "The channel", link: "/protocol/channel" },
      { text: "Glossary", link: "/reference/glossary" },
    ],
  },
];

export const sidebarZh: DefaultTheme.SidebarItem[] = [
  {
    text: "开始",
    collapsed: false,
    items: [
      { text: "概述", link: "/zh-CN/overview" },
      {
        text: "快速上手",
        collapsed: false,
        items: [
          {
            text: "第零步：装中枢，加入客户端，连上外网",
            link: "/zh-CN/quick-start",
          },
          {
            text: "在手机上接着家里的 AI 会话",
            link: "/zh-CN/quick-start/cloudcli",
          },
          {
            text: "AI 工具共用中枢的网关",
            link: "/zh-CN/quick-start/ai_gateway",
          },
          { text: "远程编辑器", link: "/zh-CN/quick-start/vscode" },
          { text: "终端", link: "/zh-CN/quick-start/terminal" },
          { text: "远程桌面", link: "/zh-CN/quick-start/remote_desktop" },
          { text: "文件共享和挂载", link: "/zh-CN/quick-start/files" },
        ],
      },
      {
        text: "安装",
        collapsed: true,
        items: [
          { text: "安装中枢", link: "/zh-CN/install/hub" },
          { text: "安装被控端", link: "/zh-CN/install/agent" },
          { text: "安装客户端", link: "/zh-CN/install/client" },
        ],
      },
      { text: "安全", link: "/zh-CN/security" },
      { text: "卸载", link: "/zh-CN/uninstall" },
    ],
  },
  {
    text: "进阶场景",
    collapsed: false,
    items: [
      { text: "选哪种外部访问", link: "/zh-CN/scenarios/choose_a_way_in" },
      {
        text: "一个客户端连多台中枢",
        link: "/zh-CN/scenarios/one_client_several_hubs",
      },
      {
        text: "一台笔记本管所有机器",
        link: "/zh-CN/scenarios/one_laptop_every_machine",
      },
      {
        text: "用自己的 VPS 中继连回家",
        link: "/zh-CN/scenarios/vps_relay",
      },
      {
        text: "把中枢配置成路由器或旁路网关",
        link: "/zh-CN/scenarios/router_or_gateway",
      },
      { text: "把一台机器做成 NAS", link: "/zh-CN/scenarios/nas" },
      {
        text: "经 NetBird 访问没装被控端的设备",
        link: "/zh-CN/scenarios/netbird_lan_routes",
      },
      {
        text: "经 EasyTier 访问没装被控端的设备",
        link: "/zh-CN/scenarios/easytier_lan_routes",
      },
    ],
  },
  {
    text: "中枢",
    collapsed: true,
    items: [
      { text: "总览", link: "/zh-CN/hub/dashboard" },
      { text: "网络", link: "/zh-CN/hub/network" },
      {
        text: "外部访问",
        link: "/zh-CN/hub/overlay",
        collapsed: false,
        items: [
          { text: "SSH 中继", link: "/zh-CN/hub/relay" },
          { text: "NetBird", link: "/zh-CN/hub/netbird" },
          { text: "EasyTier", link: "/zh-CN/hub/easytier" },
        ],
      },
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
    collapsed: true,
    items: [
      { text: "终端", link: "/zh-CN/agent/terminals" },
      { text: "文件", link: "/zh-CN/agent/files" },
      {
        text: "模块",
        link: "/zh-CN/agent/modules",
        collapsed: false,
        items: [
          { text: "AI 工具", link: "/zh-CN/agent/modules/ai_tools" },
          { text: "文件共享", link: "/zh-CN/agent/modules/shares" },
          { text: "终端", link: "/zh-CN/agent/modules/terminal" },
          { text: "远程桌面", link: "/zh-CN/agent/modules/remote_desktop" },
          { text: "Gitea", link: "/zh-CN/agent/modules/gitea" },
          { text: "VS Code", link: "/zh-CN/agent/modules/vscode" },
          { text: "code-server", link: "/zh-CN/agent/modules/code_server" },
          { text: "CloudCLI", link: "/zh-CN/agent/modules/cloudcli" },
          { text: "容器", link: "/zh-CN/agent/modules/containers" },
          { text: "ZFS 存储", link: "/zh-CN/agent/modules/zfs" },
        ],
      },
    ],
  },
  {
    text: "客户端",
    collapsed: true,
    items: [
      { text: "桌面客户端", link: "/zh-CN/client/desktop" },
      { text: "Android 应用", link: "/zh-CN/client/android" },
    ],
  },
  {
    text: "命令",
    collapsed: true,
    items: [
      { text: "nhub 命令", link: "/zh-CN/commands/nhub" },
      { text: "nagent 命令", link: "/zh-CN/commands/nagent" },
      { text: "nclient 命令", link: "/zh-CN/commands/nclient" },
    ],
  },
  {
    text: "参考",
    collapsed: true,
    items: [
      { text: "支持的平台", link: "/zh-CN/reference/platforms" },
      { text: "故障排查", link: "/zh-CN/reference/troubleshooting" },
      { text: "通道", link: "/zh-CN/protocol/channel" },
      { text: "术语表", link: "/zh-CN/reference/glossary" },
    ],
  },
];

export const navEn: DefaultTheme.NavItem[] = [
  { text: "Quick start", link: "/quick-start" },
  { text: "Advanced scenarios", link: "/scenarios/choose_a_way_in" },
  { text: "Troubleshooting", link: "/reference/troubleshooting" },
  { text: "GitHub", link: GITHUB_URL },
];

export const navZh: DefaultTheme.NavItem[] = [
  { text: "快速上手", link: "/zh-CN/quick-start" },
  { text: "进阶场景", link: "/zh-CN/scenarios/choose_a_way_in" },
  { text: "故障排查", link: "/zh-CN/reference/troubleshooting" },
  { text: "GitHub", link: GITHUB_URL },
];
