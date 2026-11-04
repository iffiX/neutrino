/**
 * The home page's pictures, install commands and app cards.
 */
export const PICTURES = {
  heroPanel: "/home/panel_dashboard.webp",
  heroPhone: "/home/phone_apps.webp",
  store: "/home/panel_store.webp",
  wolfSit: "/home/wolf_sit_block.webp",
  laptop: "/home/laptop_vscode.webp",
  wolfWalk: "/home/wolf_walk_phone.webp",
  shareDialog: "/home/share_dialog.webp",
  wolfTwo: "/home/wolf_two.webp",
  shareBrowser: "/home/share_browser.webp",
};

export const DEMO_URL = import.meta.env?.DEV
  ? "http://localhost:4780/"
  : "/demo/";

/** The release the phone links name; a release build stamps it. */
export const VERSION = "0.6.0";

export const SITES = [
  {
    id: "cn",
    label: "国内版",
    scripts:
      "https://cnb.cool/iffi-X/neutrino/-/git/raw/main/packaging/install",
    files: `https://cnb.cool/iffi-X/neutrino/-/releases/download/v${VERSION}/`,
    suffix: "-cn",
    chip: "无部分网络功能",
  },
  {
    id: "global",
    label: "国际版",
    scripts: "https://github.com/iffiX/neutrino/releases/latest/download",
    files: `https://github.com/iffiX/neutrino/releases/download/v${VERSION}/`,
    suffix: "",
  },
];

export const PARTS = [
  { id: "hub", label: "安装中枢" },
  { id: "client", label: "安装客户端" },
];

function shellCommand(scripts: string, part: string): string {
  const tail = part === "client" ? " -s -- client" : "";
  return `curl -fsSL ${scripts}/install.sh | sh${tail}`;
}

function powershellCommand(scripts: string, part: string): string {
  return part === "client"
    ? `& ([scriptblock]::Create((irm ${scripts}/install.ps1))) client`
    : `irm ${scripts}/install.ps1 | iex`;
}

function linuxPackages(
  part: string,
  suffix: string,
): { label: string; file: string }[] {
  const name = `neutrino-${part}`;
  return [
    { label: "deb amd64", file: `${name}_${VERSION}_amd64${suffix}.deb` },
    { label: "deb arm64", file: `${name}_${VERSION}_arm64${suffix}.deb` },
    { label: "rpm amd64", file: `${name}-${VERSION}-1.x86_64${suffix}.rpm` },
    { label: "rpm arm64", file: `${name}-${VERSION}-1.aarch64${suffix}.rpm` },
    { label: "Arch", file: `${name}-${VERSION}-1-x86_64${suffix}.pkg.tar.zst` },
  ];
}

function macosPackages(
  part: string,
  suffix: string,
): { label: string; file: string }[] {
  return [
    {
      label: "Apple 芯片",
      file: `neutrino-${part}-${VERSION}-macos-arm64${suffix}.pkg`,
    },
    {
      label: "Intel",
      file: `neutrino-${part}-${VERSION}-macos-amd64${suffix}.pkg`,
    },
  ];
}

function windowsPackages(
  part: string,
  suffix: string,
): { label: string; file: string }[] {
  return [
    {
      label: "amd64",
      file: `neutrino-${part}-${VERSION}-windows-amd64${suffix}.msi`,
    },
  ];
}

function androidPackages(
  part: string,
  suffix: string,
): { label: string; file: string }[] {
  return [
    {
      label: "arm64",
      file: `neutrino-${part}-${VERSION}-android${suffix}.apk`,
    },
  ];
}

function iphonePackages(
  part: string,
  suffix: string,
): { label: string; file: string }[] {
  return [
    { label: "ipa", file: `neutrino-${part}-${VERSION}-ios${suffix}.ipa` },
  ];
}

/** The tabs of the install box; a phone has no command, only the client has one, and only Android has a QR. */
export const SYSTEMS = [
  { name: "Linux", command: shellCommand, packages: linuxPackages },
  { name: "macOS", command: shellCommand, packages: macosPackages },
  { name: "Windows", command: powershellCommand, packages: windowsPackages },
  {
    name: "Android",
    isPhone: true,
    hasQr: true,
    caption: "微信或手机相机扫码，下载安装",
    phoneCaption: "点下面的 arm64，下载安装",
    packages: androidPackages,
  },
  {
    name: "iPhone",
    isPhone: true,
    caption: "下载后自己签名安装",
    packages: iphonePackages,
    guide: "/access/ios",
  },
];

export const DOCS_ORIGIN = "https://neutrinohub.net";

export const WAYS_IN = [
  "NetBird*",
  "EasyTier*",
  "SSH 中继",
  "直连",
  "SakuraFrp",
  "OpenFrp",
];

