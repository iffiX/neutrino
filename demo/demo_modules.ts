import type {
  ModuleTaskStep,
  ModuleUninstallData,
  WebShareGuestLogin,
} from "../hub/frontend/src/api_types";

/**
 * The modules the demo offers, the built modules of the catalog in its order.
 */

/** The account every demo machine runs its modules as. */
export const DEMO_ACCOUNT = "xiaoming";

/** The catalog's activity filters, in their order. */
export const DEMO_MODULE_CATEGORIES = [
  "code",
  "paper",
  "notes",
  "files",
  "remote",
  "other",
];

/** The page a module publishes. */
export interface DemoModuleWeb {
  /** The published app's title; `{account}` names the account. */
  title: string;
  /** The title in English where it differs. */
  englishTitle?: string;
  port: number;
  isPerAccount: boolean;
  isTokenRequired: boolean;
  guestLogin: WebShareGuestLogin;
  descriptionCode: string;
}

export interface DemoModuleSpec {
  name: string;
  /** The manifest's title. */
  title: string;
  category: string;
  method: string;
  version: string;
  isCarried: boolean;
  requires: string[];
  installSteps: ModuleTaskStep[];
  uninstallData: ModuleUninstallData | null;
  web: DemoModuleWeb | null;
}

function step(
  name: string,
  params: Record<string, unknown> = {},
): ModuleTaskStep {
  return { name, params };
}

function uninstallKept(zh: string, en: string): ModuleUninstallData {
  return { is_deleted: false, text: { "zh-CN": zh, en } };
}

function uninstallDeleted(zh: string, en: string): ModuleUninstallData {
  return { is_deleted: true, text: { "zh-CN": zh, en } };
}

