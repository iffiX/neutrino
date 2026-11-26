import { DEMO_ACCOUNT } from "./demo_modules";
import type {
  AboutInfo,
  AccountListView,
  AiModelDefaultPrice,
  AiModelPrice,
  AiProvidersResponse,
  AiVendorEndpointView,
  AiVendorView,
  CliproxyApiAccountsResponse,
  CliproxyApiQuotaWindowView,
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
  PodmanNewMachineView,
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

export const DEMO_HUB_VERSION = "0.6.1";
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

/** A terminal session the Services page's Terminals panel lists. */
export interface DemoTerminalSession {
  device_id: string;
  session_id: string;
  account: string;
  title: string;
  /** Minutes since it was opened. */
  age_minutes: number;
  /** The client that opened it. */
  owner_client_id: string;
  attached_count: number;
  is_persistent: boolean;
  is_shared: boolean;
}

/** The terminal sessions of two machines, oldest first. */
export const DEMO_TERMINAL_SESSIONS: DemoTerminalSession[] = [
  {
    device_id: "dev_desktop",
    session_id: "session_desktop_build",
    account: "xiaoming",
    title: "htop",
    age_minutes: 185,
    owner_client_id: "client_office",
    attached_count: 0,
    is_persistent: true,
    is_shared: false,
  },
  {
    device_id: "dev_laptop",
    session_id: "session_laptop_notes",
    account: "xiaoming",
    title: "xiaoming@laptop: ~/notes",
    age_minutes: 12,
    owner_client_id: "client_phone",
    attached_count: 2,
    is_persistent: false,
    is_shared: true,
  },
];

const ZHIPU_MODELS = ["glm-5.3", "glm-5.3-flash", "glm-5.3-flashx"];
const QWEN_MODELS = ["qwen4-max", "qwen3.7-plus", "qwen3.8-flash"];
const SILICONFLOW_MODELS = [
  "deepseek-ai/DeepSeek-V4.1-Flash",
  "deepseek-ai/DeepSeek-V4-Pro",
  "zai-org/GLM-5.3",
];

function vendorEndpoint(
  id: string,
  baseUrl: string,
  priceProvider: string,
  models: string[],
  isPlan = false,
): AiVendorEndpointView {
  return {
    id,
    base_url: baseUrl,
    price_provider: priceProvider,
    is_plan: isPlan,
    models,
  };
}

/** A limit window that resets in `resetsInS` and was seen `seenAgoS` ago. */
function quotaWindow(
  name: string,
  usedShare: number,
  resetsInS: number,
  seenAgoS: number,
  origin: CliproxyApiQuotaWindowView["origin"],
): CliproxyApiQuotaWindowView {
  return {
    name,
    used_share: usedShare,
    resets_at: secondsAgo(-resetsInS),
    seen_at: secondsAgo(seenAgoS),
    origin,
  };
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
  served_models: [
    "claude-fable-5-2",
    "deepseek-flash",
    "deepseek-v4-pro",
    "glm-5.3",
    "gpt-6.2-astra",
    "kimi-k3",
    "kimi-k3.1-pro",
  ],
  default_model: "deepseek-flash",
  has_ayakaleaf_on_default: false,
  enabled_provider_count: 4,
  account_count: 3,
  is_serving_stale: false,
  requests_today: 418,
  tokens_today: 1_284_000,
};

/** The model the demo account's OpenCode uses: one of the desktop's Ollama. */
export const DEMO_OPENCODE_MODEL = "qwen2.5:7b";

/** The provider form's vendor presets, as `data/ai_vendors.json` holds
 * them. */
export const DEMO_AI_VENDORS: AiVendorView[] = [
  {
    id: "deepseek",
    endpoints: [
      vendorEndpoint("api", "https://api.deepseek.com", "deepseek", [
        "deepseek-flash",
        "deepseek-v4-pro",
      ]),
    ],
  },
  {
    id: "kimi",
    endpoints: [
      vendorEndpoint("api_cn", "https://api.moonshot.cn/v1", "moonshotai-cn", [
        "kimi-k3.1-pro",
        "kimi-k3.1-pro-highspeed",
        "kimi-k3",
      ]),
      vendorEndpoint("api_global", "https://api.moonshot.ai/v1", "moonshotai", [
        "kimi-k3.1-pro",
        "kimi-k3.1-pro-highspeed",
        "kimi-k3",
      ]),
    ],
  },
  {
    id: "zhipu",
    endpoints: [
      vendorEndpoint(
        "api_cn",
        "https://open.bigmodel.cn/api/paas/v4",
        "zhipuai",
        ZHIPU_MODELS,
      ),
      vendorEndpoint(
        "plan_cn",
        "https://open.bigmodel.cn/api/coding/paas/v4",
        "zhipuai",
        ZHIPU_MODELS,
        true,
      ),
      vendorEndpoint(
        "api_global",
        "https://api.z.ai/api/paas/v4",
        "zai",
        ZHIPU_MODELS,
      ),
      vendorEndpoint(
        "plan_global",
        "https://api.z.ai/api/coding/paas/v4",
        "zai",
        ZHIPU_MODELS,
        true,
      ),
    ],
  },
  {
    id: "qwen",
    endpoints: [
      vendorEndpoint(
        "api_cn",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "alibaba-cn",
        QWEN_MODELS,
      ),
      vendorEndpoint(
        "api_global",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "alibaba",
        QWEN_MODELS,
      ),
      vendorEndpoint(
        "plan_cn",
        "https://coding.dashscope.aliyuncs.com/v1",
        "alibaba-cn",
        QWEN_MODELS,
        true,
      ),
      vendorEndpoint(
        "plan_global",
        "https://coding-intl.dashscope.aliyuncs.com/v1",
        "alibaba",
        QWEN_MODELS,
        true,
      ),
    ],
  },
  {
    id: "doubao",
    endpoints: [
      vendorEndpoint(
        "api",
        "https://ark.cn-beijing.volces.com/api/v3",
        "volcengine",
        [
          "doubao-seed-2-1-pro-260915",
          "doubao-seed-2-1-lite-260915",
          "doubao-seed-2-1-turbo-260628",
        ],
      ),
      vendorEndpoint(
        "plan",
        "https://ark.cn-beijing.volces.com/api/coding/v3",
        "volcengine",
        ["ark-code-latest"],
        true,
      ),
    ],
  },
  {
    id: "minimax",
    endpoints: [
      vendorEndpoint("api_cn", "https://api.minimax.cn/v1", "minimax-cn", [
        "MiniMax-M3.1-Flash",
        "MiniMax-M3",
      ]),
      vendorEndpoint("api_global", "https://api.minimax.io/v1", "minimax", [
        "MiniMax-M3.1-Flash",
        "MiniMax-M3",
      ]),
    ],
  },
  {
    id: "openrouter",
    endpoints: [
      vendorEndpoint("api", "https://openrouter.ai/api/v1", "openrouter", [
        "openai/gpt-6.2-sol",
        "anthropic/claude-fable-5.2",
      ]),
    ],
  },
  {
    id: "siliconflow",
    endpoints: [
      vendorEndpoint(
        "api_cn",
        "https://api.siliconflow.cn/v1",
        "siliconflow-cn",
        SILICONFLOW_MODELS,
      ),
      vendorEndpoint(
        "api_global",
        "https://api.siliconflow.com/v1",
        "siliconflow",
        SILICONFLOW_MODELS,
      ),
    ],
  },
  {
    id: "mistral",
    endpoints: [
      vendorEndpoint("api", "https://api.mistral.ai/v1", "mistral", [
        "mistral-large-latest",
        "mistral-small-2603",
      ]),
    ],
  },
  {
    id: "xai",
    endpoints: [
      vendorEndpoint("api", "https://api.x.ai/v1", "xai", [
        "grok-4.7",
        "grok-4.6",
        "grok-4.3",
      ]),
    ],
  },
];

export const DEMO_AI_PROVIDERS: AiProvidersResponse = {
  providers: [
    {
      id: "provider_deepseek",
      name: "DeepSeek",
      kind: "custom",
      base_url: "https://api.deepseek.com",
      secret_id: "token_deepseek",
      is_enabled: true,
      models: [
        { name: "deepseek-flash", alias: "" },
        { name: "deepseek-v4-pro", alias: "" },
      ],
      created_at: secondsAgo(86400 * 40),
      vendor: "deepseek",
      endpoint: "api",
    },
    {
      id: "provider_kimi",
      name: "Kimi",
      kind: "custom",
      base_url: "https://api.moonshot.cn/v1",
      secret_id: "token_kimi",
      is_enabled: true,
      models: [
        { name: "kimi-k3.1-pro", alias: "" },
        { name: "kimi-k3", alias: "" },
      ],
      created_at: secondsAgo(86400 * 21),
      vendor: "kimi",
      endpoint: "api_cn",
    },
    {
      id: "provider_zhipu",
      name: sample("智谱 GLM", "Zhipu GLM"),
      kind: "custom",
      base_url: "https://open.bigmodel.cn/api/coding/paas/v4",
      secret_id: "token_zhipu",
      is_enabled: true,
      models: [{ name: "glm-5.3", alias: "" }],
      created_at: secondsAgo(86400 * 14),
      vendor: "zhipu",
      endpoint: "plan_cn",
    },
    {
      id: "provider_relay",
      name: sample("中转站", "My relay"),
      kind: "anthropic",
      base_url: "https://relay.example.net",
      secret_id: "token_relay",
      is_enabled: true,
      models: [{ name: "claude-fable-5-2", alias: "" }],
      created_at: secondsAgo(86400 * 6),
      vendor: "",
      endpoint: "",
    },
  ],
  vendors: DEMO_AI_VENDORS,
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
      next_retry_after: "",
      plan: "Plus",
      subscription_ends_at: secondsAgo(-86400 * 23),
      has_quota_read: true,
      windows: [
        quotaWindow("5h", 0.42, 2.4 * 3600, 240, "signal"),
        quotaWindow("7d", 0.81, 3.2 * 86400, 240, "signal"),
      ],
      failed_count: 0,
      success_count: 214,
      created_at: secondsAgo(86400 * 9),
      updated_at: secondsAgo(1800),
    },
    {
      name: "claude-xiaoming@example.com.json",
      provider: "claude",
      label: "",
      email: "xiaoming@example.com",
      account_type: "oauth",
      status: "error",
      status_message: "rate limited",
      is_disabled: false,
      is_unavailable: true,
      next_retry_after: secondsAgo(-1.6 * 3600),
      plan: "",
      subscription_ends_at: "",
      has_quota_read: true,
      windows: [
        quotaWindow("5h", 1, 1.6 * 3600, 600, "signal"),
        quotaWindow("7d", 0.63, 4.5 * 86400, 600, "signal"),
      ],
      failed_count: 3,
      success_count: 96,
      created_at: secondsAgo(86400 * 18),
      updated_at: secondsAgo(600),
    },
    {
      name: "kimi-xiaoming.json",
      provider: "kimi",
      label: "xiaoming",
      email: "",
      account_type: "oauth",
      status: "disabled",
      status_message: "",
      is_disabled: true,
      is_unavailable: false,
      next_retry_after: "",
      plan: "",
      subscription_ends_at: "",
      has_quota_read: true,
      windows: [
        quotaWindow("5h", 0.12, 3.1 * 3600, 3 * 3600, "read"),
        quotaWindow("7d", 0.35, 5 * 86400, 3 * 3600, "read"),
        quotaWindow("month", 0.2, 19 * 86400, 3 * 3600, "read"),
      ],
      failed_count: 0,
      success_count: 41,
      created_at: secondsAgo(86400 * 27),
      updated_at: secondsAgo(3 * 3600),
    },
  ],
  login_kinds: ["anthropic", "codex", "antigravity", "kimi", "xai"],
};

