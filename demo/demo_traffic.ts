import { DEMO_WAN_ADDRESS, secondsAgo, sample } from "./demo_fixtures";
import type { DemoProxyReadings } from "./demo_proxy";
import type {
  AiUsageAmounts,
  AiUsageBucket,
  AiUsageCounters,
  AiUsageModelUpstream,
  AiUsageHealthBucket,
  AiUsageRange,
  AiUsageResponse,
  DeviceMetricsView,
  StatsFrame,
  TrafficHistoryRange,
  TrafficHistoryResponse,
  TrafficSample,
} from "../hub/frontend/src/api_types";

/**
 * The readings that change by themselves: the live stats frames, a machine's
 * metrics, the traffic history and the AI gateway's usage.
 */

const STAT_INTERVAL_S = 1;
const HUB_UPTIME_START_S = 86400 * 6 + 3600 * 5;
const IDLE_RX_BYTES_PER_S = 1_400_000;
const IDLE_TX_BYTES_PER_S = 320_000;
const APP_RX_BYTES_PER_S = 2_600_000;
const APP_TX_BYTES_PER_S = 760_000;
const GIB = 1024 ** 3;

/** Frames the stats socket opens with, the chart's two minutes. */
export const DEMO_STAT_BACKLOG = 120;

/** The fields of a frame the network and the proxy answer for. */
export type DemoFrameReadings = DemoProxyReadings &
  Pick<StatsFrame, "network_mode" | "interface_name">;

/** A repeatable value in 0 to 1 for a whole number. */
function steady(seed: number): number {
  const value = Math.sin(seed * 12.9898) * 43758.5453;
  return value - Math.floor(value);
}

/** The hub's stats frames. */
export class DemoStatsFeed {
  private readonly startedAt = Date.now();
  private uplinkBytes = 38 * GIB;
  private downlinkBytes = 212 * GIB;

  /**
   * Makes the frame for a moment.
   *
   * Args:
   *   ageS: How many seconds before now the frame stands.
   *   appsInUse: The apps the client forwards now.
   *   agentCount: The agents reporting now.
   *   readings: What the network and the proxy say now.
   *
   * Returns:
   *   The frame.
   */
  frame(
    ageS: number,
    appsInUse: number,
    agentCount: number,
    readings: DemoFrameReadings,
  ): StatsFrame {
    const at = Date.now() - ageS * 1000;
    const clock = at / 1000;
    const wave =
      0.55 +
      0.28 * Math.sin(clock / 17) +
      0.17 * Math.sin(clock / 5.3) +
      0.2 * steady(Math.floor(clock));
    const rx = IDLE_RX_BYTES_PER_S * wave + APP_RX_BYTES_PER_S * appsInUse;
    const tx =
      IDLE_TX_BYTES_PER_S * (0.6 + 0.4 * Math.cos(clock / 9)) +
      APP_TX_BYTES_PER_S * appsInUse;
    this.downlinkBytes += rx * STAT_INTERVAL_S;
    this.uplinkBytes += tx * STAT_INTERVAL_S;
    return {
      ...readings,
      timestamp: new Date(at).toISOString(),
      cpu_percent: 14 + 9 * Math.abs(Math.sin(clock / 23)) + 6 * appsInUse,
      memory_percent: 41 + 2 * Math.sin(clock / 61),
      uptime_s: Math.round(HUB_UPTIME_START_S + (at - this.startedAt) / 1000),
      wan_address: DEMO_WAN_ADDRESS,
      total_uplink_bytes: this.uplinkBytes,
      total_downlink_bytes: this.downlinkBytes,
      interface_rx_bytes_per_s: rx,
      interface_tx_bytes_per_s: tx,
      agent_device_count: agentCount,
      lan_device_count: 5,
      is_wan_reachable: true,
      is_xray_reachable: false,
      is_in_sync: true,
    };
  }
}