/** Every module, by manifest name, in the catalog's order. */
export const DEMO_MODULES: DemoModuleSpec[] = [
  {
    name: "terminal",
    title: "Terminal",
    category: "code",
    method: "agent",
    version: "",
    isCarried: true,
    requires: [],
    installSteps: [],
    uninstallData: null,
    web: null,
  },
  {
    name: "ssh_server",
    title: "SSH server",
    category: "code",
    method: "agent",
    version: "",
    isCarried: true,
    requires: [],
    installSteps: [],
    uninstallData: null,
    web: null,
  },
  {
    name: "remote_desktop",
    title: "Remote desktop",
    category: "remote",
    method: "agent",
    version: "",
    isCarried: true,
    requires: [],
    installSteps: [],
    uninstallData: null,
    web: null,
  },
  {
    name: "samba",
    title: "File share",
    category: "files",
    method: "system",
    version: "4.19.5",
    isCarried: false,
    requires: [],
    installSteps: [step("packages"), step("configure"), step("start")],
    uninstallData: uninstallKept(
      "共享的文件夹和里面的文件都原样保留。",
      "The shared folders and the files in them stay where they are.",
    ),
    web: null,
  },
  {
    name: "gitea",
    title: "Gitea",
    category: "code",
    method: "hub",
    version: "1.24.6",
    isCarried: false,
    requires: [],
    installSteps: [
      step("artifact", { name: "gitea" }),
      step("configure"),
      step("start"),
      step("admin"),
    ],
    uninstallData: uninstallKept(
      "仓库、Gitea 的账户和数据库都留在它的数据目录里。",
      "The repositories, Gitea's accounts and its database stay in its data directory.",
    ),
    web: {
      title: "Gitea",
      port: 3000,
      isPerAccount: false,
      isTokenRequired: false,
      guestLogin: "app",
      descriptionCode: "gitea_module",
    },
  },
  {
    name: "vscode",
    title: "VS Code",
    category: "code",
    method: "hub",
    version: "1.105.1",
    isCarried: false,
    requires: [],
    installSteps: [
      step("artifact", { name: "vscode" }),
      step("configure"),
      step("start"),
      step("verify"),
    ],
    uninstallData: uninstallKept(
      "每个账户的设置和扩展都留在它的主目录里。",
      "Each account's settings and extensions stay in its home folder.",
    ),
    web: {
      title: "VS Code ({account})",
      port: 8101,
      isPerAccount: true,
      isTokenRequired: true,
      guestLogin: "run_account",
      descriptionCode: "vscode_module",
    },
  },
  {
    name: "code_server",
    title: "code-server",
    category: "code",
    method: "hub",
    version: "4.104.3",
    isCarried: false,
    requires: [],
    installSteps: [
      step("artifact", { name: "code_server" }),
      step("configure"),
      step("start"),
      step("verify"),
    ],
    uninstallData: uninstallKept(
      "每个账户的 code-server 设置和扩展都留在它的主目录里。",
      "Each account's code-server settings and extensions stay in its home folder.",
    ),
    web: {
      title: "code-server ({account})",
      port: 8102,
      isPerAccount: true,
      isTokenRequired: true,
      guestLogin: "run_account",
      descriptionCode: "code_server_module",
    },
  },
  {
    name: "cloudcli",
    title: "CloudCLI",
    category: "code",
    method: "hub",
    version: "1.8.4",
    isCarried: false,
    requires: [],
    installSteps: [
      step("artifact", { name: "node" }),
      step("npm", { account: DEMO_ACCOUNT }),
      step("configure"),
      step("start"),
    ],
    uninstallData: uninstallKept(
      "每个账户的 CloudCLI 数据留在 ~/.cloudcli。",
      "Each account's CloudCLI data stays in ~/.cloudcli.",
    ),
    web: {
      title: "CloudCLI ({account})",
      port: 8104,
      isPerAccount: true,
      isTokenRequired: true,
      guestLogin: "run_account",
      descriptionCode: "cloudcli_module",
    },
  },
  {
    name: "codeg",
    title: "Codeg",
    category: "code",
    method: "hub",
    version: "0.9.2",
    isCarried: false,
    requires: [],
    installSteps: [
      step("artifact", { name: "node" }),
      step("artifact", { name: "server" }),
      step("configure"),
      step("start"),
    ],
    uninstallData: uninstallKept(
      "每个账户的 Codeg 数据留在 ~/.codeg。",
      "Each account's Codeg data stays in ~/.codeg.",
    ),
    web: {
      title: "Codeg ({account})",
      port: 8103,
      isPerAccount: true,
      isTokenRequired: true,
      guestLogin: "run_account",
      descriptionCode: "codeg_module",
    },
  },
  {
    name: "siyuan",
    title: "SiYuan",
    category: "notes",
    method: "hub",
    version: "3.3.5",
    isCarried: false,
    requires: [],
    installSteps: [
      step("artifact", { name: "siyuan" }),
      step("configure"),
      step("start"),
    ],
    uninstallData: uninstallKept(
      "每个账户的笔记留在 ~/SiYuan。",
      "Each account's notes stay in ~/SiYuan.",
    ),
    web: {
      title: "思源笔记 ({account})",
      englishTitle: "SiYuan ({account})",
      port: 6806,
      isPerAccount: true,
      isTokenRequired: true,
      guestLogin: "run_account",
      descriptionCode: "siyuan_module",
    },
  },
  {
    name: "podman",
    title: "Containers",
    category: "other",
    method: "system",
    version: "5.6.2",
    isCarried: false,
    requires: [],
    installSteps: [step("packages"), step("configure"), step("start")],
    uninstallData: uninstallKept(
      "声明的容器的卷都保留。",
      "The declared containers' volumes stay.",
    ),
    web: null,
  },
  {
    name: "hermes_webui",
    title: "Hermes WebUI",
    category: "code",
    method: "container",
    version: "0.4.1",
    isCarried: false,
    requires: ["podman"],
    installSteps: [
      step("wait_module", { module: "podman" }),
      step("pull", { image: "webui" }),
      step("pull", { image: "agent" }),
      step("render"),
      step("start"),
      step("wait_app"),
    ],
    uninstallData: uninstallDeleted(
      "对话、设置和工作区里的文件都会删除，无法恢复。",
      "The conversations, settings and workspace files are deleted and cannot be recovered.",
    ),
    web: {
      title: "Hermes WebUI",
      port: 8105,
      isPerAccount: false,
      isTokenRequired: true,
      guestLogin: "guest_account",
      descriptionCode: "hermes_webui_module",
    },
  },
  {
    name: "ayakaleaf",
    title: "Ayakaleaf",
    category: "paper",
    method: "container",
    version: "2.1.0",
    isCarried: false,
    requires: ["podman"],
    installSteps: [
      step("wait_module", { module: "podman" }),
      step("pull", { image: "app" }),
      step("pull", { image: "mongo" }),
      step("pull", { image: "redis" }),
      step("render"),
      step("replica_set"),
      step("guests"),
      step("start"),
      step("wait_app"),
    ],
    uninstallData: uninstallDeleted(
      "论文和项目都会删除，无法恢复。",
      "The papers and projects are deleted and cannot be recovered.",
    ),
    web: {
      title: "Ayakaleaf",
      port: 8106,
      isPerAccount: false,
      isTokenRequired: true,
      guestLogin: "guest_account",
      descriptionCode: "ayakaleaf_module",
    },
  },
];

/** The module of a name, or null for one the demo does not offer. */
export function demoModule(name: string): DemoModuleSpec | null {
  return DEMO_MODULES.find((spec) => spec.name === name) ?? null;
}

/** A module's published title in a language. */
export function moduleWebTitle(web: DemoModuleWeb, language: string): string {
  return language === "en" ? (web.englishTitle ?? web.title) : web.title;
}
