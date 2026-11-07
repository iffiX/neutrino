import { parseIpv4 } from "../hub/frontend/src/ipv4_address";
import {
  DEMO_HUB_ADDRESS,
  DEMO_NETBIRD_ADDRESS,
  DEMO_WAN_ADDRESS,
} from "./demo_fixtures";
import type {
  DnsLogEntry,
  InterfaceSettings,
  InterfaceView,
  NetworkMode,
  NetworkModeKey,
  NetworkOptions,
  NetworkView,
  OverlayView,
  SavedNetwork,
  SavedNetworkList,
  StaticLeaseSettings,
  UpstreamLine,
  UplinkPolicy,
  WifiScan,
} from "../hub/frontend/src/api_types";

/**
 * The fake hub's network: one machine's three ports as each mode holds them,
 * the page's own settings, and what a press on the Network page changes.
 */

const MODE_SERVER = "server";
const MODE_SIDE_GATEWAY = "side_gateway";
const MODE_ROUTER = "router";

/** The modes, in the order the panel offers them. */
const MODES: NetworkMode[] = [
  { key: MODE_SERVER, is_addressing_owned: false },
  { key: MODE_SIDE_GATEWAY, is_addressing_owned: false },
  { key: MODE_ROUTER, is_addressing_owned: true },
];

const WIRED_PORT = "eth0";
const UPLINK_PORT = "eth1";
const RADIO_PORT = "wlan0";
const UNTAGGED_SUFFIX = ".main";
const PORT_MACS: Record<string, string> = {
  [WIRED_PORT]: "52:54:00:12:34:10",
  [UPLINK_PORT]: "52:54:00:12:34:11",
  [RADIO_PORT]: "52:54:00:12:34:12",
};
const PORT_SPEED_MBPS = 1000;
const JOINED_SIGNAL_PERCENT = 72;
const PREFIX_LEN = 24;
const PREFIX_MAX = 32;
const FIRST_ROUTE_METRIC = 100;
const HOME_GATEWAY = "192.168.1.1";
const HOME_DEVICE_COUNT = 2;
const LINK_LOCAL_NETWORK = "fe80::/64";
const RADIO_ADDRESS = "192.168.2.1";

/** An address a port holds, and the router past it. */
interface DemoAddress {
  address: string;
  prefix_len: number;
  gateway: string | null;
}

/** What each port's far side hands out by DHCP. */
const DHCP_LEASES: Record<string, DemoAddress> = {
  [WIRED_PORT]: {
    address: DEMO_HUB_ADDRESS,
    prefix_len: PREFIX_LEN,
    gateway: HOME_GATEWAY,
  },
  [UPLINK_PORT]: {
    address: DEMO_WAN_ADDRESS,
    prefix_len: PREFIX_LEN,
    gateway: "203.0.113.1",
  },
  [RADIO_PORT]: {
    address: "198.51.100.24",
    prefix_len: PREFIX_LEN,
    gateway: "198.51.100.1",
  },
};

/** What DHCP hands a VLAN on a trunk. */
const DHCP_LEASE_ON_VLAN: DemoAddress = {
  address: "198.51.100.50",
  prefix_len: PREFIX_LEN,
  gateway: "198.51.100.1",
};

/** The radio's neighbours, by name and strength. */
const WIFI_IN_RANGE = [
  {
    ssid: "Home-WiFi",
    signal_percent: JOINED_SIGNAL_PERCENT,
    security: "WPA2",
  },
  { ssid: "Neighbour-5G", signal_percent: 44, security: "WPA2 WPA3" },
  { ssid: "Cafe-Guest", signal_percent: 31, security: "" },
];

/** What the DNS log holds on a hub that answers a network's queries. */
const DNS_SAMPLES = [
  { domain: "docs.example.com", client: "192.168.1.20", outbound: "direct" },
  { domain: "api.example.net", client: "192.168.1.31", outbound: "cached" },
  { domain: "hub.local", client: "192.168.1.31", outbound: "config" },
  { domain: "updates.example.org", client: "192.168.1.20", outbound: "direct" },
  { domain: "cdn.example.net", client: "192.168.1.20", outbound: "cached" },
  { domain: "time.example.com", client: "192.168.1.42", outbound: "direct" },
];
const DNS_SAMPLE_SPACING_MS = 7000;

