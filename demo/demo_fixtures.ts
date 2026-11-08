import { DEMO_ACCOUNT } from "./demo_modules";
import type {
  AboutInfo,
  AccountListView,
  AiProvidersResponse,
  CliproxyApiAccountsResponse,
  CliproxyApiStatusView,
  DirectView,
  EasyTierView,
  FrpTunnelListView,
  FrpView,
  GeneratedCredentialListView,
  HubReleaseScanView,
  HubReleaseView,
  KeysResponse,
  LoginsResponse,
  NetbirdView,
  OpenFrpView,
  OverlayKindView,
  PanelHttpsView,
  RelayView,
  SettingsView,
  TokensResponse,
} from "../hub/frontend/src/api_types";

/**
 * The hub's views that no press in the demo changes. They describe a person's
 * hub at home, on private addresses and the documentation ranges.
 */

/** Whether the demo was opened in English (?lang=en), read from the top page so every frame agrees. */
export const IS_ENGLISH_DEMO = ((): boolean => {
  try {
    const top = window.top ?? window;
    return new URLSearchParams(top.location.search).get("lang") === "en";
  } catch {
    return false;
  }
})();

/** A sample name or text in the language the demo was opened in. */
export function sample(chinese: string, english: string): string {
  return IS_ENGLISH_DEMO ? english : chinese;
}

export const DEMO_HUB_VERSION = "0.6.0";
export const DEMO_XRAY_VERSION = "25.8.3";
export const DEMO_GEODATA_RELEASE = "202510282214";
export const DEMO_HUB_NAME = sample("我的中枢", "My hub");
export const DEMO_HUB_ADDRESS = "192.168.1.10";
export const DEMO_HUB_PORT = 8080;
export const DEMO_AGENT_PORT = 8443;
export const DEMO_WAN_ADDRESS = "203.0.113.24";
export const DEMO_NETBIRD_ADDRESS = "100.92.0.1";
export const DEMO_NETBIRD_DOMAIN = "netbird.example.net";

// The second hub a client can scan on the Join page, a documentation address.
export const DEMO_SAMPLE_HUB_LINK = "neutrino://enroll/demo-sample-hub";
export const DEMO_LAB_HUB_ID = "hub_lab";
export const DEMO_LAB_HUB_ADDRESS = "198.51.100.20";
export const DEMO_LAB_DEVICE_ID = "dev_lab";
export const DEMO_LAB_DEVICE_HOSTNAME = "lab-server";
export const DEMO_LAB_METRICS_SEED = 7;
export const DEMO_LAB_APP_ID = "gitea_dev_lab";
export const DEMO_LAB_APP_TITLE = "Gitea";
export const DEMO_LAB_APP_PORT = 3000;

/** A moment `seconds` ago, as an ISO stamp. */
export function secondsAgo(seconds: number): string {
  return new Date(Date.now() - seconds * 1000).toISOString();
}

export const DEMO_AI_STATUS: CliproxyApiStatusView = {
  is_installed: true,
  is_active: true,
  listen_port: 8317,
  client_keys: [
    {
      id: "key_phone",
      name: sample("我的手机", "My phone"),
      key: "demo-key-phone",
      created_at: secondsAgo(86400 * 12),
    },
    {
      id: "key_desktop",
      name: sample("我的台式机", "My desktop"),
      key: "demo-key-desktop",
      created_at: secondsAgo(86400 * 30),
    },
  ],
  is_reachable: true,
  probe_code: "",
  probe_params: {},
  served_models: ["deepseek-chat", "qwen-max", "gpt-5-codex"],
  default_model: "deepseek-chat",
  has_ayakaleaf_on_default: false,
  enabled_provider_count: 2,
  account_count: 1,
  is_serving_stale: false,
  requests_today: 418,
  tokens_today: 1_284_000,
};

export const DEMO_AI_PROVIDERS: AiProvidersResponse = {
  providers: [
    {
      id: "provider_deepseek",
      name: "DeepSeek",
      kind: "openai",
      base_url: "https://api.example.net/deepseek/v1",
      secret_id: "token_deepseek",
      is_enabled: true,
      models: [{ name: "deepseek-chat", alias: "deepseek-chat" }],
      created_at: secondsAgo(86400 * 40),
    },
    {
      id: "provider_qwen",
      name: sample("通义千问", "Qwen"),
      kind: "openai",
      base_url: "https://api.example.net/qwen/v1",
      secret_id: "token_qwen",
      is_enabled: true,
      models: [{ name: "qwen-max", alias: "qwen-max" }],
      created_at: secondsAgo(86400 * 21),
    },
  ],
};

