/**
 * The English home page's words, apps, install box captions and comparison table.
 * The commands, files and pictures are the Chinese page's, from home_content.ts.
 */
import {
  PICTURES as PICTURES_ZH,
  SITES as SITES_ZH,
  SYSTEMS as SYSTEMS_ZH,
} from "./home_content";

/** The pictures, the panel and phone ones taken from the English demo. */
export const PICTURES = {
  ...PICTURES_ZH,
  heroPanel: "/home/en/panel_dashboard.webp",
  heroPhone: "/home/en/phone_apps.webp",
  store: "/home/en/panel_store.webp",
  shareDialog: "/home/en/share_dialog.webp",
};

export const SITES = [
  { ...SITES_ZH[0], label: "China", chip: "No proxy" },
  { ...SITES_ZH[1], label: "Global" },
];

export const PARTS = [
  { id: "hub", label: "Install the hub" },
  { id: "client", label: "Install the client" },
];

const CAPTIONS: Record<
  string,
  { caption?: string; phoneCaption?: string; guide?: string }
> = {
  Android: {
    caption: "Scan with your phone camera to download and install",
    phoneCaption: "Tap arm64 below to download and install",
  },
  iPhone: {
    caption: "Download it, then sign and install it yourself",
    guide: "/en/access/ios",
  },
};

/** The install box's tabs, with English captions and package names. */
export const SYSTEMS = SYSTEMS_ZH.map((entry) => ({
  ...entry,
  ...CAPTIONS[entry.name],
  packages: (part: string, suffix: string) =>
    entry.packages(part, suffix).map((pack) => ({
      ...pack,
      label: pack.label === "Apple 芯片" ? "Apple silicon" : pack.label,
    })),
}));

export const WAYS_IN = [
  "NetBird*",
  "EasyTier*",
  "SSH relay",
  "Direct",
  "SakuraFrp",
  "OpenFrp",
];

export const APP_GROUPS = [
  {
    label: "System access",
    apps: [
      {
        name: "Remote desktop",
        icon: "remote_desktop",
        link: "/en/deploy/remote_desktop",
      },
      { name: "File share", icon: "samba", link: "/en/deploy/file_share" },
      { name: "Terminal", icon: "terminal", link: "/en/deploy/terminal" },
      { name: "SSH", icon: "generic", link: "/en/deploy/ssh" },
    ],
  },
  {
    label: "Writing code",
    apps: [
      { name: "VS Code", icon: "vscode", link: "/en/deploy/vscode" },
      {
        name: "code-server",
        icon: "code_server",
        link: "/en/deploy/code_server",
      },
    ],
  },
  {
    label: "AI workflows",
    apps: [
      { name: "CloudCLI", icon: "cloudcli", link: "/en/deploy/cloudcli" },
      { name: "Codeg", icon: "codeg", link: "/en/deploy/codeg" },
      {
        name: "Hermes WebUI",
        icon: "generic",
        link: "/en/deploy/hermes_webui",
      },
    ],
  },
  {
    label: "Writing papers",
    apps: [
      { name: "Ayakaleaf", icon: "ayakaleaf", link: "/en/deploy/ayakaleaf" },
    ],
  },
  {
    label: "Notes",
    apps: [{ name: "SiYuan", icon: "siyuan", link: "/en/deploy/siyuan" }],
  },
  {
    label: "Hosting code",
    apps: [{ name: "Gitea", icon: "gitea", link: "/en/deploy/gitea" }],
  },
  {
    label: "Containers",
    apps: [
      { name: "Containers", icon: "podman", link: "/en/deploy/containers" },
    ],
  },
];

export const COMPARE_PRODUCTS = [
  "Neutrino Hub",
  "1Panel",
  "Cosmos",
  "Olares",
  "Tailscale",
  "ToDesk",
  "fnOS",
];

