import type { DefaultTheme } from "vitepress";

export const GITHUB_URL = "https://github.com/iffiX/neutrino";

const DEMO_URL = process.argv.includes("dev")
  ? "http://localhost:4780/"
  : "/demo/";

export const nav: DefaultTheme.NavItem[] = [
  { text: "快速上手", link: "/quick-start" },
  { text: "中枢", link: "/hub/install", activeMatch: "^/hub/" },
  { text: "一键部署", link: "/deploy/on_a_machine", activeMatch: "^/deploy/" },
  {
    text: "到处使用",
    link: "/access/install_client",
    activeMatch: "^/access/",
  },
  { text: "任意分享", link: "/share/web_share", activeMatch: "^/share/" },
  { text: "参考", link: "/reference/nhub", activeMatch: "^/reference/" },
  { text: "在线演示", link: DEMO_URL, target: "_blank", rel: "noopener" },
];

export const sidebar: DefaultTheme.SidebarItem[] = [
  {
    text: "概览",
    items: [
      {
        text: "微子·中枢是什么",
        link: "/overview",
        collapsed: true,
        items: [
          { text: "工作原理", link: "/how_it_works" },
          { text: "安全模型", link: "/share/security" },
          { text: "数据和外连", link: "/hub/what_it_holds" },
          { text: "和其他工具比较", link: "/compare" },
          { text: "常见问题", link: "/faq" },
        ],
      },
      { text: "快速上手", link: "/quick-start" },
    ],
  },
  {
    text: "中枢",
    items: [
      { text: "安装中枢", link: "/hub/install" },
      { text: "总览", link: "/hub/dashboard" },
      { text: "网络形态：服务器、路由器、旁路网关", link: "/hub/network" },
      { text: "代理", link: "/hub/proxy" },
      { text: "AI 网关", link: "/hub/ai_gateway" },
      { text: "被控端", link: "/hub/agents" },
      { text: "客户端", link: "/hub/clients" },
      { text: "设置：备份、更新、密码", link: "/hub/settings" },
      { text: "从 0.5 升级", link: "/hub/upgrade" },
      { text: "卸载", link: "/hub/uninstall" },
    ],
  },
  {
    text: "一键部署",
    items: [
      { text: "在一个系统上安装应用", link: "/deploy/on_a_machine" },
      { text: "应用的分类", link: "/deploy/app_kinds" },
      {
        text: "系统访问",
        items: [
          { text: "远程桌面", link: "/deploy/remote_desktop" },
          { text: "文件共享", link: "/deploy/file_share" },
          { text: "终端", link: "/deploy/terminal" },
          { text: "SSH", link: "/deploy/ssh" },
        ],
      },
      {
        text: "写代码",
        items: [
          { text: "VS Code", link: "/deploy/vscode" },
          { text: "code-server", link: "/deploy/code_server" },
          { text: "Gitea", link: "/deploy/gitea" },
        ],
      },
      {
        text: "AI 工作流",
        items: [
          { text: "CloudCLI", link: "/deploy/cloudcli" },
          { text: "Codeg", link: "/deploy/codeg" },
          { text: "Hermes WebUI", link: "/deploy/hermes_webui" },
          { text: "Claude Code", link: "/deploy/claude_code" },
          { text: "Codex", link: "/deploy/codex" },
        ],
      },
      {
        text: "论文和笔记",
        items: [
          { text: "Ayakaleaf", link: "/deploy/ayakaleaf" },
          { text: "思源笔记", link: "/deploy/siyuan" },
        ],
      },
      {
        text: "自己的服务",
        items: [
          { text: "容器", link: "/deploy/containers" },
          { text: "加入已有的服务", link: "/deploy/services" },
          { text: "访问没有安装被控端的设备", link: "/deploy/without_agent" },
        ],
      },
    ],
  },
  {
    text: "到处使用",
    items: [
      { text: "安装客户端", link: "/access/install_client" },
      { text: "加入中枢", link: "/access/join" },
      { text: "桌面客户端", link: "/access/desktop" },
      { text: "Android 应用", link: "/access/android" },
      { text: "iOS 应用", link: "/access/ios" },
      {
        text: "外部访问：选择一种方式",
        link: "/access/ways_in",
        items: [
          { text: "直连", link: "/access/direct" },
          { text: "SSH 中继", link: "/access/vps" },
          { text: "EasyTier", link: "/access/easytier" },
          { text: "NetBird", link: "/access/netbird" },
          { text: "SakuraFrp", link: "/access/sakurafrp" },
          { text: "OpenFrp", link: "/access/openfrp" },
        ],
      },
      {
        text: "客户端高级功能",
        items: [
          { text: "终端命令", link: "/access/terminal" },
          { text: "SSH 连接", link: "/access/ssh" },
          { text: "让本地 AI 工具操作你的系统", link: "/access/local_ai" },
        ],
      },
    ],
  },
  {
    text: "任意分享",
    items: [{ text: "应用分享", link: "/share/web_share" }],
  },
  {
    text: "参考",
    items: [
      { text: "nhub 命令", link: "/reference/nhub" },
      { text: "nagent 命令", link: "/reference/nagent" },
      { text: "nclient 命令", link: "/reference/nclient" },
      { text: "支持的平台", link: "/reference/platforms" },
      { text: "故障排查", link: "/reference/troubleshooting" },
      { text: "面板菜单对照表", link: "/reference/panel_menu" },
      { text: "术语表", link: "/reference/glossary" },
    ],
  },
];

