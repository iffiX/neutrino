import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Area, AreaChart, ResponsiveContainer, YAxis } from "recharts";

import { Icon } from "./icon";
import { apiPost, describeError } from "../api_client";
import { formatDuration, formatTimeAgo } from "../format_duration";
import type { DeviceGpuInfo, DeviceView } from "../api_types";

import "./device_monitor.css";

/**
 * Live vitals for the device whose drawer is open, in the space the drawer
 * leaves free.
 *
 * Everything here comes from the agent's heartbeat, refreshed by the page's
 * normal polling — the monitor itself opens no connection. Readings are drawn
 * as short history curves, accumulated while the panel is open, in the same
 * visual language as the dashboard's traffic chart. A device without the
 * agent gets a pointer to the one-click install instead of empty charts.
 */

const MAX_SAMPLES = 120;

// A heartbeat arrives every few seconds; past this the readings are history,
// not vitals, and the panel says so rather than drawing a frozen chart as
// though it were live.
const STALE_AFTER_MS = 30_000;

const CYAN = "#22d3ee";
const VIOLET = "#a78bfa";

interface MonitorSample {
  cpu: number | null;
  memory: number | null;
  gpu_util: (number | null)[];
  gpu_vram: (number | null)[];
}

interface DeviceMonitorProps {
  device: DeviceView;
}

export function DeviceMonitor({ device }: DeviceMonitorProps) {
  const client = device.client;
  const hasSample = client !== null && client.cpu_percent !== null;
  const isStale = hasSample && isOlderThan(client.last_seen, STALE_AFTER_MS);

  const [samples, setSamples] = useState<MonitorSample[]>([]);
  // Killing takes two clicks on the same cross; the first only arms it.
  const [pendingKillPid, setPendingKillPid] = useState<number | null>(null);
  const [killError, setKillError] = useState<string | null>(null);

  // Selecting another device keeps this component mounted, so its history has
  // to be dropped by hand rather than by a remount.
  useEffect(() => {
    setSamples([]);
    setPendingKillPid(null);
    setKillError(null);
  }, [device.mac_address]);

  const handleKill = async (pid: number) => {
    if (pendingKillPid !== pid) {
      setPendingKillPid(pid);
      setKillError(null);
      return;
    }
    setPendingKillPid(null);
    try {
      await apiPost(`/devices/${device.mac_address}/kill_process`, { pid });
    } catch (cause: unknown) {
      setKillError(describeError(cause));
    }
  };

  const lastSeen = client?.last_seen ?? null;
  useEffect(() => {
    if (client === null || client.cpu_percent === null || isStale) {
      return;
    }
    setSamples((current) =>
      [
        ...current,
        {
          cpu: client.cpu_percent,
          memory: client.memory_percent,
          gpu_util: client.gpus.map((gpu) => gpu.utilization_percent),
          gpu_vram: client.gpus.map((gpu) => vramPercent(gpu)),
        },
      ].slice(-MAX_SAMPLES),
    );
    // A new heartbeat is what makes a new point, not a rerender.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [device.mac_address, lastSeen]);

  // A portal, so the monitor escapes the page's stacking context and can sit
  // above the drawer's backdrop; the wrap centres it in the free space.
  return createPortal(
    <div className="device_monitor_wrap">
      <div className="device_monitor">
        <div className="device_monitor_head">
          <span className="section_label">Live monitor</span>
          {hasSample && client !== null && (
            <span className="device_monitor_meta">
              {client.uptime_s !== null && (
                <span>up {formatDuration(client.uptime_s)}</span>
              )}
              {client.load_average.length === 3 && (
                <span>
                  load {client.load_average.map((v) => v.toFixed(2)).join(" ")}
                </span>
              )}
              {client.disk_percent !== null && (
                <span>disk {Math.round(client.disk_percent)}%</span>
              )}
              {client.temperature_c !== null && (
                <span>{Math.round(client.temperature_c)}°C</span>
              )}
            </span>
          )}
        </div>

        {!hasSample || client === null ? (
          <div className="device_monitor_empty">
            <Icon name="devices" size={22} />
            <span>
              {client !== null
                ? "Waiting for the agent's first heartbeat."
                : "Install the agent to see the live monitor."}
            </span>
          </div>
        ) : (
          <div className="device_monitor_body">
            <div className="device_monitor_grid">
              <ChartPanel
                title="CPU"
                value={formatPercent(client.cpu_percent)}
                gradientPrefix={`mon_cpu_${device.mac_address}`}
                data={samples.map((sample) => ({ a: sample.cpu }))}
                series={[{ key: "a", color: CYAN }]}
              />
              <ChartPanel
                title="Memory"
                value={formatPercent(client.memory_percent)}
                gradientPrefix={`mon_mem_${device.mac_address}`}
                data={samples.map((sample) => ({ a: sample.memory }))}
                series={[{ key: "a", color: VIOLET }]}
              />
              {client.gpus.map((gpu, index) => (
                <ChartPanel
                  key={index}
                  isWide
                  title={gpu.name}
                  value={gpuLegend(gpu)}
                  gradientPrefix={`mon_gpu${index}_${device.mac_address}`}
                  data={samples.map((sample) => ({
                    a: sample.gpu_util[index] ?? null,
                    b: sample.gpu_vram[index] ?? null,
                  }))}
                  series={[
                    { key: "a", color: CYAN },
                    { key: "b", color: VIOLET },
                  ]}
                />
              ))}
            </div>

            {client.processes.length > 0 && (
              <div className="device_monitor_panel">
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
                      <th className="num">pid</th>
                      <th>user</th>
                      <th>command</th>
                      <th className="num">cpu%</th>
                      <th className="num">mem%</th>
                      <th className="kill" />
                    </tr>
                  </thead>
                  <tbody>
                    {client.processes.map((process) => (
                      <tr key={process.pid}>
                        <td className="num">{process.pid}</td>
                        <td>{process.user}</td>
                        <td className="device_monitor_process_name">
                          {process.name}
                        </td>
                        <td className="num accent">
                          {process.cpu_percent.toFixed(1)}
                        </td>
                        <td className="num">
                          {process.memory_percent.toFixed(1)}
                        </td>
                        <td className="kill">
                          <button
                            type="button"
                            className={`device_monitor_kill ${pendingKillPid === process.pid ? "device_monitor_kill--armed" : ""}`}
                            title={
                              pendingKillPid === process.pid
                                ? "Click again to kill"
                                : "Kill process"
                            }
                            onClick={() => void handleKill(process.pid)}
                          >
                            <Icon name="close" size={11} />
                          </button>
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
              sampled {formatTimeAgo(client.last_seen)}
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
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

/** Whether a timestamp is older than a cutoff; unparseable reads as stale. */
function isOlderThan(timestamp: string | null, ageMs: number): boolean {
  if (timestamp === null) {
    return true;
  }
  const stamp = Date.parse(timestamp);
  return Number.isNaN(stamp) || Date.now() - stamp > ageMs;
}

function formatPercent(percent: number | null): string {
  return percent === null ? "—" : `${Math.round(percent)}%`;
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
