/**
 * Request and response shapes of the panel API.
 *
 * Every type here mirrors a backend Pydantic model field-for-field, which is
 * why the field names stay snake_case and the booleans keep their `is_` /
 * `has_` spelling. The frontend never invents a shape the backend does not
 * send: if something is missing here, it is missing from the API.
 */

// --- Shared enumerations ---

export type NodeProtocol = "shadowsocks" | "vless";

/** What the whole machine is set up as. */
export type NetworkModeKey = "server" | "side_gateway" | "router";

export type DeviceAuthMethod = "key" | "password";

/** One remote-desktop product's state on a device. */
export interface RemoteDesktopStatus {
  product: "anydesk" | "teamviewer";
  is_installed: boolean;
  is_running: boolean;
  /** Why the device could not be asked, empty when it was. A machine that is
   * off and one without the software are not the same answer. */
  unreachable: string;
  session_id: string | null;
  can_set_password: boolean;
}

/** The remote-desktop products' state on a device. */
export interface RemoteDesktopView {
  anydesk: RemoteDesktopStatus;
  teamviewer: RemoteDesktopStatus;
}

// --- Auth ---

export interface AuthState {
  /** Seconds until login opens again after repeated failures; 0 when open. */
  lockout_remaining_s: number;
  is_authenticated: boolean;
  /** This panel process's start moment; a new value is a restarted panel. */
  panel_started_at: string;
  /** The port the panel serves HTTPS on. */
  https_listen_port: number;
}

export interface LoginRequest {
  password: string;
}

// --- Nodes ---

export interface NodeView {
  id: string;
  name: string;
  address: string;
  protocol: NodeProtocol;
  port: number;
  /** Whether the node may be chosen as the exit. Every node is measured. */
  is_enabled: boolean;
  has_reality: boolean;
  /** Whether the node has a measurement and the latest one did not fail. */
  is_alive: boolean;
  /** Whether this is the exit the hub has pinned. */
  is_selected: boolean;
  /** The TCP connect to the node's own port. */
  connect_ms: number | null;
  /** A full request through the node to the probe URL. */
  request_ms: number | null;
  /** When the last measurement was taken, empty for a node never measured. */
  probed_at: string;
  /** The share of measurements that answered, 0 to 1. */
  success_rate: number;
  /** What the exit is ranked by, null until there is something to rank. */
  score_ms: number | null;
  uplink_bytes: number;
  downlink_bytes: number;
}

export interface BalancerSettings {
  /** Fetched through each node, which is what request_ms times. */
  probe_url: string;
  /** Fetched directly, which is what tells a dead node from a dead uplink. */
  reference_url: string;
  probe_interval_s: number;
}

export interface NodesResponse {
  nodes: NodeView[];
  balancer: BalancerSettings;
  is_dirty: boolean;
}

export interface NodeUpdateRequest {
  is_enabled?: boolean;
  name?: string;
}

/** Which nodes to measure now. An absent id means every node. */
export interface NodeTestRequest {
  node_id?: string;
}

/** A share link to add as a node. */
export interface NodeCreateRequest {
  link: string;
}

/** One thing an apply did, or why it did not; the page words the code. */
export interface ApplyChange {
  code: string;
  params: Record<string, string | number>;
}

export interface ApplyResult {
  is_applied: boolean;
  changes: ApplyChange[];
  failures: ApplyChange[];
}

// --- Dashboard and live stats ---

export interface TrafficSample {
  label: string;
  received_bytes: number;
  sent_bytes: number;
}

export type TrafficHistoryRange = "day" | "week" | "month" | "year";

export interface TrafficHistoryResponse {
  range: TrafficHistoryRange;
  samples: TrafficSample[];
  today: TrafficSample | null;
}

export interface OutboundTraffic {
  tag: string;
  uplink_bytes: number;
  downlink_bytes: number;
}

export interface NodeProbe {
  tag: string;
  is_alive: boolean;
  is_enabled: boolean;
  is_selected: boolean;
  connect_ms: number | null;
  request_ms: number | null;
  probed_at: string;
  success_rate: number;
}

/**
 * Whose traffic the proxy is taking, read from the applied ruleset: the
 * master switch is off; on but nothing is sent to it; only the SOCKS ports
 * reach it; the forwarded network is diverted; the hub's own traffic is; or
 * both are.
 */
/**
 * Whose traffic the proxy is taking: off, unused, ports, or the diverted
 * scopes out of `lan`, `overlay` and `hub` joined with `+`.
 */
export type ProxyScope = string;

export interface StatsFrame {
  /** ISO 8601 UTC stamp, as produced by `datetime.now(timezone.utc)`. */
  timestamp: string;
  outbounds: OutboundTraffic[];
  nodes: NodeProbe[];
  cpu_percent: number;
  memory_percent: number;
  uptime_s: number;
  wan_address: string | null;
  total_uplink_bytes: number;
  total_downlink_bytes: number;
  /** The machine's own uplink, empty when it has neither WAN nor default route. */
  interface_name: string;
  /** What that interface is carrying, from its kernel counters — not xray's. */
  interface_rx_bytes_per_s: number;
  interface_tx_bytes_per_s: number;
  proxy_scope: ProxyScope;
  /** What this machine is set up as; every other chip is read by it. */
  network_mode: NetworkModeKey;
  /** Devices whose agent is reporting, which an SSH login is not. */
  agent_device_count: number;
  /** Devices the kernel currently has in its neighbour table on the LANs. */
  lan_device_count: number;
  /** The outbound tag of the pinned exit, empty when none is pinned. */
  exit_tag: string;
  /** When that exit was pinned, empty when none is. */
  exit_since: string;
  /** Whether the reference URL answered without the proxy. */
  is_wan_reachable: boolean;
  /** Whether xray's own API answered. */
  is_xray_reachable: boolean;
  /** Whether the running xray matches what config/ says. */
  is_in_sync: boolean;
  enabled_node_count: number;
}

export interface DashboardSummary {
  stats: StatsFrame;
  active_exit_tags: string[];
  dns_query_count: number;
  lan_device_count: number;
}

export interface DnsLogEntry {
  /** The dnsmasq syslog stamp, e.g. `Aug 27 12:51:40`. Not ISO 8601. */
  timestamp: string;
  domain: string;
  client: string;
  outbound: string | null;
}

export interface DnsLogFrame {
  entries: DnsLogEntry[];
}

// --- Network ---

/**
 * What an interface is for. The role decides which settings block is live;
 * "split" turns a wired port into a pure 802.1Q trunk whose VLANs are further
 * interfaces with roles of their own.
 */
export type InterfaceRole = "wan" | "lan" | "split" | "disabled";

/**
 * What the user wants of an uplink, as opposed to what the gateway works out.
 * Ordering is inferred from the links themselves; this carries only the part
 * that cannot be — chiefly that a metered link must stay dark however fast it
 * benchmarks.
 */
export type UplinkIntent = "auto" | "primary" | "backup_only";

/** What to do when the box has more than one way out. */
export type UplinkPolicy = "failover" | "balance";

/** How a WAN gets its address. */
export type WanMethod = "dhcp" | "static";

export interface WanInterfaceSettings {
  method: WanMethod;
  address: string | null;
  prefix_len: number;
  gateway: string | null;
  intent: UplinkIntent;
  cloned_mac: string | null;
  /** A static uplink's resolvers, in the order they are asked. */
  dns: DnsServer[];
}

export interface LanInterfaceSettings {
  address: string;
  prefix_len: number;
  is_dhcp_enabled: boolean;
  dhcp_range_start: string;
  dhcp_range_end: string;
  dhcp_lease_time: string;
  /**
   * The network's real router, for side-gateway mode: the box joins an
   * existing LAN and this router is its way out. Null is an ordinary LAN.
   */
  upstream_gateway: string | null;
}

export interface WifiInterfaceSettings {
  ssid: string;
  ap_ssid: string;
  ap_passphrase: string;
  ap_band: string;
  ap_country_code: string;
}

/**
 * What makes an interface ride on a trunk port. `id` null marks the trunk's
 * untagged main, shown as `<parent>.main`.
 */
