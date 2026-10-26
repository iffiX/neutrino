import { useState } from "react";
import { Area, AreaChart, ResponsiveContainer, YAxis } from "recharts";

import { Icon } from "./icon";
import { RowMenu } from "./row_menu";
import { apiPost, describeError } from "../api_client";
import { toDeviceMetrics } from "../device_metrics";
import { formatDuration, formatTimeAgo } from "../format_duration";
import { t, useLanguage } from "../i18n";
import { HUB_EVENT_METRICS, useHubEvents } from "../use_hub_events";
import type { HubEvent } from "../use_hub_events";
import type { DeviceGpuInfo, DeviceView } from "../api_types";

import "./device_monitor.css";

/**
 * The machine page's **Monitor**: four numbers, then the CPU and memory
 * curves, one curve per GPU, and the process table.
 *
 * Everything here comes from the agent's reports, which reach the panel as
 * an event carrying the machine's readings: the monitor opens no connection
 * and asks for nothing. One report makes one point, so the curves are short
 * histories gathered while the page is open. The disk and the temperature
 * are toned by their thresholds. A machine that is offline, or has not
 * reported, shows that it waits for a report alone.
 */

const MAX_SAMPLES = 120;

/** The process table's columns, the abbreviations the agent reports under. */
const COLUMN_PID = "pid";
const COLUMN_CPU = "cpu%";
const COLUMN_MEMORY = "mem%";

interface MonitorSample {
  cpu: number | null;
  memory: number | null;
  gpu_util: (number | null)[];
  gpu_vram: (number | null)[];
}

/** The disk tile's thresholds, in percent, as the Agents page's rings. */
const DISK_WARN_PERCENT = 75;
const DISK_ERROR_PERCENT = 90;

/** The temperature tile's thresholds, in °C. */
const TEMPERATURE_WARN_C = 70;
const TEMPERATURE_ERROR_C = 85;

/** What a tile shows for a reading nobody has reported. */
const NOTHING = "—";

interface DeviceMonitorProps {
  /** The machine; the page keeps it the same for the monitor's life. */
  device: DeviceView;
}