/** The names each sample account serves, by its token file. */
export const DEMO_AI_ACCOUNT_MODELS: Record<string, string[]> = {
  "codex-xiaoming@example.com.json": ["gpt-6.2-astra"],
  "claude-xiaoming@example.com.json": ["claude-fable-5-2"],
  "kimi-xiaoming.json": ["kimi-k3.1-pro"],
};

/** Each sample cloud name's default context length, as the hub's table and
 * the gateway's catalog give it, and the length of a name neither names. */
export const DEMO_CONTEXT_DEFAULTS: Record<string, number> = {
  "claude-fable-5-2": 1000000,
  "deepseek-flash": 1000000,
  "deepseek-v4-pro": 1000000,
  "glm-5.3": 1000000,
  "gpt-6.2-astra": 272000,
  "kimi-k3": 1048576,
  "kimi-k3.1-pro": 262144,
};
export const DEMO_CONTEXT_FALLBACK = 200000;

/** The context lengths a person set, by cloud name. */
export const DEMO_CONTEXT_SAVED: Record<string, number> = {
  "deepseek-v4-pro": 262144,
};

/** Each sample cloud name's default price per million tokens, the
 * models.dev price of its first source that has one. */
export const DEMO_MODEL_PRICES: Record<string, AiModelDefaultPrice> = {
  "claude-fable-5-2": {
    input: 5,
    output: 25,
    cache_read: 0.5,
    cache_write: 6.25,
    currency: "USD",
  },
  "deepseek-flash": {
    input: 0.28,
    output: 1.1,
    cache_read: 0.028,
    currency: "USD",
  },
  "deepseek-v4-pro": {
    input: 0.55,
    output: 2.2,
    cache_read: 0.14,
    currency: "USD",
  },
  "glm-5.3": { input: 0.6, output: 2.2, cache_read: 0.11, currency: "USD" },
  "gpt-6.2-astra": {
    input: 1.25,
    output: 10,
    cache_read: 0.125,
    currency: "USD",
  },
  "kimi-k3": { input: 0.58, output: 2.32, cache_read: 0.1, currency: "USD" },
  "kimi-k3.1-pro": {
    input: 0.6,
    output: 2.5,
    cache_read: 0.15,
    currency: "USD",
  },
};