export interface VlanInterfaceSettings {
  parent: string;
  id: number | null;
}

export interface InterfaceSettings {
  name: string;
  role: InterfaceRole;
  /**
   * Whether the hub's own ports answer the senders inside this interface's
   * IPv4 segment, and inside its IPv6 segment. Read-only here: both sets are
   * written at once by the panel that shows every segment, so a save of one
   * interface cannot reopen or close either.
   */
  is_ipv4_exposed: boolean;
  is_ipv6_exposed: boolean;
  wan: WanInterfaceSettings;
  lan: LanInterfaceSettings;
  wifi: WifiInterfaceSettings;
  vlan: VlanInterfaceSettings | null;
}

/** What an interface is actually doing, as opposed to what it is for. */
export interface InterfaceLink {
  name: string;
  kind: string;
  is_present: boolean;
  is_up: boolean;
  ipv4_address: string | null;
  mac_address: string | null;
  ssid: string | null;
  signal_percent: number | null;
  speed_mbps: number | null;
  gateway: string | null;
  /**
   * Whether this interface can serve a network at all. Always true for a wired
   * port; false for a radio whose chipset has no access-point mode, which is
   * what greys out the LAN role.
   */
  is_ap_capable: boolean;
  /**
   * The resolvers a DHCP uplink's lease names; empty for a static uplink and
   * for an interface holding no lease.
   */
  lease_dns: string[];
}

/** One of an interface's two segments, as the Exposure section draws it. */
export interface SegmentView {
  /**
   * Every network of the segment's family the interface holds an address in
   * now; an IPv6 segment holds `fe80::/64` while it has a link-local address.
   */
  networks: string[];
  /**
   * Managed devices reaching this hub from inside those networks right now,
   * which is what closing the segment would end. Live, so a device that is
   * off is not counted.
   */
  device_count: number;
}

export interface InterfaceView {
  settings: InterfaceSettings;
  link: InterfaceLink;
  ipv4_segment: SegmentView;
  ipv6_segment: SegmentView;
  /** The configuration does not name it and the hub does not use it until
   * the person turns it on: every such interface on Linux, none elsewhere. */
  is_unsaved: boolean;
}

/** One overlay network this box is a member of. */
export interface OverlayView {
  /** Who runs it. The key the write side names it by. */
  provider: string;
  title: string;
  /** This box's address on it, empty while the overlay is not up. */
  address: string;
  is_exposed: boolean;
  device_count: number;
}

/** One uplink's place in the gateway's plan for them. */
export interface PlannedUplink {
  name: string;
  rank: number;
  is_active: boolean;
  route_metric: number;
  reason: string;
  speed_mbps: number | null;
}

/**
 * One path to the internet, and the interfaces that reach it.
 *
 * Two interfaces on one line are two doors onto one broadband connection, so
 * only the first of them carries traffic.
 */
export interface UpstreamLine {
  id: string;
  gateway: string | null;
  is_shared: boolean;
  is_carrying: boolean;
  members: PlannedUplink[];
}

/** One mode, as the Mode panel lists it; the panel words the key itself. */
export interface NetworkMode {
  key: NetworkModeKey;
  is_addressing_owned: boolean;
}

/** One device that always gets the same address from a served network. */
export interface StaticLeaseSettings {
  mac_address: string;
  address: string;
  /** Optional; dnsmasq resolves it as well. */
  name: string;
}

/** The system the hub runs on. */
export type HubOs = "linux" | "darwin" | "windows";

export interface NetworkView {
  hub_os: HubOs;
  /** What this whole machine is; the page below the Mode panel follows it. */
  mode: NetworkModeKey;
  /** The modes this system can be: `server` alone outside Linux. */
  modes: NetworkMode[];
  interfaces: InterfaceView[];
  overlays: OverlayView[];
  static_leases: StaticLeaseSettings[];
  uplink_policy: UplinkPolicy;
  is_inter_lan_allowed: boolean;
  /**
   * Whether the hub addresses this machine's interfaces. False is a machine
   * somebody else configured, where the panel answers on the addresses the
   * ports already have and the Network form is read-only.
   */
  is_addressing_owned: boolean;
  default_gateway: string | null;
  lines: UpstreamLine[];
  /** Live conditions worth pointing at that the gateway cannot resolve itself. */
  warnings: string[];
}

/**
 * The page's own settings. Each list is absent or whole: absent leaves what
 * the box holds as it is, so a panel sends only the list it owns.
 */
export interface NetworkOptions {
  uplink_policy: UplinkPolicy;
  is_inter_lan_allowed: boolean;
  /** The interfaces whose IPv4 segment is exposed, by name. Every other
   * IPv4 segment is closed. */
  ipv4_exposed_interfaces?: string[];
  /** The interfaces whose IPv6 segment is exposed, by name. Every other
   * IPv6 segment is closed. */
  ipv6_exposed_interfaces?: string[];
  /** The overlays that answer, by provider. Everything else is closed. */
  exposed_overlays?: string[];
  /** The devices that always get one address, whole. */
  static_leases?: StaticLeaseSettings[];
  /** In router mode, the role each port with a segment turned on takes. */
  interface_roles?: Record<string, ExposedRole>;
}

/** The roles a router gives a port in the exposure row. */
export type ExposedRole = "wan" | "lan";

/** The mode to become. Nothing else: what each port is for is its own. */
export interface NetworkModeRequest {
  mode: NetworkModeKey;
}

export interface WifiNetwork {
  ssid: string;
  signal_percent: number;
  security: string;
  is_active: boolean;
  is_saved: boolean;
}

/**
 * One wireless network the box knows how to join. The passphrase never comes
 * back out — `has_secret` is the whole of what the panel is told about it.
 */
export interface SavedNetwork {
  ssid: string;
  key_mgmt: string;
  /** False when the key was read from a store that kept it somewhere
   * unreadable, such as a desktop keyring. The page asks for it once. */
  has_secret: boolean;
  priority: number;
  is_hidden: boolean;
  /** `panel` for one somebody typed, `inherited:<manager>` for one read out of
   * what this machine already held. */
  source: string;
}

export interface SavedNetworkList {
  networks: SavedNetwork[];
}

export interface WifiScan {
  networks: WifiNetwork[];
}

export interface WifiJoinRequest {
  name: string;
  ssid: string;
  passphrase: string | null;
}

// --- Proxy ---

export interface DnsServer {
  address: string;
  port: number;
}

/** One SOCKS5 listener: a port, and which way what arrives there leaves. */
export interface SocksPort {
  port: number;
  /** True goes out through the exit nodes; false leaves out the uplink. */
  is_proxied: boolean;
}

export interface ProxySettings {
  /** The served networks' switch: off leaves forwarded traffic alone. */
  is_proxy_enabled: boolean;
  /** The overlays' switch, for members using this box as their exit node. */
  is_overlay_proxy_enabled: boolean;
  is_direct_fallback_enabled: boolean;
  is_geoip_split_enabled: boolean;
  direct_domains: string[];
  direct_ips: string[];
  is_local_proxy_enabled: boolean;
  socks_ports: SocksPort[];
  /** Each asked in order; an empty direct list follows the network's. */
  remote_dns: DnsServer[];
  direct_dns: DnsServer[];
}

/** The release each of the two databases is taken from. */
export interface GeodataRelease {
  geoip_version: string;
  geosite_version: string;
}

/** Which release of each database the box loads, and where it came from. */
export interface GeodataView extends GeodataRelease {
  /** `package` for the carried copies, `release` for fetched ones. */
  source: string;
  /** What the repositories publish now; null until a scan asks them. */
  latest: GeodataRelease | null;
}

/** The Proxy page: its settings, and the databases the split runs on. */
export interface ProxyView extends ProxySettings {
  geodata: GeodataView;
}

// --- Devices ---

/** One SSH key the gateway holds, without its material. */
export interface KeyView {
  id: string;
  name: string;
  key_type: string;
  fingerprint: string;
  has_passphrase: boolean;
  created_at: string;
  device_count: number;
  /** Whether `config/overlay/relay.json` names this key. */
  is_relay_key: boolean;
}