export function DeviceMonitor({ device }: DeviceMonitorProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const metrics = device.client?.metrics ?? null;
  const hasSample =
    device.is_agent_online && metrics !== null && metrics.cpu_percent !== null;
  const [samples, setSamples] = useState<MonitorSample[]>([]);
  // Killing takes two clicks on the same cross; the first only arms it.
  const [pendingKillPid, setPendingKillPid] = useState<number | null>(null);
  const [killError, setKillError] = useState<string | null>(null);

  const handleKill = async (pid: number) => {
    if (pendingKillPid !== pid) {
      setPendingKillPid(pid);
      setKillError(null);
      return;
    }
    setPendingKillPid(null);
    try {
      await apiPost("/hub/device/process/kill", {
        device_id: device.id,
        pid,
      });
    } catch (cause: unknown) {
      setKillError(describeError(cause));
    }
  };

  // A report is what makes a new point, not a rerender.
  const handleMetrics = (event: HubEvent) => {
    const reading = toDeviceMetrics(event);
    if (reading === null || reading.cpu_percent === null) {
      return;
    }
    setSamples((current) =>
      [
        ...current,
        {
          cpu: reading.cpu_percent,
          memory: reading.memory_percent,
          gpu_util: reading.gpus.map((gpu) => gpu.utilization_percent),
          gpu_vram: reading.gpus.map((gpu) => vramPercent(gpu)),
        },
      ].slice(-MAX_SAMPLES),
    );
  };
  useHubEvents([{ type: HUB_EVENT_METRICS, key: device.id }], handleMetrics);

  if (!hasSample || metrics === null) {
    return (
      <div className="device_monitor_empty">
        <Icon name="devices" size={22} />
        <span>{t("ui.device_monitor.waiting")}</span>
      </div>
    );
  }

  return (
    <div className="device_monitor">
      <div className="device_monitor_tiles">
        <MonitorTile
          label={t("ui.machine.uptime")}
          value={
            metrics.uptime_s === null
              ? NOTHING
              : formatDuration(metrics.uptime_s)
          }
        />
        <MonitorTile
          label={t("ui.machine.load")}
          value={
            metrics.load_average.length === 3
              ? metrics.load_average.map((value) => value.toFixed(2)).join(" ")
              : NOTHING
          }
        />
        <MonitorTile
          label={t("ui.machine.disk")}
          value={formatPercent(metrics.disk_percent)}
          tone={toneOf(
            metrics.disk_percent,
            DISK_WARN_PERCENT,
            DISK_ERROR_PERCENT,
          )}
        />
        <MonitorTile
          label={t("ui.machine.temperature")}
          value={
            metrics.temperature_c === null
              ? NOTHING
              : `${Math.round(metrics.temperature_c)}°C`
          }
          tone={toneOf(
            metrics.temperature_c,
            TEMPERATURE_WARN_C,
            TEMPERATURE_ERROR_C,
          )}
        />
      </div>

      <div className="device_monitor_grid">
        <ChartPanel
          title={t("ui.device_monitor.cpu")}
          value={formatPercent(metrics.cpu_percent)}
          gradientPrefix={`mon_cpu_${device.id}`}
          data={samples.map((sample) => ({ a: sample.cpu }))}
          series={[{ key: "a", color: "var(--color-chart-down)" }]}
        />
        <ChartPanel
          title={t("ui.device_monitor.memory")}
          value={formatPercent(metrics.memory_percent)}
          gradientPrefix={`mon_mem_${device.id}`}
          data={samples.map((sample) => ({ a: sample.memory }))}
          series={[{ key: "a", color: "var(--color-chart-up)" }]}
        />
        {metrics.gpus.map((gpu, index) => (
          <ChartPanel
            key={index}
            isWide
            title={gpu.name}
            value={gpuLegend(gpu)}
            gradientPrefix={`mon_gpu${index}_${device.id}`}
            data={samples.map((sample) => ({
              a: sample.gpu_util[index] ?? null,
              b: sample.gpu_vram[index] ?? null,
            }))}
            series={[
              { key: "a", color: "var(--color-chart-down)" },
              { key: "b", color: "var(--color-chart-up)" },
            ]}
          />
        ))}
      </div>

      {metrics.processes.length > 0 && (
        <div className="device_monitor_panel device_monitor_panel--table">
          <table className="device_monitor_processes">
            <colgroup>
              <col className="pid" />
              <col className="user" />
              <col />
              <col className="cpu" />
              <col className="mem" />
              <col className="kill" />
            </colgroup>
            <thead>
              <tr>
                <th className="num">{COLUMN_PID}</th>
                <th>{t("ui.device_monitor.column_user")}</th>
                <th>{t("ui.device_monitor.column_command")}</th>
                <th className="num">{COLUMN_CPU}</th>
                <th className="num">{COLUMN_MEMORY}</th>
                <th className="kill" />
              </tr>
            </thead>
            <tbody>
              {metrics.processes.map((process) => (
                <tr key={process.pid}>
                  <td className="num">{process.pid}</td>
                  <td>{process.user}</td>
                  <td className="device_monitor_process_name">
                    {process.name}
                  </td>
                  <td className="num accent">
                    {process.cpu_percent.toFixed(1)}
                  </td>
                  <td className="num">{process.memory_percent.toFixed(1)}</td>
                  <td className="kill">
                    <RowMenu
                      items={[
                        {
                          key: "kill",
                          label:
                            pendingKillPid === process.pid
                              ? t("ui.device_monitor.kill_again")
                              : t("ui.device_monitor.kill"),
                          icon: "close",
                          isDanger: true,
                          isArming: true,
                          isArmed: pendingKillPid === process.pid,
                          onSelect: () => void handleKill(process.pid),
                        },
                      ]}
                    >
                      <button
                        type="button"
                        className={`device_monitor_kill ${pendingKillPid === process.pid ? "device_monitor_kill--armed" : ""}`}
                        title={
                          pendingKillPid === process.pid
                            ? t("ui.device_monitor.kill_again")
                            : t("ui.device_monitor.kill")
                        }
                        onClick={() => void handleKill(process.pid)}
                      >
                        <Icon name="close" size={11} />
                      </button>
                    </RowMenu>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {killError !== null && (
            <span className="device_monitor_kill_error">{killError}</span>
          )}
        </div>
      )}

      <div className="device_monitor_footer">
        {t("ui.device_monitor.sampled", {
          when: formatTimeAgo(device.client?.last_report_at ?? null),
        })}
      </div>
    </div>
  );
}

interface MonitorTileProps {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "error";
}

/** One number of the four above the curves. */
function MonitorTile({ label, value, tone = "ok" }: MonitorTileProps) {
  return (
    <div className="device_monitor_tile">
      <span className="device_monitor_tile_label">{label}</span>
      <span
        className={`device_monitor_tile_value device_monitor_tile_value--${tone}`}
      >
        {value}
      </span>
    </div>
  );
}

interface ChartSeries {
  key: string;
  color: string;
}

interface ChartPanelProps {
  title: string;
  value: string;
  data: Record<string, number | null>[];
  series: ChartSeries[];
  gradientPrefix: string;
  isWide?: boolean;
}

function ChartPanel({
  title,
  value,
  data,
  series,
  gradientPrefix,
  isWide = false,
}: ChartPanelProps) {
  const gradientId = (key: string) =>
    `${gradientPrefix}_${key}`.replace(/[^a-zA-Z0-9_]/g, "");
  return (
    <div
      className={`device_monitor_panel ${isWide ? "device_monitor_panel--wide" : ""}`}
    >
      <div className="device_monitor_panel_head">
        <span className="device_monitor_panel_title">{title}</span>
        <span className="device_monitor_panel_value">{value}</span>
      </div>
      <div className="device_monitor_chart">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={data}
            margin={{ top: 2, right: 0, bottom: 0, left: 0 }}
          >
            <defs>
              {series.map((entry) => (
                <linearGradient
                  key={entry.key}
                  id={gradientId(entry.key)}
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop offset="0%" stopColor={entry.color} stopOpacity={0.4} />
                  <stop offset="100%" stopColor={entry.color} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <YAxis hide domain={[0, 100]} />
            {series.map((entry) => (
              <Area
                key={entry.key}
                type="monotone"
                dataKey={entry.key}
                stroke={entry.color}
                strokeWidth={1.6}
                fill={`url(#${gradientId(entry.key)})`}
                isAnimationActive={false}
                dot={false}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function formatPercent(percent: number | null): string {
  return percent === null ? NOTHING : `${Math.round(percent)}%`;
}

/** A reading's tone by its two thresholds. */
function toneOf(
  reading: number | null,
  warnAt: number,
  errorAt: number,
): "ok" | "warn" | "error" {
  if (reading === null || reading < warnAt) {
    return "ok";
  }
  return reading >= errorAt ? "error" : "warn";
}

function vramPercent(gpu: DeviceGpuInfo): number | null {
  if (
    gpu.memory_used_mb === null ||
    gpu.memory_total_mb === null ||
    gpu.memory_total_mb === 0
  ) {
    return null;
  }
  return (100 * gpu.memory_used_mb) / gpu.memory_total_mb;
}

function gpuLegend(gpu: DeviceGpuInfo): string {
  const parts = [];
  if (gpu.utilization_percent !== null) {
    parts.push(`${Math.round(gpu.utilization_percent)}%`);
  }
  if (gpu.memory_used_mb !== null && gpu.memory_total_mb !== null) {
    const used = (gpu.memory_used_mb / 1024).toFixed(1);
    const total = (gpu.memory_total_mb / 1024).toFixed(1);
    parts.push(`${used}/${total} GiB`);
  }
  if (gpu.temperature_c !== null) {
    parts.push(`${Math.round(gpu.temperature_c)}°C`);
  }
  if (gpu.power_w !== null) {
    parts.push(`${Math.round(gpu.power_w)} W`);
  }
  return parts.length > 0 ? parts.join(" · ") : "—";
}