function portSettings(
  name: string,
  change: Partial<InterfaceSettings> = {},
): InterfaceSettings {
  return {
    name,
    role: "disabled",
    is_ipv4_exposed: false,
    is_ipv6_exposed: false,
    wan: {
      method: "dhcp",
      address: null,
      prefix_len: PREFIX_LEN,
      gateway: null,
      intent: "auto",
      cloned_mac: null,
      dns: [],
    },
    lan: {
      address: "",
      prefix_len: PREFIX_LEN,
      is_dhcp_enabled: true,
      dhcp_range_start: "",
      dhcp_range_end: "",
      dhcp_lease_time: "12h",
      upstream_gateway: null,
    },
    wifi: {
      ssid: "",
      ap_ssid: "",
      ap_passphrase: "",
      ap_band: "bg",
      ap_country_code: "",
    },
    vlan: null,
    ...change,
  };
}

/** The leases one served network hands out, on its `/24`. */
function servedNetwork(
  address: string,
  upstreamGateway: string | null = null,
): InterfaceSettings["lan"] {
  const prefix = address.slice(0, address.lastIndexOf("."));
  return {
    address,
    prefix_len: PREFIX_LEN,
    is_dhcp_enabled: upstreamGateway === null,
    dhcp_range_start: upstreamGateway === null ? `${prefix}.100` : "",
    dhcp_range_end: upstreamGateway === null ? `${prefix}.200` : "",
    dhcp_lease_time: "12h",
    upstream_gateway: upstreamGateway,
  };
}

function serverPorts(): InterfaceSettings[] {
  return [
    portSettings(WIRED_PORT, { is_ipv4_exposed: true }),
    portSettings(UPLINK_PORT),
    portSettings(RADIO_PORT),
  ];
}

function sideGatewayPorts(): InterfaceSettings[] {
  return [
    portSettings(WIRED_PORT, {
      role: "lan",
      is_ipv4_exposed: true,
      is_ipv6_exposed: true,
      lan: servedNetwork(DEMO_HUB_ADDRESS, HOME_GATEWAY),
    }),
    portSettings(UPLINK_PORT),
    portSettings(RADIO_PORT),
  ];
}

function routerPorts(): InterfaceSettings[] {
  const uplink = portSettings(UPLINK_PORT, { role: "wan" });
  const radio = portSettings(RADIO_PORT, {
    role: "lan",
    is_ipv4_exposed: true,
    lan: servedNetwork(RADIO_ADDRESS),
  });
  radio.wifi.ap_ssid = "Neutrino-Home";
  radio.wifi.ap_passphrase = "neutrino-demo";
  return [
    portSettings(WIRED_PORT, {
      role: "lan",
      is_ipv4_exposed: true,
      lan: servedNetwork(DEMO_HUB_ADDRESS),
    }),
    uplink,
    radio,
  ];
}

/** The network an address stands in, as `a.b.c.d/n`. */
function networkOf({ address, prefix_len: prefixLen }: DemoAddress): string {
  const value = parseIpv4(address) ?? 0;
  const hostBits = PREFIX_MAX - prefixLen;
  const network = (value >>> hostBits) * 2 ** hostBits;
  const octets = [24, 16, 8, 0].map((shift) => (network >>> shift) & 0xff);
  return `${octets.join(".")}/${prefixLen}`;
}

/** The address a port's settings give it, or null where they give none. */
function heldAddress(
  settings: InterfaceSettings,
  mode: NetworkModeKey,
): DemoAddress | null {
  const { name, role, lan, wan, wifi } = settings;
  if (role === "lan") {
    return lan.address === ""
      ? null
      : {
          address: lan.address,
          prefix_len: lan.prefix_len,
          gateway: lan.upstream_gateway,
        };
  }
  if (role === "wan" && wan.method === "static") {
    return wan.address === null
      ? null
      : {
          address: wan.address,
          prefix_len: wan.prefix_len,
          gateway: wan.gateway,
        };
  }
  if (role === "wan") {
    if (name === RADIO_PORT && wifi.ssid === "") {
      return null;
    }
    return DHCP_LEASES[name] ?? DHCP_LEASE_ON_VLAN;
  }
  // A server answers on what the machine itself set up.
  return mode === MODE_SERVER && name === WIRED_PORT
    ? (DHCP_LEASES[name] ?? null)
    : null;
}

