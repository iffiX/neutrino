import {
  DEMO_ACCOUNT,
  DEMO_MODULE_CATEGORIES,
  DEMO_MODULES,
  demoModule,
  moduleWebTitle,
} from "./demo_modules";
import type { DemoModuleSpec } from "./demo_modules";
import { demoWord } from "./demo_words";
import type { DemoWordKey } from "./demo_words";
import {
  DEMO_AI_ACCOUNTS,
  DEMO_AI_JOURNAL_LINES,
  DEMO_AI_PROVIDERS,
  DEMO_AI_STATUS,
  DEMO_DIRECT,
  DEMO_EASYTIER,
  DEMO_GENERATED_CREDENTIALS,
  DEMO_HTTPS,
  DEMO_HUB_ADDRESS,
  DEMO_HUB_VERSION,
  DEMO_KEYS,
  DEMO_LOGINS,
  DEMO_NETBIRD,
  DEMO_OPENFRP,
  DEMO_OPENFRP_TUNNELS,
  DEMO_OVERLAY_KINDS,
  DEMO_RELAY,
  DEMO_RELEASE,
  DEMO_RELEASE_SCAN,
  DEMO_SAKURAFRP,
  DEMO_SAKURAFRP_TUNNELS,
  DEMO_SETTINGS,
  DEMO_TOKENS,
  demoAbout,
  demoAccounts,
  secondsAgo,
  sample,
} from "./demo_fixtures";
import { DemoNetwork, demoDnsLog } from "./demo_network";
import { DemoProxy, DemoRefusal } from "./demo_proxy";
import {
  DEMO_STAT_BACKLOG,
  DemoStatsFeed,
  demoAiUsage,
  demoHistory,
  demoMetrics,
} from "./demo_traffic";
import type { DemoFrameReadings } from "./demo_traffic";
import type {
  AiUsageRange,
  AppEntryView,
  CliproxyApiStatusView,
  AppView,
  AuthState,
  AyakaleafDeviceView,
  BalancerSettings,
  ClientListView,
  ClientView,
  DeclaredAppCreate,
  DeviceFileListView,
  DeviceModuleListView,
  DeviceModuleView,
  DeviceView,
  DevicesResponse,
  EnabledAccountsView,
  FolderShareListView,
  GiteaDeviceView,
  InterfaceSettings,
  ModuleCatalogView,
  ModuleDeviceState,
  ModuleTask,
  ModuleVersionView,
  NetworkModeKey,
  NetworkOptions,
  NetworkView,
  NodesResponse,
  OverlayChoiceView,
  PermissionRowView,
  PodmanDeviceView,
  ProxySettings,
  PublishedService,
  RemoteDesktopDeviceView,
  SambaStatus,
  ServiceListView,
  SettingsView,
  StatsFrame,
  TrafficHistoryRange,
  WebShareCreatedView,
  WebShareEntryView,
  WebShareView,
} from "../hub/frontend/src/api_types";

/**
 * The fake hub: the state both halves of the page read, the panel's routes
 * over it, and its live sockets.
 */

/** A machine a client may open a terminal on, with what its shell shows. */
export interface DemoTerminalMachine {
  device_id: string;
  name: string;
  is_online: boolean;
  accounts: string[];
  hostname: string;
  platform_os: string;
  address: string;
  metrics_seed: number;
}

/** A response the panel's fetch returns. */
export interface DemoAnswer {
  status: number;
  body: unknown;
}

/** A language, a palette choice, or both, that one side is set to. */
export type DemoDisplayChange = Partial<
  Pick<SettingsView, "language" | "theme">
>;

/** The edition the panel is drawn as. */
export type DemoEdition = "cn" | "intl";

/** A frame of the event socket. */
interface DemoHubEvent {
  type: string;
  key: string;
  at: string;
  data?: unknown;
}

type DemoFrameSender = (frame: unknown) => void;
type DemoRoute = (query: URLSearchParams, body: DemoBody) => unknown;
type DemoBody = Record<string, unknown>;

/** A module on one machine. */
interface DemoModuleState {
  state: string;
  want: string;
  isShown: boolean;
  task: ModuleTask | null;
  isTermsAccepted: boolean;
}

interface DemoDevice {
  id: string;
  name: string;
  icon: string | null;
  address: string;
  mac: string;
  isOnline: boolean;
  hostname: string;
  platformOs: string;
  platformArch: string;
  lastSeen: string | null;
  metricsSeed: number;
  modules: Record<string, DemoModuleState>;
}

/** An app declared on the Services page. */
interface DemoDeclaredApp {
  id: string;
  title: string;
  host: string;
  description: string;
  entries: AppEntryView[];
}

// The modules whose data moves forward only: the Upgrade only chip.
const FORWARD_ONLY_MODULES = new Set([
  "gitea",
  "ayakaleaf",
  "codeg",
  "cloudcli",
]);
const STEP_MS = 1100;
const MINIMUM_ANSWER_MS = 40;
const APPLY_MS = 600;
const NODE_MEASURE_MS = 700;
const NODE_FIRST_MEASURE_MS = 2500;
const STAT_TICK_MS = 1000;
const METRICS_TICK_MS = 3000;
const METRICS_BACKLOG = 40;
const METRICS_BACKLOG_PAUSE_S = 30;
const JOIN_DELAY_MS = 9000;
const SHARE_PREPARE_MS = 1800;
const LINK_LIFE_S = 1800;
const JOURNAL_NOW_LINE = "module is healthy";
const CLIENT_SELF_ID = "client_phone";
const SHARE_SITE = "https://share.example.net";
const PERMISSION_KINDS = [
  "web",
  "port",
  "ssh",
  "ai",
  "file",
  "rdp",
  "overlay",
  "terminal",
  "panel",
];
const DEFAULT_PERMISSION = PERMISSION_KINDS.filter((kind) => kind !== "panel");
const ROW_KINDS = ["web", "port", "ssh", "file", "rdp", "terminal"];

function moduleState(
  state: string,
  isTermsAccepted: boolean = false,
): DemoModuleState {
  return {
    state,
    want: state === "absent" ? "" : "running",
    isShown: state !== "absent",
    task: null,
    isTermsAccepted,
  };
}

function modulesWith(running: string[]): Record<string, DemoModuleState> {
  const modules: Record<string, DemoModuleState> = {};
  for (const spec of DEMO_MODULES) {
    const isRunning = spec.isCarried || running.includes(spec.name);
    modules[spec.name] = moduleState(
      isRunning ? "running" : "absent",
      isRunning,
    );
  }
  return modules;
}

function initialDevices(): DemoDevice[] {
  return [
    {
      id: "dev_desktop",
      name: sample("我的台式机", "My desktop"),
      icon: "desktop",
      address: "192.168.1.20",
      mac: "52:54:00:12:34:20",
      isOnline: true,
      hostname: "desktop",
      platformOs: "linux",
      platformArch: "amd64",
      lastSeen: null,
      metricsSeed: 0,
      modules: modulesWith(["samba", "vscode", "gitea", "siyuan", "podman"]),
    },
    {
      id: "dev_laptop",
      name: sample("笔记本", "Laptop"),
      icon: "laptop",
      address: "192.168.1.31",
      mac: "52:54:00:12:34:31",
      isOnline: true,
      hostname: "laptop",
      platformOs: "windows",
      platformArch: "amd64",
      lastSeen: null,
      metricsSeed: 1,
      modules: modulesWith(["code_server", "cloudcli"]),
    },
    {
      id: "dev_mini",
      name: sample("书房小主机", "Study mini PC"),
      icon: "server",
      address: "192.168.1.42",
      mac: "52:54:00:12:34:42",
      isOnline: false,
      hostname: "mini",
      platformOs: "linux",
      platformArch: "arm64",
      lastSeen: secondsAgo(3600 * 7),
      metricsSeed: 2,
      modules: modulesWith(["samba"]),
    },
  ];
}

