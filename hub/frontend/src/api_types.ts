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

export type BalancerStrategy = "leastPing" | "roundRobin" | "random";

/** What the whole machine is set up as. */
export type NetworkModeKey = "server" | "side_gateway" | "router";

export type DeviceAuthMethod = "key" | "password";

export type DeviceActionName = "install_client" | "reboot" | "shutdown";

/** One remote-desktop product's state on a device. */
export interface RemoteDesktopStatus {
  product: "anydesk";
  is_installed: boolean;
  is_running: boolean;
  /** Why the device could not be asked, empty when it was. A machine that is
   * off and one without the software are not the same answer. */
  unreachable: string;
  session_id: string | null;
  can_set_password: boolean;
}

/** The remote-desktop product's state on a device. */
export interface RemoteDesktopView {
  anydesk: RemoteDesktopStatus;
  /** The id a peer connects to RustDesk by, off the module's own report. */
  rustdesk_id: string;
}

export type ModuleActionName =
  "start" | "stop" | "restart" | "enable" | "disable";

// --- Auth ---

export interface AuthState {
  /** Seconds until login opens again after repeated failures; 0 when open. */
  lockout_remaining_s: number;
  is_authenticated: boolean;
  /** This panel process's start moment; a new value is a restarted panel. */
  panel_started_at: string;
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
  is_enabled: boolean;
  has_reality: boolean;
  is_alive: boolean;
  delay_ms: number | null;
  uplink_bytes: number;
  downlink_bytes: number;
}

export interface BalancerSettings {
  strategy: BalancerStrategy;
  probe_url: string;
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

export interface NodeTestResult {
  tag: string;
  is_alive: boolean;
  delay_ms: number | null;
}

/** A share link to add as a node. */
export interface NodeCreateRequest {
  link: string;
}

export interface ApplyResult {
  is_applied: boolean;
  message: string;
}

// --- Dashboard and live stats ---

export interface TrafficSample {
  label: string;
  received_bytes: number;
  sent_bytes: number;
}

export interface TrafficHistoryResponse {
  samples: TrafficSample[];
}

export interface OutboundTraffic {
  tag: string;
  uplink_bytes: number;
  downlink_bytes: number;
}

export interface NodeProbe {
  tag: string;
  is_alive: boolean;
  delay_ms: number | null;
}

/**
 * Whose traffic the proxy is taking, read from the applied ruleset: the
 * master switch is off; on but nothing is sent to it; only the SOCKS ports
 * reach it; the forwarded network is diverted; the hub's own traffic is; or
 * both are.
 */
export type ProxyScope =
  "off" | "unused" | "ports" | "lan" | "hub" | "lan_and_hub";

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
  /** How the balancer spreads traffic: leastPing has one exit, the others do not. */
  balancer_strategy: BalancerStrategy;
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
   * Whether what this box listens on answers on this interface. Read-only
   * here: the whole set is written at once by the panel that shows every
   * interface, so a save of one interface cannot reopen or close it.
   */
  is_exposed: boolean;
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
}

