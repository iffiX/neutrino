import { nodeTagFromId } from "../hub/frontend/src/node_tag";
import { DEMO_GEODATA_RELEASE, secondsAgo } from "./demo_fixtures";
import type {
  ApplyResult,
  BalancerSettings,
  GeodataView,
  NetworkModeKey,
  NodeView,
  NodesResponse,
  ProxySettings,
  ProxyView,
  StatsFrame,
} from "../hub/frontend/src/api_types";

/**
 * The fake hub's proxy: two measured exits, the routing settings, and what a
 * press on the Proxy page changes. Nothing is carried and nothing is measured.
 */

/** The fields of a stats frame the proxy answers for. */
export type DemoProxyReadings = Pick<
  StatsFrame,
  | "outbounds"
  | "nodes"
  | "proxy_scope"
  | "exit_tag"
  | "exit_name"
  | "exit_since"
  | "enabled_node_count"
>;

/** A write the fake hub refuses, with the code the panel words. */
export class DemoRefusal extends Error {
  constructor(
    readonly code: string,
    readonly params: Record<string, string> = {},
  ) {
    super(code);
  }
}

const GIB = 1024 ** 3;
const SHARE_LINK_SCHEMES = /^(ss|vless):\/\//;
const NEW_NODE_FIRST_OCTET = 60;
const NEW_NODE_PORT = 443;
const NEW_NODE_MIN_CONNECT_MS = 90;
const NEW_NODE_CONNECT_SPREAD_MS = 80;
const REQUEST_PER_CONNECT = 4;
const REQUEST_EXTRA_MS = 60;
const CONNECT_JITTER = 0.2;
const EXIT_RX_BYTES_PER_S = 420_000;
const EXIT_TX_BYTES_PER_S = 80_000;
const STAT_INTERVAL_S = 1;

const SCOPE_OFF = "off";
const SCOPE_UNUSED = "unused";
const SCOPE_LAN = "lan";
const SCOPE_OVERLAY = "overlay";
const SCOPE_HUB = "hub";
const SCOPE_JOINER = "+";

function measuredNode(
  node: Pick<
    NodeView,
    | "id"
    | "name"
    | "address"
    | "port"
    | "protocol"
    | "has_reality"
    | "is_selected"
    | "connect_ms"
    | "request_ms"
    | "success_rate"
    | "uplink_bytes"
    | "downlink_bytes"
  >,
): NodeView {
  return {
    ...node,
    is_enabled: true,
    is_alive: true,
    probed_at: secondsAgo(40),
    score_ms: node.request_ms,
  };
}

function initialNodes(): NodeView[] {
  return [
    measuredNode({
      id: "tokyo-3f9a",
      name: "Tokyo 01",
      address: "203.0.113.41",
      port: 443,
      protocol: "vless",
      has_reality: true,
      is_selected: true,
      connect_ms: 38,
      request_ms: 186,
      success_rate: 1,
      uplink_bytes: 18 * GIB,
      downlink_bytes: 96 * GIB,
    }),
    measuredNode({
      id: "singapore-71c2",
      name: "Singapore 02",
      address: "203.0.113.57",
      port: 8388,
      protocol: "shadowsocks",
      has_reality: false,
      is_selected: false,
      connect_ms: 71,
      request_ms: 322,
      success_rate: 0.96,
      uplink_bytes: 3 * GIB,
      downlink_bytes: 14 * GIB,
    }),
  ];
}

export class DemoProxy {
  private readonly geodata: GeodataView = {
    geoip_version: DEMO_GEODATA_RELEASE,
    geosite_version: DEMO_GEODATA_RELEASE,
    source: "release",
    latest: null,
  };
  private settings: ProxySettings = {
    is_proxy_enabled: true,
    is_overlay_proxy_enabled: false,
    is_local_proxy_enabled: false,
    is_direct_fallback_enabled: false,
    is_geoip_split_enabled: true,
    direct_domains: ["geosite:cn", "example.com"],
    direct_ips: ["geoip:cn", "geoip:private"],
    remote_dns: [{ address: "203.0.113.53", port: 53 }],
    direct_dns: [{ address: "198.51.100.53", port: 53 }],
  };
  private applied: ProxySettings = this.settings;
  private nodes = initialNodes();
  private balancer: BalancerSettings = {
    probe_url: "https://probe.example.net/generate_204",
    reference_url: "http://reference.example.com/connecttest.txt",
    probe_interval_s: 60,
  };
  private isDirty = false;
  private exitSince = secondsAgo(3600 * 5);
  private serial = 0;