/** A pasted key to store under a name. */
export interface KeyCreate {
  name: string;
  private_key: string;
  passphrase: string | null;
}

/** The Keys tab payload. */
export interface KeysResponse {
  keys: KeyView[];
}

/**
 * One login the vault holds, without its password. A null `username` is a
 * bare password.
 */
export interface LoginView {
  id: string;
  name: string;
  username: string | null;
  created_at: string;
  device_count: number;
  /** Whether `config/overlay/relay.json` names this login. */
  is_relay_login: boolean;
}

/** The Credentials page's login section payload. */
export interface LoginsResponse {
  logins: LoginView[];
}

/** One token the vault holds, without its value. */
export interface TokenView {
  id: string;
  name: string;
  created_at: string;
  provider_count: number;
  /** xray nodes referencing it; share-link imports generate these. */
  node_count: number;
}

/** A secret the hub generated for a machine, without its value. */
export interface GeneratedCredentialItemView {
  /** `smb_password`, `seat_password` or `ssh_key`. */
  kind: string;
  /** The account it belongs to; empty for the seat password. */
  account: string;
  /** An SSH key's `SHA256:<base64>`; empty for a password. */
  fingerprint: string;
}

/** A machine's generated secrets. */
export interface GeneratedCredentialMachineView {
  device_id: string;
  name: string;
  items: GeneratedCredentialItemView[];
}

/** The Credentials page's Generated by the hub section. */
export interface GeneratedCredentialListView {
  machines: GeneratedCredentialMachineView[];
}

/** A request naming a generated secret. */
export interface GeneratedCredentialRequest {
  device_id: string;
  kind: string;
  account: string;
}

/** A generated password, opened for this answer alone. */
export interface GeneratedCredentialRevealView {
  value: string;
}

/** The Credentials page's token section payload. */
export interface TokensResponse {
  tokens: TokenView[];
}

export type AiProviderKind = "anthropic" | "openai" | "gemini" | "custom";

/** One model alias a provider serves: real name in, served alias out. */
export interface AiProviderModel {
  name: string;
  alias: string;
}

/** One stored AI provider; `secret_id` names the vault token it is keyed
 * with, null when it has none yet. */
export interface AiProviderView {
  id: string;
  name: string;
  kind: AiProviderKind;
  base_url: string;
  secret_id: string | null;
  is_enabled: boolean;
  models: AiProviderModel[];
  created_at: string;
}

/** One client key of the AI gateway, shown in full to its owner. */
export interface CliproxyApiKeyView {
  id: string;
  name: string;
  key: string;
  created_at: string;
}

/** The AI page payload. */
export interface CliproxyApiStatusView {
  is_installed: boolean;
  is_active: boolean;
  listen_port: number;
  client_keys: CliproxyApiKeyView[];
  is_reachable: boolean;
  /** Why the probe found nothing to serve; empty when models are served. */
  probe_code: string;
  probe_params: Record<string, string | number>;
  /** The model names /v1/models answered with; empty when unreachable. */
  served_models?: string[];
  enabled_provider_count: number;
  /** How many subscription accounts the gateway holds. */
  account_count: number;
  /** Whether the running gateway is older than the stored providers; absent
   * reads as false. */
  is_serving_stale?: boolean;
  /** Served over the current UTC day; absent until usage is collected. */
  requests_today?: number;
  tokens_today?: number;
}

/**
 * One subscription the gateway is signed in to.
 *
 * `provider` and a login's `kind` name the same service differently — an
 * account carries the name of the credential file it was written to, a login
 * the name of the protocol it speaks — so neither is a closed set here.
 */
export interface CliproxyApiAccountView {
  /** The credential file this account lives in; its identifier in every path. */
  name: string;
  provider: string;
  label: string;
  email: string;
  account_type: string;
  status: string;
  status_message: string;
  is_disabled: boolean;
  is_unavailable: boolean;
  failed_count: number;
  success_count: number;
  created_at: string;
  updated_at: string;
}

/** Every account, and the sign-ins this gateway build actually offers. */
export interface CliproxyApiAccountsResponse {
  accounts: CliproxyApiAccountView[];
  login_kinds: string[];
}

/**
 * How a sign-in finishes: `redirect` lands the browser on a local address the
 * person brings back, `device` shows a code they type into the provider.
 */
export type CliproxyApiLoginFlow = "redirect" | "device";

export type CliproxyApiLoginStatus = "pending" | "complete" | "failed";

/** A sign-in as it starts: where to send the person, and how it comes back. */
export interface CliproxyApiLoginStartView {
  state: string;
  kind: string;
  url: string;
  flow: CliproxyApiLoginFlow;
  /** What the person types at the provider; empty on a redirect flow. */
  user_code: string;
  /** Seconds the code stays good; 0 where the flow sets no deadline. */
  expires_in: number;
}

/** A sign-in in flight, polled until it is one of the other two states. */
export interface CliproxyApiLoginStateView {
  state: string;
  status: CliproxyApiLoginStatus;
  message: string;
}

/** The Credentials page's AI provider section payload. */
export interface AiProvidersResponse {
  providers: AiProviderView[];
}

/** The serving order write: every provider id, in the order tried. */
export interface AiProviderOrderUpdate {
  provider_ids: string[];
}

export type AiUsageRange = "day" | "week" | "month" | "year";

/** Request and token rates averaged over the last 60 minutes. */
export interface AiUsageRates {
  rpm: number;
  tpm: number;
}

/** Counter set shared by usage totals, buckets, keys and providers. */
export interface AiUsageCounters {
  requests: number;
  failed: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
}

/** One time bucket of the usage series; hourly for day, daily otherwise. */
export interface AiUsageBucket extends AiUsageCounters {
  bucket: string;
}

/** One client key's usage; `client_name` when a client program holds the key. */
export interface AiUsageKey extends AiUsageCounters {
  key_id: string;
  name: string;
  client_name: string | null;
  /** The device whose CloudCLI holds the key; null for a client's key. */
  device_name: string | null;
  first_seen_at: string;
  last_seen_at: string;
}

/** One hourly slot of a provider's last-5h health window. */
export interface AiUsageHealthBucket {
  bucket: string;
  requests: number;
  failed: number;
}

/**
 * One upstream's usage over the range.
 *
 * An upstream is a keyed provider or a subscription account. `provider_id` is
 * the provider's id or the account's credential file, and `kind` the
 * provider's `AiProviderKind` or the account's service — which, like an
 * account's `provider`, is not a closed set.
 */
export interface AiUsageProvider extends AiUsageCounters {
  provider_id: string;
  name: string;
  kind: string;
  /** Whether this row is an account rather than a keyed provider; absent
   * reads as false. */
  is_account?: boolean;
  first_seen_at: string;
  last_seen_at: string;
  health: AiUsageHealthBucket[];
}

/** The `/cliproxyapi/usage` payload. */
export interface AiUsageResponse {
  range: AiUsageRange;
  generated_at: string;
  rates: AiUsageRates;
  totals: AiUsageCounters;
  series: AiUsageBucket[];
  keys: AiUsageKey[];
  providers: AiUsageProvider[];
}

/** The gateway's journal tail, most recent line last. */
export interface CliproxyApiJournalResponse {
  lines: string[];
}

/**
 * The SSH login the hub last installed this device's agent with.
 *
 * Every credential is a reference: `key_id` names a stored key and `login_id`
 * a stored login. No secret material crosses this shape, and a sudo password
 * is typed per install rather than kept.
 */
export interface DeviceSshConfig {
  host: string;
  port: number;
  username: string;
  auth: DeviceAuthMethod;
  key_id: string | null;
  login_id: string | null;
}

export interface DeviceGpuInfo {
  vendor: string;
  name: string;
  utilization_percent: number | null;
  memory_used_mb: number | null;
  memory_total_mb: number | null;
  temperature_c: number | null;
  power_w: number | null;
}

export interface DeviceProcessInfo {
  pid: number;
  user: string;
  name: string;
  cpu_percent: number;
  memory_percent: number;
}