function initialClients(): ClientView[] {
  return [
    {
      id: CLIENT_SELF_ID,
      name: sample("我的手机", "My phone"),
      hostname: "phone",
      platform_os: "android",
      version: DEMO_HUB_VERSION,
      is_online: true,
      last_seen: null,
      is_disabled: false,
      permission: null,
      permission_devices: {},
      permission_entries: {},
      link_expires_in_s: null,
    },
    {
      id: "client_office",
      name: sample("公司电脑", "Work computer"),
      hostname: "office-pc",
      platform_os: "windows",
      version: DEMO_HUB_VERSION,
      is_online: false,
      last_seen: secondsAgo(3600 * 16),
      is_disabled: false,
      permission: null,
      permission_devices: {},
      permission_entries: {},
      link_expires_in_s: null,
    },
  ];
}

function initialDeclaredApps(): DemoDeclaredApp[] {
  const id = "declared_router";
  return [
    {
      id,
      title: sample("路由器后台", "Router admin"),
      host: "192.168.1.1",
      description: sample(
        "家里路由器的管理页面",
        "The home router's admin page",
      ),
      entries: [
        {
          id: `${id}_web`,
          name: "web",
          type: "web",
          payload: { url: "http://192.168.1.1/" },
          is_healthy: true,
          local_port: localPort(`${id}_web`),
          detail_code: null,
          guest_login: "app",
        },
      ],
    },
  ];
}

