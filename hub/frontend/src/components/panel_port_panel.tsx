import { useEffect, useRef, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { interruptionWarning } from "../network_warnings";
import { hubHost, isOffPanelPort } from "../origins";
import { useApiResource } from "../use_api_resource";
import { useDraft } from "../use_draft";
import {
  HUB_EVENT_CLIENTS,
  HUB_EVENT_CONFIG,
  HUB_EVENT_DEVICES,
} from "../use_hub_events";
import type { DirectView, FrpView, SettingsView } from "../api_types";

import "./panel_port_panel.css";

/**
 * The three ports the hub answers on: the panel's HTTP and HTTPS ports, and
 * the port agents and clients connect to.
 *
 * Every other service settles its port in its own tab; these belong on this
 * page because they are a question about how the box is reached, which is
 * what the rest of the page is.
 *
 * Applying restarts the panel. The answer is written before the socket
 * closes, and after a panel port change this waits for the port of the scheme
 * this page is on to answer and goes there; the host does not change, so
 * where to look is known exactly. A page that came through a client's forward
 * names the hub by a placeholder and comes back on its own address, which the
 * client keeps forwarding to the panel. After an agent port change alone the
 * page stays where it is and reloads when the restarted panel answers.
 */

const PORT_MIN = 1;
const PORT_MAX = 65535;
// How long the panel gets to come back before that is called a failure. It
// is a process restart, not a reboot; a machine that has not answered in this
// long has something else wrong with it.
const MOVE_TIMEOUT_MS = 30000;
const MOVE_POLL_MS = 500;
const HTTPS_SCHEME_PORT = 443;
// The offline counts move as agents and clients come and go.
const SETTINGS_INVALIDATE_ON = [
  { type: HUB_EVENT_DEVICES },
  { type: HUB_EVENT_CLIENTS },
];
const DIRECT_INVALIDATE_ON = [
  { type: HUB_EVENT_CONFIG, key: "overlay/direct.json" },
];
const SAKURAFRP_INVALIDATE_ON = [
  { type: HUB_EVENT_CONFIG, key: "overlay/sakurafrp.json" },
];
const OPENFRP_INVALIDATE_ON = [
  { type: HUB_EVENT_CONFIG, key: "overlay/openfrp.json" },
];

export function PanelPortPanel() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<SettingsView>("/hub/setting", {
    invalidateOn: SETTINGS_INVALIDATE_ON,
  });
  const direct = useApiResource<DirectView>("/hub/overlay/direct", {
    invalidateOn: DIRECT_INVALIDATE_ON,
  });
  const sakurafrp = useApiResource<FrpView>("/hub/overlay/sakurafrp", {
    invalidateOn: SAKURAFRP_INVALIDATE_ON,
  });
  const openfrp = useApiResource<FrpView>("/hub/overlay/openfrp", {
    invalidateOn: OPENFRP_INVALIDATE_ON,
  });
  const portsDraft = useDraft(resource.data, portsOf);
  const port = portsDraft.draft?.listen_port ?? null;
  const httpsPort = portsDraft.draft?.https_listen_port ?? null;
  const agentPort = portsDraft.draft?.agent_listen_port ?? null;
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [movingTo, setMovingTo] = useState<string | null>(null);
  const isForwarded = isOffPanelPort(resource.data);
  const host = hubHost(isForwarded);

  const applied = resource.data?.listen_port ?? null;
  const appliedHttps = resource.data?.https_listen_port ?? null;
  const appliedAgent = resource.data?.agent_listen_port ?? null;
  const isPanelMoving = port !== applied || httpsPort !== appliedHttps;
  const isAgentMoving = agentPort !== appliedAgent;
  const isDirty =
    port !== null &&
    httpsPort !== null &&
    agentPort !== null &&
    applied !== null &&
    (isPanelMoving || isAgentMoving);
  const isSetValid =
    isValid(port) &&
    isValid(httpsPort) &&
    isValid(agentPort) &&
    port !== httpsPort &&
    agentPort !== port &&
    agentPort !== httpsPort;
  const isDirectOn = direct.data?.is_enabled ?? false;
  const hasSakurafrpTunnel = (sakurafrp.data?.tunnel_id ?? "") !== "";
  const hasOpenfrpTunnel = (openfrp.data?.tunnel_id ?? "") !== "";

  const apply = async () => {
    if (port === null || httpsPort === null || agentPort === null) {
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      const saved = await apiPost<SettingsView>("/hub/setting/set", {
        listen_port: port,
        https_listen_port: httpsPort,
        agent_listen_port: agentPort,
      });
      resource.setData(saved);
      if (isPanelMoving) {
        setMovingTo(
          isForwarded ? window.location.origin : currentOrigin(saved, host),
        );
      }
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <section
      className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t("ui.network.panel_port_title")}</h2>
      </div>
      <p className="field_hint">{t("ui.network.panel_port_hint")}</p>

      {resource.data === null ? (
        <div className="skeleton" style={{ height: 72 }} />
      ) : (
        <div className="field_grid">
          <PortField
            label={t("ui.network.panel_port_field")}
            value={port}
            applied={applied}
            scheme="http"
            host={host}
            onChange={(value) => {
              setError(null);
              portsDraft.setDraft((current) => ({
                ...current,
                listen_port: value,
              }));
            }}
          />
          <PortField
            label={t("ui.network.panel_https_port_field")}
            value={httpsPort}
            applied={appliedHttps}
            scheme="https"
            host={host}
            onChange={(value) => {
              setError(null);
              portsDraft.setDraft((current) => ({
                ...current,
                https_listen_port: value,
              }));
            }}
          />
          <label className="field">
            <span className="field_label">
              {t("ui.network.agent_port_field")}
            </span>
            <input
              className="input"
              value={agentPort === null ? "" : String(agentPort)}
              inputMode="numeric"
              onChange={(event) => {
                setError(null);
                const value = Number(event.target.value) || 0;
                portsDraft.setDraft((current) => ({
                  ...current,
                  agent_listen_port: value,
                }));
              }}
            />
          </label>
        </div>
      )}

      <ApplyBar
        isDirty={isDirty}
        isApplyDisabled={!isSetValid}
        isBusy={isBusy}
        label={t("ui.network.apply_panel_port")}
        hint={applyHint(port, httpsPort, agentPort, isPanelMoving)}
        warning={interruptionWarning(
          t("ui.network.warning_panel_restart"),
          isAgentMoving
            ? t("ui.network.agent_port_offline_warning", {
                clients: resource.data?.offline_client_count ?? 0,
                agents: resource.data?.offline_agent_count ?? 0,
              })
            : null,
          isAgentMoving && isDirectOn
            ? t("ui.network.agent_port_direct_warning")
            : null,
          isAgentMoving && hasSakurafrpTunnel
            ? t("ui.network.agent_port_frp_warning", {
                vendor: t("ui.overlay.sakurafrp_title"),
              })
            : null,
          isAgentMoving && hasOpenfrpTunnel
            ? t("ui.network.agent_port_frp_warning", {
                vendor: t("ui.overlay.openfrp_title"),
              })
            : null,
        )}
        error={error}
        onReset={portsDraft.reset}
        onApply={() => void apply()}
      />

      {movingTo !== null && <MovingOverlay destination={movingTo} />}
    </section>
  );
}