/** A machine's readings, `ageS` seconds ago. */
export function demoMetrics(
  deviceSeed: number,
  ageS: number = 0,
): DeviceMetricsView {
  const clock = Date.now() / 1000 - ageS + deviceSeed * 40;
  const cpu = 12 + 18 * Math.abs(Math.sin(clock / 19));
  return {
    cpu_percent: cpu,
    cpu_core_percents: Array.from({ length: 8 }, (_, core) =>
      Math.max(2, cpu + 22 * Math.sin(clock / 7 + core)),
    ),
    memory_percent: 46 + 3 * Math.sin(clock / 31),
    disk_percent: 58 + deviceSeed * 7,
    temperature_c: 46 + 5 * Math.sin(clock / 41),
    uptime_s: 86400 * 3 + (clock % 3600),
    load_average: [1.2, 0.9, 0.7],
    gpus:
      deviceSeed === 0
        ? [
            {
              vendor: "nvidia",
              name: "GeForce RTX 4070",
              utilization_percent: 22 + 16 * Math.abs(Math.sin(clock / 13)),
              memory_used_mb: 3280,
              memory_total_mb: 12288,
              temperature_c: 52,
              power_w: 64,
            },
            {
              vendor: "nvidia",
              name: "GeForce RTX 3060",
              utilization_percent: 58 + 24 * Math.abs(Math.sin(clock / 17)),
              memory_used_mb: 7120,
              memory_total_mb: 12288,
              temperature_c: 67,
              power_w: 121,
            },
          ]
        : [],
    processes: [
      {
        pid: 2143,
        user: "xiaoming",
        name: "code-server",
        cpu_percent: 6.4,
        memory_percent: 3.1,
      },
      {
        pid: 1877,
        user: "xiaoming",
        name: "node",
        cpu_percent: 3.8,
        memory_percent: 2.2,
      },
      {
        pid: 912,
        user: "root",
        name: "neutrino_agent",
        cpu_percent: 0.6,
        memory_percent: 0.4,
      },
    ],
  };
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function dayLabel(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function trafficSample(label: string, seed: number, scale: number) {
  const received = scale * (0.4 + 0.6 * steady(seed));
  return {
    label,
    received_bytes: Math.round(received),
    sent_bytes: Math.round(received * (0.15 + 0.2 * steady(seed + 91))),
  };
}

/** The traffic history a dashboard range draws. */
export function demoHistory(
  range: TrafficHistoryRange,
): TrafficHistoryResponse {
  const now = new Date();
  const samples: TrafficSample[] = [];
  if (range === "day") {
    for (let back = 23; back >= 0; back -= 1) {
      const at = new Date(now.getTime() - back * 3600_000);
      const label = `${dayLabel(at)} ${pad(at.getHours())}:00`;
      samples.push(trafficSample(label, at.getHours(), 1.6 * GIB));
    }
  } else if (range === "year") {
    for (let back = 11; back >= 0; back -= 1) {
      const at = new Date(now.getFullYear(), now.getMonth() - back, 1);
      const label = `${at.getFullYear()}-${pad(at.getMonth() + 1)}`;
      samples.push(trafficSample(label, at.getMonth() + 40, 240 * GIB));
    }
  } else {
    const count = range === "week" ? 7 : 30;
    for (let back = count - 1; back >= 0; back -= 1) {
      const at = new Date(now.getTime() - back * 86400_000);
      samples.push(trafficSample(dayLabel(at), at.getDate(), 14 * GIB));
    }
  }
  return {
    range,
    samples,
    today: {
      label: dayLabel(now),
      received_bytes: Math.round(9.4 * GIB),
      sent_bytes: Math.round(2.1 * GIB),
    },
  };
}

function usageCounters(seed: number, scale: number): AiUsageCounters {
  const requests = Math.round(scale * (0.3 + steady(seed)));
  return {
    requests,
    failed: Math.round(requests * 0.01 * steady(seed + 5)),
    input_tokens: requests * 1450,
    output_tokens: requests * 420,
    cache_read_tokens: requests * 600,
    cache_write_tokens: requests * 90,
    cost: {},
    api_value: {},
    unpriced_requests: 0,
  };
}

/** Two sets of amounts summed per currency. */
function addAmounts(a: AiUsageAmounts, b: AiUsageAmounts): AiUsageAmounts {
  const sum: AiUsageAmounts = { ...a };
  for (const [currency, value] of Object.entries(b)) {
    sum[currency] = (sum[currency] ?? 0) + value;
  }
  return sum;
}

function scaledAmounts(amounts: AiUsageAmounts, share: number): AiUsageAmounts {
  return Object.fromEntries(
    Object.entries(amounts)
      .map(([currency, value]) => [currency, Math.round(value * share)])
      .filter(([, value]) => Number(value) > 0),
  ) as AiUsageAmounts;
}

function sumCounters(rows: AiUsageCounters[]): AiUsageCounters {
  const total: AiUsageCounters = {
    requests: 0,
    failed: 0,
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    cache_write_tokens: 0,
    cost: {},
    api_value: {},
    unpriced_requests: 0,
  };
  for (const row of rows) {
    total.requests += row.requests;
    total.failed += row.failed;
    total.input_tokens += row.input_tokens;
    total.output_tokens += row.output_tokens;
    total.cache_read_tokens += row.cache_read_tokens;
    total.cache_write_tokens += row.cache_write_tokens;
    total.cost = addAmounts(total.cost, row.cost);
    total.api_value = addAmounts(total.api_value, row.api_value);
    total.unpriced_requests += row.unpriced_requests;
  }
  return total;
}

function scaledCounters(
  counters: AiUsageCounters,
  share: number,
): AiUsageCounters {
  return {
    requests: Math.round(counters.requests * share),
    failed: Math.round(counters.failed * share),
    input_tokens: Math.round(counters.input_tokens * share),
    output_tokens: Math.round(counters.output_tokens * share),
    cache_read_tokens: Math.round(counters.cache_read_tokens * share),
    cache_write_tokens: Math.round(counters.cache_write_tokens * share),
    cost: scaledAmounts(counters.cost, share),
    api_value: scaledAmounts(counters.api_value, share),
    unpriced_requests: Math.round(counters.unpriced_requests * share),
  };
}

function usageSeries(range: AiUsageRange): AiUsageBucket[] {
  const now = new Date();
  const series: AiUsageBucket[] = [];
  if (range === "day") {
    for (let back = 23; back >= 0; back -= 1) {
      const at = new Date(now.getTime() - back * 3600_000);
      series.push({
        bucket: `${dayLabel(at)}T${pad(at.getHours())}:00:00`,
        ...usageCounters(at.getHours(), 24),
      });
    }
    return series;
  }
  const count = range === "week" ? 7 : range === "month" ? 30 : 365;
  for (let back = count - 1; back >= 0; back -= 1) {
    const at = new Date(now.getTime() - back * 86400_000);
    series.push({
      bucket: dayLabel(at),
      ...usageCounters(back + 3, 340),
    });
  }
  return series;
}

function usageHealth(seed: number): AiUsageHealthBucket[] {
  const now = Date.now();
  return Array.from({ length: 5 }, (_, slot) => ({
    bucket: new Date(now - (4 - slot) * 3600_000).toISOString(),
    requests: Math.round(20 + 40 * steady(seed + slot)),
    failed: 0,
  }));
}

/** How a sample slice of the traffic is counted: as cost, as an API value,
 * unpriced, with no model, or a machine's Ollama counted in none. */
type DemoPricing = "cost" | "api_value" | "unpriced" | "no_model" | "none";

/** A slice of the traffic: one model on one upstream. */
interface DemoUsageSlice {
  upstream: string;
  model: string;
  share: number;
  pricing: DemoPricing;
  /** The price per million tokens it is counted at. */
  input: number;
  output: number;
  currency: string;
}

/** The sample traffic, sliced by upstream and model; the shares sum to 1. */
const DEMO_USAGE_SLICES: DemoUsageSlice[] = [
  slice("provider_deepseek", "deepseek-flash", 0.15, "cost", 0.28, 1.1),
  slice("provider_deepseek", "deepseek-v4-pro", 0.1, "cost", 0.55, 2.2),
  slice("provider_deepseek", "", 0.04, "no_model", 0, 0),
  slice("provider_kimi", "kimi-k3.1-pro", 0.1, "cost", 4, 16, "CNY"),
  slice("provider_kimi", "kimi-k3", 0.06, "cost", 0.58, 2.32),
  slice("provider_zhipu", "glm-5.3", 0.12, "api_value", 0.6, 2.2),
  slice("provider_relay", "claude-fable-5-2", 0.06, "unpriced", 0, 0),
  slice("ollama:dev_desktop", "qwen2.5:7b", 0.03, "none", 0, 0),
  slice("ollama:dev_laptop", "qwen2.5:7b", 0.02, "none", 0, 0),
  slice(
    "codex-xiaoming@example.com.json",
    "gpt-6.2-astra",
    0.18,
    "api_value",
    1.25,
    10,
  ),
  slice(
    "claude-xiaoming@example.com.json",
    "claude-fable-5-2",
    0.1,
    "api_value",
    5,
    25,
  ),
  slice("kimi-xiaoming.json", "kimi-k3.1-pro", 0.04, "api_value", 4, 16, "CNY"),
];

/** The sample upstreams, in the order the table lists them before its sort. */
const DEMO_USAGE_UPSTREAMS = [
  upstream("provider_deepseek", "DeepSeek", "custom", false, 40, 300),
  upstream("provider_kimi", "Kimi", "custom", false, 21, 420),
  upstream(
    "provider_zhipu",
    sample("智谱 GLM", "Zhipu GLM"),
    "custom",
    false,
    14,
    900,
  ),
  upstream(
    "provider_relay",
    sample("中转站", "My relay"),
    "anthropic",
    false,
    6,
    1500,
  ),
  upstream(
    "codex-xiaoming@example.com.json",
    "xiaoming@example.com",
    "codex",
    true,
    9,
    1800,
  ),
  upstream(
    "claude-xiaoming@example.com.json",
    "xiaoming@example.com",
    "claude",
    true,
    18,
    600,
  ),
  upstream("kimi-xiaoming.json", "xiaoming", "kimi", true, 27, 3 * 3600),
];

function slice(
  upstreamId: string,
  model: string,
  share: number,
  pricing: DemoPricing,
  input: number,
  output: number,
  currency = "USD",
): DemoUsageSlice {
  return {
    upstream: upstreamId,
    model,
    share,
    pricing,
    input,
    output,
    currency,
  };
}

function upstream(
  id: string,
  name: string,
  kind: string,
  isAccount: boolean,
  firstSeenDays: number,
  lastSeenS: number,
) {
  return { id, name, kind, isAccount, firstSeenDays, lastSeenS };
}

/** A slice of the traffic counted with its price, in millionths. */
function slicedCounters(
  totals: AiUsageCounters,
  entry: DemoUsageSlice,
): AiUsageCounters {
  const counters = scaledCounters(totals, entry.share);
  const amount = Math.round(
    (counters.input_tokens - counters.cache_read_tokens) * entry.input +
      (counters.cache_read_tokens * entry.input) / 10 +
      counters.output_tokens * entry.output,
  );
  const amounts = { [entry.currency]: amount };
  return {
    ...counters,
    cost: entry.pricing === "cost" ? amounts : {},
    api_value: entry.pricing === "api_value" ? amounts : {},
    unpriced_requests: entry.pricing === "unpriced" ? counters.requests : 0,
  };
}

/** The AI gateway's usage over a range, for one key or for every key. */
export function demoAiUsage(
  range: AiUsageRange,
  keyId: string,
): AiUsageResponse {
  const series = usageSeries(range);
  const tokenTotals = sumCounters(series);
  const slices = DEMO_USAGE_SLICES.map((entry) => ({
    entry,
    counters: slicedCounters(tokenTotals, entry),
  }));
  const totals = sumCounters(slices.map((item) => item.counters));
  const phoneShare = 0.38;
  const desktopShare = 0.62;
  const share = keyId === "key_phone" ? phoneShare : keyId === "" ? 1 : 0.62;
  const shownSeries = series.map((bucket) => ({
    bucket: bucket.bucket,
    ...scaledCounters(
      totals,
      share * (bucket.requests / Math.max(1, tokenTotals.requests)),
    ),
  }));
  const models = new Map<string, AiUsageModelUpstream[]>();
  for (const { entry, counters } of slices) {
    models.set(entry.model, [
      ...(models.get(entry.model) ?? []),
      { upstream: entry.upstream, ...counters },
    ]);
  }
  return {
    range,
    generated_at: secondsAgo(0),
    rates: { rpm: 4.2, tpm: 7800 },
    totals: scaledCounters(totals, share),
    series: shownSeries,
    keys: [
      {
        key_id: "key_desktop",
        name: sample("我的台式机", "My desktop"),
        client_name: null,
        device_name: sample("我的台式机", "My desktop"),
        first_seen_at: secondsAgo(86400 * 30),
        last_seen_at: secondsAgo(300),
        ...scaledCounters(totals, desktopShare),
      },
      {
        key_id: "key_phone",
        name: sample("我的手机", "My phone"),
        client_name: sample("我的手机", "My phone"),
        device_name: null,
        first_seen_at: secondsAgo(86400 * 12),
        last_seen_at: secondsAgo(1200),
        ...scaledCounters(totals, phoneShare),
      },
    ],
    providers: DEMO_USAGE_UPSTREAMS.map((row, index) => ({
      provider_id: row.id,
      name: row.name,
      kind: row.kind,
      is_account: row.isAccount,
      first_seen_at: secondsAgo(86400 * row.firstSeenDays),
      last_seen_at: secondsAgo(row.lastSeenS),
      health: usageHealth(index + 1),
      ...sumCounters(
        slices
          .filter((item) => item.entry.upstream === row.id)
          .map((item) => item.counters),
      ),
    })),
    models: [...models.entries()].map(([model, upstreams]) => ({
      model,
      ...sumCounters(upstreams),
      upstreams,
    })),
  };
}