/** One row: its name, then each product's cell in COMPARE_PRODUCTS' order; a cell starting with "x:" is a miss. */
export const COMPARE_GROUPS = [
  {
    title: "Complete",
    rows: [
      [
        "OS support",
        "All three",
        "x:Linux only",
        "x:Linux only",
        "x:Its own OS",
        "All three",
        "All three",
        "x:Its own OS",
      ],
      [
        "Client support",
        "All platforms",
        "x:Web; phone in the Pro plan",
        "x:Web; phone in the paid plan",
        "All platforms",
        "All platforms",
        "All platforms",
        "x:Phone and web",
      ],
      ["One-click apps", "Yes", "Yes", "Yes", "Yes", "x:No", "x:No", "Yes"],
      [
        "Containers",
        "All three",
        "x:Linux only",
        "x:Linux only",
        "x:Its own OS",
        "x:No",
        "x:No",
        "x:Its own OS",
      ],
      [
        "Open apps from outside",
        "Ready",
        "x:Open a port",
        "x:Open a port",
        "Yes",
        "x:DIY",
        "x:No",
        "x:Partly",
      ],
      [
        "Remote desktop",
        "Ready",
        "x:No",
        "x:DIY",
        "x:DIY",
        "x:DIY",
        "Yes",
        "x:DIY",
      ],
      [
        "Terminal",
        "Ready",
        "Yes",
        "x:Containers only",
        "Yes",
        "x:DIY",
        "Yes",
        "x:Turn it on",
      ],
      [
        "Mounted drive",
        "Ready",
        "x:Web only",
        "x:Paid plan",
        "x:LAN only",
        "x:Transfer only",
        "x:Transfer only",
        "Yes",
      ],
      [
        "SSH/SFTP",
        "Ready",
        "x:Open a port",
        "x:Open a port",
        "Yes",
        "Yes",
        "x:No",
        "x:Turn it on",
      ],
      [
        "App sharing",
        "One link",
        "x:No",
        "x:Needs a domain",
        "x:Files only",
        "Yes",
        "x:Needs an install",
        "x:Files only",
      ],
    ],
  },
  {
    title: "Secure",
    rows: [
      [
        "Encrypted transport",
        "Yes",
        "x:DIY",
        "x:Needs a domain",
        "Yes",
        "Yes",
        "Yes",
        "x:Not stated",
      ],
      [
        "Fingerprint on a scan",
        "None",
        "x:Yes",
        "x:Yes",
        "x:Yes",
        "None",
        "None",
        "x:Yes",
      ],
    ],
  },
  {
    title: "Yours",
    rows: [
      [
        "Where it installs",
        "A computer you own",
        "x:Linux server",
        "x:Linux server",
        "x:Bare metal",
        "A computer you own",
        "A computer you own",
        "x:Replaces the OS",
      ],
      [
        "Ways back to the computer",
        "6",
        "x:Open a port",
        "x:Open a port",
        "x:3",
        "x:1",
        "x:1",
        "x:2",
      ],
      [
        "Relies on vendor servers",
        "No",
        "No",
        "No",
        "x:For remote access",
        "x:Yes",
        "x:Yes",
        "x:For remote access",
      ],
      [
        "What you can share",
        "One app",
        "x:Nothing",
        "One app",
        "Files",
        "One service",
        "x:The whole desktop",
        "Files and photos",
      ],
    ],
  },
  {
    title: "Free",
    rows: [
      [
        "Paid tier",
        "None",
        "x:Yes",
        "x:Yes",
        "x:Yes",
        "x:Yes",
        "x:Yes",
        "x:Yes",
      ],
      [
        "Several computers",
        "Free",
        "x:¥1500 per set",
        "x:$99/year",
        "x:One",
        "Free",
        "Free",
        "x:One",
      ],
      [
        "Global access",
        "Free",
        "x:Open a port",
        "x:Open a port",
        "x:$19.8/month",
        "Free",
        "x:¥66/month",
        "x:Paid extra",
      ],
      [
        "Bandwidth",
        "Unlimited",
        "Unlimited",
        "Unlimited",
        "x:5 Mbps",
        "Unlimited",
        "x:4 Mbps",
        "x:2 Mbps",
      ],
      [
        "Open source",
        "Yes",
        "Yes",
        "x:Restricted",
        "Yes",
        "x:Partly",
        "x:Closed",
        "x:Closed",
      ],
    ],
  },
];