/** What one machine last said about sharing its desktop. */
export interface DeviceRdp {
  is_shared: boolean;
  /** Whose desktop is shared; empty while nothing is. */
  account: string;
  /** The port a direct connection lands on; 0 while nothing is shared. */
  port: number;
  /** What somebody must do at that machine before a peer is shown its
   * desktop, as a code this panel words; empty when nothing stands in the
   * way. */
  attention: string;
  connected_count: number;
  /** Whether this machine's agent package carries the remote desktop host.
   * False only on a package built before it did. */
  is_available: boolean;
}

/** The agent's `machine.metrics`: one sample of the machine's health. */
export interface DeviceMetricsView {
  cpu_percent: number | null;
  cpu_core_percents: number[];
  memory_percent: number | null;
  disk_percent: number | null;
  temperature_c: number | null;
  uptime_s: number | null;
  /** The one, five and fifteen minute load averages; empty on Windows. */
  load_average: number[];
  gpus: DeviceGpuInfo[];
  processes: DeviceProcessInfo[];
}

/** What a managed machine's agent reports of itself. */
export interface DeviceClientInfo {
  version: string | null;
  /** What the agent reports it runs on: `linux`, `windows`, `darwin`. */
  platform_os: string | null;
  platform_arch: string | null;
  hostname: string | null;
  /** When its last report arrived. */
  last_report_at: string | null;
  /** When its session last ended; null while it is online. */
  last_seen: string | null;
  is_version_mismatched: boolean;
  /** The readings of its last report; null before its first. */
  metrics: DeviceMetricsView | null;
}

/** One install on a device, whatever asked for it: the agent's own over
 * SSH, or a module's install or uninstall whose lines its agent sent up. */
export interface DeviceInstallTaskView {
  task_id: string;
  /** The module installed or uninstalled; empty for the agent's own install. */
  module: string;
  /** The module's own title, so a failure reads beside the thing it was. */
  title: string;
  is_finished: boolean;
  exit_code: number | null;
  /** What the task printed. */
  output: string;
  started_at: string;
  finished_at: string;
}

/** Every install this device has run since the panel started, newest first. */
export interface DeviceInstallOutputResponse {
  tasks: DeviceInstallTaskView[];
}

/** Ask for a link a machine can join with, bound to a device or blank. */
export interface DeviceEnrollmentRequest {
  name: string;
  device_id: string | null;
}

export interface DeviceEnrollmentView {
  link: string;
  token: string;
  expires_in_s: number;
}

/** One enrolled client program on the Clients page. */
export interface ClientView {
  id: string;
  name: string;
  hostname: string;
  platform_os: string;
  version: string;
  is_online: boolean;
  last_seen: string | null;
  is_disabled: boolean;
  /** The kinds this client is allowed; null while it follows the default. */
  permission: string[] | null;
  /** With a permission of its own, the device ids each kind is narrowed to. */
  permission_devices: Record<string, string[]>;
  /** With a permission of its own, row id to on or off. */
  permission_entries: Record<string, boolean>;
  /** The seconds its link still works while it waits to join; null once it
   * joined. */
  link_expires_in_s: number | null;
}

/** A row the fine mode lists under a kind. */
export interface PermissionRowView {
  id: string;
  title: string;
  /** The machine providing it; empty for none known. */
  device_id: string;
  device_name: string;
}

export interface ClientListView {
  clients: ClientView[];
  /** The kinds a client with no set of its own is allowed. */
  default_permission: string[];
  /** The device ids each kind of the default is narrowed to. */
  default_permission_devices: Record<string, string[]>;
  /** The default's rows, row id to on or off. */
  default_permission_entries: Record<string, boolean>;
  /** Every kind, in the order the switches are drawn. */
  permission_kinds: string[];
  /** The rows the fine mode lists, by kind, in the Services page's order. */
  permission_rows: Record<string, PermissionRowView[]>;
  /** Newest first. */
  web_shares: WebShareView[];
  web_share_entries: WebShareEntryView[];
  web_share_sites: WebShareSiteView[];
}

/** How a Web share's visitor signs in to a web entry. */
export type WebShareGuestLogin = "app" | "guest_account" | "run_account";

/** Where a Web share stands. */
export type WebShareState = "active" | "preparing" | "unavailable" | "failed";

/** A Web share on the Clients page. */
export interface WebShareView {
  id: string;
  name: string;
  app_id: string;
  entry_id: string;
  app_title: string;
  device_name: string;
  /** ISO stamp of its end; null for a share that lasts until it is revoked. */
  expires_at: string | null;
  expires_in_s: number | null;
  state: WebShareState;
  code: string;
  params: Record<string, unknown>;
  online_count: number;
  /** The guest account's e-mail, empty for an entry with no guest account. */
  guest_email: string;
}

/** A web entry a new share can offer now. */
export interface WebShareEntryView {
  entry_id: string;
  app_id: string;
  title: string;
  device_name: string;
  guest_login: WebShareGuestLogin;
  /** The account a visitor uses the app as, for run_account; else empty. */
  visitor_account: string;
}

/** A site that serves the share page. */
export interface WebShareSiteView {
  url: string;
  title: string;
}

/** A new Web share; `days` null lasts until it is revoked. */
export interface WebShareCreateRequest {
  name: string;
  entry_id: string;
  days: number | null;
  site: string;
}

/** A new share and its link, which the hub returns this once. */
export interface WebShareCreatedView {
  link: string;
  share: WebShareView;
}

/** A request naming one Web share. */
export interface WebShareRevokeRequest {
  share_id: string;
}

/** A client's new name. */
export interface ClientUpdate {
  client_id: string;
  name: string;
}

/** A permission as a form sends it. */
export interface ClientPermissionFields {
  kinds: string[];
  /** Device ids by kind; a kind not named allows every device. */
  devices: Record<string, string[]> | null;
  /** Row id to on or off; a row not named follows its kind. */
  entries: Record<string, boolean> | null;
}

export type ClientDefaultPermissionRequest = ClientPermissionFields;

export interface ClientPermissionRequest {
  client_id: string;
  kinds: string[] | null;
  /** Device ids by kind; a kind not named allows every device. */
  devices: Record<string, string[]> | null;
  /** Row id to on or off; a row not named follows its kind. */
  entries: Record<string, boolean> | null;
}

/** A client's name and the permission it joins with; null follows the
 * default. */
export interface ClientEnrollmentRequest {
  name: string;
  permission: ClientPermissionFields | null;
}

/** The link a named client joins with, and when it lapses. */
export interface ClientEnrollmentView {
  link: string;
  client_id: string;
  expires_at: string;
  expires_in_s: number;
}

export interface DeviceFileEntry {
  name: string;
  path: string;
  is_dir: boolean;
  is_link: boolean;
  size_bytes: number;
  modified_at: number;
}

export interface DeviceFileListView {
  path: string;
  separator: string;
  entries: DeviceFileEntry[];
}

/** One managed machine, as the Agents page draws its row. */
export interface DeviceView {
  /** The binding id. */
  id: string;
  /** Its name; the host it was added by until it reports. */
  name: string | null;
  icon: string | null;
  ipv4_address: string;
  /** The MAC its agent last used on its link. */
  link_mac: string;
  /** Whether its agent holds a session now. */
  is_agent_online: boolean;
  /** The SSH login the hub last installed its agent with. */
  ssh: DeviceSshConfig | null;
  /** What its agent reports; null before it first reports. */
  client: DeviceClientInfo | null;
}

/** The Agents page's count: every machine, and those online. */
export interface DeviceCount {
  total: number;
  online: number;
}

export interface DevicesResponse {
  devices: DeviceView[];
  count: DeviceCount;
}

/** A write to one machine's row: its name, its icon, its SSH login, or the
 * module tabs its machine page shows. */
export interface DeviceAnnotation {
  device_id: string;
  name?: string;
  icon?: string;
  ssh?: DeviceSshConfig | null;
  shown_module?: string[];
}

export interface DeviceWolResult {
  is_sent: boolean;
  code: string;
  params: Record<string, string | number>;
}