export const DEMO_AI_ACCOUNTS: CliproxyApiAccountsResponse = {
  accounts: [
    {
      name: "codex-xiaoming@example.com.json",
      provider: "codex",
      label: "",
      email: "xiaoming@example.com",
      account_type: "oauth",
      status: "active",
      status_message: "",
      is_disabled: false,
      is_unavailable: false,
      failed_count: 0,
      success_count: 214,
      created_at: secondsAgo(86400 * 9),
      updated_at: secondsAgo(1800),
    },
  ],
  login_kinds: ["anthropic", "codex", "antigravity", "kimi", "xai"],
};

export const DEMO_AI_JOURNAL_LINES = [
  "gateway listening on 127.0.0.1:8317",
  "loaded 2 providers and 1 account",
  "served deepseek-chat for key_phone in 812 ms",
  "served qwen-max for key_desktop in 1204 ms",
];

function overlayKind(
  key: string,
  title: string,
  isEnabled: boolean,
  clientCount: number,
): OverlayKindView {
  return {
    key,
    title,
    is_enabled: isEnabled,
    is_integrated: true,
    is_supported: true,
    is_installed: true,
    is_active: isEnabled,
    client_count: clientCount,
  };
}

export const DEMO_OVERLAY_KINDS: OverlayKindView[] = [
  overlayKind("netbird", "NetBird", true, 1),
  overlayKind("easytier", "EasyTier", true, 0),
  overlayKind("relay", sample("SSH 中继", "SSH relay"), true, 0),
  overlayKind("direct", sample("直连", "Direct"), true, 1),
  overlayKind("sakurafrp", "SakuraFrp", true, 0),
  overlayKind("openfrp", "OpenFrp", true, 0),
];

export const DEMO_NETBIRD: NetbirdView = {
  is_installed: true,
  is_active: true,
  version: "0.59.3",
  daemon_status: "Connected",
  is_enrolled: true,
  is_management_connected: true,
  management_url: `https://${DEMO_NETBIRD_DOMAIN}`,
  netbird_ip: DEMO_NETBIRD_ADDRESS,
  fqdn: `hub.${DEMO_NETBIRD_DOMAIN}`,
  peers: [
    {
      fqdn: `laptop.${DEMO_NETBIRD_DOMAIN}`,
      netbird_ip: "100.92.0.31",
      is_connected: true,
      connection_type: "P2P",
      latency_ms: 18,
      rx_bytes: 824_000_000,
      tx_bytes: 139_000_000,
      last_handshake_s: 42,
    },
  ],
  lan_subnets: ["192.168.1.0/24"],
  has_setup_key: true,
};

export const DEMO_EASYTIER: EasyTierView = {
  is_installed: true,
  is_active: true,
  version: "2.4.5",
  mode: "manual",
  has_config_server: false,
  is_secure_mode: true,
  instances: [],
  network_name: "xiaoming-home",
  is_secret_set: true,
  address: "10.144.0.1",
  hostname: "hub",
  peers: [],
  exported_networks: ["192.168.1.0/24"],
  suggested_networks: [{ cidr: "192.168.1.0/24", interface: "eth0" }],
  join_host: DEMO_WAN_ADDRESS,
  node: {
    is_connected: true,
    address: "10.144.0.1",
    hostname: "hub",
    nat_type: "PortRestricted",
  },
  live_peers: [
    {
      hostname: "laptop",
      address: "10.144.0.31",
      link: "direct",
      protocol: "tcp",
      latency_ms: 21,
      loss_ratio: 0,
      rx_bytes: 310_000_000,
      tx_bytes: 42_000_000,
      nat_type: "Symmetric",
      version: "2.4.5",
      is_connected: true,
    },
  ],
};