function portView(
  settings: InterfaceSettings,
  mode: NetworkModeKey,
): InterfaceView {
  const { name, role, wan, wifi, vlan } = settings;
  const isRadio = name === RADIO_PORT;
  const isJoined = isRadio && role === "wan" && wifi.ssid !== "";
  const isServing = isRadio && role === "lan";
  const isUp = !isRadio || isJoined || isServing;
  const held = heldAddress(settings, mode);
  const kind = vlan !== null ? "vlan" : isRadio ? "wifi" : "ethernet";
  const isHomeNetwork = held?.address === DEMO_HUB_ADDRESS;
  return {
    settings,
    link: {
      name,
      kind,
      is_present: true,
      is_up: isUp,
      ipv4_address: held === null ? null : `${held.address}/${held.prefix_len}`,
      mac_address: PORT_MACS[vlan?.parent ?? name] ?? null,
      ssid: isJoined ? wifi.ssid : isServing ? wifi.ap_ssid : null,
      signal_percent: isJoined ? JOINED_SIGNAL_PERCENT : null,
      speed_mbps: isRadio ? null : PORT_SPEED_MBPS,
      gateway: held?.gateway ?? null,
      is_ap_capable: true,
      lease_dns:
        role === "wan" && wan.method === "dhcp" && held?.gateway
          ? [held.gateway]
          : [],
    },
    ipv4_segment: {
      networks: held === null ? [] : [networkOf(held)],
      device_count: isHomeNetwork ? HOME_DEVICE_COUNT : 0,
    },
    ipv6_segment: {
      networks: isUp ? [LINK_LOCAL_NETWORK] : [],
      device_count: 0,
    },
    is_unsaved: false,
  };
}

/** The sample DNS log, newest first, in dnsmasq's stamp. */
export function demoDnsLog(): DnsLogEntry[] {
  const now = Date.now();
  return DNS_SAMPLES.map((sample, at) => ({
    ...sample,
    timestamp: new Date(now - at * DNS_SAMPLE_SPACING_MS)
      .toString()
      .slice(4, 24)
      .replace(/ \d{4}/, ""),
  }));
}

export class DemoNetwork {
  private readonly ports: Record<NetworkModeKey, InterfaceSettings[]> = {
    server: serverPorts(),
    side_gateway: sideGatewayPorts(),
    router: routerPorts(),
  };
  private readonly overlays: OverlayView[] = [
    {
      provider: "netbird",
      title: "NetBird",
      address: DEMO_NETBIRD_ADDRESS,
      is_exposed: true,
      device_count: 1,
    },
    {
      provider: "easytier",
      title: "EasyTier",
      address: "10.144.0.1",
      is_exposed: true,
      device_count: 1,
    },
  ];
  private readonly savedWifi: SavedNetwork[] = [
    {
      ssid: "Home-WiFi",
      key_mgmt: "WPA-PSK",
      has_secret: true,
      priority: 0,
      is_hidden: false,
      source: "panel",
    },
  ];
  private mode: NetworkModeKey = MODE_SERVER;
  private staticLeases: StaticLeaseSettings[] = [
    {
      mac_address: "52:54:00:12:34:20",
      address: "192.168.1.20",
      name: "desktop",
    },
  ];
  private uplinkPolicy: UplinkPolicy = "failover";
  private isInterLanAllowed = false;

  /** The mode this machine is in. */
  currentMode(): NetworkModeKey {
    return this.mode;
  }

  /**
   * The Network page's view.
   *
   * Args:
   *   isSideGatewayOffered: Whether the edition has the side gateway mode.
   *
   * Returns:
   *   The view.
   */
  view(isSideGatewayOffered: boolean): NetworkView {
    const interfaces = this.ports[this.mode].map((settings) =>
      portView(settings, this.mode),
    );
    const lines = this.lines(interfaces);
    return {
      hub_os: "linux",
      mode: this.mode,
      modes: MODES.filter(
        (mode) => isSideGatewayOffered || mode.key !== MODE_SIDE_GATEWAY,
      ),
      interfaces,
      overlays: this.overlays,
      static_leases: this.staticLeases,
      uplink_policy: this.uplinkPolicy,
      is_inter_lan_allowed: this.isInterLanAllowed,
      is_addressing_owned: this.mode === MODE_ROUTER,
      default_gateway: lines[0]?.gateway ?? null,
      lines,
      warnings: [],
    };
  }

  /** The port this machine's traffic leaves by. */
  uplinkName(): string {
    const interfaces = this.ports[this.mode].map((settings) =>
      portView(settings, this.mode),
    );
    return this.lines(interfaces)[0]?.members[0]?.name ?? WIRED_PORT;
  }

  /** Becomes a mode, each mode holding its ports as they were last left. */
  setMode(mode: NetworkModeKey): void {
    this.mode = mode;
  }

  /** Goes back to server mode from the mode the mainland edition leaves out. */
  leaveSideGateway(): void {
    if (this.mode === MODE_SIDE_GATEWAY) {
      this.mode = MODE_SERVER;
    }
  }

  /** Writes one port, or adds the VLAN it names. */
  setInterface(settings: InterfaceSettings): void {
    const ports = this.ports[this.mode];
    const at = ports.findIndex((port) => port.name === settings.name);
    if (at >= 0) {
      ports[at] = settings;
    } else {
      this.addVlan(settings);
    }
    if (settings.vlan === null) {
      this.settleTrunk(settings);
    }
  }