/**
 * What installing the agent over SSH needs, on a machine added by the host
 * typed here.
 *
 * The credential is exactly one of the two the vault holds: a stored key or a
 * stored login. `sudo_login_id` is the stored login whose password sudo is
 * given on the device, and null where sudo asks for none.
 */
export interface DeviceAddRequest {
  host: string;
  port: number;
  username: string;
  key_id: string | null;
  login_id: string | null;
  sudo_login_id: string | null;
}

/** The same install, on a device on record. */
export interface DeviceAgentInstallRequest extends DeviceAddRequest {
  device_id: string;
}

/** The job an action started, followed on `/ws/hub/task`. */
export interface TaskStarted {
  task_id: string;
}

// --- Modules on devices ---

/** Where a module stands on one device, as its agent last reported. */
export interface ModuleDeviceState {
  /** Whether the agent on this device is answering. */
  is_online: boolean;
  /** absent, installed, stopped, running, installing, uninstalling, queued,
   * failed, install_failed or unsupported; unknown until the agent has
   * reported. */
  state: string;
  /** Why the state is what it is; the panel words it. Empty when there is
   * nothing to say. */
  code: string;
  params: Record<string, unknown>;
}

/** One module a device could run, as its agent last reported it beside
 * what the hub asks of it. */
export interface DeviceModuleView {
  name: string;
  /** The manifest's title. */
  title: string;
  /** The install method of its entry for the machine's platform. */
  method: string;
  /** absent, installed, stopped or running; empty when the hub asks nothing. */
  want: string;
  state: string;
  is_active: boolean;
  /** The version installed, as the machine reports it. */
  version: string;
  code: string;
  params: Record<string, unknown>;
  details: Record<string, unknown>;
  is_supported: boolean;
  /** Whether the agent's package carries it: Terminal, Remote desktop and
   * the SSH server. */
  is_carried: boolean;
  /** Whether its tab is on the machine page. */
  is_shown: boolean;
  /** The line the uninstall dialog shows under its body. Null for a module
   * the agent carries. */
  uninstall_data: ModuleUninstallData | null;
  /** Whether the hub holds a configuration for the module on this device;
   * the first Configure imports one from the machine where it holds none. */
  is_configured: boolean;
  /** The task carrying the module's last install or uninstall lines, to
   * follow on `/ws/hub/task`; empty when none has run. */
  task_id: string;
}

/** What an uninstall does to a module's data, as the manifest words it. */
export interface ModuleUninstallData {
  /** True when the data goes with the module. */
  is_deleted: boolean;
  /** The line in each language of the panel, keyed `en` and `zh-CN`. */
  text: Record<string, string>;
}

export interface DeviceModuleListView {
  modules: DeviceModuleView[];
  is_agent_online: boolean;
  /** Set on Windows and macOS while the container modules need more memory
   * than the Podman machine has; null otherwise. */
  memory_need: PodmanMemoryNeed | null;
}

/** A request naming one device. */
export interface DeviceRequest {
  device_id: string;
}

/** One module on one device, for the four presses under `/agent/module`. */
export interface DeviceModuleRequest {
  device_id: string;
  module: string;
}

/** One module of the catalog, as the **+ Add module** dialog draws its card. */
export interface ModuleCatalogEntry {
  name: string;
  /** The manifest's title, or the catalog's for a module with no manifest. */
  title: string;
  /** The activity filter it sits under. */
  category: string;
  /** False for a module the hub has no manifest of yet. */
  is_available: boolean;
  /** Whether the machine's platform has an entry. */
  is_supported: boolean;
  is_carried: boolean;
  is_shown: boolean;
  /** As last reported. */
  state: string;
}

export interface ModuleCatalogView {
  /** The activity filters, in their order. */
  categories: string[];
  modules: ModuleCatalogEntry[];
}

/** One listed version of a module. */
export interface ModuleVersionEntry {
  version: string;
  is_tested: boolean;
  /** Newer than the tested one. */
  is_untested: boolean;
}

/** A module's versions on one machine. */
export interface ModuleVersionView {
  /** The version the machine reports installed. */
  installed: string;
  /** The machine's choice; empty while it follows the tested one. */
  chosen: string;
  tested: string;
  newest: string;
  is_locked: boolean;
  /** Newest first. */
  versions: ModuleVersionEntry[];
  is_data_forward_only: boolean;
  /** When the feeds were last read. */
  read_at: string;
}

/** A module's version chosen; empty to follow the tested one. */
export interface ModuleVersionSetRequest {
  device_id: string;
  module: string;
  version: string;
}

// --- Available accounts ---

/** A tool's choices: Claude's slots, Codex's model and effort, Gemini's model. */
export type AiToolConfigs = Record<string, Record<string, string>>;

/** An account's last AI tools result, as the machine reported it. */
export interface AccountAiToolsView {
  /** `switched`, `switched_back` or `failed`; empty before it reported. */
  state: string;
  code: string;
  params: Record<string, unknown>;
}

/** One available account of a machine. */
export interface AvailableAccountView {
  account: string;
  /** Whether the vault holds its Windows login. */
  has_login: boolean;
  /** Empty for the account's home. */
  share_path: string;
  /** Empty for the account's login shell. */
  shell_path: string;
  is_ai_tools_enabled: boolean;
  tool_configs: AiToolConfigs;
  /** The modules that enable it. */
  modules: string[];
  ai_tools: AccountAiToolsView;
}

/** One account the machine reports, with its defaults. */
export interface SystemAccountView {
  account: string;
  home: string;
  shell: string;
}

export interface AccountListView {
  /** In the order they were added. */
  accounts: AvailableAccountView[];
  system_accounts: SystemAccountView[];
  platform_os: string;
  /** The names the gateway serves, for the model pickers. */
  models: string[];
  is_gateway_serving: boolean;
}

/** An account added or replaced; `password` on Windows alone, empty to keep
 * the login on an edit. */
export interface AccountSetRequest {
  device_id: string;
  account: string;
  password: string;
  share_path: string;
  shell_path: string;
  is_ai_tools_enabled: boolean;
  tool_configs: AiToolConfigs;
}

export interface AccountRemoveRequest {
  device_id: string;
  account: string;
}

/** One available account as an account-layer module's tab lists it. */
export interface EnabledAccountView {
  account: string;
  is_enabled: boolean;
  port: number;
  is_running: boolean;
  code: string;
  params: Record<string, unknown>;
  /** Terminal's field: the account's shell. */
  shell_path?: string;
  /** The file share's fields: the share path and the SMB user. */
  share_path?: string;
  user?: string;
}

/** An account-layer module on one machine: Terminal, the file share, the SSH
 * server, VS Code, code-server, CloudCLI or Codeg. */
export interface EnabledAccountsView extends ModuleDeviceState {
  device_id: string;
  accounts: EnabledAccountView[];
  /** The SSH server's host key, `SHA256:<base64>`. */
  host_key_fingerprint?: string;
  /** VS Code's: whether the person accepted Microsoft's terms here. */
  is_terms_accepted?: boolean;
  /** VS Code's: the address of the terms. */
  terms_url?: string;
  /** The version the machine reports; empty before it reports one. */
  version?: string;
}

/** The enabled accounts, in the order they were checked. */
export interface EnabledAccountsUpdate {
  device_id: string;
  accounts: string[];
}

/** A named share at a folder, open to the accounts checked. */
export interface FolderShareView {
  name: string;
  path: string;
  /** The accounts checked for it, in the file share's order. */
  accounts: string[];
}

/** A machine's folder shares and the accounts a folder share can name. */
export interface FolderShareListView {
  /** In the order they were added. */
  shares: FolderShareView[];
  /** The file share's enabled accounts as applied, in their order. */
  accounts: string[];
}

/** A folder share being added, or replaced under its name. */
export interface FolderShareUpdate {
  device_id: string;
  name: string;
  path: string;
  accounts: string[];
}

/** A folder share being removed. */
export interface FolderShareRemove {
  device_id: string;
  name: string;
}

// --- Services ---

export type PublishedServiceType =
  "web" | "port" | "ssh" | "ai" | "file" | "rdp";

