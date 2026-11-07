import qrcode from "qrcode-generator";

import { textField } from "./demo_hub";
import type { DemoHub } from "./demo_hub";
import {
  DEMO_AGENT_PORT,
  DEMO_HUB_ADDRESS,
  DEMO_HUB_VERSION,
  DEMO_LAB_APP_ID,
  DEMO_LAB_APP_PORT,
  DEMO_LAB_APP_TITLE,
  DEMO_LAB_DEVICE_HOSTNAME,
  DEMO_LAB_DEVICE_ID,
  DEMO_LAB_HUB_ADDRESS,
  DEMO_LAB_HUB_ID,
  DEMO_LAB_METRICS_SEED,
  DEMO_NETBIRD_ADDRESS,
  DEMO_SAMPLE_HUB_LINK,
  sample,
} from "./demo_fixtures";
import { DEMO_ACCOUNT } from "./demo_modules";
import { DemoShell } from "./demo_shell";
import { demoWord } from "./demo_words";
import type { DemoWordKey } from "./demo_words";

/**
 * The fake core of the client page: the one state document the page draws,
 * and the page's routes over it. It reads the fake hub and writes back what a
 * real client's actions would move on the hub.
 */

const DEMO_HUB_ID = "hub_home";
const JOB_MS = 700;
const OVERLAY_CONNECT_MS = 1800;
const MOUNT_MS = 1400;
const RTT_MS = 3;
const LAB_RTT_MS = 18;
const LAB_CONNECT_MS = 1400;
const SHELL_OPEN_MS = 120;
const CLEAR_QUIET_MS = 500;
const TERMINAL_KEPT_CHARS = 100_000;
const TERMINAL_FONT_DEFAULT = 13;
const TERMINAL_FONT_MIN = 8;
const TERMINAL_FONT_MAX = 24;

/** The running state of an app, by app id. */
interface DemoAppRun {
  job: string;
  isInUse: boolean;
  ports: Record<string, number>;
}

/** A share mounted or being mounted. */
interface DemoMount {
  record_id: string;
  hub_id: string;
  entry_id: string;
  path: string;
  state: string;
  is_attached: boolean;
  code: string;
  params: Record<string, unknown>;
}

interface DemoOverlay {
  network: string;
  state: "off" | "on";
  address: string;
  job: string;
}

/** A shell the page has open. A viewer's own shell is listed nowhere. */
interface DemoTerminal {
  terminalId: string;
  sessionId: string;
  hubId: string;
  deviceId: string;
  title: string;
  isViewer: boolean;
  isPersistent: boolean;
  isShared: boolean;
  isDropping: boolean;
  kept: string;
  shell: DemoShell;
}

/** A request the page sends, as its bridge passes it on. */
export interface DemoClientRequest {
  path: string;
  body: Record<string, unknown> | null;
}

type DemoStateListener = (state: unknown) => void;