  /** Takes a VLAN off its trunk. */
  removeInterface(name: string): void {
    this.ports[this.mode] = this.ports[this.mode].filter(
      (port) => port.name !== name,
    );
  }

  /** Writes what the request names of the page's own settings. */
  setOptions(options: NetworkOptions): void {
    this.uplinkPolicy = options.uplink_policy;
    this.isInterLanAllowed = options.is_inter_lan_allowed;
    for (const port of this.ports[this.mode]) {
      if (options.ipv4_exposed_interfaces !== undefined) {
        port.is_ipv4_exposed = options.ipv4_exposed_interfaces.includes(
          port.name,
        );
      }
      if (options.ipv6_exposed_interfaces !== undefined) {
        port.is_ipv6_exposed = options.ipv6_exposed_interfaces.includes(
          port.name,
        );
      }
      port.role = options.interface_roles?.[port.name] ?? port.role;
    }
    if (options.exposed_overlays !== undefined) {
      for (const overlay of this.overlays) {
        overlay.is_exposed = options.exposed_overlays.includes(
          overlay.provider,
        );
      }
    }
    this.staticLeases = options.static_leases ?? this.staticLeases;
  }

  /** The radio's scan, marked with what it joined and what it remembers. */
  wifiScan(name: string): WifiScan {
    const joined = this.ports[this.mode].find((port) => port.name === name);
    return {
      networks: WIFI_IN_RANGE.map((network) => ({
        ...network,
        is_active: joined?.wifi.ssid === network.ssid,
        is_saved: this.savedWifi.some((saved) => saved.ssid === network.ssid),
      })),
    };
  }

  /** Joins a radio to a network, and remembers the network. */
  joinWifi(name: string, ssid: string): void {
    const port = this.ports[this.mode].find((held) => held.name === name);
    if (port !== undefined) {
      port.role = "wan";
      port.wifi.ssid = ssid;
    }
    if (!this.savedWifi.some((saved) => saved.ssid === ssid)) {
      this.savedWifi.push({
        ssid,
        key_mgmt: "WPA-PSK",
        has_secret: true,
        priority: 0,
        is_hidden: false,
        source: "panel",
      });
    }
  }

  /** The wireless networks the machine remembers. */
  savedWifiList(): SavedNetworkList {
    return { networks: this.savedWifi };
  }

  /** Forgets a remembered wireless network. */
  forgetWifi(ssid: string): void {
    const at = this.savedWifi.findIndex((saved) => saved.ssid === ssid);
    if (at >= 0) {
      this.savedWifi.splice(at, 1);
    }
  }

  private lines(interfaces: InterfaceView[]): UpstreamLine[] {
    const uplinks = interfaces.filter(
      (entry) =>
        entry.link.gateway !== null &&
        (this.mode !== MODE_ROUTER || entry.settings.role === "wan"),
    );
    return uplinks.map((entry, at) => {
      const isCarrying = at === 0 || this.uplinkPolicy === "balance";
      return {
        id: `line_${entry.settings.name}`,
        gateway: entry.link.gateway,
        is_shared: false,
        is_carrying: isCarrying,
        members: [
          {
            name: entry.settings.name,
            rank: at + 1,
            is_active: isCarrying,
            route_metric: FIRST_ROUTE_METRIC * (at + 1),
            reason: "",
            speed_mbps: entry.link.speed_mbps,
          },
        ],
      };
    });
  }

  /** Adds a VLAN behind its trunk and the VLANs already on it. */
  private addVlan(settings: InterfaceSettings): void {
    const ports = this.ports[this.mode];
    const parent = settings.vlan?.parent;
    const lastSibling = ports
      .map((port) => port.name === parent || port.vlan?.parent === parent)
      .lastIndexOf(true);
    ports.splice(lastSibling + 1, 0, settings);
  }

  /** Gives a split port its untagged main, and takes a trunk's VLANs back. */
  private settleTrunk({ name, role }: InterfaceSettings): void {
    if (role !== "split") {
      this.ports[this.mode] = this.ports[this.mode].filter(
        (port) => port.vlan?.parent !== name,
      );
      return;
    }
    const hasMain = this.ports[this.mode].some(
      (port) => port.vlan?.parent === name && port.vlan.id === null,
    );
    if (!hasMain) {
      this.addVlan(
        portSettings(`${name}${UNTAGGED_SUFFIX}`, {
          vlan: { parent: name, id: null },
        }),
      );
    }
  }
}