/** The type's own payload; each entry fills the fields its type has. */
export interface PublishedServicePayload {
  url?: string;
  host?: string;
  port?: number;
  endpoint?: string;
  /** port: `tcp` or `udp`; file: `smb`. */
  protocol?: string;
  models?: string[];
  share?: string;
  users?: string[];
  /** rdp: what somebody must do at the sharing machine, as a code. */
  attention?: string;
  /** rdp: the sharing machine's `linux`, `windows` or `darwin`. */
  platform_os?: string;
  /** ssh: the account the instance runs as. file: the account a folder
   * share's entry logs in as, empty on any other share. */
  account?: string;
  /** ssh: the machine's host key, `SHA256:<base64>`. */
  host_key_fingerprint?: string;
  /** web: whether the page opens with a token the hub hands. */
  is_token_required?: boolean;
}

/**
 * One entry that belongs to no app: the AI gateway, a shared desktop, a
 * machine's file share.
 */
export interface PublishedService {
  id: string;
  type: PublishedServiceType;
  title: string;
  payload: PublishedServicePayload;
  is_healthy: boolean | null;
  /** A hub module, a person's declaration, or a machine sharing its
   * desktop. */
  source: "module" | "declared" | "device";
  /** The English provenance line, shown where no code words it. */
  description: string;
  /** Where the entry comes from, worded by the page. */
  description_code: string;
  description_params: Record<string, string | number>;
  device_id: string;
  device_name: string;
}

/** Who answers for an app. */
export type AppSource = "module" | "declared" | "manual";

/** One entry of an app. */
export interface AppEntryView {
  /** `<app id>_<name>`. */
  id: string;
  /** The entry's name inside its app. */
  name: string;
  type: PublishedServiceType;
  payload: PublishedServicePayload;
  /** Null on an entry no probe has reached, and on a UDP port. */
  is_healthy: boolean | null;
  /** The port a client forwards it on; 0 on a file entry. */
  local_port: number;
  /** What a declared entry's last probe measured, null when it answered. */
  detail_code: string | null;
  /** How a Web share's visitor signs in to a web entry; empty on an entry
   * of another type. */
  guest_login: WebShareGuestLogin | "";
}

/** One program on one machine, with one or more entries. */
export interface AppView {
  id: string;
  title: string;
  source: AppSource;
  device_id: string;
  /** The machine that provides it; empty when no machine the hub knows is
   * there. */
  device_name: string;
  local_name: string;
  description: string;
  entries: AppEntryView[];
}

/** The Services page: a module's apps first, then the declared, then the
 * manual; and the entries of no app. */
export interface ServiceListView {
  apps: AppView[];
  services: PublishedService[];
}

export type DeclaredEntryType = "web" | "port" | "file";

/** One entry of an app declared by hand. */
export interface DeclaredEntryCreate {
  type: DeclaredEntryType;
  /** Empty on a file entry for 445. */
  port: number | null;
  /** web: `http` or `https`. */
  scheme: string | null;
  /** web: the path the page opens at. */
  path: string | null;
  /** port: `tcp` or `udp`. */
  protocol: "tcp" | "udp" | null;
  /** file: the SMB share's name. */
  share: string | null;
}

/** An app declared on the Services page. */
export interface DeclaredAppCreate {
  name: string;
  host: string;
  description: string;
  entries: DeclaredEntryCreate[];
}

/** A request naming one declared app. */
export interface DeclaredAppRequest {
  app_id: string;
}

export interface ServiceJournal {
  text: string;
}

// --- Settings ---

export interface PasswordChangeRequest {
  current_password: string;
  new_password: string;
}

export interface PasswordChangeResult {
  is_changed: boolean;
}

export interface RestoreResult {
  is_restored: boolean;
  task_id: string;
}

/** The panel's own settings. */
/** The panel's scheme and the certificates behind it. */
export interface PanelHttpsView {
  /** Whether the HTTP port sends every browser to the HTTPS port. */
  is_https_enabled: boolean;
  /** The port the panel answers HTTP on. */
  listen_port: number;
  /** The port the panel answers HTTPS on, whatever the scheme setting. */
  https_listen_port: number;
  has_authority: boolean;
  /** SHA-256 of the authority's DER, as hex; empty without one. */
  authority_fingerprint: string;
  authority_created_at: string | null;
  /** What the downloaded authority is called. */
  authority_file_name: string;
  /** The addresses and names the served certificate carries. */
  leaf_names: string[];
  leaf_issued_at: string | null;
  leaf_expires_at: string | null;
  /** When it was last issued again; null when not since the panel started. */
  renewed_at: string | null;
}

/** The certificates after the authority was made again. */
export interface PanelHttpsResetView extends PanelHttpsView {
  /** The new authority's DER in base64, downloaded at once. */
  authority_der: string;
}

export interface PanelSettings {
  /** The port the panel answers HTTP on. */
  listen_port: number;
  /** The port the panel answers HTTPS on. Left out of a write, it stays. */
  https_listen_port: number;
  /** The port agents and clients connect to. Left out of a write, it stays. */
  agent_listen_port: number;
  /** The language the panel is drawn in. Left out of a write, it stays. */
  language: string;
  /** The palette the panel is drawn in. Left out of a write, it stays. */
  theme: string;
  /** The name clients show this hub as. Left out of a write, it stays. */
  hub_name: string;
}

/** The panel's own settings, with the peers an agent port change loses. */
export interface SettingsView extends PanelSettings {
  /** The clients with a binding row and no live session at this moment. */
  offline_client_count: number;
  /** The agents with a binding row and no live session at this moment. */
  offline_agent_count: number;
}

/**
 * The language and the palette the panel is drawn in, and the hub's update
 * under way or finished in the last 30 minutes, answered before there is a
 * session.
 */
export interface PanelDisplay {
  language: string;
  theme: string;
  update: HubUpdateProgress | null;
}

/** One component the hub's package carries, with its license and exact
 * source. */
export interface Acknowledgement {
  name: string;
  version: string;
  license: string;
  corresponding_source: string;
}

export interface AboutInfo {
  xray_version: string;
  gateway_version: string;
  cliproxyapi_version: string;
  python_version: string;
  geodata_version: string;
  kernel: string;
  os: HubOs;
  /** The macOS release, the Windows build, or the kernel release on Linux. */
  os_version: string;
  uptime_s: number;
  acknowledgements: Acknowledgement[];
}

export type HubUpdateStage =
  | "preparing"
  | "installing"
  | "installed"
  | "rolling_back"
  | "rolled_back"
  | "failed";

export interface HubUpdateRecord {
  stage: HubUpdateStage;
  from_version: string;
  to_version: string;
  started_at: string;
  finished_at: string;
  reason: string;
  output: string;
  /** The update's short lines, one stage each. */
  steps: string[];
}

/** Where an update of the hub stands, as a page without a session reads it. */
export interface HubUpdateProgress {
  stage: HubUpdateStage;
  from_version: string;
  to_version: string;
  finished_at: string;
}

/** The kind of package the hub was installed from; empty in a checkout. */
export type HubPackageFamily = "" | "deb" | "rpm" | "arch" | "msi" | "pkg";

export interface HubReleaseView {
  current: string;
  is_packaged: boolean;
  package_family: HubPackageFamily;
  /** The directory the hub writes its logs to. */
  log_root: string;
  update: HubUpdateRecord | null;
  task_id: string | null;
}

export interface HubReleaseLatest {
  version: string;
  size_bytes: number;
}

export interface HubReleaseScanView {
  current: string;
  latest: HubReleaseLatest | null;
  /** Whether the newest release carries a package of this hub's family. */
  has_package: boolean;
  is_newer: boolean;
  is_major: boolean;
  is_rollback_available: boolean;
  needed_bytes: number;
  free_bytes: number;
  is_space_enough: boolean;
}

export interface HubUpdateRequest {
  version: string;
}

// --- Samba ---

export interface SambaSession {
  username: string;
  hostname: string;
  remote_address: string;
  shares: string[];
}

export interface SambaDisk {
  share: string;
  total_bytes: number;
  free_bytes: number;
}