export const APP_GROUPS = [
  {
    label: "系统访问",
    apps: [
      {
        name: "远程桌面",
        icon: "remote_desktop",
        link: "/deploy/remote_desktop",
      },
      { name: "传文件", icon: "samba", link: "/deploy/file_share" },
      { name: "终端", icon: "terminal", link: "/deploy/terminal" },
      { name: "SSH", icon: "generic", link: "/deploy/ssh" },
    ],
  },
  {
    label: "写代码",
    apps: [
      { name: "VS Code", icon: "vscode", link: "/deploy/vscode" },
      { name: "code-server", icon: "code_server", link: "/deploy/code_server" },
    ],
  },
  {
    label: "AI 工作流",
    apps: [
      { name: "CloudCLI", icon: "cloudcli", link: "/deploy/cloudcli" },
      { name: "Codeg", icon: "codeg", link: "/deploy/codeg" },
      { name: "Hermes WebUI", icon: "generic", link: "/deploy/hermes_webui" },
    ],
  },
  {
    label: "写论文",
    apps: [{ name: "Ayakaleaf", icon: "ayakaleaf", link: "/deploy/ayakaleaf" }],
  },
  {
    label: "记笔记",
    apps: [{ name: "思源笔记", icon: "siyuan", link: "/deploy/siyuan" }],
  },
  {
    label: "放代码",
    apps: [{ name: "Gitea", icon: "gitea", link: "/deploy/gitea" }],
  },
  {
    label: "跑容器",
    apps: [{ name: "容器", icon: "podman", link: "/deploy/containers" }],
  },
];

export const COMPARE_PRODUCTS = [
  "微子·中枢",
  "1Panel",
  "Cosmos",
  "Olares",
  "Tailscale",
  "ToDesk",
  "飞牛",
];

/** One row: its name, then each product's cell in COMPARE_PRODUCTS' order; a cell starting with "x:" is a miss. */
export const COMPARE_GROUPS = [
  {
    title: "全能",
    rows: [
      [
        "系统支持",
        "三系统",
        "x:仅 Linux",
        "x:仅 Linux",
        "x:仅它的系统",
        "三系统",
        "三系统",
        "x:仅它的系统",
      ],
      [
        "客户端支持",
        "全平台",
        "x:网页，手机专业版",
        "x:网页，手机付费版",
        "全平台",
        "全平台",
        "全平台",
        "x:手机和网页",
      ],
      ["一键装应用", "有", "有", "有", "有", "x:没有", "x:没有", "有"],
      [
        "容器",
        "三系统",
        "x:仅 Linux",
        "x:仅 Linux",
        "x:仅它的系统",
        "x:没有",
        "x:没有",
        "x:仅它的系统",
      ],
      [
        "在外面打开应用",
        "配好了",
        "x:自己开端口",
        "x:自己开端口",
        "有",
        "x:自己配",
        "x:没有",
        "x:部分",
      ],
      [
        "远程桌面",
        "配好了",
        "x:没有",
        "x:自己装",
        "x:自己装",
        "x:自己装",
        "有",
        "x:自己装",
      ],
      [
        "终端",
        "配好了",
        "有",
        "x:只有容器",
        "有",
        "x:自己配",
        "有",
        "x:自己开",
      ],
      [
        "文件盘挂载",
        "配好了",
        "x:只有网页",
        "x:付费版",
        "x:局域网",
        "x:只传文件",
        "x:只传文件",
        "有",
      ],
      [
        "SSH/SFTP",
        "配好了",
        "x:自己开端口",
        "x:自己开端口",
        "有",
        "有",
        "x:没有",
        "x:自己开",
      ],
      [
        "应用分享",
        "一个链接",
        "x:没有",
        "x:要域名",
        "x:只有文件",
        "有",
        "x:要装软件",
        "x:只有文件",
      ],
    ],
  },
  {
    title: "安全",
    rows: [
      ["传输加密", "有", "x:自己配", "x:要域名", "有", "有", "有", "x:未声明"],
      ["扫描有指纹", "没有", "x:有", "x:有", "x:有", "没有", "没有", "x:有"],
    ],
  },
  {
    title: "自主",
    rows: [
      [
        "装在哪",
        "已有电脑",
        "x:Linux 服务器",
        "x:Linux 服务器",
        "x:裸机",
        "已有电脑",
        "已有电脑",
        "x:要换系统",
      ],
      [
        "连回电脑的办法",
        "6 种",
        "x:自己开端口",
        "x:自己开端口",
        "x:3 种",
        "x:1 种",
        "x:1 种",
        "x:2 种",
      ],
      [
        "靠厂商服务器",
        "不靠",
        "不靠",
        "不靠",
        "x:远程靠",
        "x:靠",
        "x:靠",
        "x:远程靠",
      ],
      [
        "分享范围",
        "一个应用",
        "x:不能分享",
        "一个应用",
        "文件",
        "一个服务",
        "x:整个桌面",
        "文件相册",
      ],
    ],
  },
  {
    title: "免费",
    rows: [
      ["付费档", "没有", "x:有", "x:有", "x:有", "x:有", "x:有", "x:有"],
      [
        "多台电脑",
        "免费",
        "x:¥1500/套",
        "x:$99/年",
        "x:一台",
        "免费",
        "免费",
        "x:一台",
      ],
      [
        "全球连接",
        "免费",
        "x:自己开端口",
        "x:自己开端口",
        "x:$19.8/月",
        "免费",
        "x:¥66/月",
        "x:另收费",
      ],
      [
        "带宽",
        "不限",
        "不限",
        "不限",
        "x:5 Mbps",
        "不限",
        "x:4 Mbps",
        "x:2 Mbps",
      ],
      [
        "开源",
        "开源",
        "开源",
        "x:有限制",
        "开源",
        "x:部分",
        "x:闭源",
        "x:闭源",
      ],
    ],
  },
];
