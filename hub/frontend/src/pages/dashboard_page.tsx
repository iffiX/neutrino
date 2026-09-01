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

import { ChartTooltip } from "../components/chart_tooltip";
import { DnsLogList } from "../components/dns_log_list";
import { ErrorPanel } from "../components/error_panel";
import { StatTile } from "../components/stat_tile";
import { StatusDot } from "../components/status_dot";
import { computeActiveExits } from "../active_exits";
import { formatByteRate, formatBytes } from "../format_bytes";
import { formatDuration, formatLatency } from "../format_duration";
import { toHistorySeries, toTrafficSeries } from "../traffic_series";
import { useApiResource } from "../use_api_resource";
import { useDnsLogSocket } from "../use_dns_log_socket";
import { useLiveStats } from "../use_live_stats";
import type { DashboardSummary, TrafficHistoryResponse } from "../api_types";

import "./dashboard_page.css";

/**
 * The landing page: what the gateway is doing right now.
 *
 * The live chart is driven entirely by the shared stats socket, so it keeps
 * streaming even when the summary fetch fails — which is the common case while
 * the backend restarts. Each block therefore renders its own error rather than
 * one failure blanking the page.
 */

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
  const { frames, latestFrame, status } = useLiveStats();
  const summary = useApiResource<DashboardSummary>("/dashboard/summary");
  const history = useApiResource<TrafficHistoryResponse>(
    `/dashboard/history?days=${HISTORY_DAYS}`,
  );
  const dnsLog = useDnsLogSocket();

  const trafficSeries = toTrafficSeries(frames);
  const latestPoint = trafficSeries[trafficSeries.length - 1];
  const historySeries = toHistorySeries(history.data?.samples ?? []);
  const activeExits = computeActiveExits(
    frames,
    summary.data?.active_exit_tags ?? [],
  );
  const stats = latestFrame ?? summary.data?.stats ?? null;

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_header_text">
          <h1>Dashboard</h1>
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
                ? "streaming"
                : status === "connecting"
                  ? "connecting"
                  : "stats socket offline"
            }
          />
        </div>
      </div>

      {summary.error !== null && (
        <ErrorPanel
          title="Summary unavailable"
          message={summary.error}
          onRetry={summary.reload}
        />
      )}

      <div className="stat_tile_grid">
        <StatTile
          label="Downloaded"
          value={stats?.total_downlink_bytes ?? 0}
          format={formatBytes}
          icon="arrow_down"
          tone="accent"
          detail={
            latestPoint === undefined
              ? "waiting for frames"
              : formatByteRate(latestPoint.downlink_bytes_per_s)
          }
        />
        <StatTile
          label="Uploaded"
          value={stats?.total_uplink_bytes ?? 0}
          format={formatBytes}
          icon="arrow_up"
          tone="secondary"
          detail={
            latestPoint === undefined
              ? "waiting for frames"
              : formatByteRate(latestPoint.uplink_bytes_per_s)
          }
        />
        <StatTile
          label="Active exits"
          value={activeExits.length}
          format={formatCount}
          icon="nodes"
          tone="ok"
          detail={`${stats?.nodes.length ?? 0} probed`}
        />
        <StatTile
          label="LAN devices"
          value={summary.data?.lan_device_count ?? 0}
          format={formatCount}
          icon="devices"
          tone="secondary"
          detail="seen on the LAN"
        />
        <StatTile
          label="DNS queries"
          value={summary.data?.dns_query_count ?? 0}
          format={formatCount}
          icon="search"
          tone="accent"
          detail="in the recent log"
        />
        <StatTile
          label="CPU"
          value={stats?.cpu_percent ?? 0}
          format={formatPercent}
          unit="%"
          icon="cpu"
          tone={toLoadTone(stats?.cpu_percent ?? 0)}
          meterPercent={stats?.cpu_percent ?? 0}
        />
        <StatTile
          label="Memory"
          value={stats?.memory_percent ?? 0}
          format={formatPercent}
          unit="%"
          icon="memory"
          tone={toLoadTone(stats?.memory_percent ?? 0)}
          meterPercent={stats?.memory_percent ?? 0}
        />
        <StatTile
          label="Uptime"
          value={stats?.uptime_s ?? 0}
          format={formatDuration}
          icon="clock"
          tone="ok"
          detail={stats?.wan_address ?? "no WAN address"}
        />
      </div>

      <div className="dashboard_layout">
        <div className="dashboard_column">
          <section className="card">
            <div className="card_header">
              <div className="card_title">
                <h2>Live traffic</h2>
                <span className="badge">last 2 min</span>
              </div>
              <div className="dashboard_legend">
                <span className="dashboard_legend_item">
                  <span className="dashboard_legend_swatch dashboard_legend_swatch--down" />
                  <span className="muted">down</span>
                  <span className="dashboard_legend_value">
                    {latestPoint === undefined
                      ? "—"
                      : formatByteRate(latestPoint.downlink_bytes_per_s)}
                  </span>
                </span>
                <span className="dashboard_legend_item">
                  <span className="dashboard_legend_swatch dashboard_legend_swatch--up" />
                  <span className="muted">up</span>
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
                <span>Waiting for the first stats frames</span>
                <span className="faint">
                  The gateway pushes a frame every two seconds on /ws/stats.
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
                      name="down"
                      stroke="#22d3ee"
                      strokeWidth={1.6}
                      fill="url(#fill_down)"
                      isAnimationActive={false}
                      dot={false}
                    />
                    <Area
                      type="monotone"
                      dataKey="uplink_bytes_per_s"
                      name="up"
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
                <h2>Traffic history</h2>
                <span className="badge">last {HISTORY_DAYS} days · vnstat</span>
              </div>
            </div>

            {history.error !== null ? (
              <ErrorPanel
                title="History unavailable"
                message={history.error}
                hint="vnstat may not have collected any data on this interface yet."
                onRetry={history.reload}
              />
            ) : historySeries.length === 0 ? (
              <div className="placeholder">
                <span>No history yet</span>
                <span className="faint">
                  vnstat needs a day of samples before the chart fills in.
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
                      name="received"
                      stackId="traffic"
                      fill="#22d3ee"
                      radius={[0, 0, 0, 0]}
                    />
                    <Bar
                      dataKey="sent_bytes"
                      name="sent"
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
                <h2>Active exits</h2>
              </div>
            </div>
            {activeExits.length === 0 ? (
              <div className="placeholder">
                <span>No exit is carrying traffic</span>
                <span className="faint">
                  Either the LAN is idle or every request is matching a direct
                  rule.
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
                        <span>{formatBytes(exit.totalBytes)} / 2 min</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="card">
            <div className="card_header dashboard_dns_head">
              <div className="card_title">
                <h2>DNS queries</h2>
                <span className="badge">newest first</span>
              </div>
              <StatusDot
                tone={dnsLog.status === "open" ? "ok" : "warn"}
                label={`${dnsLog.entries.length} held`}
              />
            </div>
            <DnsLogList entries={dnsLog.entries} />
          </section>
        </div>
      </div>
    </div>
  );
}

function formatCount(value: number): string {
  return Math.round(value).toLocaleString();
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