export interface SambaStatus {
  is_active: boolean;
  sessions: SambaSession[];
  disks: SambaDisk[];
}

// --- Gitea ---

export interface GiteaSettings {
  listen_port: number;
  /** Empty derives http://<LAN address>:<port>/ on the gateway. */
  root_url: string;
  is_registration_enabled: boolean;
  is_installed: boolean;
  is_active: boolean;
  version: string;
  /**
   * False until the first administrator is made — and with registration off,
   * a Gitea with no accounts is one nobody can enter.
   */
  has_admin: boolean;
  admin_usernames: string[];
}

/** Gitea on one device: its settings, and where the module stands there. */
export interface GiteaDeviceView extends GiteaSettings, ModuleDeviceState {}

/** The person's acceptance of Microsoft's terms for one machine. */
export interface VscodeTermsUpdate {
  device_id: string;
  is_accepted: boolean;
}

/** One machine's Remote desktop module: the switch and where it stands. */
export interface RemoteDesktopDeviceView extends ModuleDeviceState {
  device_id: string;
  host: string;
  is_enabled: boolean;
  /** `linux`, `windows` or `darwin`; empty before the machine reported. */
  platform_os: string;
  /** The machine's own word on its desktop, from its last report; null
   * before it reported. */
  rdp: DeviceRdp | null;
}

export interface RemoteDesktopConfigUpdate {
  device_id: string;
  is_enabled: boolean;
}

/** One machine's Hermes WebUI: the forwarder's port and where the module stands. */
export interface HermesWebuiDeviceView extends ModuleDeviceState {
  device_id: string;
  host: string;
  /** The forwarder's port as the machine reports it. */
  port: number;
  /** The version the machine reports; empty before it reports one. */
  version: string;
  /** What the machine last reported: `{version, port}`. */
  details: Record<string, unknown>;
}

/** One machine's Ayakaleaf: the forwarder's port, the AI model and where the
 * module stands. */
export interface AyakaleafDeviceView extends ModuleDeviceState {
  device_id: string;
  host: string;
  /** The forwarder's port as the machine reports it. */
  port: number;
  /** The tab's AI model; empty for the gateway's first. */
  model: string;
  /** The names the gateway serves, for the picker. */
  models: string[];
  is_gateway_serving: boolean;
  /** The version the machine reports; empty before it reports one. */
  version: string;
  /** What the machine last reported: `{version, port, guests}`. */
  details: Record<string, unknown>;
}

/** The AI model Ayakaleaf's app uses on one machine; empty for the gateway's
 * first. */
export interface AyakaleafModelUpdate {
  device_id: string;
  model: string;
}

export interface GiteaConfigUpdate {
  device_id: string;
  listen_port: number;
  root_url: string;
  is_registration_enabled: boolean;
}

export interface GiteaAdminCreate {
  device_id: string;
  username: string;
  password: string;
  email: string;
}

// --- Overlay ---

/** One overlay engine, as the Overlay page lists it. */
export interface OverlayKindView {
  /** What config/ names it by. */
  key: string;
  /** The product's own name, the same in every language. */
  title: string;
  /** Whether the hub runs it. */
  is_enabled: boolean;
  /** Whether this hub can run it at all yet. */
  is_integrated: boolean;
  /** Whether there is a build of it for this machine. */
  is_supported: boolean;
  is_installed: boolean;
  is_active: boolean;
  /** How many online clients reach the hub through it now. */
  client_count: number;
}

/** A route a running overlay installed that the hub refused. */
export interface OverlayRouteConflictView {
  /** overlay_default_route_refused or overlay_route_overlap. */
  code: string;
  /** {title, route, conflict}. */
  params: Record<string, string>;
  /** Whether the hub took the route away. */
  is_withdrawn: boolean;
}

export interface OverlayChoiceView {
  kinds: OverlayKindView[];
  route_conflicts: OverlayRouteConflictView[];
}

/** Whether one engine runs. */
export interface OverlayEngineSwitch {
  is_enabled: boolean;
}

/** The engines to turn on or off; one left out keeps what it has. */
export interface OverlayChoiceRequest {
  netbird?: OverlayEngineSwitch;
  easytier?: OverlayEngineSwitch;
  relay?: OverlayEngineSwitch;
  direct?: OverlayEngineSwitch;
  sakurafrp?: OverlayEngineSwitch;
  openfrp?: OverlayEngineSwitch;
}

// --- Direct ---

export interface DirectView {
  is_enabled: boolean;
  public_host: string;
  public_port: number;
  /** What Direct adds to `urls`: every enabled interface's address that is
   * not exposed, then the stated public address. */
  urls: string[];
  /** Whether Direct adds an interface's address (`added`), adds none because
   * every one already answers (`exposed`), or finds none (`none`). */
  interface_state: DirectInterfaceState;
}

export type DirectInterfaceState = "added" | "exposed" | "none";

export interface DirectSetRequest {
  public_host: string;
  public_port: number;
}

// --- Relay ---

/** The relay's state codes, network.md "The states". */
export type RelayState =
  | "disabled"
  | "not_configured"
  | "vault_locked"
  | "connecting"
  | "connected"
  | "port_closed"
  | "auth_failed"
  | "host_key_changed"
  | "forward_refused"
  | "unreachable";

export interface RelayView {
  is_enabled: boolean;
  host: string;
  ssh_port: number;
  account: string;
  /** The SSH key the relay logs in with; empty with a login. */
  key_id: string;
  /** The login whose password the relay logs in with; empty with a key. */
  login_id: string;
  public_port: number;
  /** The address the relay adds to `urls`; empty while not configured. */
  url: string;
  state: RelayState;
  /** The recorded host key as `SHA256:<base64>`; empty when none is. */
  host_key_fingerprint: string;
  last_error: string;
  /** The last check's time in ISO 8601; empty before the first. */
  checked_at: string;
}

/** Exactly one of `key_id` and `login_id`, as the agent install names it. */
export interface RelaySetRequest {
  host: string;
  ssh_port: number;
  account: string;
  key_id: string | null;
  login_id: string | null;
  public_port: number;
}

// --- SakuraFrp and OpenFrp ---

/** A frp way in's state codes, network.md "The frp states". */
export type FrpState =
  | "disabled"
  | "not_signed_in"
  | "vault_locked"
  | "no_tunnel"
  | "loopback_port_taken"
  | "config_failed"
  | "connecting"
  | "connected"
  | "proxy_refused"
  | "port_closed"
  | "login_failed"
  | "unreachable";

/** One frp vendor's way in, read with no call to the vendor. */
export interface FrpView {
  is_enabled: boolean;
  is_signed_in: boolean;
  /** The vendor's id of the picked tunnel; empty for none. */
  tunnel_id: string;
  node_name: string;
  /** The picked tunnel's local port at the vendor. */
  local_port: number;
  /** The address the tunnel adds to `urls`; empty while none is picked. */
  url: string;
  state: FrpState;
  /** frpc's last line before it exited, or the failed check's reason. */
  last_error: string;
  /** The last check's time in ISO 8601; empty before the first. */
  checked_at: string;
  /** The vendor's console. */
  console_url: string;
}

/** Where OpenFrp's browser login stands. */
export type OpenFrpLoginState = "idle" | "waiting" | "timed_out" | "failed";

export interface OpenFrpLoginView {
  state: OpenFrpLoginState;
  /** The address the person confirms at while `waiting`; empty otherwise. */
  authorization_url: string;
}

export interface OpenFrpView extends FrpView {
  /** Whether OpenFrp answered 401 to the stored `Authorization`. */
  is_login_expired: boolean;
  login: OpenFrpLoginView;
}

/** A node's region, network.md "The tunnel list". */
export type FrpRegion = "mainland" | "hk_mo_tw" | "abroad" | "outside_mainland";

export interface FrpTunnelView {
  tunnel_id: string;
  name: string;
  node_name: string;
  region: FrpRegion;
  /** The hub's TCP connect time to the node; null when none finished in
   * time. */
  latency_ms: number | null;
  is_picked: boolean;
}