export const DEMO_DIRECT: DirectView = {
  is_enabled: true,
  public_host: DEMO_WAN_ADDRESS,
  public_port: DEMO_AGENT_PORT,
  urls: [`tcp://${DEMO_WAN_ADDRESS}:${DEMO_AGENT_PORT}`],
  interface_state: "exposed",
};

export const DEMO_RELAY: RelayView = {
  is_enabled: true,
  host: "relay.example.net",
  ssh_port: 22,
  account: DEMO_ACCOUNT,
  key_id: "key_home",
  login_id: "",
  public_port: 18443,
  url: "tcp://relay.example.net:18443",
  state: "connected",
  host_key_fingerprint: "SHA256:demo-fingerprint-of-a-made-up-relay",
  last_error: "",
  checked_at: secondsAgo(40),
};

export const DEMO_SAKURAFRP: FrpView = {
  is_enabled: true,
  is_signed_in: true,
  tunnel_id: "sakura_home",
  node_name: sample("示例节点 上海", "Sample node Shanghai"),
  local_port: DEMO_AGENT_PORT,
  url: "tcp://sakura-node.example.net:23456",
  state: "connected",
  last_error: "",
  checked_at: secondsAgo(25),
  console_url: "https://console.example.net/sakurafrp",
};

export const DEMO_OPENFRP: OpenFrpView = {
  is_enabled: true,
  is_signed_in: true,
  tunnel_id: "openfrp_home",
  node_name: sample("示例节点 香港", "Sample node Hong Kong"),
  local_port: DEMO_AGENT_PORT,
  url: "tcp://openfrp-node.example.net:34567",
  state: "connected",
  last_error: "",
  checked_at: secondsAgo(25),
  console_url: "https://console.example.net/openfrp",
  is_login_expired: false,
  login: { state: "idle", authorization_url: "" },
};

export const DEMO_SAKURAFRP_TUNNELS: FrpTunnelListView = {
  tunnels: [
    {
      tunnel_id: "sakura_home",
      name: sample("家里的电脑", "Home computer"),
      node_name: sample("示例节点 上海", "Sample node Shanghai"),
      region: "mainland",
      latency_ms: 24,
      is_picked: true,
    },
    {
      tunnel_id: "sakura_abroad",
      name: sample("在国外时用", "For trips abroad"),
      node_name: sample("示例节点 东京", "Sample node Tokyo"),
      region: "abroad",
      latency_ms: 86,
      is_picked: false,
    },
  ],
};

export const DEMO_OPENFRP_TUNNELS: FrpTunnelListView = {
  tunnels: [
    {
      tunnel_id: "openfrp_home",
      name: sample("家里的电脑", "Home computer"),
      node_name: sample("示例节点 香港", "Sample node Hong Kong"),
      region: "hk_mo_tw",
      latency_ms: 47,
      is_picked: true,
    },
  ],
};

export const DEMO_KEYS: KeysResponse = {
  keys: [
    {
      id: "key_home",
      name: sample("家里机器的 SSH 密钥", "Home machine SSH key"),
      key_type: "ed25519",
      fingerprint: "SHA256:demo-fingerprint-of-a-made-up-key",
      has_passphrase: false,
      created_at: secondsAgo(86400 * 60),
      device_count: 2,
      is_relay_key: true,
    },
  ],
};

export const DEMO_LOGINS: LoginsResponse = {
  logins: [
    {
      id: "login_desktop",
      name: sample("台式机登录", "Desktop login"),
      username: DEMO_ACCOUNT,
      created_at: secondsAgo(86400 * 60),
      device_count: 1,
      is_relay_login: false,
    },
  ],
};

export const DEMO_TOKENS: TokensResponse = {
  tokens: [
    {
      id: "token_deepseek",
      name: sample("DeepSeek 令牌", "DeepSeek token"),
      created_at: secondsAgo(86400 * 40),
      provider_count: 1,
      node_count: 0,
      node_names: [],
    },
    {
      id: "token_qwen",
      name: sample("通义千问令牌", "Qwen token"),
      created_at: secondsAgo(86400 * 21),
      provider_count: 1,
      node_count: 0,
      node_names: [],
    },
  ],
};

