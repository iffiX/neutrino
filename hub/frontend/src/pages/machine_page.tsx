import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { AccountsPanel } from "../components/accounts_panel";
import { DeviceMonitor } from "../components/device_monitor";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { InstallAgentModal } from "../components/install_agent_modal";
import { MachineModules } from "../components/machine_modules";
import { Spinner } from "../components/spinner";
import { StatusDot } from "../components/status_dot";
import { apiPost, describeError } from "../api_client";
import { toDeviceLabel } from "../device_level";
import { toDeviceMetrics, withDeviceMetrics } from "../device_metrics";
import { formatTimeAgo } from "../format_duration";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import {
  HUB_EVENT_DEVICE_REPORT,
  HUB_EVENT_DEVICES,
  HUB_EVENT_METRICS,
  useHubEvents,
} from "../use_hub_events";
import type { HubEvent } from "../use_hub_events";
import { useTaskStream } from "../use_task_stream";
import type {
  DeviceRequest,
  DevicesResponse,
  DeviceView,
  TaskStarted,
} from "../api_types";

import "./machine_page.css";

/**
 * The machine page, `/agents/<id>`: one managed machine, what it does now,
 * what it hosts, and its agent.
 *
 * The header names the machine, its online dot, its agent's version, its
 * system, host name and address, with **Agents** back to the table. Three
 * sections follow: **Monitor**, **Modules** (its available accounts, then
 * its module tabs) and **The agent**. A machine that has not reported yet
 * shows that it waits in each section; an id the hub holds no row for says
 * so, with **Agents** alone.
 */

const DEVICES_PATH = "/hub/device";

// What moves this machine's row: its session opening or ending, its name,
// and a report saying something new about it.
const INVALIDATE_ON = [
  { type: HUB_EVENT_DEVICES },
  { type: HUB_EVENT_DEVICE_REPORT },
];

/** What a field shows for a value the machine has not reported. */
const NOTHING = "—";

export function MachinePage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const { deviceId = "" } = useParams();
  const resource = useApiResource<DevicesResponse>(DEVICES_PATH, {
    invalidateOn: INVALIDATE_ON,
  });
  const [devices, setDevices] = useState<DeviceView[]>([]);

  useEffect(() => {
    if (resource.data !== null) {
      setDevices(resource.data.devices);
    }
  }, [resource.data]);

  // Readings ride their own event; the monitor redraws from what arrived.
  const handleMetrics = (event: HubEvent) => {
    const metrics = toDeviceMetrics(event);
    if (metrics === null || event.key !== deviceId) {
      return;
    }
    setDevices((current) =>
      withDeviceMetrics(current, event.key, metrics, event.at),
    );
  };
  useHubEvents([{ type: HUB_EVENT_METRICS, key: deviceId }], handleMetrics);

  if (resource.error !== null && resource.data === null) {
    return (
      <div className="page">
        <h1>{t("ui.nav.devices")}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }
  if (resource.data === null) {
    return (
      <div className="page">
        <div className="skeleton" style={{ height: 48 }} />
        <div className="skeleton" style={{ height: 320 }} />
      </div>
    );
  }

  const device = devices.find((held) => held.id === deviceId) ?? null;
  if (device === null) {
    return (
      <div className="page">
        <div className="page_header">
          <div className="page_header_text">
            <div className="page_title_row">
              <h1>{t("ui.machine.not_found")}</h1>
            </div>
          </div>
          <div className="page_actions">
            <BackButton />
          </div>
        </div>
      </div>
    );
  }

  return (
    <MachineView
      key={device.id}
      device={device}
      onReinstalled={resource.reload}
    />
  );
}

interface MachineViewProps {
  device: DeviceView;
  /** Called once an install of the agent ends. */
  onReinstalled: () => void;
}