  /** The Proxy page's view. */
  view(): ProxyView {
    return { ...this.settings, geodata: this.geodata };
  }

  /** The exits' list. */
  nodesView(): NodesResponse {
    return {
      nodes: this.nodes,
      balancer: this.balancer,
      is_dirty: this.isDirty,
    };
  }

  /** Writes the routing settings, which `apply` puts in force. */
  setSettings(settings: ProxySettings): ProxyView {
    this.settings = structuredClone(settings);
    return this.view();
  }

  /** Puts what is written in force and pins the exit again. */
  apply(): ApplyResult {
    this.applied = this.settings;
    this.isDirty = false;
    this.pinExit();
    return {
      is_applied: true,
      changes: [{ code: "xray_restarted", params: {} }],
      failures: [],
    };
  }

  /**
   * Adds an exit from a share link, at a documentation address.
   *
   * Args:
   *   link: The link a visitor pasted.
   *   fallbackName: The exit's name where the link names none.
   *
   * Returns:
   *   The exit, not yet measured.
   *
   * Raises:
   *   DemoRefusal: For a link that is neither `ss://` nor `vless://`.
   */
  addNode(link: string, fallbackName: string): NodeView {
    const scheme = SHARE_LINK_SCHEMES.exec(link)?.[1];
    if (scheme === undefined) {
      throw new DemoRefusal("share_link_unreadable");
    }
    this.serial += 1;
    const node: NodeView = {
      id: `exit-${this.serial}`,
      name: this.linkName(link) || `${fallbackName} ${this.serial}`,
      address: `203.0.113.${NEW_NODE_FIRST_OCTET + this.serial}`,
      protocol: scheme === "vless" ? "vless" : "shadowsocks",
      port: NEW_NODE_PORT,
      is_enabled: true,
      has_reality: link.includes("security=reality"),
      is_alive: false,
      is_selected: false,
      connect_ms: null,
      request_ms: null,
      probed_at: "",
      success_rate: 0,
      score_ms: null,
      uplink_bytes: 0,
      downlink_bytes: 0,
    };
    this.nodes.push(node);
    this.isDirty = true;
    return node;
  }

  /** Writes an exit's switch and name. */
  setNode(nodeId: string, isEnabled: boolean, name: string): NodeView | null {
    const node = this.nodes.find((held) => held.id === nodeId) ?? null;
    if (node !== null) {
      node.is_enabled = isEnabled;
      node.name = name;
    }
    return node;
  }

  /** Removes an exit, and pins another where it was the pinned one. */
  removeNode(nodeId: string): NodesResponse {
    this.nodes = this.nodes.filter((node) => node.id !== nodeId);
    this.isDirty = true;
    this.pinExit();
    return this.nodesView();
  }

  /** Writes how the hub measures. */
  setBalancer(balancer: BalancerSettings): BalancerSettings {
    this.balancer = structuredClone(balancer);
    return this.balancer;
  }

  /** The databases' release, already the newest. */
  scanGeodata(): GeodataView {
    return {
      ...this.geodata,
      latest: {
        geoip_version: this.geodata.geoip_version,
        geosite_version: this.geodata.geosite_version,
      },
    };
  }

  /**
   * Takes new readings and pins the exit again.
   *
   * Args:
   *   nodeId: The one exit to read, every exit when empty.
   */
  measure(nodeId: string = ""): void {
    for (const node of this.nodes) {
      if (nodeId === "" || node.id === nodeId) {
        this.readNode(node);
      }
    }
    this.pinExit();
  }

  /** The pinned exit's tag, as the dashboard's summary names it. */
  activeExitTags(): string[] {
    const pinned = this.pinned();
    return pinned === undefined ? [] : [nodeTagFromId(pinned.id)];
  }