function base64(text: string): string {
  let binary = "";
  for (const byte of new TextEncoder().encode(text)) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

export class DemoClientCore {
  private readonly listeners = new Set<DemoStateListener>();
  private readonly runs = new Map<string, DemoAppRun>();
  private readonly mounts: DemoMount[] = [];
  private readonly terminals = new Map<string, DemoTerminal>();
  private readonly desktopJobs = new Map<string, string>();
  private readonly openViewers = new Set<string>();
  private readonly overlay: DemoOverlay = {
    network: "netbird",
    state: "off",
    address: "",
    job: "",
  };
  private clientId: string;
  private isJoined = true;
  private isLabJoined = false;
  private isLabConnected = false;
  private isLabLeaving = false;
  private isRefreshing = false;
  private isLeaving = false;
  private isExit = false;
  private language = "zh-CN";
  private theme = "light";
  private serial = 0;
  private clipboard = "";
  private terminalFontSize = TERMINAL_FONT_DEFAULT;

  constructor(private readonly hub: DemoHub) {
    this.clientId = hub.firstClientId();
    hub.onChange(() => {
      this.dropGoneApps();
      this.push();
    });
  }

  /** Calls a listener with every new state document. */
  onState(listener: DemoStateListener): void {
    this.listeners.add(listener);
  }

  /**
   * Returns the reply to a request of the page.
   *
   * Args:
   *   request: The page's path and body.
   *
   * Returns:
   *   The whole state, or `{code}` for a refusal.
   */
  request(request: DemoClientRequest): unknown {
    const pathname = request.path.split("?")[0] ?? "";
    const body = request.body ?? {};
    switch (pathname) {
      case "/api/state":
        return this.state();
      case "/api/refresh":
        return this.refresh();
      case "/api/app/use":
        return this.useApp(textField(body, "app_id"));
      case "/api/app/stop":
        return this.stopApp(textField(body, "app_id"));
      case "/api/app/open":
        return this.openApp(textField(body, "app_id"));
      case "/api/app/set":
        return this.setPorts(body);
      case "/api/panel/open":
        this.notify("panel_notice");
        return this.state();
      case "/api/leave":
        return this.leave(textField(body, "hub_id"));
      case "/api/join":
        return this.join(textField(body, "link"));
      case "/api/overlay/pick":
        this.overlay.network = textField(body, "provider");
        return this.pushed();
      case "/api/overlay/connect":
        return this.connectOverlay();
      case "/api/overlay/cancel":
        this.overlay.job = "";
        return this.pushed();
      case "/api/overlay/disconnect":
        return this.disconnectOverlay();
      case "/api/services/rdp":
        return this.desktopAction(body);
      case "/api/services/file":
        return this.fileAction(body);
      case "/api/services/ai":
        return this.state();
      case "/api/exit/set":
        this.isExit = !this.isExit;
        return this.pushed();
      case "/api/settings/set":
        this.language = textField(body, "language") || this.language;
        this.theme = textField(body, "theme") || this.theme;
        return this.pushed();
      case "/api/terminal/open":
        return this.openTerminal(body);
      case "/api/terminal/input":
        return this.terminalInput(body);
      case "/api/terminal/resize":
        return this.terminalResize(body);
      case "/api/terminal/persist":
        return this.terminalPersist(body);
      case "/api/terminal/clear":
        return this.terminalClear(body);
      case "/api/terminal/close":
        return this.terminalClose(body);
      case "/api/terminal/stop":
        return this.terminalStop(body);
      case "/api/terminal/font":
        this.terminalFontSize = Math.max(
          TERMINAL_FONT_MIN,
          Math.min(TERMINAL_FONT_MAX, Number(body.size)),
        );
        return this.pushed();
      case "/api/clipboard":
        return this.clipboardRoute(request.body);
      case "/api/demo/sample_hub":
        return this.sampleHub();
      case "/api/font":
        return { code: "font_absent" };
      case "/api/fs":
        return { path: "/", dirs: ["remote"] };
      case "/api/open_link":
        window.open(textField(body, "url"), "_blank", "noopener");
        return {};
      default:
        return {};
    }
  }

  private state(): unknown {
    const client = this.hub.clientRow(this.clientId);
    const list = this.hub.serviceList(this.language);
    const isVisible = this.isJoined && client !== null;
    const isOverlayAllowed = this.hub.isAllowed(
      this.clientId,
      "overlay",
      "",
      "",
    );
    const networks = isOverlayAllowed
      ? this.hub.publishedOverlays().map((provider) => ({ provider }))
      : [];
    const apps = isVisible
      ? list.apps.filter((app) =>
          app.entries.some((entry) =>
            this.hub.isAllowed(
              this.clientId,
              entry.type,
              app.device_id,
              app.id,
            ),
          ),
        )
      : [];
    const appEntries = apps.flatMap((app) =>
      app.entries.map((entry) => {
        const run = this.runs.get(app.id);
        const port = run?.ports[entry.name] ?? entry.local_port;
        return {
          hub_id: DEMO_HUB_ID,
          id: entry.id,
          app_id: app.id,
          name: entry.name,
          type: entry.type,
          title: app.title,
          device_id: app.device_id,
          device_name: app.device_name,
          payload: entry.payload,
          is_healthy: entry.is_healthy,
          local_port: port,
          forward: run?.isInUse === true ? port : 0,
          job: "",
          last_error: null,
        };
      }),
    );
    const others = isVisible
      ? list.services
          .filter((service) =>
            this.hub.isAllowed(
              this.clientId,
              service.type,
              service.device_id,
              service.id,
            ),
          )
          .map((service) => ({
            hub_id: DEMO_HUB_ID,
            id: service.id,
            app_id: "",
            name: service.title,
            type: service.type,
            title: service.title,
            device_id: service.device_id,
            device_name: service.device_name,
            module: service.description_code,
            description_code: service.description_code,
            description_params: service.description_params,
            payload: service.payload,
            is_healthy: service.is_healthy,
            local_port: "auto",
            forward: 0,
            job: this.desktopJobs.get(service.id) ?? "",
            last_error: null,
            mount_default: `~/remote/${service.device_name}-${service.title}`,
          }))
      : [];
    return {
      version: DEMO_HUB_VERSION,
      carried_versions: {},
      edition: "cn",
      language: this.language,
      theme: this.theme,
      terminal_font_size: this.terminalFontSize,
      hostname: client?.name ?? sample("我的手机", "My phone"),
      platform: { os: "android", arch: "arm64" },
      mount_location_shape: "path",
      mount_location_suggestion: "~/remote",
      mount_location_choices: [],
      home: "~",
      is_ssh_include_enabled: false,
      notices: [],
      viewers: Object.fromEntries(
        [...this.openViewers].map((key) => [key, { is_running: true }]),
      ),
      ai: {},
      ai_tool_configs: {},
      hubs: [
        ...(this.isJoined ? [this.hubRow(client !== null, networks)] : []),
        ...(this.isLabJoined ? [this.labHubRow()] : []),
      ],
      apps: [
        ...this.labApps(),
        ...apps.map((app) => {
          const run = this.runs.get(app.id);
          return {
            hub_id: DEMO_HUB_ID,
            id: app.id,
            title: app.title,
            source: app.source,
            device_id: app.device_id,
            device_name: app.device_name,
            local_name: app.local_name,
            job: run?.job ?? "",
            last_error: null,
            is_in_use: run?.isInUse ?? false,
          };
        }),
      ],
      services: [...appEntries, ...others, ...this.labEntries()],
      mounts: this.mounts,
      terminals: {
        machines: this.machines(),
        sessions: this.sessions(),
      },
    };
  }

  private word(key: DemoWordKey): string {
    return demoWord(this.language, key);
  }

  private notify(key: DemoWordKey): void {
    this.hub.notify(this.word(key));
  }

  private machines(): {
    hub_id: string;
    device_id: string;
    name: string;
    is_online: boolean;
    accounts: string[];
    hostname: string;
    platform_os: string;
    address: string;
    metrics_seed: number;
  }[] {
    const own =
      this.isJoined && this.hub.clientRow(this.clientId) !== null
        ? this.hub
            .terminalMachines(this.clientId)
            .map((machine) => ({ ...machine, hub_id: DEMO_HUB_ID }))
        : [];
    const lab = this.isLabJoined
      ? [
          {
            hub_id: DEMO_LAB_HUB_ID,
            device_id: DEMO_LAB_DEVICE_ID,
            name: this.word("lab_machine_name"),
            is_online: true,
            accounts: [DEMO_ACCOUNT],
            hostname: DEMO_LAB_DEVICE_HOSTNAME,
            platform_os: "linux",
            address: DEMO_LAB_HUB_ADDRESS,
            metrics_seed: DEMO_LAB_METRICS_SEED,
          },
        ]
      : [];
    return [...own, ...lab];
  }

  private sessions(): Record<string, unknown>[] {
    const owner = this.hub.clientRow(this.clientId);
    return [...this.terminals.values()]
      .filter((terminal) => !terminal.isViewer)
      .map((terminal) => ({
        hub_id: terminal.hubId,
        session_id: terminal.sessionId,
        device_id: terminal.deviceId,
        owner: this.clientId,
        owner_name: owner?.name ?? "",
        is_owned: true,
        is_persistent: terminal.isPersistent,
        is_shared: terminal.isShared,
        attached_count: 1,
        title: terminal.title,
      }));
  }

  private labApps(): Record<string, unknown>[] {
    if (!this.isLabJoined) {
      return [];
    }
    const run = this.runs.get(DEMO_LAB_APP_ID);
    return [
      {
        hub_id: DEMO_LAB_HUB_ID,
        id: DEMO_LAB_APP_ID,
        title: DEMO_LAB_APP_TITLE,
        source: "module",
        device_id: DEMO_LAB_DEVICE_ID,
        device_name: this.word("lab_machine_name"),
        local_name: `jupyterlab.${DEMO_LAB_DEVICE_HOSTNAME}.localhost`,
        job: run?.job ?? "",
        last_error: null,
        is_in_use: run?.isInUse ?? false,
      },
    ];
  }

  private labEntries(): Record<string, unknown>[] {
    if (!this.isLabJoined) {
      return [];
    }
    const run = this.runs.get(DEMO_LAB_APP_ID);
    const port = run?.ports.web ?? DEMO_LAB_APP_PORT;
    return [
      {
        hub_id: DEMO_LAB_HUB_ID,
        id: `${DEMO_LAB_APP_ID}_web`,
        app_id: DEMO_LAB_APP_ID,
        name: "web",
        type: "web",
        title: DEMO_LAB_APP_TITLE,
        device_id: DEMO_LAB_DEVICE_ID,
        device_name: this.word("lab_machine_name"),
        payload: {
          url: `http://${DEMO_LAB_HUB_ADDRESS}:${DEMO_LAB_APP_PORT}/`,
          is_token_required: false,
        },
        is_healthy: true,
        local_port: port,
        forward: run?.isInUse === true ? port : 0,
        job: "",
        last_error: null,
      },
    ];
  }

  private labHubRow(): Record<string, unknown> {
    const connection = this.isLabConnected ? "connected" : "connecting";
    return {
      hub_id: DEMO_LAB_HUB_ID,
      binding_id: DEMO_LAB_HUB_ID,
      hub_name: this.word("lab_hub_name"),
      gateway_url: `https://${DEMO_LAB_HUB_ADDRESS}:${DEMO_AGENT_PORT}`,
      software: `neutrino_hub ${DEMO_HUB_VERSION}`,
      connection,
      wait_reason: "",
      reached_through: "direct",
      rtt_ms: this.isLabConnected ? LAB_RTT_MS : null,
      is_panel_allowed: false,
      panel_forward: "",
      last_error: null,
      is_exit: false,
      overlay: {
        network: "",
        networks: [],
        state: "off",
        stage: "",
        address: "",
        error: null,
      },
      jobs: {
        is_refreshing: this.isRefreshing,
        overlay_job: "",
        is_leaving: this.isLabLeaving,
        is_opening_panel: false,
      },
    };
  }

  private hubRow(
    isKnown: boolean,
    networks: { provider: string }[],
  ): Record<string, unknown> {
    const client = this.hub.clientRow(this.clientId);
    const isDisabled = client?.is_disabled ?? false;
    const connection = !isKnown
      ? "waiting"
      : isDisabled
        ? "disabled"
        : "connected";
    return {
      hub_id: DEMO_HUB_ID,
      binding_id: DEMO_HUB_ID,
      hub_name: this.hub.hubName(),
      gateway_url: `https://${DEMO_HUB_ADDRESS}:${DEMO_AGENT_PORT}`,
      software: `neutrino_hub ${DEMO_HUB_VERSION}`,
      connection,
      wait_reason: isKnown ? "" : "unknown_device",
      reached_through:
        this.overlay.state === "on" ? this.overlay.network : "lan",
      rtt_ms: connection === "connected" ? RTT_MS : null,
      is_panel_allowed:
        isKnown && this.hub.isAllowed(this.clientId, "panel", "", ""),
      panel_forward: "",
      last_error: null,
      is_exit: this.isExit,
      overlay: {
        network: this.overlay.network,
        networks,
        state: this.overlay.state,
        stage: this.overlay.job === "connecting" ? "login" : "",
        address: this.overlay.address,
        error: null,
      },
      jobs: {
        is_refreshing: this.isRefreshing,
        overlay_job: this.overlay.job,
        is_leaving: this.isLeaving,
        is_opening_panel: false,
      },
    };
  }

  private push(): void {
    const state = this.state();
    for (const listener of this.listeners) {
      listener(state);
    }
  }

  private pushed(): unknown {
    this.push();
    return this.state();
  }

  private run(appId: string): DemoAppRun {
    const held = this.runs.get(appId);
    if (held !== undefined) {
      return held;
    }
    const made: DemoAppRun = { job: "", isInUse: false, ports: {} };
    this.runs.set(appId, made);
    return made;
  }

  /** Drops the running state of an app the hub no longer publishes. */
  private dropGoneApps(): void {
    const published = new Set(this.hub.serviceList().apps.map((app) => app.id));
    published.add(DEMO_LAB_APP_ID);
    for (const appId of this.runs.keys()) {
      if (!published.has(appId)) {
        this.runs.delete(appId);
      }
    }
    this.noteAppsInUse();
  }

  private noteAppsInUse(): void {
    let count = 0;
    for (const run of this.runs.values()) {
      if (run.isInUse) {
        count += 1;
      }
    }
    this.hub.setAppsInUse(count);
  }

  private refresh(): unknown {
    this.isRefreshing = true;
    window.setTimeout(() => {
      this.isRefreshing = false;
      this.push();
    }, JOB_MS);
    return this.pushed();
  }

  private useApp(appId: string): unknown {
    const run = this.run(appId);
    run.job = "opening";
    window.setTimeout(() => {
      run.job = "";
      run.isInUse = true;
      this.noteAppsInUse();
      this.push();
    }, JOB_MS);
    return this.pushed();
  }

  private stopApp(appId: string): unknown {
    const run = this.run(appId);
    run.job = "disconnecting";
    window.setTimeout(() => {
      run.job = "";
      run.isInUse = false;
      this.noteAppsInUse();
      this.push();
    }, JOB_MS);
    return this.pushed();
  }

  private openApp(appId: string): unknown {
    const run = this.run(appId);
    run.job = "opening";
    window.setTimeout(() => {
      run.job = "";
      this.notify("open_notice");
      this.push();
    }, JOB_MS);
    return this.pushed();
  }

  private setPorts(body: Record<string, unknown>): unknown {
    const run = this.run(textField(body, "app_id"));
    const ports = (body.ports ?? {}) as Record<string, number | null>;
    for (const [name, port] of Object.entries(ports)) {
      if (port === null) {
        delete run.ports[name];
      } else {
        run.ports[name] = port;
      }
    }
    return this.pushed();
  }

  private leave(hubId: string): unknown {
    if (hubId === DEMO_LAB_HUB_ID) {
      return this.leaveLab();
    }
    this.isLeaving = true;
    window.setTimeout(() => {
      this.isLeaving = false;
      this.isJoined = false;
      this.endTerminalsOf(DEMO_HUB_ID);
      this.closeViewersOf(DEMO_HUB_ID);
      for (const appId of this.runs.keys()) {
        if (appId !== DEMO_LAB_APP_ID) {
          this.runs.delete(appId);
        }
      }
      this.mounts.length = 0;
      if (this.overlay.state === "on") {
        this.hub.noteOverlayClient(this.overlay.network, -1);
      }
      this.overlay.state = "off";
      this.overlay.address = "";
      this.overlay.job = "";
      this.noteAppsInUse();
      this.hub.setClientOnline(this.clientId, false);
      this.push();
    }, JOB_MS);
    return this.pushed();
  }

  private leaveLab(): unknown {
    this.isLabLeaving = true;
    window.setTimeout(() => {
      this.isLabLeaving = false;
      this.isLabJoined = false;
      this.isLabConnected = false;
      this.endTerminalsOf(DEMO_LAB_HUB_ID);
      this.runs.delete(DEMO_LAB_APP_ID);
      this.noteAppsInUse();
      this.push();
    }, JOB_MS);
    return this.pushed();
  }

  private joinLab(): unknown {
    this.isLabJoined = true;
    this.isLabConnected = false;
    window.setTimeout(() => {
      this.isLabConnected = true;
      this.push();
    }, LAB_CONNECT_MS);
    return this.pushed();
  }

  /** The sample hub's link and its QR code, as a path in module units. */
  private sampleHub(): unknown {
    const code = qrcode(0, "M");
    code.addData(DEMO_SAMPLE_HUB_LINK);
    code.make();
    const size = code.getModuleCount();
    let path = "";
    for (let row = 0; row < size; row += 1) {
      for (let column = 0; column < size; column += 1) {
        if (code.isDark(row, column)) {
          path += `M${column} ${row}h1v1h-1z`;
        }
      }
    }
    return {
      link: DEMO_SAMPLE_HUB_LINK,
      is_joined: this.isLabJoined,
      size,
      path,
    };
  }

  private join(link: string): unknown {
    if (link.trim() === DEMO_SAMPLE_HUB_LINK) {
      return this.joinLab();
    }
    const joined = this.hub.joinByLink(link);
    if (joined === null) {
      return {
        ...(this.state() as Record<string, unknown>),
        error: { code: "link_unreadable", params: {} },
      };
    }
    if (this.isJoined && joined !== this.clientId) {
      this.hub.setClientOnline(this.clientId, false);
    }
    this.clientId = joined;
    this.isJoined = true;
    return this.pushed();
  }

  private connectOverlay(): unknown {
    this.overlay.job = "connecting";
    window.setTimeout(() => {
      if (this.overlay.job !== "connecting") {
        return;
      }
      this.overlay.job = "";
      this.overlay.state = "on";
      this.overlay.address =
        this.overlay.network === "netbird"
          ? DEMO_NETBIRD_ADDRESS.replace(/\d+$/, "77")
          : "10.144.0.77";
      this.hub.noteOverlayClient(this.overlay.network, 1);
    }, OVERLAY_CONNECT_MS);
    return this.pushed();
  }

  private disconnectOverlay(): unknown {
    this.overlay.job = "disconnecting";
    window.setTimeout(() => {
      this.overlay.job = "";
      this.overlay.state = "off";
      this.overlay.address = "";
      this.hub.noteOverlayClient(this.overlay.network, -1);
    }, JOB_MS);
    return this.pushed();
  }

  private fileAction(body: Record<string, unknown>): unknown {
    const action = textField(body, "action");
    if (action === "open_in_files") {
      this.notify("open_notice");
      return this.state();
    }
    if (action === "mount") {
      return this.mount(body);
    }
    if (action === "unmount") {
      const record = this.mounts.find(
        (held) => held.record_id === textField(body, "record_id"),
      );
      if (record !== undefined) {
        record.state = "unmounting";
        window.setTimeout(() => {
          record.state = "detached";
          record.is_attached = false;
          this.push();
        }, JOB_MS);
      }
    }
    return this.pushed();
  }

  /**
   * Starts or ends a viewer: Connect reads the seat password and makes the
   * forward, and the viewer page opens once `viewers` names the entry.
   */
  private desktopAction(body: Record<string, unknown>): unknown {
    const hubId = textField(body, "hub_id");
    const entryId = textField(body, "id");
    const key = `${hubId}/${entryId}`;
    if (textField(body, "action") === "connect") {
      this.desktopJobs.set(entryId, "connecting");
      window.setTimeout(() => {
        this.desktopJobs.delete(entryId);
        this.openViewers.add(key);
        this.push();
      }, JOB_MS);
    } else {
      this.openViewers.delete(key);
    }
    return this.pushed();
  }

  private closeViewersOf(hubId: string): void {
    for (const key of this.openViewers) {
      if (key.startsWith(`${hubId}/`)) {
        this.openViewers.delete(key);
      }
    }
  }

  private openTerminal(body: Record<string, unknown>): unknown {
    const hubId = textField(body, "hub_id");
    const deviceId = textField(body, "device_id");
    const sessionId = textField(body, "session_id");
    const cols = Number(body.cols ?? 80);
    const rows = Number(body.rows ?? 24);
    const held = [...this.terminals.values()].find(
      (terminal) => terminal.sessionId === sessionId,
    );
    if (held !== undefined) {
      window.setTimeout(() =>
        this.sendPiece(held, { data: base64(held.kept) }),
      );
      return { terminal_id: held.terminalId, session_id: held.sessionId };
    }
    const machine = this.machines().find(
      (row) => row.hub_id === hubId && row.device_id === deviceId,
    );
    if (machine === undefined) {
      return { code: "hub_unreachable" };
    }
    this.serial += 1;
    const terminalId = `terminal_${this.serial}`;
    const terminal: DemoTerminal = {
      terminalId,
      sessionId: `session_${this.serial}`,
      hubId,
      deviceId,
      title: machine.name,
      isViewer: body.is_viewer === true,
      isPersistent: false,
      isShared: false,
      isDropping: false,
      kept: "",
      shell: new DemoShell(
        {
          hostname: machine.hostname,
          account: textField(body, "account") || DEMO_ACCOUNT,
          platformOs: machine.platform_os,
          address: machine.address,
          metricsSeed: machine.metrics_seed,
          language: this.language,
        },
        (text) => this.takeOutput(terminalId, text),
        () => this.endTerminal(terminalId),
      ),
    };
    this.terminals.set(terminalId, terminal);
    terminal.shell.resize(cols, rows);
    window.setTimeout(() => {
      terminal.shell.start();
      this.push();
    }, SHELL_OPEN_MS);
    return { terminal_id: terminalId, session_id: terminal.sessionId };
  }

  private terminalOf(body: Record<string, unknown>): DemoTerminal | undefined {
    return this.terminals.get(textField(body, "terminal_id"));
  }

  private sendPiece(
    terminal: DemoTerminal,
    piece: Record<string, unknown>,
  ): void {
    for (const listener of this.listeners) {
      listener({ terminal: { id: terminal.terminalId, ...piece } });
    }
  }

  private takeOutput(terminalId: string, text: string): void {
    const terminal = this.terminals.get(terminalId);
    if (terminal === undefined || terminal.isDropping) {
      return;
    }
    terminal.kept = (terminal.kept + text).slice(-TERMINAL_KEPT_CHARS);
    this.sendPiece(terminal, { data: base64(text) });
  }

  /** Ends a session whose shell ended, as `exit` or Ctrl+D ends it. */
  private endTerminal(terminalId: string): void {
    const terminal = this.terminals.get(terminalId);
    if (terminal === undefined) {
      return;
    }
    this.sendPiece(terminal, { end: {} });
    this.terminals.delete(terminalId);
    window.setTimeout(() => this.push());
  }

  private endTerminalsOf(hubId: string): void {
    for (const terminal of [...this.terminals.values()]) {
      if (terminal.hubId === hubId) {
        terminal.shell.stop();
        this.endTerminal(terminal.terminalId);
      }
    }
  }

  private terminalInput(body: Record<string, unknown>): unknown {
    const data = new TextDecoder().decode(
      Uint8Array.from(atob(textField(body, "data")), (character) =>
        character.charCodeAt(0),
      ),
    );
    this.terminalOf(body)?.shell.input(data);
    return {};
  }

  private terminalResize(body: Record<string, unknown>): unknown {
    this.terminalOf(body)?.shell.resize(
      Number(body.cols ?? 80),
      Number(body.rows ?? 24),
    );
    return {};
  }

  private terminalPersist(body: Record<string, unknown>): unknown {
    const terminal = this.terminalOf(body);
    if (terminal !== undefined) {
      terminal.isPersistent = body.is_persistent === true;
      terminal.isShared = body.is_shared === true;
      this.push();
    }
    return {};
  }

  /**
   * Clears as the page asks: Ctrl+C, and the output dropped until the stream
   * has been quiet.
   */
  private terminalClear(body: Record<string, unknown>): unknown {
    const terminal = this.terminalOf(body);
    if (terminal === undefined) {
      return {};
    }
    terminal.isDropping = true;
    this.sendPiece(terminal, { clearing: true });
    terminal.shell.interrupt();
    window.setTimeout(() => {
      terminal.isDropping = false;
      this.sendPiece(terminal, { clearing: false });
      terminal.shell.reprompt();
    }, CLEAR_QUIET_MS);
    return {};
  }

  private terminalClose(body: Record<string, unknown>): unknown {
    const terminal = this.terminalOf(body);
    if (terminal !== undefined) {
      terminal.shell.stop();
      this.terminals.delete(terminal.terminalId);
      window.setTimeout(() => this.push());
    }
    return {};
  }

  private terminalStop(body: Record<string, unknown>): unknown {
    const terminal = [...this.terminals.values()].find(
      (held) => held.sessionId === textField(body, "session_id"),
    );
    if (terminal !== undefined) {
      terminal.shell.stop();
      this.terminals.delete(terminal.terminalId);
    }
    return {};
  }

  /** The system clipboard as far as a page holds it: the last text it put. */
  private clipboardRoute(body: Record<string, unknown> | null): unknown {
    if (body === null) {
      return { text: this.clipboard || this.word("clipboard_sample") };
    }
    this.clipboard = textField(body, "text");
    return {};
  }

  private mountDefault(entryId: string): string {
    const service = this.hub
      .serviceList(this.language)
      .services.find((held) => held.id === entryId);
    return `~/remote/${service?.device_name ?? ""}-${service?.title ?? ""}`;
  }

  private mount(body: Record<string, unknown>): unknown {
    const recordId = textField(body, "record_id");
    let record = this.mounts.find((held) => held.record_id === recordId);
    if (record === undefined) {
      this.serial += 1;
      const entryId = textField(body, "id");
      record = {
        record_id: `mount_${this.serial}`,
        hub_id: DEMO_HUB_ID,
        entry_id: entryId,
        path: textField(body, "path") || this.mountDefault(entryId),
        state: "pending",
        is_attached: false,
        code: "",
        params: {},
      };
      this.mounts.push(record);
    }
    const held = record;
    held.state = "mounting";
    window.setTimeout(() => {
      held.state = "mounted";
      held.is_attached = true;
      this.push();
    }, MOUNT_MS);
    return this.pushed();
  }
}