export interface InterfaceView {
  settings: InterfaceSettings;
  link: InterfaceLink;
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

/** One mode, as the Mode panel lists it. */
export interface NetworkMode {
  key: NetworkModeKey;
  summary: string;
  is_addressing_owned: boolean;
  caution: string;
}

export interface NetworkView {
  /** What this whole machine is; the page below the Mode panel follows it. */
  mode: NetworkModeKey;
  modes: NetworkMode[];
  interfaces: InterfaceView[];
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

export interface NetworkOptions {
  uplink_policy: UplinkPolicy;
  is_inter_lan_allowed: boolean;
  /** The interfaces that answer, by name. Everything else is closed. */
  exposed_interfaces: string[];
}

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
  /** The master switch: off takes the proxy out of the path entirely. */
  is_proxy_enabled: boolean;
  is_direct_fallback_enabled: boolean;
  is_geoip_split_enabled: boolean;
  direct_domains: string[];
  direct_ips: string[];
  is_local_proxy_enabled: boolean;
  socks_ports: SocksPort[];
  remote_dns: DnsServer;
  direct_dns: DnsServer;
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
  probe_message: string;
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

/** One client key's usage; `device_name` when a device owns the key. */
export interface AiUsageKey extends AiUsageCounters {
  key_id: string;
  name: string;
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
 * SSH credentials for a device.
 *
 * Every credential is a reference: `key_id` names a stored key, `password_id`
 * and `sudo_password_id` name vault login objects. No secret material
 * crosses this shape; `key_name` is the resolved label for display.
 */
export interface DeviceSshConfig {
  host: string;
  port: number;
  username: string;
  auth: DeviceAuthMethod;
  key_id: string | null;
  key_name: string | null;
  password_id: string | null;
  sudo_password_id: string | null;
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

/** The most recent error an agent reported; the pages do the wording. */
export interface DeviceClientError {
  code: string;
  params: Record<string, unknown>;
}

/** How one queued command went, as the agent reported it back. */
export interface DeviceCommandResult {
  id: string;
  exit_code: number;
  output: string;
  finished_at: string;
}

export interface DeviceClientInfo {
  /** An agent that completed its handshake and still holds a token; a
   * failed install never reads managed. */
  is_managed: boolean;
  /** Whether the agent is answering inside the heartbeat window. */
  is_online: boolean;
  version: string | null;
  is_version_mismatched: boolean;
  last_seen: string | null;
  /** What the agent reports it runs on: `linux`, `windows`, `darwin`. Null
   * until it beats again after a panel restart, since it is never stored. */
  platform_os: string | null;
  platform_arch: string | null;
  hostname: string | null;
  cpu_percent: number | null;
  memory_percent: number | null;
  disk_percent: number | null;
  temperature_c: number | null;
  uptime_s: number | null;
  load_average: number[];
  cpu_core_percents: number[];
  gpus: DeviceGpuInfo[];
  processes: DeviceProcessInfo[];
  last_error: DeviceClientError | null;
  /** The last outcome of each queued command, newest first. */
  command_results: DeviceCommandResult[];
}

/** One managed module on a device, as the panel shows it. */
export interface DeviceModuleView {
  name: string;
  title: string;
  description: string;
  /** The manifest kind; the SSH server's uninstall confirmation keys on it. */
  kind: string;
  /** Who installs it: platform (the OS carries it), hub (the hub fetches
   * it), or user (the person installs it; the hub only detects and
   * manages). A user-tier row offers no install or uninstall button. */
  installer: string;
  is_supported: boolean;
  /** The platform carries this natively: worded built in, no button. */
  is_native: boolean;
  /** What the hub conveys this under, and where its exact source is. Empty
   * for software the hub does not hand on itself. */
  license: string;
  corresponding_source: string;
  state: string;
  /** Why the state is what it is, when the agent said; the page words it. */
  code: string;
  params: Record<string, unknown>;
}

export interface DeviceModulesResponse {
  modules: DeviceModuleView[];
  /** Whether an agent install was ever asked for. Never cleared by itself. */
  is_agent_managed: boolean;
  /** Whether the agent has checked in inside the heartbeat window. Every
   * module state below comes from it, so this is what says whether they
   * mean anything. */
  is_agent_online: boolean;
}

/** What one install on a device did, whatever asked for it. */
export interface DeviceInstallOrderView {
  id: string;
  module: string;
  /** The module's own title, so a failure reads beside the thing it was. */
  title: string;
  action: string;
  state: string;
  code: string;
  params: Record<string, unknown>;
  /** What the failing step printed, so a person reads the vendor's own
   * words rather than only that something went wrong. */
  output: string;
  asked_at: string;
  finished_at: string;
}

/** Every install this device has run, newest first. */
export interface DeviceInstallOutputResponse {
  orders: DeviceInstallOrderView[];
}

/** A link a machine can join the gateway with. */
export interface DeviceEnrollmentView {
  link: string;
  token: string;
  expires_in_s: number;
}

export interface DeviceFileEntry {
  name: string;
  is_dir: boolean;
  is_link: boolean;
  size_bytes: number;
  modified_at: number;
}

export interface DeviceFileList {
  path: string;
  entries: DeviceFileEntry[];
}

export interface DeviceView {
  mac_address: string;
  ipv4_address: string;
  name: string | null;
  icon: string | null;
  vendor: string;
  /** Reachable by any route: seen on the network, or its agent is beating. */
  is_online: boolean;
  /** Its agent beat within the last half minute. */
  is_agent_online: boolean;
  is_wol_enabled: boolean;
  has_ssh: boolean;
  /** Whether this box holds anything about the device; a scan-only row has
   * nothing to forget. */
  is_stored: boolean;
  ssh: DeviceSshConfig | null;
  client: DeviceClientInfo | null;
}

export interface DeviceAnnotation {
  name?: string;
  icon?: string;
  is_wol_enabled?: boolean;
  ssh?: DeviceSshConfig | null;
}

export interface DevicesResponse {
  devices: DeviceView[];
}

export interface DeviceWolResult {
  is_sent: boolean;
  message: string;
}

export interface DeviceActionRequest {
  action: DeviceActionName;
}

export interface DeviceActionResult {
  task_id: string;
}

// --- Modules ---

export interface ModuleView {
  name: string;
  unit: string;
  is_installed: boolean;
  is_active: boolean;
  is_enabled: boolean;
  /** Core modules are what makes this a gateway; they have no off switch. */
  is_core: boolean;
  /** Whether the panel can install and remove this module. */
  is_installable: boolean;
  is_machine_supported: boolean;
  unsupported_reason: string | null;
  /** What installing entails — a download's size, a repository added. */
  install_note: string;
  /** What "delete the data too" would delete, named plainly. */
  data_description: string;
}

export interface ProvisionConsentView {
  code: string;
  detail: Record<string, unknown>;
}

export interface ModuleInstallPlanView {
  name: string;
  is_consent_needed: boolean;
  consents: ProvisionConsentView[];
}

export interface ModuleInstallRequest {
  is_consented: boolean;
}

export interface ModuleUninstallRequest {
  is_data_kept: boolean;
}

export interface ModulesResponse {
  modules: ModuleView[];
}

// --- Services ---

export type PublishedServiceType = "web" | "port" | "ai" | "file";

/** The type's own payload; each entry fills the fields its type has. */
export interface PublishedServicePayload {
  url?: string;
  host?: string;
  port?: number;
  endpoint?: string;
  protocol?: string;
  models?: string[];
  share?: string;
}

/**
 * One entry of the typed service list. A `record_id` names the declared
 * record behind a declared entry; a module-declared entry carries null and
 * is read-only. `detail_code` is what that record's last probe measured,
 * null on one that answered as declared and on every module entry.
 */
export interface PublishedService {
  id: string;
  type: PublishedServiceType;
  title: string;
  payload: PublishedServicePayload;
  is_healthy: boolean | null;
  source: "module" | "declared";
  description: string;
  /** The device modules this entry cannot work without. */
  modules: string[];
  record_id: string | null;
  detail_code: string | null;
}

/** A declaration as the form submits it; `kind` is a service type. */
export interface DeclaredServiceCreate {
  name: string;
  kind: "web" | "port" | "file";
  host: string;
  port: number | null;
  scheme: string | null;
  path: string | null;
  shares: string[] | null;
  description: string;
}

export interface ServicesResponse {
  services: PublishedService[];
}

/** What one SMB server exports, administrative shares dropped. */
export interface ServiceSharesResponse {
  shares: string[];
}

export interface ServiceJournal {
  text: string;
}

/** One background job the panel is still running. */
export interface TaskView {
  id: string;
  /** How the job was started: `install <module>`, `uninstall <module>`. */
  label: string;
}

export interface TaskListResponse {
  tasks: TaskView[];
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
export interface PanelSettings {
  listen_port: number;
}

/**
 * One carried component, credited with its license and exact source.
 *
 * Only software whose bytes pass through the hub's hands is listed: what
 * the hub fetches and hands to a machine, it conveys.
 */
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
  uptime_s: number;
  acknowledgements: Acknowledgement[];
}

// --- Samba ---

export interface SambaShare {
  name: string;
  path: string;
  comment: string;
  is_read_only: boolean;
  /** Accounts allowed in; empty means every configured user. */
  valid_users: string[];
}

export interface SambaUser {
  name: string;
  is_present: boolean;
  /**
   * False for a user whose password was never set — including every user
   * after a restore from backup, since passwords are not in config/.
   */
  has_password: boolean;
}

export interface SambaSettings {
  shares: SambaShare[];
  users: SambaUser[];
}

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

export interface GiteaConfigUpdate {
  listen_port: number;
  root_url: string;
  is_registration_enabled: boolean;
}

export interface GiteaAdminCreate {
  username: string;
  password: string;
  email: string;
}

// --- NetBird ---

export interface NetbirdPeer {
  fqdn: string;
  netbird_ip: string;
  is_connected: boolean;
  /** P2P when direct, Relayed when through a relay. */
  connection_type: string;
  latency_ms: number | null;
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
}

export interface NetbirdJoinRequest {
  setup_key: string;
  management_url: string;
}

// --- Containers ---

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
}

export interface PodmanContainerState {
  name: string;
  image: string;
  status: string;
  is_running: boolean;
  /** Declared in config/, so it is systemd-supervised and reboots with the box. */
  is_declared: boolean;
}

export interface PodmanSettings {
  containers: PodmanContainer[];
  /** docker.io mirrors, tried in order before the registry itself. */
  mirrors: string[];
  running: PodmanContainerState[];
  is_installed: boolean;
  is_active: boolean;
  version: string;
}

// --- Websocket frames ---

/** Client to server on `/ws/ssh/{mac}`. */
export type TerminalClientMessage =
  | { type: "input"; data: string }
  | { type: "resize"; cols: number; rows: number };

/** Server to client on `/ws/ssh/{mac}` and `/ws/task/{task_id}`. */
export type StreamServerMessage =
  | { type: "output"; data: string }
  | { type: "exit"; code: number }
  | { type: "done"; exit_code: number };

// --- ZFS ---

/** One physical disk, in a pool or waiting for one. */
export interface ZfsDisk {
  device: string;
  by_id: string;
  size_bytes: number;
  model: string;
  serial: string;
  is_rotational: boolean;
  /** The bus: nvme, sata, usb… empty when the kernel will not say. */
  transport: string;
  wwn: string | null;
  /** The by-path name, encoding the PCI slot and port the drive sits in. */
  by_path: string | null;
  fstype: string;
  pool: string | null;
  is_available: boolean;
  smart_passed: boolean | null;
  temperature_c: number | null;
}

/** One device inside a vdev. */
export interface ZfsVdevMember {
  name: string;
  state: string;
  read_errors: number;
  write_errors: number;
  checksum_errors: number;
  is_resilvering: boolean;
}

export type ZfsVdevLayout = "single" | "mirror" | "raidz1" | "raidz2";

/** One vdev of a pool. */
export interface ZfsVdev {
  name: string;
  layout: string;
  state: string;
  members: ZfsVdevMember[];
}

/** What a pool's scrub or resilver is doing. */
export interface ZfsScan {
  kind: string | null;
  percent: number | null;
  eta: string | null;
  summary: string;
}

/** One filesystem dataset, with its achieved compression. */
export interface ZfsDataset {
  name: string;
  used_bytes: number;
  available_bytes: number;
  mountpoint: string;
  compression: string;
  compressratio: number;
  recordsize_bytes: number;
  share: string | null;
}

/** One imported pool with its topology and datasets. */
export interface ZfsPool {
  name: string;
  state: string;
  size_bytes: number;
  allocated_bytes: number;
  capacity_percent: number;
  fragmentation_percent: number;
  vdevs: ZfsVdev[];
  scan: ZfsScan;
  errors: string;
  datasets: ZfsDataset[];
}

/** A pool found on attached disks, waiting to be imported. */
export interface ZfsImportable {
  name: string;
  state: string;
}

/** What the share dialog needs to know about Samba. */
export interface ZfsSamba {
  is_ready: boolean;
  users: string[];
}

export interface ZfsView {
  is_installed: boolean;
  pools: ZfsPool[];
  disks: ZfsDisk[];
  importable: ZfsImportable[];
  samba: ZfsSamba;
}
