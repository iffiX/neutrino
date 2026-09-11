import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { AiUsageOverview } from "../components/ai_usage_overview";
import { ChartTooltip } from "../components/chart_tooltip";
import { DnsLogList } from "../components/dns_log_list";
import { ErrorPanel } from "../components/error_panel";
import { DeadExitsNotice } from "../components/dead_exits_notice";
import { StatTile } from "../components/stat_tile";
import { StatusDot } from "../components/status_dot";
import { computeActiveExits } from "../active_exits";
import { formatByteRate, formatBytes } from "../format_bytes";
import { formatCompact } from "../format_compact";
import { formatDuration, formatLatency } from "../format_duration";
import { t, useLanguage } from "../i18n";
import { toHistorySeries, toTrafficSeries } from "../traffic_series";
import { useApiResource } from "../use_api_resource";
import { useDnsLogSocket } from "../use_dns_log_socket";
import { useLiveStats } from "../use_live_stats";
import { HUB_EVENT_AI_USAGE, HUB_EVENT_CONFIG } from "../use_hub_events";
import type {
  CliproxyApiStatusView,
  DashboardSummary,
  TrafficHistoryResponse,
} from "../api_types";

import "./dashboard_page.css";

/**
 * The landing page: what the gateway is doing right now.
 *
 * The live chart is driven entirely by the shared stats socket, so it keeps
 * streaming even when the summary fetch fails — which is the common case while
 * the backend restarts. Each block therefore renders its own error rather than
 * one failure blanking the page.
 */

/** A reading the gateway has not reported at all, as opposed to a zero. */
const MISSING_READING = "—";

const HISTORY_DAYS = 30;
const AXIS_STYLE = {
  fill: "#5b6675",
  fontSize: 11,
  fontFamily: "ui-monospace",
};
const CHART_MARGIN = { top: 8, right: 8, bottom: 0, left: 0 };
const LOAD_WARN_PERCENT = 70;
const LOAD_ERROR_PERCENT = 90;