/** The models.dev price of each sample source's records of a name, by
 * `<source id>|<name>`; a source left out has none. */
export const DEMO_SOURCE_PRICES: Record<string, AiModelDefaultPrice> = {
  "claude-xiaoming@example.com.json|claude-fable-5-2": {
    input: 5,
    output: 25,
    cache_read: 0.5,
    cache_write: 6.25,
    currency: "USD",
  },
  "provider_deepseek|deepseek-flash": {
    input: 0.28,
    output: 1.1,
    cache_read: 0.028,
    currency: "USD",
  },
  "provider_deepseek|deepseek-v4-pro": {
    input: 0.55,
    output: 2.2,
    cache_read: 0.14,
    currency: "USD",
  },
  "provider_zhipu|glm-5.3": {
    input: 0.6,
    output: 2.2,
    cache_read: 0.11,
    currency: "USD",
  },
  "codex-xiaoming@example.com.json|gpt-6.2-astra": {
    input: 1.25,
    output: 10,
    cache_read: 0.125,
    currency: "USD",
  },
  "provider_kimi|kimi-k3": {
    input: 0.58,
    output: 2.32,
    cache_read: 0.1,
    currency: "USD",
  },
  "provider_kimi|kimi-k3.1-pro": {
    input: 0.58,
    output: 2.32,
    cache_read: 0.1,
    currency: "USD",
  },
  "kimi-xiaoming.json|kimi-k3.1-pro": {
    input: 0.6,
    output: 2.5,
    cache_read: 0.15,
    currency: "USD",
  },
};