function MachineView({ device, onReinstalled }: MachineViewProps) {
  const client = device.client;
  const isOnline = device.is_agent_online;
  const name = toDeviceLabel(device);
  const platform = [client?.platform_os, client?.platform_arch]
    .filter((part): part is string => part != null && part !== "")
    .join(" · ");
  return (
    <div className="page machine_page">
      <div className="page_header">
        <div className="page_header_text">
          <div className="page_title_row">
            <h1>{name}</h1>
            <StatusDot
              tone={isOnline ? "ok" : "idle"}
              isPulsing={isOnline}
              label={t(isOnline ? "state.online" : "state.offline")}
            />
            {client?.version != null && (
              <span
                className={`badge ${client.is_version_mismatched ? "badge--warn" : "badge--ok"}`}
              >
                {t("ui.machine.agent_version", { version: client.version })}
              </span>
            )}
            {platform !== "" && <span className="badge mono">{platform}</span>}
            {client?.hostname != null && client.hostname !== "" && (
              <span className="badge mono">{client.hostname}</span>
            )}
            {device.ipv4_address !== "" && (
              <span className="badge mono">{device.ipv4_address}</span>
            )}
          </div>
        </div>
        <div className="page_actions">
          <BackButton />
        </div>
      </div>

      <section className="machine_section">
        <h2 className="machine_section_title">{t("ui.machine.monitor")}</h2>
        <div className="card">
          <DeviceMonitor device={device} />
        </div>
      </section>

      <section className="machine_section">
        <h2 className="machine_section_title">{t("ui.machine.modules")}</h2>
        {client === null ? (
          <WaitingCard />
        ) : (
          <>
            <AccountsPanel deviceId={device.id} isEditable={isOnline} />
            <section className="settings_group">
              <div className="settings_group_title">
                <h2>{t("ui.modules.tabs_title")}</h2>
              </div>
              <MachineModules
                deviceId={device.id}
                deviceName={name}
                platformOs={client.platform_os ?? ""}
              />
            </section>
          </>
        )}
      </section>

      <section className="machine_section">
        <h2 className="machine_section_title">{t("ui.machine.agent")}</h2>
        {client === null ? (
          <WaitingCard />
        ) : (
          <AgentPanel device={device} onReinstalled={onReinstalled} />
        )}
      </section>
    </div>
  );
}

interface AgentPanelProps {
  device: DeviceView;
  onReinstalled: () => void;
}

/** **The agent**: four rows, **Update agent** and **Reinstall**. */
function AgentPanel({ device, onReinstalled }: AgentPanelProps) {
  const client = device.client;
  const [taskId, setTaskId] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isInstallOpen, setIsInstallOpen] = useState(false);
  const task = useTaskStream(taskId);
  const wasRunning = useRef(false);

  useEffect(() => {
    if (task.isRunning) {
      wasRunning.current = true;
      return;
    }
    if (wasRunning.current) {
      wasRunning.current = false;
      onReinstalled();
    }
  }, [task.isRunning, onReinstalled]);

  const update = async () => {
    setIsBusy(true);
    setError(null);
    setTaskId(null);
    const request: DeviceRequest = { device_id: device.id };
    try {
      const started = await apiPost<TaskStarted>(
        `${DEVICES_PATH}/agent/reinstall`,
        request,
      );
      setTaskId(started.task_id);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const canUpdate =
    device.is_agent_online &&
    client?.is_version_mismatched === true &&
    !isBusy &&
    !task.isRunning;
  const platform = [client?.platform_os, client?.platform_arch]
    .filter((part): part is string => part != null && part !== "")
    .join(" · ");

  return (
    <div className="settings_group">
      <dl className="machine_facts">
        <dt>{t("ui.machine.version")}</dt>
        <dd className="mono">{client?.version ?? NOTHING}</dd>
        <dt>{t("ui.machine.platform")}</dt>
        <dd className="mono">{platform || NOTHING}</dd>
        <dt>{t("ui.machine.hostname")}</dt>
        <dd className="mono">{client?.hostname || NOTHING}</dd>
        <dt>{t("ui.machine.last_report")}</dt>
        <dd className="mono">
          {formatTimeAgo(client?.last_report_at ?? null)}
        </dd>
      </dl>
      <div className="machine_agent_actions">
        <button
          type="button"
          className="button"
          disabled={!canUpdate}
          onClick={() => void update()}
        >
          {task.isRunning ? (
            <Spinner size={13} />
          ) : (
            <Icon name="download" size={14} />
          )}
          {t("ui.machine.agent_update")}
        </button>
        <button
          type="button"
          className="button"
          disabled={task.isRunning}
          onClick={() => setIsInstallOpen(true)}
        >
          <Icon name="refresh" size={14} />
          {t("ui.machine.agent_reinstall")}
        </button>
      </div>
      {taskId !== null && (
        <StatusDot
          tone={
            task.isRunning
              ? "warn"
              : task.exitCode === 0
                ? "ok"
                : task.exitCode === null
                  ? "idle"
                  : "error"
          }
          isPulsing={task.isRunning}
          label={
            task.isRunning
              ? t("ui.devices.task_running", {
                  action: t("ui.machine.agent_update"),
                })
              : t("ui.devices.task_finished", {
                  action: t("ui.machine.agent_update"),
                  code: task.exitCode ?? "",
                })
          }
        />
      )}
      {error !== null && <span className="field_error">{error}</span>}
      {isInstallOpen && (
        <InstallAgentModal
          device={device}
          onClose={() => setIsInstallOpen(false)}
          onFinished={onReinstalled}
        />
      )}
    </div>
  );
}

/** A section's whole content while the machine has not reported. */
function WaitingCard() {
  return (
    <div className="card machine_waiting">
      <Icon name="devices" size={22} />
      <span>{t("ui.device_monitor.waiting")}</span>
    </div>
  );
}

/** **Agents**, back to the table. */
function BackButton() {
  return (
    <Link to="/agents" className="button">
      <Icon name="devices" size={14} />
      {t("ui.nav.devices")}
    </Link>
  );
}