/** The three ports as the form holds them; a cleared field holds null. */
interface PanelPortsDraft {
  listen_port: number | null;
  https_listen_port: number | null;
  agent_listen_port: number | null;
}

/** What the form starts from: the three ports as saved. */
function portsOf(settings: SettingsView): PanelPortsDraft {
  return {
    listen_port: settings.listen_port,
    https_listen_port: settings.https_listen_port,
    agent_listen_port: settings.agent_listen_port,
  };
}

interface MovingOverlayProps {
  /** The origin the restarted panel answers on. */
  destination: string;
}

/**
 * The wait between the old panel closing and the new one answering.
 *
 * Polling the new origin rather than counting seconds: a restart takes as long
 * as it takes, and the panel answering is the only thing that means it is
 * over. The session cookie is named after the port, so the new origin is
 * arrived at signed out and its login page is what answers.
 */
function MovingOverlay({ destination }: MovingOverlayProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const startedAt = useRef(Date.now());
  const [isLost, setIsLost] = useState(false);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (Date.now() - startedAt.current > MOVE_TIMEOUT_MS) {
        window.clearInterval(timer);
        setIsLost(true);
        return;
      }
      // no-cors: the answer is unreadable across origins, and it does not
      // need reading — a response at all is the panel being back.
      void fetch(`${destination}/api/hub/auth/session`, {
        mode: "no-cors",
        cache: "no-store",
      })
        .then(() => {
          window.clearInterval(timer);
          window.location.replace(destination);
        })
        .catch(() => undefined);
    }, MOVE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [destination]);

  return (
    <div className="panel_move">
      {isLost ? (
        <>
          <Icon name="alert" size={16} />
          <div className="panel_move_body">
            {t("ui.network.panel_move_lost", { origin: destination })}
          </div>
        </>
      ) : (
        <>
          <Spinner />
          <div className="panel_move_body">
            {t("ui.network.panel_moving", { origin: destination })}
          </div>
        </>
      )}
    </div>
  );
}