  /**
   * The next stats frame's fields, one second more of traffic on the exit.
   *
   * Args:
   *   mode: The network mode, which says what there is to divert.
   *
   * Returns:
   *   The fields.
   */
  readings(mode: NetworkModeKey): DemoProxyReadings {
    const scope = this.scope(mode);
    const pinned = this.pinned();
    if (pinned !== undefined && scope !== SCOPE_OFF && scope !== SCOPE_UNUSED) {
      const load = 0.7 + 0.6 * Math.random();
      pinned.downlink_bytes += EXIT_RX_BYTES_PER_S * load * STAT_INTERVAL_S;
      pinned.uplink_bytes += EXIT_TX_BYTES_PER_S * load * STAT_INTERVAL_S;
    }
    return {
      outbounds: this.nodes.map((node) => ({
        tag: nodeTagFromId(node.id),
        uplink_bytes: node.uplink_bytes,
        downlink_bytes: node.downlink_bytes,
      })),
      nodes: this.nodes.map((node) => ({
        tag: nodeTagFromId(node.id),
        name: node.name,
        is_alive: node.is_alive,
        is_enabled: node.is_enabled,
        is_selected: node.is_selected,
        connect_ms: node.connect_ms,
        request_ms: node.request_ms,
        probed_at: node.probed_at,
        success_rate: node.success_rate,
      })),
      proxy_scope: scope,
      exit_tag: pinned === undefined ? "" : nodeTagFromId(pinned.id),
      exit_name: pinned?.name ?? "",
      exit_since: pinned === undefined ? "" : this.exitSince,
      enabled_node_count: this.nodes.filter((node) => node.is_enabled).length,
    };
  }

  private pinned(): NodeView | undefined {
    return this.nodes.find((node) => node.is_selected);
  }

  /** Keeps a pinned exit that answers, or pins the best one that does. */
  private pinExit(): void {
    const isUsable = (node: NodeView) => node.is_enabled && node.is_alive;
    const pinned = this.pinned();
    if (pinned !== undefined && isUsable(pinned)) {
      return;
    }
    const [best] = this.nodes
      .filter(isUsable)
      .sort((left, right) => (left.score_ms ?? 0) - (right.score_ms ?? 0));
    for (const node of this.nodes) {
      node.is_selected = node === best;
    }
    this.exitSince = new Date().toISOString();
  }

  private readNode(node: NodeView): void {
    const usual =
      node.connect_ms ??
      NEW_NODE_MIN_CONNECT_MS + Math.random() * NEW_NODE_CONNECT_SPREAD_MS;
    const connectMs = Math.round(
      usual * (1 - CONNECT_JITTER / 2 + Math.random() * CONNECT_JITTER),
    );
    node.connect_ms = connectMs;
    node.request_ms = Math.round(
      connectMs * REQUEST_PER_CONNECT + Math.random() * REQUEST_EXTRA_MS,
    );
    node.score_ms = node.request_ms;
    node.success_rate = node.success_rate === 0 ? 1 : node.success_rate;
    node.is_alive = true;
    node.probed_at = new Date().toISOString();
  }

  /** The name after a link's `#`, empty where it has none. */
  private linkName(link: string): string {
    const fragment = link.split("#")[1] ?? "";
    try {
      return decodeURIComponent(fragment).trim();
    } catch {
      return fragment.trim();
    }
  }

  /** Whose traffic the settings in force take, as the hub answers it. */
  private scope(mode: NetworkModeKey): string {
    const {
      is_proxy_enabled: isLanOn,
      is_overlay_proxy_enabled: isOverlayOn,
      is_local_proxy_enabled: isHubOn,
    } = this.applied;
    const parts = [
      ...(isLanOn && mode !== "server" ? [SCOPE_LAN] : []),
      ...(isOverlayOn ? [SCOPE_OVERLAY] : []),
      ...(isHubOn ? [SCOPE_HUB] : []),
    ];
    if (parts.length > 0) {
      return parts.join(SCOPE_JOINER);
    }
    return isLanOn || isOverlayOn || isHubOn ? SCOPE_UNUSED : SCOPE_OFF;
  }
}