export interface FrpTunnelListView {
  tunnels: FrpTunnelView[];
}

/** An empty key forgets the stored one. */
export interface FrpAccessKeySetRequest {
  access_key: string;
}

export interface FrpTunnelSetRequest {
  tunnel_id: string;
}

// --- NetBird ---

export interface NetbirdPeer {
  fqdn: string;
  netbird_ip: string;
  is_connected: boolean;
  /** P2P when direct, Relayed when through a relay. */
  connection_type: string;
  latency_ms: number | null;
  rx_bytes: number | null;
  tx_bytes: number | null;
  /** Seconds since the tunnel to this peer last shook hands. */
  last_handshake_s: number | null;
}

export interface NetbirdView {
  is_installed: boolean;
  is_active: boolean;
  version: string;
  daemon_status: string;
  is_enrolled: boolean;
  is_management_connected: boolean;
  management_url: string;
  netbird_ip: string;
  fqdn: string;
  peers: NetbirdPeer[];
  /** The LAN networks whose routes belong on the management plane. */
  lan_subnets: string[];
  /** Whether a setup key is kept for the clients admitted to the overlay. */
  has_setup_key: boolean;
}

/** One node on the EasyTier network, as this box sees it. */
export interface EasyTierPeer {
  hostname: string;
  address: string;
  /** local, direct, relayed or unknown. */
  link: string;
  /** The tunnel it is reached over, the engine's own word. */
  protocol: string;
  latency_ms: number | null;
  /** Share of packets lost, 0 to 1. */
  loss_ratio: number | null;
  rx_bytes: number | null;
  tx_bytes: number | null;
  nat_type: string;
  version: string;
  is_connected: boolean;
}

/** This box on its own EasyTier network. */
export interface EasyTierNode {
  is_connected: boolean;
  address: string;
  hostname: string;
  nat_type: string;
}

/** One network of this machine's own, offered for export. */
export interface EasyTierSuggestedNetwork {
  cidr: string;
  interface: string;
}

/** One network the engine runs, as it reports it; read-only. */
export interface EasyTierInstance {
  instance_name: string;
  network_name: string;
  address: string;
  hostname: string;
  subnet_routes: string[];
  /** Which of network_name, address and hostname came back empty. */
  withheld: string[];
}

/** Where the network comes from. */
export type EasyTierMode = "manual" | "console";

export interface EasyTierView {
  is_installed: boolean;
  is_active: boolean;
  version: string;
  mode: EasyTierMode;
  has_config_server: boolean;
  is_secure_mode: boolean;
  /** What the engine reports it runs; filled in console mode. */
  instances: EasyTierInstance[];
  network_name: string;
  is_secret_set: boolean;
  /** This box's address on the overlay; empty means the engine assigns one. */
  address: string;
  hostname: string;
  /** What this box connects to when it starts. */
  peers: string[];
  exported_networks: string[];
  suggested_networks: EasyTierSuggestedNetwork[];
  /** What another machine dials to reach this one. */
  join_host: string;
  node: EasyTierNode | null;
  live_peers: EasyTierPeer[];
}

/** Every EasyTier setting, applied at once. */
export interface EasyTierSettingsRequest {
  mode: EasyTierMode;
  /** Null keeps the stored console address; empty forgets it. */
  config_server: string | null;
  is_secure_mode: boolean;
  network_name: string;
  /** Empty keeps the secret already stored. */
  network_secret: string;
  address: string;
  hostname: string;
  peers: string[];
  exported_networks: string[];
}

export interface EasyTierSuggestion {
  network_name: string;
  network_secret: string;
  address: string;
}

export interface EasyTierSecret {
  network_secret: string;
}

export interface NetbirdJoinRequest {
  setup_key: string;
  management_url: string;
}

// --- Containers ---

export type PodmanServiceKind = "auto" | "web" | "port";
export type PodmanServiceScheme = "http" | "https";
export type PodmanServiceProtocol = "tcp" | "udp";

/** The service type of one host port of a declared container. */
export interface PodmanService {
  port: number;
  kind: PodmanServiceKind;
  /** A web port's scheme. */
  scheme: PodmanServiceScheme;
  /** What a port port publishes, at least one. */
  protocols: PodmanServiceProtocol[];
}

export interface PodmanContainer {
  name: string;
  image: string;
  /** host:container, or host:container/udp. */
  ports: string[];
  /** source:destination; absolute source binds a host path, bare name is a named volume. */
  volumes: string[];
  /** KEY=value lines. */
  environment: string[];
  /** Overrides the image's own command; empty keeps the default. */
  command: string;
  is_autostart: boolean;
  /** One per host port; a port with none is auto. */
  services: PodmanService[];
}

/** One published host port of a container, as the machine reported it. */
export interface PodmanHostBinding {
  /** Empty for every address. */
  address: string;
  port: number;
  protocol: PodmanServiceProtocol;
  /** http, https or tcp once probed on a running container; empty before and on UDP. */
  detected: string;
}

/** Where a container comes from: a module of the hub's, the hub's
 * declarations, or a person who started it by hand. */
export type PodmanContainerSource = "hub" | "declared" | "manual";

export interface PodmanContainerState {
  name: string;
  image: string;
  status: string;
  is_running: boolean;
  source: PodmanContainerSource;
  /** The module its label names; empty for any other container. */
  module: string;
  host_bindings: PodmanHostBinding[];
}

/** A hub container's image: its digest and the references that serve it. */
export interface PodmanHubImage {
  digest: string;
  sources: string[];
}

/** One container a container module runs, as the hub composes it. */
export interface PodmanHubContainer {
  module: string;
  name: string;
  image: PodmanHubImage;
  ports: string[];
  volumes: string[];
}

/** The Run settings as stored: the account whose Podman machine runs the
 * containers, the vault login it signs in with on Windows, and the machine's
 * resources, each 0 for Podman's default. */
export interface PodmanMachine {
  account: string;
  cpus: number;
  memory_gib: number;
  disk_gib: number;
}

/** The Podman machine as the computer last reported it. */
export interface PodmanMachineState {
  account: string;
  is_running: boolean;
  cpus: number;
  memory_gib: number;
  /** The size of its disk now, the least a disk limit can be. */
  disk_gib: number;
  /** The memory a 0 in the Run settings gives on this computer. */
  default_memory_gib: number;
}

/** The memory the machine's container modules need, beside the Podman
 * machine's memory. */
export interface PodmanMemoryNeed {
  /** The sum of their `memory_mib`, in whole GiB rounded up. */
  need_gib: number;
  memory_gib: number;
}

export interface PodmanSettings {
  containers: PodmanContainer[];
  /** The containers the machine's container modules run, read only. */
  hub_containers: PodmanHubContainer[];
  /** docker.io mirrors, tried in order before the registry itself. */
  mirrors: string[];
  running: PodmanContainerState[];
  is_installed: boolean;
  is_active: boolean;
  version: string;
  /** The machine's available accounts, for the Run settings. */
  accounts: string[];
  /** The Run settings on Windows and macOS; null on Linux. */
  machine: PodmanMachine | null;
  /** The Podman machine as last reported; null until one is. */
  machine_state: PodmanMachineState | null;
  /** Set on Windows and macOS while the container modules need more memory
   * than the Podman machine has; null otherwise. */
  memory_need: PodmanMemoryNeed | null;
}

/** Podman on one device: its settings, and where the module stands there. */
export interface PodmanDeviceView extends PodmanSettings, ModuleDeviceState {}

/** The Run settings being saved. */
export interface PodmanMachineUpdate {
  device_id: string;
  /** An available account; a Windows machine signs in with its login. */
  account: string;
  cpus: number;
  memory_gib: number;
  disk_gib: number;
}

// --- Websocket frames ---

/** Client to server on `/ws/agent/terminal`. */
export type TerminalClientMessage =
  | { type: "input"; data: string }
  | { type: "resize"; cols: number; rows: number };

/** Server to client on a shell socket and on `/ws/hub/task`. */
export type StreamServerMessage =
  | { type: "output"; data: string }
  | { type: "exit"; code: number }
  | { type: "done"; exit_code: number };