export const DEMO_GENERATED_CREDENTIALS: GeneratedCredentialListView = {
  machines: [
    {
      device_id: "dev_desktop",
      name: sample("我的台式机", "My desktop"),
      items: [
        { kind: "smb_password", account: DEMO_ACCOUNT, fingerprint: "" },
        { kind: "seat_password", account: "", fingerprint: "" },
      ],
    },
  ],
};

export const DEMO_SETTINGS: SettingsView = {
  listen_port: DEMO_HUB_PORT,
  https_listen_port: 443,
  agent_listen_port: DEMO_AGENT_PORT,
  language: "zh-CN",
  theme: "light",
  hub_name: DEMO_HUB_NAME,
  offline_client_count: 1,
  offline_agent_count: 1,
};

export const DEMO_HTTPS: PanelHttpsView = {
  is_https_enabled: false,
  listen_port: DEMO_HUB_PORT,
  https_listen_port: 443,
  has_authority: true,
  authority_fingerprint: "demo0000000000000000000000000000",
  authority_created_at: secondsAgo(86400 * 60),
  authority_file_name: "neutrino_hub_ca.crt",
  leaf_names: [DEMO_HUB_ADDRESS, "hub.local"],
  leaf_issued_at: secondsAgo(86400 * 60),
  leaf_expires_at: secondsAgo(-86400 * 300),
  renewed_at: null,
};

export const DEMO_RELEASE: HubReleaseView = {
  current: DEMO_HUB_VERSION,
  is_packaged: true,
  package_family: "deb",
  log_root: "/var/log/neutrino/hub",
  update: null,
  task_id: null,
};

export const DEMO_RELEASE_SCAN: HubReleaseScanView = {
  current: DEMO_HUB_VERSION,
  latest: { version: DEMO_HUB_VERSION, size_bytes: 92_000_000 },
  has_package: true,
  is_newer: false,
  is_major: false,
  is_rollback_available: false,
  needed_bytes: 0,
  free_bytes: 48_000_000_000,
  is_space_enough: true,
};

/**
 * The Settings page's About card.
 *
 * Args:
 *   uptimeS: How long the hub has been up.
 *   isProxyCarried: Whether the edition has the proxy, which fills its rows.
 *
 * Returns:
 *   The card's view.
 */
export function demoAbout(uptimeS: number, isProxyCarried: boolean): AboutInfo {
  return {
    xray_version: isProxyCarried ? DEMO_XRAY_VERSION : "",
    gateway_version: DEMO_HUB_VERSION,
    cliproxyapi_version: "6.3.2",
    python_version: "3.12.3",
    geodata_version: isProxyCarried ? DEMO_GEODATA_RELEASE : "",
    kernel: "6.8.0",
    os: "linux",
    os_version: "Ubuntu 24.04",
    uptime_s: uptimeS,
    acknowledgements: [
      {
        name: "NetBird",
        version: "0.59.3",
        license: "BSD-3-Clause",
        corresponding_source: "https://github.com/netbirdio/netbird",
      },
      {
        name: "EasyTier",
        version: "2.4.5",
        license: "LGPL-3.0",
        corresponding_source: "https://github.com/EasyTier/EasyTier",
      },
      ...(isProxyCarried
        ? [
            {
              name: "Xray",
              version: DEMO_XRAY_VERSION,
              license: "MPL-2.0",
              corresponding_source: "https://github.com/XTLS/Xray-core",
            },
          ]
        : []),
    ],
  };
}

/** A machine's available accounts, all on the one demo account. */
export function demoAccounts(platformOs: string): AccountListView {
  const home =
    platformOs === "windows"
      ? `C:\\Users\\${DEMO_ACCOUNT}`
      : `/home/${DEMO_ACCOUNT}`;
  return {
    accounts: [
      {
        account: DEMO_ACCOUNT,
        has_login: true,
        share_path: "",
        shell_path: "",
        is_ai_tools_enabled: true,
        tool_configs: {},
        modules: ["terminal", "samba"],
        ai_tools: { state: "switched", code: "", params: {} },
      },
    ],
    system_accounts: [
      {
        account: DEMO_ACCOUNT,
        home,
        shell: platformOs === "windows" ? "cmd.exe" : "/bin/bash",
      },
    ],
    platform_os: platformOs,
    models: DEMO_AI_STATUS.served_models ?? [],
    is_gateway_serving: true,
  };
}