/** The port every client forwards an entry on, from its id alone. */
function localPort(entryId: string): number {
  let hash = 0;
  for (const letter of entryId) {
    hash = (hash * 31 + letter.charCodeAt(0)) % 8000;
  }
  return 24000 + hash;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/** The text of a body's field, empty when it holds none. */
export function textField(body: DemoBody, name: string): string {
  const value = body[name];
  return typeof value === "string" ? value : "";
}

/** The source chip's word for each install method the demo's modules name. */
const DEMO_SOURCE: Record<string, string> = {
  agent: "agent",
  builtin: "system",
  system: "system",
  hub: "upstream",
  container: "container",
};

export class DemoHub {
  private readonly stats = new DemoStatsFeed();
  private readonly network = new DemoNetwork();
  private readonly proxy = new DemoProxy();
  private readonly statFrames: StatsFrame[] = [];
  private readonly devices = initialDevices();
  private readonly declaredApps = initialDeclaredApps();
  private readonly clients = initialClients();
  private readonly shares: WebShareView[] = [];
  /** Every client's join link, to its client id. */
  private readonly clientLinks = new Map<string, string>();
  private readonly statSenders = new Set<DemoFrameSender>();
  private readonly eventSenders = new Set<DemoFrameSender>();
  private readonly changeListeners = new Set<() => void>();
  private readonly noticeListeners = new Set<(text: string) => void>();
  private readonly displayListeners = new Set<() => void>();
  private readonly overlayKinds = DEMO_OVERLAY_KINDS.map((kind) => ({
    ...kind,
  }));
  private readonly reads: Record<string, DemoRoute>;
  private readonly writes: Record<string, DemoRoute>;
  private settings: SettingsView = { ...DEMO_SETTINGS };
  private defaultModel = DEMO_AI_STATUS.default_model ?? "";
  private currentEdition: DemoEdition = "cn";
  private defaultPermission = [...DEFAULT_PERMISSION];
  private defaultPermissionDevices: Record<string, string[]> = {};
  private defaultPermissionEntries: Record<string, boolean> = {};
  private appsInUse = 0;
  private isSignedIn = true;
  private serial = 0;
  private readonly metricsSentAt = new Map<string, number>();

  constructor() {
    this.reads = this.readRoutes();
    this.writes = this.writeRoutes();
    this.addFirstShare();
    for (let age = DEMO_STAT_BACKLOG; age > 0; age -= 1) {
      this.statFrames.push(
        this.stats.frame(age, 0, this.onlineCount(), this.frameReadings()),
      );
    }
    window.setInterval(() => this.tickStats(), STAT_TICK_MS);
    window.setInterval(() => this.tickMetrics(), METRICS_TICK_MS);
  }

  /**
   * Returns the response to a panel call.
   *
   * Args:
   *   method: `GET` or `POST`.
   *   path: The route with its query, under `/api`.
   *   body: The parsed JSON body, or an empty object.
   *
   * Returns:
   *   The status and the body, after a short delay.
   */
  async answer(
    method: string,
    path: string,
    body: DemoBody,
  ): Promise<DemoAnswer> {
    await delay(MINIMUM_ANSWER_MS);
    const [pathname = "", queryText = ""] = path.split("?");
    const query = new URLSearchParams(queryText);
    const routes = method === "GET" ? this.reads : this.writes;
    const route = routes[pathname];
    if (route !== undefined) {
      return this.routeAnswer(route, query, body);
    }
    if (method === "GET") {
      const moduleName = /^\/agent\/module\/([a-z_]+)$/.exec(pathname)?.[1];
      if (moduleName !== undefined && demoModule(moduleName) !== null) {
        return {
          status: 200,
          body: this.moduleView(query.get("device_id") ?? "", moduleName),
        };
      }
    }
    return { status: 409, body: { detail: this.word("refusal") } };
  }

  /**
   * Opens a live feed of the panel.
   *
   * Args:
   *   path: The socket's path, with its query.
   *   send: Called with each frame.
   *
   * Returns:
   *   The function that closes the feed.
   */
  openSocket(path: string, send: DemoFrameSender): () => void {
    const pathname = path.split("?")[0];
    if (pathname === "/ws/hub/dashboard/stat") {
      for (const frame of this.statFrames) {
        send(frame);
      }
      this.statSenders.add(send);
      return () => this.statSenders.delete(send);
    }
    if (pathname === "/ws/hub/event") {
      send(this.event("hello", ""));
      this.eventSenders.add(send);
      return () => this.eventSenders.delete(send);
    }
    if (pathname === "/ws/hub/dashboard/dns_log") {
      send({ entries: demoDnsLog() });
      return () => undefined;
    }
    send({ type: "output", data: `${this.word("refusal")}\r\n` });
    send({ type: "exit", code: 0 });
    send({ type: "done", exit_code: 0 });
    return () => undefined;
  }

  /** The edition the panel is drawn as. */
  edition(): DemoEdition {
    return this.currentEdition;
  }

  /** Whether the edition has the proxy and the side gateway mode. */
  isProxyCarried(): boolean {
    return this.currentEdition === "intl";
  }

  /** Sets the edition, leaving the mode the mainland edition does not have. */
  setEdition(edition: DemoEdition): void {
    this.currentEdition = edition;
    if (!this.isProxyCarried()) {
      this.network.leaveSideGateway();
    }
    this.tickStats();
  }

  /** Calls a listener after every change a client's state may draw. */
  onChange(listener: () => void): void {
    this.changeListeners.add(listener);
  }

  /**
   * Calls a listener after each `overwriteDisplay`.
   *
   * Args:
   *   listener: What runs after the overwrite.
   *
   * Returns:
   *   The function that removes the listener.
   */
  onDisplayOverwrite(listener: () => void): () => void {
    this.displayListeners.add(listener);
    return () => this.displayListeners.delete(listener);
  }

  /** Calls a listener with each short message for the visitor. */
  onNotice(listener: (text: string) => void): void {
    this.noticeListeners.add(listener);
  }

  /** Shows a short message to the visitor. */
  notify(text: string): void {
    for (const listener of this.noticeListeners) {
      listener(text);
    }
  }

  /** Records how many apps the client forwards. The traffic follows the count. */
  setAppsInUse(count: number): void {
    this.appsInUse = count;
  }

  /** The hub's name, as a client shows it. */
  hubName(): string {
    return this.settings.hub_name;
  }

  /** The client row of an id, or null once the panel deleted it. */
  clientRow(clientId: string): ClientView | null {
    return this.clients.find((row) => row.id === clientId) ?? null;
  }

  /** The id of the client the phone in the page joined as first. */
  firstClientId(): string {
    return CLIENT_SELF_ID;
  }

  /**
   * Whether a client's permission allows a thing.
   *
   * Args:
   *   clientId: The client's id.
   *   kind: The permission's kind.
   *   deviceId: The machine providing the thing, empty for none.
   *   rowId: The thing's row, empty for none.
   *
   * Returns:
   *   True when the permission allows it.
   */
  isAllowed(
    clientId: string,
    kind: string,
    deviceId: string,
    rowId: string,
  ): boolean {
    const client = this.clientRow(clientId);
    if (client === null) {
      return false;
    }
    const kinds = client.permission ?? this.defaultPermission;
    const devices =
      client.permission === null
        ? this.defaultPermissionDevices
        : client.permission_devices;
    const entries =
      client.permission === null
        ? this.defaultPermissionEntries
        : client.permission_entries;
    const entry = entries[rowId];
    if (entry !== undefined) {
      return entry;
    }
    if (!kinds.includes(kind)) {
      return false;
    }
    const narrowed = devices[kind];
    return narrowed === undefined || narrowed.includes(deviceId);
  }

  /**
   * The Services page's apps and entries.
   *
   * Args:
   *   language: The language of their titles, the panel's by default.
   *
   * Returns:
   *   The apps and the entries.
   */
  serviceList(language: string = this.settings.language): ServiceListView {
    return {
      apps: this.composeApps(language),
      services: this.composeServices(language),
    };
  }

  /** The panel's language. */
  language(): string {
    return this.settings.language;
  }

  /** The panel's palette choice. */
  theme(): string {
    return this.settings.theme;
  }

  /** Sets the panel's language or palette from outside the panel. */
  overwriteDisplay(change: DemoDisplayChange): void {
    this.setSettings(change);
    for (const listener of this.displayListeners) {
      listener();
    }
  }

  private word(key: DemoWordKey, params: Record<string, string> = {}): string {
    return demoWord(this.settings.language, key, params);
  }

  /** The machines a client may open a terminal on. */
  terminalMachines(clientId: string): DemoTerminalMachine[] {
    return this.devices
      .filter((device) =>
        this.isAllowed(clientId, "terminal", device.id, device.id),
      )
      .map((device) => ({
        device_id: device.id,
        name: device.name,
        is_online: device.isOnline,
        accounts: [DEMO_ACCOUNT],
        hostname: device.hostname,
        platform_os: device.platformOs,
        address: device.address,
        metrics_seed: device.metricsSeed,
      }));
  }

  /** The virtual networks the hub publishes to clients. */
  publishedOverlays(): string[] {
    return this.overlayKinds
      .filter(
        (kind) =>
          kind.is_enabled &&
          (kind.key === "netbird" || kind.key === "easytier"),
      )
      .map((kind) => kind.key);
  }

  /** Records a client on or off a virtual network. */
  noteOverlayClient(provider: string, change: number): void {
    const kind = this.overlayKinds.find((row) => row.key === provider);
    if (kind !== undefined) {
      kind.client_count = Math.max(0, kind.client_count + change);
    }
    this.publish("config", "overlay");
  }

  /** Marks a client online or offline, from the client's own side. */
  setClientOnline(clientId: string, isOnline: boolean): void {
    const client = this.clientRow(clientId);
    if (client === null) {
      return;
    }
    client.is_online = isOnline;
    client.last_seen = isOnline ? null : secondsAgo(0);
    this.publish("clients", clientId);
  }

  /**
   * Spends a join link.
   *
   * Args:
   *   link: The link a client pasted.
   *
   * Returns:
   *   The joined client's id, or null for a link the hub never made.
   */
  joinByLink(link: string): string | null {
    const clientId = this.clientLinks.get(link.trim());
    if (clientId === undefined) {
      return null;
    }
    this.finishJoin(clientId, "phone");
    return clientId;
  }

  private readRoutes(): Record<string, DemoRoute> {
    return {
      "/hub/display": () => ({
        language: this.settings.language,
        theme: this.settings.theme,
        update: null,
      }),
      "/hub/auth/session": () => this.authState(),
      "/hub/device": () => this.deviceList(),
      "/hub/device/remote_desktop": () => {
        const absent = {
          is_installed: false,
          is_running: false,
          unreachable: "",
          session_id: null,
          can_set_password: false,
        };
        return {
          anydesk: { product: "anydesk", ...absent },
          teamviewer: { product: "teamviewer", ...absent },
        };
      },
      "/hub/network": () => this.networkView(),
      "/hub/network/wifi_network": () => this.network.savedWifiList(),
      "/hub/network/interface/wifi/scan": (query) =>
        this.network.wifiScan(query.get("name") ?? ""),
      "/hub/proxy": () => this.proxy.view(),
      "/hub/proxy/node": () => this.proxy.nodesView(),
      "/hub/dashboard/summary": () => ({
        stats: this.statFrames[this.statFrames.length - 1],
        active_exit_tags: this.proxy.activeExitTags(),
        dns_query_count: demoDnsLog().length,
        lan_device_count: 5,
      }),
      "/hub/dashboard/history": (query) =>
        demoHistory((query.get("range") ?? "month") as TrafficHistoryRange),
      "/hub/ai": () => DEMO_AI_PROVIDERS,
      "/hub/ai/gateway": () => this.aiStatus(),
      "/hub/ai/gateway/usage": (query) =>
        demoAiUsage(
          (query.get("range") ?? "month") as AiUsageRange,
          query.get("key_id") ?? "",
        ),
      "/hub/ai/gateway/account": () => DEMO_AI_ACCOUNTS,
      "/hub/ai/gateway/journal": () => ({ lines: DEMO_AI_JOURNAL_LINES }),
      "/hub/overlay": () => this.overlayChoice(),
      "/hub/overlay/netbird": () => DEMO_NETBIRD,
      "/hub/overlay/easytier": () => DEMO_EASYTIER,
      "/hub/overlay/direct": () => DEMO_DIRECT,
      "/hub/overlay/relay": () => DEMO_RELAY,
      "/hub/overlay/sakurafrp": () => DEMO_SAKURAFRP,
      "/hub/overlay/sakurafrp/tunnel": () => DEMO_SAKURAFRP_TUNNELS,
      "/hub/overlay/openfrp": () => DEMO_OPENFRP,
      "/hub/overlay/openfrp/tunnel": () => DEMO_OPENFRP_TUNNELS,
      "/hub/client": () => this.clientList(),
      "/hub/service": () => this.serviceList(),
      "/hub/credential/ssh_key": () => DEMO_KEYS,
      "/hub/credential/login": () => DEMO_LOGINS,
      "/hub/credential/token": () => DEMO_TOKENS,
      "/hub/credential/generated": () => DEMO_GENERATED_CREDENTIALS,
      "/hub/setting": () => this.settings,
      "/hub/setting/about": () =>
        demoAbout(
          this.statFrames[this.statFrames.length - 1]?.uptime_s ?? 0,
          this.isProxyCarried(),
        ),
      "/hub/setting/https": () => DEMO_HTTPS,
      "/hub/setting/release": () => DEMO_RELEASE,
      "/agent/module": (query) => {
        const deviceId = query.get("device_id") ?? "";
        this.sendMetricsBacklog(deviceId);
        return this.moduleList(deviceId);
      },
      "/agent/module/catalog": (query) =>
        this.moduleCatalog(query.get("device_id") ?? ""),
      "/agent/module/account": (query) =>
        demoAccounts(this.device(query.get("device_id") ?? "").platformOs),
      "/agent/module/version": (query) =>
        this.moduleVersion(
          query.get("device_id") ?? "",
          query.get("module") ?? "",
        ),
      "/agent/module/journal": (query) => ({
        text: this.moduleJournal(
          query.get("device_id") ?? "",
          query.get("module") ?? "",
        ),
      }),
      "/agent/module/samba/status": (query) =>
        this.sambaStatus(query.get("device_id") ?? ""),
      "/agent/module/samba/folder_share": () => this.folderShares(),
      "/agent/file": (query) => this.fileList(query.get("path") ?? "/"),
      "/agent/module/podman/container/journal": () => ({ text: "" }),
    };
  }

  private writeRoutes(): Record<string, DemoRoute> {
    return {
      "/hub/auth/logout": () => {
        this.isSignedIn = false;
        return this.authState();
      },
      "/hub/auth/login": () => {
        this.isSignedIn = true;
        return this.authState();
      },
      "/hub/device/set": (_query, body) => this.setDevice(body),
      "/hub/device/enrollment/create": (_query, body) =>
        this.createDeviceLink(body),
      "/agent/module/install": (_query, body) =>
        this.pressModule(body, "install"),
      "/agent/module/start": (_query, body) => this.pressModule(body, "start"),
      "/agent/module/stop": (_query, body) => this.pressModule(body, "stop"),
      "/agent/module/uninstall": (_query, body) =>
        this.pressModule(body, "uninstall"),
      "/agent/module/vscode/terms/set": (_query, body) =>
        this.setVscodeTerms(body),
      "/hub/client/enrollment/create": (_query, body) =>
        this.createClientLink(body),
      "/hub/client/web_share/create": (_query, body) => this.createShare(body),
      "/hub/client/web_share/destroy": (_query, body) =>
        this.destroyShare(body),
      "/hub/client/enable": (_query, body) => this.setClientOff(body, false),
      "/hub/client/disable": (_query, body) => this.setClientOff(body, true),
      "/hub/client/set": (_query, body) => this.renameClient(body),
      "/hub/client/remove": (_query, body) => this.removeClient(body),
      "/hub/client/permission/set": (_query, body) =>
        this.setClientPermission(body),
      "/hub/client/default_permission/set": (_query, body) =>
        this.setDefaultPermission(body),
      "/hub/service/declaration/add": (_query, body) =>
        this.declareApp(body as unknown as DeclaredAppCreate),
      "/hub/service/declaration/remove": (_query, body) =>
        this.removeDeclaredApp(body),
      "/hub/setting/release/scan": () => DEMO_RELEASE_SCAN,
      "/hub/setting/set": (_query, body) => this.setSettings(body),
      "/hub/ai/gateway/set": (_query, body) => {
        const picked = (body as { default_model?: unknown }).default_model;
        this.defaultModel = typeof picked === "string" ? picked : "";
        return this.aiStatus();
      },
      "/hub/overlay/set": (_query, body) => this.setOverlays(body),
      "/hub/network/mode/set": (_query, body) => this.setNetworkMode(body),
      "/hub/network/set": (_query, body) =>
        this.writeNetwork(() =>
          this.network.setOptions(
            structuredClone(body) as unknown as NetworkOptions,
          ),
        ),
      "/hub/network/interface/set": (_query, body) =>
        this.writeNetwork(() =>
          this.network.setInterface(
            structuredClone(body) as unknown as InterfaceSettings,
          ),
        ),
      "/hub/network/interface/remove": (_query, body) =>
        this.writeNetwork(() =>
          this.network.removeInterface(textField(body, "name")),
        ),
      "/hub/network/interface/wifi/join": (_query, body) =>
        this.writeNetwork(() =>
          this.network.joinWifi(
            textField(body, "name"),
            textField(body, "ssid"),
          ),
        ),
      "/hub/network/wifi_network/leave": (_query, body) => {
        this.network.forgetWifi(textField(body, "ssid"));
        return this.network.savedWifiList();
      },
      "/hub/proxy/set": (_query, body) =>
        this.proxy.setSettings(body as unknown as ProxySettings),
      "/hub/proxy/apply": () => this.applyProxy(),
      "/hub/proxy/balancer/set": (_query, body) =>
        this.proxy.setBalancer(body as unknown as BalancerSettings),
      "/hub/proxy/geodata/scan": () => this.proxy.scanGeodata(),
      "/hub/proxy/node/add": (_query, body) => this.addProxyNode(body),
      "/hub/proxy/node/set": (_query, body) =>
        this.proxy.setNode(
          textField(body, "node_id"),
          body.is_enabled === true,
          textField(body, "name"),
        ),
      "/hub/proxy/node/remove": (_query, body) =>
        this.removeProxyNode(textField(body, "node_id")),
      "/hub/proxy/node/test": (_query, body) =>
        this.testProxyNodes(textField(body, "node_id")),
    };
  }

  /** A route's answer, a refusal it raised worded as the hub words one. */
  private async routeAnswer(
    route: DemoRoute,
    query: URLSearchParams,
    body: DemoBody,
  ): Promise<DemoAnswer> {
    try {
      return { status: 200, body: await route(query, body) };
    } catch (cause: unknown) {
      if (cause instanceof DemoRefusal) {
        const detail = { code: cause.code, params: cause.params };
        return { status: 400, body: { detail } };
      }
      throw cause;
    }
  }

  private networkView(): NetworkView {
    return this.network.view(this.isProxyCarried());
  }

  private writeNetwork(write: () => void): NetworkView {
    write();
    this.publish("config", "network");
    return this.networkView();
  }

  private async setNetworkMode(body: DemoBody): Promise<NetworkView> {
    const mode = textField(body, "mode") as NetworkModeKey;
    if (!this.networkView().modes.some((offered) => offered.key === mode)) {
      throw new DemoRefusal("network_mode_unknown", { mode });
    }
    await delay(APPLY_MS);
    const view = this.writeNetwork(() => this.network.setMode(mode));
    this.tickStats();
    return view;
  }

  private async applyProxy(): Promise<unknown> {
    await delay(APPLY_MS);
    const result = this.proxy.apply();
    this.tickStats();
    this.publish("config", "proxy");
    return result;
  }

  private addProxyNode(body: DemoBody): unknown {
    const node = this.proxy.addNode(
      textField(body, "link").trim(),
      this.word("new_exit"),
    );
    window.setTimeout(() => {
      this.proxy.measure(node.id);
      this.publish("nodes", node.id);
    }, NODE_FIRST_MEASURE_MS);
    return node;
  }

  private removeProxyNode(nodeId: string): NodesResponse {
    const nodes = this.proxy.removeNode(nodeId);
    this.tickStats();
    return nodes;
  }

  private async testProxyNodes(nodeId: string): Promise<NodesResponse> {
    await delay(NODE_MEASURE_MS);
    this.proxy.measure(nodeId);
    this.tickStats();
    return this.proxy.nodesView();
  }

  private frameReadings(): DemoFrameReadings {
    const mode = this.network.currentMode();
    return {
      ...this.proxy.readings(mode),
      network_mode: mode,
      interface_name: this.network.uplinkName(),
    };
  }

  private authState(): AuthState {
    return {
      lockout_remaining_s: 0,
      is_authenticated: this.isSignedIn,
      panel_started_at: "demo",
      https_listen_port: DEMO_HTTPS.https_listen_port,
    };
  }

  private device(deviceId: string): DemoDevice {
    return (
      this.devices.find((device) => device.id === deviceId) ?? {
        id: deviceId,
        name: "",
        icon: null,
        address: "",
        mac: "",
        isOnline: false,
        hostname: "",
        platformOs: "linux",
        platformArch: "amd64",
        lastSeen: null,
        metricsSeed: 0,
        modules: modulesWith([]),
      }
    );
  }

  private onlineCount(): number {
    return this.devices.filter((device) => device.isOnline).length;
  }

  private deviceView(device: DemoDevice): DeviceView {
    return {
      id: device.id,
      name: device.name,
      icon: device.icon,
      ipv4_address: device.address,
      link_mac: device.mac,
      is_agent_online: device.isOnline,
      ssh: null,
      client: {
        version: DEMO_HUB_VERSION,
        platform_os: device.platformOs,
        platform_arch: device.platformArch,
        hostname: device.hostname,
        last_report_at: device.isOnline ? secondsAgo(2) : device.lastSeen,
        last_seen: device.lastSeen,
        is_version_mismatched: false,
        metrics: demoMetrics(device.metricsSeed),
        last_error: null,
      },
    };
  }

  /** The AI gateway's state, with the default model a visitor picked. */
  private aiStatus(): CliproxyApiStatusView {
    return { ...DEMO_AI_STATUS, default_model: this.defaultModel };
  }

  private deviceList(): DevicesResponse {
    return {
      devices: this.devices.map((device) => this.deviceView(device)),
      count: { total: this.devices.length, online: this.onlineCount() },
    };
  }

  private moduleRow(
    device: DemoDevice,
    spec: DemoModuleSpec,
  ): DeviceModuleView {
    const held = device.modules[spec.name] ?? moduleState("absent");
    return {
      name: spec.name,
      title: spec.title,
      method: spec.method,
      source: DEMO_SOURCE[spec.method] ?? "upstream",
      kind: "service",
      want: held.want,
      state: held.state,
      is_active: held.state === "running",
      is_data_forward_only: FORWARD_ONLY_MODULES.has(spec.name),
      version: held.state === "absent" ? "" : spec.version,
      code: "",
      params: {},
      details: {},
      is_supported: true,
      is_carried: spec.isCarried,
      is_shown: held.isShown,
      uninstall_data: spec.uninstallData,
      requires: spec.requires,
      is_configured: held.state !== "absent",
      is_without_accounts: false,
      task: held.task,
      step: null,
      task_id: "",
    };
  }

  private moduleList(deviceId: string): DeviceModuleListView {
    const device = this.device(deviceId);
    return {
      modules: DEMO_MODULES.map((spec) => this.moduleRow(device, spec)),
      is_agent_online: device.isOnline,
      memory_need: null,
    };
  }

  private moduleCatalog(deviceId: string): ModuleCatalogView {
    const device = this.device(deviceId);
    return {
      categories: DEMO_MODULE_CATEGORIES,
      modules: DEMO_MODULES.map((spec) => ({
        name: spec.name,
        title: spec.title,
        category: spec.category,
        is_available: true,
        is_supported: true,
        is_carried: spec.isCarried,
        is_shown: device.modules[spec.name]?.isShown ?? false,
        state: device.modules[spec.name]?.state ?? "absent",
        requires: spec.requires,
      })),
    };
  }

  private moduleDeviceState(
    device: DemoDevice,
    name: string,
  ): ModuleDeviceState {
    const held = device.modules[name] ?? moduleState("absent");
    return {
      is_online: device.isOnline,
      state: held.state,
      code: "",
      params: {},
      task: held.task,
    };
  }

  private moduleView(deviceId: string, name: string): unknown {
    const device = this.device(deviceId);
    if (name === "gitea") {
      return this.giteaView(device);
    }
    if (name === "podman") {
      return this.podmanView(device);
    }
    if (name === "remote_desktop") {
      return this.remoteDesktopView(device);
    }
    if (name === "ayakaleaf") {
      return this.ayakaleafView(device);
    }
    return this.accountsView(device, name);
  }

  private accountsView(device: DemoDevice, name: string): EnabledAccountsView {
    const state = this.moduleDeviceState(device, name);
    const spec = demoModule(name);
    return {
      ...state,
      device_id: device.id,
      accounts: [
        {
          account: DEMO_ACCOUNT,
          is_enabled: true,
          port: spec?.web?.port ?? 0,
          is_running: state.state === "running",
          code: "",
          params: {},
          shell_path: "",
          share_path: "",
          user: DEMO_ACCOUNT,
          host_key_fingerprint: "SHA256:demo-host-key-of-a-made-up-system",
        },
      ],
      is_terms_accepted: device.modules[name]?.isTermsAccepted ?? false,
      terms_url: "https://code.visualstudio.com/license",
      version: spec?.version ?? "",
    };
  }

  private giteaView(device: DemoDevice): GiteaDeviceView {
    const state = this.moduleDeviceState(device, "gitea");
    const isPresent = state.state !== "absent";
    return {
      ...state,
      listen_port: 3000,
      root_url: "",
      is_registration_enabled: false,
      is_installed: isPresent,
      is_active: state.state === "running",
      version: demoModule("gitea")?.version ?? "",
      has_admin: isPresent,
      admin_usernames: isPresent ? [DEMO_ACCOUNT] : [],
    };
  }

  private podmanView(device: DemoDevice): PodmanDeviceView {
    const state = this.moduleDeviceState(device, "podman");
    const isOnMachine = device.platformOs !== "linux";
    const isRunning = state.state === "running";
    return {
      ...state,
      containers: [
        {
          name: "blog",
          image: "docker.io/library/nginx:1.27",
          ports: ["8088:80"],
          volumes: ["blog_data:/usr/share/nginx/html"],
          environment: [],
          command: "",
          is_autostart: true,
          services: [
            { port: 8088, kind: "auto", scheme: "http", protocols: ["tcp"] },
          ],
        },
      ],
      hub_containers: [],
      mirrors: [],
      running: isRunning
        ? [
            {
              name: "blog",
              image: "docker.io/library/nginx:1.27",
              status: "running",
              is_running: true,
              code: "",
              params: {},
              source: "declared",
              module: "",
              host_bindings: [
                { address: "", port: 8088, protocol: "tcp", detected: "http" },
              ],
            },
          ]
        : [],
      is_installed: state.state !== "absent",
      is_active: isRunning,
      version: demoModule("podman")?.version ?? "",
      accounts: [DEMO_ACCOUNT],
      machine: isOnMachine
        ? { account: DEMO_ACCOUNT, cpus: 4, memory_gib: 6, disk_gib: 60 }
        : null,
      machine_state: isOnMachine
        ? {
            account: DEMO_ACCOUNT,
            is_running: isRunning,
            cpus: 4,
            memory_gib: 6,
            disk_gib: 60,
            default_memory_gib: 4,
          }
        : null,
      memory_need: null,
    };
  }

  private remoteDesktopView(device: DemoDevice): RemoteDesktopDeviceView {
    return {
      ...this.moduleDeviceState(device, "remote_desktop"),
      device_id: device.id,
      host: device.address,
      is_enabled: true,
      platform_os: device.platformOs,
      rdp: {
        is_shared: device.isOnline,
        account: DEMO_ACCOUNT,
        port: 21118,
        attention: "",
        connected_count: 0,
        is_available: true,
      },
    };
  }

  private ayakaleafView(device: DemoDevice): AyakaleafDeviceView {
    return {
      ...this.moduleDeviceState(device, "ayakaleaf"),
      device_id: device.id,
      host: device.address,
      port: demoModule("ayakaleaf")?.web?.port ?? 0,
      model: "",
      models: DEMO_AI_STATUS.served_models ?? [],
      is_gateway_serving: true,
      version: demoModule("ayakaleaf")?.version ?? "",
      details: {},
    };
  }

  private sambaStatus(deviceId: string): SambaStatus {
    const device = this.device(deviceId);
    return {
      is_active: device.modules.samba?.state === "running",
      sessions: [],
      disks: [
        {
          share: DEMO_ACCOUNT,
          total_bytes: 1_000_000_000_000,
          free_bytes: 412_000_000_000,
        },
      ],
    };
  }

  private folderShares(): FolderShareListView {
    return {
      shares: [
        {
          name: sample("照片", "Photos"),
          path: "/data/photos",
          accounts: [DEMO_ACCOUNT],
        },
      ],
      accounts: [DEMO_ACCOUNT],
    };
  }

  private fileList(path: string): DeviceFileListView {
    const names = ["data", "home", "projects"];
    return {
      path,
      separator: "/",
      entries: names.map((name) => ({
        name,
        path: `${path.replace(/\/$/, "")}/${name}`,
        is_dir: true,
        is_link: false,
        size_bytes: 4096,
        modified_at: Date.now() / 1000 - 86400,
      })),
    };
  }

  private moduleVersion(deviceId: string, name: string): ModuleVersionView {
    const version = demoModule(name)?.version ?? "";
    const device = this.device(deviceId);
    const isPresent =
      device.modules[name] !== undefined &&
      device.modules[name]?.state !== "absent";
    return {
      installed: isPresent ? version : "",
      chosen: "",
      tested: version,
      newest: version,
      is_locked: false,
      versions: [
        {
          version,
          is_tested: true,
          is_untested: false,
          is_older_than_run: false,
        },
      ],
      is_data_forward_only: FORWARD_ONLY_MODULES.has(name),
      newest_run: isPresent ? version : "",
      read_at: secondsAgo(3600),
    };
  }

  private moduleJournal(deviceId: string, name: string): string {
    const held = this.device(deviceId).modules[name];
    if (held === undefined || held.state === "absent") {
      return "";
    }
    const stamp = new Date().toISOString().slice(0, 19).replace("T", " ");
    return [
      `${stamp} ${name}: started by neutrino_agent`,
      `${stamp} ${name}: ${JOURNAL_NOW_LINE}`,
    ].join("\n");
  }

  private setDevice(body: DemoBody): DevicesResponse {
    const device = this.device(textField(body, "device_id"));
    if (typeof body.name === "string" && body.name !== "") {
      device.name = body.name;
    }
    if (typeof body.icon === "string") {
      device.icon = body.icon;
    }
    if (Array.isArray(body.shown_module)) {
      const shown = body.shown_module as string[];
      for (const spec of DEMO_MODULES) {
        const held = device.modules[spec.name];
        if (held !== undefined && !spec.isCarried && held.state === "absent") {
          held.isShown = shown.includes(spec.name);
        }
      }
    }
    this.publish("devices", device.id);
    this.publish("device_report", device.id);
    return this.deviceList();
  }

  private createDeviceLink(body: DemoBody): unknown {
    const name = textField(body, "name");
    this.serial += 1;
    const link = `neutrino://enroll/demo-agent-${this.serial}`;
    window.setTimeout(() => this.addDevice(name), JOIN_DELAY_MS);
    return { link, token: `demo-${this.serial}`, expires_in_s: LINK_LIFE_S };
  }

  private addDevice(name: string): void {
    const number = this.devices.length + 1;
    this.devices.push({
      id: `dev_new_${number}`,
      name: name === "" ? `${this.word("new_machine")} ${number}` : name,
      icon: "desktop",
      address: `192.168.1.${50 + number}`,
      mac: `52:54:00:12:34:${50 + number}`,
      isOnline: true,
      hostname: `machine-${number}`,
      platformOs: "linux",
      platformArch: "amd64",
      lastSeen: null,
      metricsSeed: number,
      modules: modulesWith([]),
    });
    this.publish("devices", "");
    this.notify(
      this.word("device_joined", {
        name: name === "" ? this.word("new_machine") : name,
      }),
    );
  }

  private pressModule(
    body: DemoBody,
    action: "install" | "start" | "stop" | "uninstall",
  ): DeviceModuleListView {
    const device = this.device(textField(body, "device_id"));
    const name = textField(body, "module");
    const spec = demoModule(name);
    const held = device.modules[name];
    if (spec === null || held === undefined) {
      return this.moduleList(device.id);
    }
    if (action === "install") {
      this.installRequired(device, spec);
      held.isShown = true;
      this.runTask(device, spec, "installing", spec.installSteps, "installed");
    } else if (action === "start" && held.state === "running") {
      held.want = "running";
    } else if (action === "start") {
      this.runTask(
        device,
        spec,
        "queued",
        [{ name: "start", params: {} }],
        "running",
      );
    } else if (action === "stop") {
      this.runTask(
        device,
        spec,
        "queued",
        [{ name: "stop", params: {} }],
        "stopped",
      );
    } else {
      this.runTask(
        device,
        spec,
        "uninstalling",
        [{ name: "uninstall", params: {} }],
        "absent",
      );
    }
    return this.moduleList(device.id);
  }

  private installRequired(device: DemoDevice, spec: DemoModuleSpec): void {
    for (const name of spec.requires) {
      const required = demoModule(name);
      const held = device.modules[name];
      if (required !== null && held !== undefined && held.state === "absent") {
        held.isShown = true;
        this.runTask(
          device,
          required,
          "installing",
          required.installSteps,
          "running",
        );
      }
    }
  }

  private runTask(
    device: DemoDevice,
    spec: DemoModuleSpec,
    busyState: string,
    steps: ModuleTask["steps"],
    endState: string,
  ): void {
    const held = device.modules[spec.name];
    if (held === undefined) {
      return;
    }
    held.state = busyState;
    held.want = endState === "absent" ? "" : endState;
    held.task = {
      steps,
      index: 1,
      wait: { code: "", params: {} },
      is_running: true,
    };
    this.publish("device_report", device.id);
    const timer = window.setInterval(() => {
      const task = held.task;
      if (task === null) {
        window.clearInterval(timer);
        return;
      }
      if (task.index < steps.length) {
        held.task = { ...task, index: task.index + 1 };
        this.publish("device_report", device.id);
        return;
      }
      window.clearInterval(timer);
      held.task = { ...task, is_running: false };
      held.state = endState;
      this.publish("device_report", device.id);
      this.publish("task", spec.name);
      this.publish("services", "");
      this.publish("clients", "");
      if (endState === "running") {
        this.noteRunning(spec);
      }
    }, STEP_MS);
  }

  private noteRunning(spec: DemoModuleSpec): void {
    if (spec.web === null) {
      return;
    }
    const title = moduleWebTitle(spec.web, this.settings.language).replace(
      " ({account})",
      "",
    );
    this.notify(this.word("module_running", { title }));
  }

  private setVscodeTerms(body: DemoBody): EnabledAccountsView {
    const device = this.device(textField(body, "device_id"));
    const held = device.modules.vscode;
    if (held !== undefined) {
      held.isTermsAccepted = body.is_accepted === true;
    }
    this.publish("config", "vscode");
    return this.accountsView(device, "vscode");
  }

  private appId(device: DemoDevice, spec: DemoModuleSpec): string {
    return spec.web?.isPerAccount === true
      ? `${spec.name}_${device.id}_${DEMO_ACCOUNT}`
      : `${spec.name}_${device.id}`;
  }

  private composeApps(language: string): AppView[] {
    const apps: AppView[] = [];
    for (const device of this.devices) {
      for (const spec of DEMO_MODULES) {
        const held = device.modules[spec.name];
        const isPublished =
          held !== undefined &&
          (held.state === "running" || held.state === "stopped");
        if (spec.web !== null && isPublished) {
          apps.push(
            this.moduleApp(device, spec, held.state === "running", language),
          );
        }
      }
      apps.push(this.sshApp(device));
    }
    for (const declared of this.declaredApps) {
      apps.push({
        id: declared.id,
        title: declared.title,
        source: "declared",
        device_id: "",
        device_name: "",
        local_name: `${declared.id.replace("declared_", "")}.hub.localhost`,
        description: declared.description,
        entries: declared.entries,
      });
    }
    return apps;
  }

  private moduleApp(
    device: DemoDevice,
    spec: DemoModuleSpec,
    isHealthy: boolean,
    language: string,
  ): AppView {
    const id = this.appId(device, spec);
    const title = (
      spec.web === null ? spec.title : moduleWebTitle(spec.web, language)
    ).replace("{account}", DEMO_ACCOUNT);
    const slug = spec.name.replace(/_/g, "-");
    const entryId = `${id}_web`;
    return {
      id,
      title,
      source: "module",
      device_id: device.id,
      device_name: device.name,
      local_name: `${slug}.${device.hostname}.localhost`,
      description: "",
      entries: [
        {
          id: entryId,
          name: "web",
          type: "web",
          payload: {
            url: `http://${device.address}:${spec.web?.port ?? 0}/`,
            is_token_required: spec.web?.isTokenRequired ?? false,
          },
          is_healthy: device.isOnline && isHealthy,
          local_port: localPort(entryId),
          detail_code: null,
          guest_login: spec.web?.guestLogin ?? "",
        },
      ],
    };
  }

  private sshApp(device: DemoDevice): AppView {
    const id = `ssh_server_${device.id}`;
    const entryId = `${id}_${DEMO_ACCOUNT}`;
    return {
      id,
      title: `SSH (${DEMO_ACCOUNT})`,
      source: "module",
      device_id: device.id,
      device_name: device.name,
      local_name: `ssh.${device.hostname}.localhost`,
      description: "",
      entries: [
        {
          id: entryId,
          name: DEMO_ACCOUNT,
          type: "ssh",
          payload: {
            host: device.address,
            port: 22,
            account: DEMO_ACCOUNT,
            host_key_fingerprint: "SHA256:demo-host-key-of-a-made-up-machine",
          },
          is_healthy: device.isOnline,
          local_port: localPort(entryId),
          detail_code: null,
          guest_login: "",
        },
      ],
    };
  }

  private composeServices(language: string): PublishedService[] {
    const services: PublishedService[] = [
      {
        id: "ai_gateway",
        type: "ai",
        title: demoWord(language, "ai_gateway"),
        payload: {
          endpoint: `http://${DEMO_HUB_ADDRESS}:${DEMO_AI_STATUS.listen_port}`,
          models: DEMO_AI_STATUS.served_models,
        },
        is_healthy: true,
        source: "module",
        description: "",
        description_code: "ai_gateway",
        description_params: {},
        device_id: "",
        device_name: "",
      },
    ];
    for (const device of this.devices) {
      services.push({
        id: `rdp_${device.id}`,
        type: "rdp",
        title: demoWord(language, "device_desktop", { device: device.name }),
        payload: {
          host: device.address,
          port: 21118,
          platform_os: device.platformOs,
          attention: "",
        },
        is_healthy: device.isOnline,
        source: "device",
        description: "",
        description_code: "device_share",
        description_params: { device: device.name },
        device_id: device.id,
        device_name: device.name,
      });
      if (device.modules.samba?.state === "running") {
        services.push({
          id: `samba_${device.id}_${DEMO_ACCOUNT}`,
          type: "file",
          title: DEMO_ACCOUNT,
          payload: {
            host: device.address,
            port: 445,
            protocol: "smb",
            share: DEMO_ACCOUNT,
            users: [DEMO_ACCOUNT],
          },
          is_healthy: device.isOnline,
          source: "module",
          description: "",
          description_code: "samba_module",
          description_params: { host: device.name },
          device_id: device.id,
          device_name: device.name,
        });
      }
    }
    return services;
  }

  private clientList(): ClientListView {
    return {
      clients: this.clients,
      default_permission: this.defaultPermission,
      default_permission_devices: this.defaultPermissionDevices,
      default_permission_entries: this.defaultPermissionEntries,
      permission_kinds: PERMISSION_KINDS,
      permission_rows: this.permissionRows(),
      web_shares: this.shares,
      web_share_entries: this.webShareEntries(),
      web_share_sites: [{ url: SHARE_SITE, title: "Neutrino" }],
    };
  }

  private permissionRows(): Record<string, PermissionRowView[]> {
    const rows: Record<string, PermissionRowView[]> = {};
    for (const kind of ROW_KINDS) {
      rows[kind] = [];
    }
    const add = (
      kind: string,
      id: string,
      title: string,
      deviceId: string,
      deviceName: string,
    ) => {
      rows[kind]?.push({
        id,
        title,
        device_id: deviceId,
        device_name: deviceName,
      });
    };
    for (const app of this.composeApps(this.settings.language)) {
      for (const entry of app.entries) {
        add(entry.type, app.id, app.title, app.device_id, app.device_name);
      }
    }
    for (const service of this.composeServices(this.settings.language)) {
      if (service.type !== "ai") {
        add(
          service.type,
          service.id,
          service.title,
          service.device_id,
          service.device_name,
        );
      }
    }
    for (const device of this.devices) {
      add("terminal", device.id, device.name, device.id, device.name);
    }
    return rows;
  }

  private webShareEntries(): WebShareEntryView[] {
    const entries: WebShareEntryView[] = [];
    for (const app of this.composeApps(this.settings.language)) {
      for (const entry of app.entries) {
        if (entry.type === "web" && entry.is_healthy === true) {
          entries.push({
            entry_id: entry.id,
            app_id: app.id,
            title: app.title,
            device_name: app.device_name,
            guest_login: entry.guest_login === "" ? "app" : entry.guest_login,
            visitor_account:
              entry.guest_login === "run_account" ? DEMO_ACCOUNT : "",
          });
        }
      }
    }
    return entries;
  }

  private addFirstShare(): void {
    const entry = this.webShareEntries().find(
      (row) => row.app_id === "gitea_dev_desktop",
    );
    if (entry !== undefined) {
      this.shares.push(
        this.shareRow(
          "share_first",
          sample("给同事看的仓库", "Repository for a colleague"),
          entry,
          5,
          "active",
        ),
      );
    }
  }

  private shareRow(
    id: string,
    name: string,
    entry: WebShareEntryView,
    days: number | null,
    state: WebShareView["state"],
  ): WebShareView {
    const lifeS = days === null ? null : days * 86400;
    return {
      id,
      name,
      app_id: entry.app_id,
      entry_id: entry.entry_id,
      app_title: entry.title,
      device_name: entry.device_name,
      expires_at: lifeS === null ? null : secondsAgo(-lifeS),
      expires_in_s: lifeS,
      state,
      code: "",
      params: {},
      online_count: 0,
      guest_email:
        entry.guest_login === "guest_account" ? "guest@example.com" : "",
    };
  }

  private createShare(body: DemoBody): WebShareCreatedView {
    const entryId = textField(body, "entry_id");
    const entry = this.webShareEntries().find(
      (row) => row.entry_id === entryId,
    );
    if (entry === undefined) {
      throw new Error(`no entry ${entryId}`);
    }
    this.serial += 1;
    const id = `share_${this.serial}`;
    const days = typeof body.days === "number" ? body.days : null;
    const share = this.shareRow(
      id,
      textField(body, "name"),
      entry,
      days,
      "preparing",
    );
    this.shares.unshift(share);
    this.publish("clients", id);
    window.setTimeout(() => {
      share.state = "active";
      this.publish("clients", id);
    }, SHARE_PREPARE_MS);
    const site = textField(body, "site") || SHARE_SITE;
    return { link: `${site}/#demo-share-${this.serial}`, share };
  }

  private destroyShare(body: DemoBody): ClientListView {
    const at = this.shares.findIndex(
      (share) => share.id === textField(body, "share_id"),
    );
    if (at >= 0) {
      this.shares.splice(at, 1);
    }
    this.publish("clients", "");
    return this.clientList();
  }

  private createClientLink(body: DemoBody): unknown {
    const name = textField(body, "name");
    this.serial += 1;
    const id = `client_${this.serial}`;
    const link = `neutrino://enroll/demo-client-${this.serial}`;
    this.clients.push({
      id,
      name,
      hostname: "",
      platform_os: "",
      version: "",
      is_online: false,
      last_seen: null,
      is_disabled: false,
      permission: null,
      permission_devices: {},
      permission_entries: {},
      link_expires_in_s: LINK_LIFE_S,
    });
    this.clientLinks.set(link, id);
    this.publish("clients", id);
    window.setTimeout(() => this.finishJoin(id, "my-tablet"), JOIN_DELAY_MS);
    return {
      link,
      client_id: id,
      expires_at: secondsAgo(-LINK_LIFE_S),
      expires_in_s: LINK_LIFE_S,
    };
  }

  private finishJoin(clientId: string, hostname: string): void {
    const client = this.clientRow(clientId);
    if (client === null || client.link_expires_in_s === null) {
      return;
    }
    client.hostname = hostname;
    client.platform_os = "android";
    client.version = DEMO_HUB_VERSION;
    client.is_online = true;
    client.link_expires_in_s = null;
    this.publish("clients", clientId);
    this.notify(this.word("client_joined", { name: client.name }));
  }

  private setClientOff(body: DemoBody, isDisabled: boolean): ClientListView {
    const client = this.clientRow(textField(body, "client_id"));
    if (client !== null) {
      client.is_disabled = isDisabled;
    }
    this.publish("clients", "");
    return this.clientList();
  }

  private renameClient(body: DemoBody): ClientListView {
    const client = this.clientRow(textField(body, "client_id"));
    if (client !== null) {
      client.name = textField(body, "name");
    }
    this.publish("clients", "");
    return this.clientList();
  }

  private removeClient(body: DemoBody): ClientListView {
    const at = this.clients.findIndex(
      (client) => client.id === textField(body, "client_id"),
    );
    if (at >= 0) {
      this.clients.splice(at, 1);
    }
    this.publish("clients", "");
    return this.clientList();
  }

  private setClientPermission(body: DemoBody): ClientListView {
    const client = this.clientRow(textField(body, "client_id"));
    if (client !== null) {
      client.permission = Array.isArray(body.kinds)
        ? (body.kinds as string[])
        : null;
      client.permission_devices =
        (body.devices as Record<string, string[]> | null) ?? {};
      client.permission_entries =
        (body.entries as Record<string, boolean> | null) ?? {};
    }
    this.publish("clients", "");
    return this.clientList();
  }

  private setDefaultPermission(body: DemoBody): ClientListView {
    this.defaultPermission = Array.isArray(body.kinds)
      ? (body.kinds as string[])
      : [];
    this.defaultPermissionDevices =
      (body.devices as Record<string, string[]> | null) ?? {};
    this.defaultPermissionEntries =
      (body.entries as Record<string, boolean> | null) ?? {};
    this.publish("clients", "");
    return this.clientList();
  }

  private declareApp(request: DeclaredAppCreate): ServiceListView {
    this.serial += 1;
    const id = `declared_${this.serial}`;
    this.declaredApps.push({
      id,
      title: request.name,
      host: request.host,
      description: request.description,
      entries: request.entries.map((entry, at) => {
        const entryId = `${id}_${at}`;
        return {
          id: entryId,
          name: entry.type === "web" ? "web" : `port_${at}`,
          type: entry.type,
          payload:
            entry.type === "web"
              ? {
                  url: `${entry.scheme ?? "http"}://${request.host}:${entry.port ?? 80}${entry.path ?? "/"}`,
                }
              : entry.type === "file"
                ? {
                    host: request.host,
                    port: 445,
                    protocol: "smb",
                    share: entry.share ?? "",
                  }
                : {
                    host: request.host,
                    port: entry.port ?? 0,
                    protocol: entry.protocol ?? "tcp",
                  },
          is_healthy: true,
          local_port: entry.type === "file" ? 0 : localPort(entryId),
          detail_code: null,
          guest_login: entry.type === "web" ? "app" : "",
        };
      }),
    });
    this.publish("services", "");
    return this.serviceList();
  }

  private removeDeclaredApp(body: DemoBody): ServiceListView {
    const at = this.declaredApps.findIndex(
      (app) => app.id === textField(body, "app_id"),
    );
    if (at >= 0) {
      this.declaredApps.splice(at, 1);
    }
    this.publish("services", "");
    return this.serviceList();
  }

  private setSettings(body: DemoBody): SettingsView {
    this.settings = {
      ...this.settings,
      hub_name: textField(body, "hub_name") || this.settings.hub_name,
      language: textField(body, "language") || this.settings.language,
      theme: textField(body, "theme") || this.settings.theme,
    };
    this.publish("config", "web/settings.json");
    return this.settings;
  }

  private overlayChoice(): OverlayChoiceView {
    return { kinds: this.overlayKinds, route_conflicts: [] };
  }

  private setOverlays(body: DemoBody): OverlayChoiceView {
    for (const kind of this.overlayKinds) {
      const change = body[kind.key] as { is_enabled?: boolean } | undefined;
      if (change?.is_enabled !== undefined) {
        kind.is_enabled = change.is_enabled;
        kind.is_active = change.is_enabled;
      }
    }
    this.publish("config", "overlay");
    return this.overlayChoice();
  }

  private event(type: string, key: string, data?: unknown): DemoHubEvent {
    return { type, key, at: new Date().toISOString(), data };
  }

  private publish(type: string, key: string): void {
    const frame = this.event(type, key);
    for (const send of this.eventSenders) {
      send(frame);
    }
    for (const listener of this.changeListeners) {
      listener();
    }
  }

  private tickStats(): void {
    const frame = this.stats.frame(
      0,
      this.appsInUse,
      this.onlineCount(),
      this.frameReadings(),
    );
    this.statFrames.push(frame);
    this.statFrames.shift();
    for (const send of this.statSenders) {
      send(frame);
    }
  }

  /** Sends a machine page that just opened its monitor's recent readings. */
  private sendMetricsBacklog(deviceId: string): void {
    const device = this.device(deviceId);
    const now = Date.now() / 1000;
    const sentAt = this.metricsSentAt.get(deviceId) ?? 0;
    if (!device.isOnline || now - sentAt < METRICS_BACKLOG_PAUSE_S) {
      return;
    }
    this.metricsSentAt.set(deviceId, now);
    for (let at = METRICS_BACKLOG; at > 0; at -= 1) {
      const frame = this.event(
        "metrics",
        deviceId,
        demoMetrics(device.metricsSeed, at * 3),
      );
      for (const send of this.eventSenders) {
        send(frame);
      }
    }
  }

  private tickMetrics(): void {
    const nodesMoved = this.event("nodes", "");
    for (const send of this.eventSenders) {
      send(nodesMoved);
    }
    for (const device of this.devices) {
      if (!device.isOnline) {
        continue;
      }
      const frame = this.event(
        "metrics",
        device.id,
        demoMetrics(device.metricsSeed),
      );
      for (const send of this.eventSenders) {
        send(frame);
      }
    }
  }
}