/** The English words of every nav and sidebar entry, by its Chinese words. */
const ENGLISH: Record<string, string> = {
  快速上手: "Quick start",
  中枢: "Hub",
  一键部署: "Deploy",
  到处使用: "Access",
  任意分享: "Share",
  参考: "Reference",
  在线演示: "Live demo",
  概览: "Overview",
  "微子·中枢是什么": "What Neutrino Hub is",
  工作原理: "How it works",
  安全模型: "Security model",
  数据和外连: "Data and outbound connections",
  和其他工具比较: "Comparison with other tools",
  常见问题: "FAQ",
  安装中枢: "Install the hub",
  总览: "Dashboard",
  "网络形态：服务器、路由器、旁路网关":
    "Network modes: server, router, side gateway",
  代理: "Proxy",
  "AI 网关": "AI gateway",
  被控端: "Agents",
  客户端: "Clients",
  "设置：备份、更新、密码": "Settings: backup, updates, password",
  "从 0.5 升级": "Upgrade from 0.5",
  卸载: "Uninstall",
  在一个系统上安装应用: "Install apps on a system",
  应用的分类: "App kinds",
  系统访问: "System access",
  远程桌面: "Remote desktop",
  文件共享: "File sharing",
  终端: "Terminal",
  写代码: "Coding",
  "AI 工作流": "AI workflows",
  论文和笔记: "Papers and notes",
  思源笔记: "SiYuan",
  自己的服务: "Your own services",
  容器: "Containers",
  加入已有的服务: "Add existing services",
  访问没有安装被控端的设备: "Devices without an agent",
  安装客户端: "Install the client",
  加入中枢: "Join the hub",
  桌面客户端: "Desktop client",
  "Android 应用": "Android app",
  "iOS 应用": "iOS app",
  "外部访问：选择一种方式": "Access from outside: choose a method",
  直连: "Direct",
  "SSH 中继": "SSH relay",
  客户端高级功能: "Advanced client features",
  终端命令: "Terminal commands",
  "SSH 连接": "SSH connections",
  "让本地 AI 工具操作你的系统": "Let local AI tools work on your systems",
  应用分享: "App share",
  "nhub 命令": "nhub commands",
  "nagent 命令": "nagent commands",
  "nclient 命令": "nclient commands",
  支持的平台: "Supported platforms",
  故障排查: "Troubleshooting",
  面板菜单对照表: "Panel menu map",
  术语表: "Glossary",
};

/** A Chinese entry's English words; names such as Gitea stay as they are. */
function english(text: string): string {
  return ENGLISH[text] ?? text;
}

/** An internal link under /en/; the demo opens in English; outside links stay. */
function englishLink(link: string): string {
  if (link === DEMO_URL) {
    return `${DEMO_URL}?lang=en`;
  }
  return link.startsWith("/") ? `/en${link}` : link;
}

function englishItem<T extends DefaultTheme.SidebarItem>(item: T): T {
  return {
    ...item,
    text: item.text === undefined ? undefined : english(item.text),
    link: item.link === undefined ? undefined : englishLink(item.link),
    items: item.items?.map(englishItem),
  };
}

export const navEn: DefaultTheme.NavItem[] = nav.map((item) =>
  "link" in item
    ? {
        ...item,
        text: english(item.text),
        link:
          typeof item.link === "string" ? englishLink(item.link) : item.link,
        activeMatch: item.activeMatch?.replace("^/", "^/en/"),
      }
    : item,
);

export const sidebarEn: DefaultTheme.SidebarItem[] = sidebar.map(englishItem);
