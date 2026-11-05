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