export function DashboardPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const { frames, latestFrame, status } = useLiveStats();
  const summary = useApiResource<DashboardSummary>("/dashboard/summary");
  const history = useApiResource<TrafficHistoryResponse>(
    `/dashboard/history?days=${HISTORY_DAYS}`,
  );
  const dnsLog = useDnsLogSocket();
  // The same status view the top bar reads. A gateway that is absent or has
  // served nothing leaves the tile blank rather than reporting a failure.
  const ai = useApiResource<CliproxyApiStatusView>("/cliproxyapi", {
    invalidateOn: [{ type: HUB_EVENT_AI_USAGE }, { type: HUB_EVENT_CONFIG }],
  });

  const trafficSeries = toTrafficSeries(frames);
  const latestPoint = trafficSeries[trafficSeries.length - 1];
  const historySeries = toHistorySeries(history.data?.samples ?? []);
  const activeExits = computeActiveExits(
    frames,
    summary.data?.active_exit_tags ?? [],
  );
  const stats = latestFrame ?? summary.data?.stats ?? null;
  const todaySample = history.data?.samples.at(-1) ?? null;
  const aiTokensToday = ai.data?.tokens_today ?? null;

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_header_text">
          <h1>{t("ui.dashboard.title")}</h1>
        </div>
        <div className="page_actions">
          <StatusDot
            tone={
              status === "open"
                ? "ok"
                : status === "connecting"
                  ? "warn"
                  : "error"
            }
            label={
              status === "open"
                ? t("state.streaming")
                : status === "connecting"
                  ? t("state.connecting")
                  : t("ui.dashboard.stats_offline")
            }
          />
        </div>
      </div>

      {summary.error !== null && (
        <ErrorPanel
          title={t("ui.dashboard.summary_unavailable")}
          message={summary.error}
          onRetry={summary.reload}
        />
      )}

      <DeadExitsNotice />

      <div className="stat_tile_grid dashboard_tiles">
        <StatTile
          label={t("ui.dashboard.tile_download")}
          value={stats?.interface_rx_bytes_per_s ?? 0}
          format={formatByteRate}
          icon="arrow_down"
          tone="accent"
          detail={
            todaySample === null
              ? MISSING_READING
              : t("ui.dashboard.tile_today_total", {
                  total: formatBytes(todaySample.received_bytes),
                })
          }
        />
        <StatTile
          label={t("ui.dashboard.tile_upload")}
          value={stats?.interface_tx_bytes_per_s ?? 0}
          format={formatByteRate}
          icon="arrow_up"
          tone="secondary"
          detail={
            todaySample === null
              ? MISSING_READING
              : t("ui.dashboard.tile_today_total", {
                  total: formatBytes(todaySample.sent_bytes),
                })
          }
        />
        <StatTile
          label={t("ui.dashboard.tile_dns_queries")}
          value={summary.data?.dns_query_count ?? 0}
          format={formatCount}
          icon="search"
          tone="accent"
          detail={t("ui.dashboard.tile_in_recent_log")}
        />
        <StatTile
          label={t("ui.dashboard.tile_proxy_exits")}
          value={activeExits.length}
          format={formatCount}
          icon="nodes"
          tone="ok"
          detail={t("ui.dashboard.tile_probed", {
            count: stats?.nodes.length ?? 0,
          })}
        />
        <StatTile
          label={t("ui.dashboard.tile_ai_tokens")}
          value={aiTokensToday ?? 0}
          format={aiTokensToday === null ? formatMissing : formatCompact}
          icon="sparkles"
          tone="secondary"
          detail={t("ui.dashboard.tile_served_today")}
        />
        <StatTile
          label={t("ui.dashboard.tile_devices")}
          value={stats?.agent_device_count ?? 0}
          format={formatCount}
          icon="devices"
          tone="secondary"
          detail={t("ui.dashboard.tile_agents_reporting")}
        />
        <StatTile
          label={t("ui.dashboard.tile_cpu")}
          value={stats?.cpu_percent ?? 0}
          format={formatPercent}
          unit="%"
          icon="cpu"
          tone={toLoadTone(stats?.cpu_percent ?? 0)}
          meterPercent={stats?.cpu_percent ?? 0}
        />
        <StatTile
          label={t("ui.dashboard.tile_memory")}
          value={stats?.memory_percent ?? 0}
          format={formatPercent}
          unit="%"
          icon="memory"
          tone={toLoadTone(stats?.memory_percent ?? 0)}
          meterPercent={stats?.memory_percent ?? 0}
        />
        <StatTile
          label={t("ui.dashboard.tile_uptime")}
          value={stats?.uptime_s ?? 0}
          format={formatDuration}
          icon="clock"
          tone="ok"
          detail={stats?.wan_address ?? t("ui.dashboard.tile_no_wan_address")}
        />
      </div>

      <div className="dashboard_layout">
        <div className="dashboard_column">
          <section className="card">
            <div className="card_header">
              <div className="card_title">
                <h2>{t("ui.dashboard.live_traffic_title")}</h2>
                <span className="badge">
                  {t("ui.dashboard.live_traffic_window")}
                </span>
              </div>
              <div className="dashboard_legend">
                <span className="dashboard_legend_item">
                  <span className="dashboard_legend_swatch dashboard_legend_swatch--down" />
                  <span className="muted">{t("ui.dashboard.legend_down")}</span>
                  <span className="dashboard_legend_value">
                    {latestPoint === undefined
                      ? "—"
                      : formatByteRate(latestPoint.downlink_bytes_per_s)}
                  </span>
                </span>
                <span className="dashboard_legend_item">
                  <span className="dashboard_legend_swatch dashboard_legend_swatch--up" />
                  <span className="muted">{t("ui.dashboard.legend_up")}</span>
                  <span className="dashboard_legend_value">
                    {latestPoint === undefined
                      ? "—"
                      : formatByteRate(latestPoint.uplink_bytes_per_s)}
                  </span>
                </span>
              </div>
            </div>

            {trafficSeries.length === 0 ? (
              <div className="placeholder">
                <span>{t("ui.dashboard.live_empty")}</span>
                <span className="faint">
                  {t("ui.dashboard.live_empty_hint")}
                </span>
              </div>
            ) : (
              <div className="dashboard_chart">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={trafficSeries} margin={CHART_MARGIN}>
                    <defs>
                      <linearGradient
                        id="fill_down"
                        x1="0"
                        y1="0"
                        x2="0"
                        y2="1"
                      >
                        <stop
                          offset="0%"
                          stopColor="#22d3ee"
                          stopOpacity={0.42}
                        />
                        <stop
                          offset="100%"
                          stopColor="#22d3ee"
                          stopOpacity={0}
                        />
                      </linearGradient>
                      <linearGradient id="fill_up" x1="0" y1="0" x2="0" y2="1">
                        <stop
                          offset="0%"
                          stopColor="#a78bfa"
                          stopOpacity={0.34}
                        />
                        <stop
                          offset="100%"
                          stopColor="#a78bfa"
                          stopOpacity={0}
                        />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="#1a2230" vertical={false} />
                    <XAxis
                      dataKey="label"
                      tick={AXIS_STYLE}
                      tickLine={false}
                      axisLine={{ stroke: "#1f2937" }}
                      minTickGap={44}
                    />
                    <YAxis
                      tick={AXIS_STYLE}
                      tickLine={false}
                      axisLine={false}
                      width={64}
                      tickFormatter={formatByteRate}
                    />
                    <Tooltip
                      cursor={{ stroke: "#2b3648" }}
                      content={<ChartTooltip format={formatByteRate} />}
                    />
                    <Area
                      type="monotone"
                      dataKey="downlink_bytes_per_s"
                      name={t("ui.dashboard.legend_down")}
                      stroke="#22d3ee"
                      strokeWidth={1.6}
                      fill="url(#fill_down)"
                      isAnimationActive={false}
                      dot={false}
                    />
                    <Area
                      type="monotone"
                      dataKey="uplink_bytes_per_s"
                      name={t("ui.dashboard.legend_up")}
                      stroke="#a78bfa"
                      strokeWidth={1.6}
                      fill="url(#fill_up)"
                      isAnimationActive={false}
                      dot={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>

          <section className="card">
            <div className="card_header">
              <div className="card_title">
                <h2>{t("ui.dashboard.history_title")}</h2>
                <span className="badge">
                  {t("ui.dashboard.history_window", { days: HISTORY_DAYS })}
                </span>
              </div>
            </div>

            {history.error !== null ? (
              <ErrorPanel
                title={t("ui.dashboard.history_unavailable")}
                message={history.error}
                hint={t("ui.dashboard.history_unavailable_hint")}
                onRetry={history.reload}
              />
            ) : historySeries.length === 0 ? (
              <div className="placeholder">
                <span>{t("ui.dashboard.history_empty")}</span>
                <span className="faint">
                  {t("ui.dashboard.history_empty_hint")}
                </span>
              </div>
            ) : (
              <div className="dashboard_chart dashboard_chart--history">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={historySeries} margin={CHART_MARGIN}>
                    <CartesianGrid stroke="#1a2230" vertical={false} />
                    <XAxis
                      dataKey="label"
                      tick={AXIS_STYLE}
                      tickLine={false}
                      axisLine={{ stroke: "#1f2937" }}
                      minTickGap={24}
                    />
                    <YAxis
                      tick={AXIS_STYLE}
                      tickLine={false}
                      axisLine={false}
                      width={64}
                      tickFormatter={formatBytes}
                    />
                    <Tooltip
                      cursor={{ fill: "rgba(34, 211, 238, 0.06)" }}
                      content={<ChartTooltip format={formatBytes} />}
                    />
                    <Bar
                      dataKey="received_bytes"
                      name={t("ui.dashboard.series_received")}
                      stackId="traffic"
                      fill="#22d3ee"
                      radius={[0, 0, 0, 0]}
                    />
                    <Bar
                      dataKey="sent_bytes"
                      name={t("ui.dashboard.series_sent")}
                      stackId="traffic"
                      fill="#a78bfa"
                      radius={[2, 2, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>
        </div>

        <div className="dashboard_column">
          <section className="card">
            <div className="card_header">
              <div className="card_title">
                <h2>{t("ui.dashboard.exits_title")}</h2>
              </div>
            </div>
            {activeExits.length === 0 ? (
              <div className="placeholder">
                <span>{t("ui.dashboard.exits_empty")}</span>
                <span className="faint">
                  {t("ui.dashboard.exits_empty_hint")}
                </span>
              </div>
            ) : (
              <div className="dashboard_exits">
                {activeExits.map((exit) => (
                  <div
                    key={exit.tag}
                    className={`dashboard_exit ${exit.is_alive ? "" : "dashboard_exit--dead"}`}
                  >
                    <StatusDot
                      tone={exit.is_alive ? "ok" : "error"}
                      isPulsing={exit.is_alive}
                      isLarge
                    />
                    <div>
                      <div className="dashboard_exit_tag">{exit.tag}</div>
                      <div className="dashboard_exit_meta">
                        <span className="dashboard_exit_latency">
                          {formatLatency(exit.delayMs)}
                        </span>
                        <span>
                          {t("ui.dashboard.exit_window", {
                            bytes: formatBytes(exit.totalBytes),
                          })}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="card dashboard_dns_card">
            <div className="card_header dashboard_dns_head">
              <div className="card_title">
                <h2>{t("ui.dashboard.dns_title")}</h2>
                <span className="badge">{t("ui.dashboard.dns_order")}</span>
              </div>
              <StatusDot
                tone={dnsLog.status === "open" ? "ok" : "warn"}
                label={t("ui.dashboard.dns_held", {
                  count: dnsLog.entries.length,
                })}
              />
            </div>
            <DnsLogList entries={dnsLog.entries} />
          </section>
        </div>
      </div>

      <AiUsageOverview />
    </div>
  );
}

function formatCount(value: number): string {
  return Math.round(value).toLocaleString();
}

function formatMissing(): string {
  return MISSING_READING;
}

function formatPercent(value: number): string {
  return value.toFixed(1);
}

function toLoadTone(percent: number): "ok" | "warn" | "error" {
  if (percent >= LOAD_ERROR_PERCENT) {
    return "error";
  }
  if (percent >= LOAD_WARN_PERCENT) {
    return "warn";
  }
  return "ok";
}