/** The prices a person set, by cloud name. */
export const DEMO_PRICES_SAVED: Record<string, AiModelPrice> = {
  "kimi-k3.1-pro": { input: 4, output: 16, currency: "CNY" },
};

export const DEMO_AI_JOURNAL_LINES = [
  "gateway listening on 127.0.0.1:8317",
  "loaded 4 providers and 3 accounts",
  "served deepseek-flash for key_phone in 812 ms",
  "served kimi-k3.1-pro for key_desktop in 1204 ms",
  "claude-xiaoming@example.com.json cooling after 429",
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

/** The numbers a new Podman machine starts from on a demo machine. */
export const DEMO_NEW_PODMAN_MACHINE: PodmanNewMachineView = {
  cpus: 4,
  memory_gib: 4,
  disk_gib: 100,
  disk_gib_now: 0,
  need_gib: 0,
};

/**
 * A machine's available accounts, whose OpenCode uses a model of the
 * desktop's Ollama, on a machine that reports the one demo account.
 *
 * Args:
 *   platformOs: The machine's system.
 *   models: The names the gateway serves.
 *   accounts: The available accounts in the order they were added, the
 *     first the default; none on a machine that is incomplete.
 *
 * Returns:
 *   The accounts' view.
 */
export function demoAccounts(
  platformOs: string,
  models: string[],
  accounts: string[],
): AccountListView {
  const home =
    platformOs === "windows"
      ? `C:\\Users\\${DEMO_ACCOUNT}`
      : `/home/${DEMO_ACCOUNT}`;
  return {
    default_account: accounts[0] ?? "",
    accounts: accounts.map((account) => ({
      account,
      has_login: true,
      share_path: "",
      shell_path: "",
      is_ai_tools_enabled: true,
      tool_configs: { opencode: { model: DEMO_OPENCODE_MODEL } },
      modules: ["terminal", "samba"],
      ai_tools: { state: "switched", code: "", params: {} },
    })),
    system_accounts: [
      {
        account: DEMO_ACCOUNT,
        home,
        shell: platformOs === "windows" ? "cmd.exe" : "/bin/bash",
      },
    ],
    platform_os: platformOs,
    models,
    is_gateway_serving: true,
  };
}