/** The advanced features after the share section; a command shows as code before its text. */
export const ADVANCED = [
  {
    title: "AI gateway",
    command: "",
    text: "Set up an AI provider once on the hub, and Claude Code and Codex on every computer can use it.",
    link: "/en/hub/ai_gateway",
  },
  {
    title: "Wake-on-LAN",
    command: "",
    text: "Wake a computer on your LAN that is off, with one click in the panel.",
    link: "/en/hub/agents#wake",
  },
  {
    title: "Multi-machine management",
    command: "",
    text: "Add your computers at home and in the lab, and see their CPU, memory, GPU and temperature at a glance.",
    link: "/en/hub/agents",
  },
  {
    title: "Client permissions",
    command: "",
    text: "Turn apps, terminals, files and remote desktop on or off for each client, down to single apps.",
    link: "/en/hub/clients#permission-kinds",
  },
  {
    title: "Credential vault",
    command: "",
    text: "The hub generates and keeps the passwords for file sharing and remote desktop, and the SSH keys.",
    link: "/en/hub/what_it_holds#stored-data",
  },
  {
    title: "Remote execution",
    command: "nclient terminal exec",
    text: "runs commands on another computer, for scripts and AI agents alike.",
    link: "/en/access/terminal#run-one-command",
  },
];

/** Every sentence and label of the English page. */
export const WORDS = {
  name: "Neutrino Hub",
  title: ["Deploy apps in one click,", "use them anywhere"],
  lead: "Code, write papers, take notes, use a remote desktop and move files. One click installs an app on your own computer, your phone and laptop open it anytime, and a link shares it with a friend.",
  small:
    "Installs on Windows, macOS and Linux. Open source, free, MIT license.",
  quickStart: "Quick start",
  quickStartLink: "/en/quick-start",
  demo: "Live demo",
  chooseSystem: "Choose a system",
  switchSite: "Switch between the China edition and the International edition",
  copy: "Copy",
  copied: "Copied",
  download: "Download",
  guide: "Install guide",
  qrAlt: "QR code to download the Android client",
  heroPanelAlt: "The panel's dashboard",
  heroPhoneAlt: "The app list on a phone",
  deployTitle: "Deploy in one click",
  deployText:
    "Pick an app and it installs in one click, with no environment to prepare and no system to replace. Containers deploy the same way on Windows, macOS and Linux. Each machine picks a fast and steady one of several download sources.",
  deployNote:
    "Apps missing from the list work too: declare a service yourself, with several ports and HTTP entries. Ports a container publishes become apps automatically.",
  storeAlt: "Choosing an app to install on the panel",
  wolfSitAlt: "The mascot on a block, using a laptop",
  waysTitle: "Use it anywhere",
  waysText:
    "Scan a code once with your phone, then open your computer's apps from the subway, a train, in-flight Wi-Fi or another country. Six ways connect the two, and smart routing takes the fastest*.",
  waysAria:
    "Six ways between the computer and the phone, with the fastest one lit",
  laptopAlt: "VS Code on a laptop",
  waysSeparator: ", ",
  waysNote:
    "* You pick NetBird and EasyTier by hand; the rest are automatic. iOS leaves those two out, and you need a US App Store account to install their own apps.",
  shareTitle: "Share with a link",
  shareText:
    "Select Share on any web app to get a link. A friend opens it in a browser with nothing to install. The link expires on its own, and you can revoke it sooner.",
  shareDialogAlt: "The share dialog on the panel",
  shareYou: "You select Share",
  wolfTwoAlt: "Two mascots at a table",
  shareBrowserAlt: "Ayakaleaf open in a friend's browser",
  shareFriend: "Your friend opens it",
  advancedTitle: "Advanced features",
  points: [
    {
      title: "Complete",
      lines: [
        "Apps, the desktop, terminals, files and SSH.",
        "One click installs them, and the client has them ready.",
      ],
    },
    {
      title: "Secure",
      lines: [
        "Encrypted all the way between a device and the hub, and third-party lines cannot read it. Neutrino's service port strictly guards every app.",
        "Only people you approve get in.",
      ],
    },
    {
      title: "Yours",
      lines: [
        "No server, domain or special hardware to buy.",
        "Neutrino runs no public server,",
        "and a share connects only to your hub.",
      ],
    },
    {
      title: "Free",
      lines: [
        "Manage several computers, wake them over the LAN,",
        "connect worldwide, with no limit on users",
        "or traffic. All free.",
      ],
    },
  ],
  tableNote:
    "Prices and limits come from each vendor's page on 2026-10-30. Third-party services set their own bandwidth and account rules.",
};