interface PortFieldProps {
  label: string;
  value: number | null;
  applied: number | null;
  scheme: "http" | "https";
  /** The hub's host as this page names it. */
  host: string;
  onChange: (value: number) => void;
}

/** One of the two ports, with the address it is reached at or moves to. */
function PortField({
  label,
  value,
  applied,
  scheme,
  host,
  onChange,
}: PortFieldProps) {
  return (
    <label className="field">
      <span className="field_label">{label}</span>
      <input
        className="input"
        value={value === null ? "" : String(value)}
        inputMode="numeric"
        onChange={(event) => onChange(Number(event.target.value) || 0)}
      />
      <span className="field_hint">
        {value !== applied
          ? t("ui.network.panel_port_moves_to", {
              origin: originOf(scheme, value ?? 0, host),
            })
          : t("ui.network.panel_port_reached_at", {
              origin: originOf(scheme, applied ?? 0, host),
            })}
      </span>
    </label>
  );
}

function applyHint(
  port: number | null,
  httpsPort: number | null,
  agentPort: number | null,
  isPanelMoving: boolean,
): string {
  if (!isValid(port) || !isValid(httpsPort) || !isValid(agentPort)) {
    return t("ui.network.port_range", { min: PORT_MIN, max: PORT_MAX });
  }
  if (port === httpsPort) {
    return t("ui.network.panel_ports_differ");
  }
  if (agentPort === port || agentPort === httpsPort) {
    return t("ui.network.agent_port_differs");
  }
  return isPanelMoving
    ? t("ui.network.apply_panel_port_hint")
    : t("ui.network.apply_agent_port_hint");
}

function isValid(port: number | null): boolean {
  return port !== null && port >= PORT_MIN && port <= PORT_MAX;
}

/** A host on a scheme and port, the port left out where it is the default. */
function originOf(
  scheme: "http" | "https",
  port: number,
  host: string,
): string {
  const isDefault = scheme === "https" && port === HTTPS_SCHEME_PORT;
  return `${scheme}://${host}${isDefault ? "" : `:${port}`}`;
}

/** Where this page goes after a move: the port of the scheme it is on. */
function currentOrigin(saved: SettingsView, host: string): string {
  return window.location.protocol === "https:"
    ? originOf("https", saved.https_listen_port, host)
    : originOf("http", saved.listen_port, host);
}
