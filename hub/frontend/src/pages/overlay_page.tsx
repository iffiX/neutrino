import { useEffect, useState } from "react";
import { copyText } from "../copy_text";

import { ApplyBar } from "../components/apply_bar";
import { EasyTierSection } from "../components/easytier_panels";
import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { OverlayModePanel } from "../components/overlay_mode_panel";
import { OverlayPeers } from "../components/overlay_peers";
import type { OverlayPeerRow } from "../components/overlay_peers";
import { OverlayTopology } from "../components/overlay_topology";
import { PasswordInput } from "../components/password_input";
import { StatusDot } from "../components/status_dot";
import { apiPost, describeError } from "../api_client";
import { formatDuration } from "../format_duration";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import { usePageMemory } from "../use_page_memory";
import { HUB_EVENT_CONFIG } from "../use_hub_events";
import type {
  DevicesResponse,
  NetbirdPeer,
  NetbirdView,
  OverlayChoiceView,
} from "../api_types";

import "./overlay_page.css";

/**
 * How this box is reached from outside: which overlays it runs, and the
 * settings of the one picked below the switches.
 */

/** The engines by the key `config/` names them. */
const PROVIDER_NETBIRD = "netbird";
const PROVIDER_EASYTIER = "easytier";

/** The product's own name, which is the same in every language. */
const NETBIRD_PRODUCT_NAME = "NetBird";

// What moves the switches: any write to the hub's own configuration.
const OVERLAY_INVALIDATE_ON = [{ type: HUB_EVENT_CONFIG }];

/** How often the switches are read; clients come and go on their own. */
const OVERLAY_RELOAD_MS = 10000;

export function OverlayPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<OverlayChoiceView>("/hub/overlay", {
    invalidateOn: OVERLAY_INVALIDATE_ON,
  });
  const [picked, setPicked] = usePageMemory<string>("overlay.engine", "");

  const reload = resource.reload;
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) {
        reload();
      }
    }, OVERLAY_RELOAD_MS);
    return () => window.clearInterval(timer);
  }, [reload]);

  const choice = resource.data;

  if (resource.error !== null && choice === null) {
    return (
      <div className="page">
        <h1>{t("ui.overlay.title")}</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  if (choice === null) {
    return (
      <div className="page">
        <h1>{t("ui.overlay.title")}</h1>
        <div className="skeleton" style={{ height: 320 }} />
      </div>
    );
  }

  const selected =
    picked !== ""
      ? picked
      : (choice.kinds.find((kind) => kind.is_enabled)?.key ?? PROVIDER_NETBIRD);
  const isEnabled = (key: string) =>
    choice.kinds.some((kind) => kind.key === key && kind.is_enabled);

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>{t("ui.overlay.title")}</h1>
        </div>
      </div>

      <OverlayModePanel
        choice={choice}
        selected={selected}
        onSelect={setPicked}
        onApplied={resource.setData}
      />

      {!choice.kinds.some((kind) => kind.is_enabled) && (
        <div className="notice">
          <Icon name="blocked" size={15} />
          <div className="notice_body">{t("ui.overlay.none_body")}</div>
        </div>
      )}

      {selected === PROVIDER_NETBIRD && (
        <NetbirdSection isEnabled={isEnabled(PROVIDER_NETBIRD)} />
      )}

      {selected === PROVIDER_EASYTIER && (
        <EasyTierSection isEnabled={isEnabled(PROVIDER_EASYTIER)} />
      )}
    </div>
  );
}

/** The daemon's own words for where it stands, as `netbird status` says them. */
const DAEMON_CONNECTED = "Connected";
const DAEMON_CONNECTING = "Connecting";
const DAEMON_LOGIN_FAILED = "LoginFailed";
const DAEMON_SESSION_EXPIRED = "SessionExpired";

/**
 * The badge beside the name, from the daemon's word and whether a join is
 * in flight. A join in flight and a daemon still connecting both read as
 * work under way, and only a login the plane could not be reached for
 * reads as unreachable; the two used to share one red badge, and a join
 * that was going well wore it for its first seconds.
 */
function daemonBadge(view: NetbirdView, isJoining: boolean) {
  if (isJoining) {
    return {
      tone: "badge--warn",
      key: "ui.overlay.badge_joining",
      isPulsing: true,
    };
  }
  if (view.daemon_status === DAEMON_LOGIN_FAILED) {
    return {
      tone: "badge--error",
      key: "ui.overlay.badge_unreachable",
      isPulsing: false,
    };
  }
  if (!view.is_enrolled) {
    return {
      tone: "badge--warn",
      key: "ui.overlay.badge_not_joined",
      isPulsing: false,
    };
  }
  switch (view.daemon_status) {
    case DAEMON_CONNECTED:
      return {
        tone: "badge--ok",
        key: "ui.overlay.badge_connected",
        isPulsing: false,
      };
    case DAEMON_CONNECTING:
      return {
        tone: "badge--warn",
        key: "ui.overlay.badge_connecting",
        isPulsing: true,
      };
    default:
      return { tone: "", key: "ui.overlay.badge_idle", isPulsing: false };
  }
}

interface NetbirdSectionProps {
  /** Whether the hub runs NetBird now. */
  isEnabled: boolean;
}

/**
 * NetBird: its settings, LAN route guidance, and live peers.
 */
function NetbirdSection({ isEnabled }: NetbirdSectionProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<NetbirdView>("/hub/overlay/netbird");
  const devices = useApiResource<DevicesResponse>("/hub/device");
  // While a join is in flight the page stays on the join form whatever the
  // polled status says: the daemon passes through Connecting on its way,
  // and a form that unmounts under a pending press loses its answer.
  const [isJoining, setIsJoining] = useState(false);

  // Peers connect and drop on their own schedule.
  const reload = resource.reload;
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) {
        reload();
      }
    }, 5000);
    return () => window.clearInterval(timer);
  }, [reload]);

  const view = resource.data;

  if (resource.error !== null && view === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }

  if (view === null) {
    return <div className="skeleton" style={{ height: 320 }} />;
  }

  return (
    <>
      <div className="overlay_product_header">
        <div className="page_title_row">
          <h2>{NETBIRD_PRODUCT_NAME}</h2>
          {view.is_installed && (
            <DaemonBadge view={view} isJoining={isJoining} />
          )}
          {view.version !== "" && (
            <span className="badge">v{view.version}</span>
          )}
        </div>
        <div className="page_actions">
          <a
            className="button button--primary"
            href="https://app.netbird.io"
            target="_blank"
            rel="noreferrer"
          >
            <Icon name="link" size={14} />
            {t("ui.overlay.open_console")}
          </a>
        </div>
      </div>

      {!isEnabled && (
        <div className="notice">
          <Icon name="blocked" size={15} />
          <div className="notice_body">
            {t("ui.overlay.engine_off", { title: NETBIRD_PRODUCT_NAME })}
          </div>
        </div>
      )}

      {isEnabled && !view.is_installed && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">{t("ui.overlay.install_first")}</div>
        </div>
      )}

      {!isJoining && view.daemon_status === DAEMON_LOGIN_FAILED && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            {t("ui.overlay.management_unreachable")}
          </div>
        </div>
      )}
      {!isJoining && view.daemon_status === DAEMON_SESSION_EXPIRED && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">{t("ui.overlay.session_expired")}</div>
        </div>
      )}

      {view.is_enrolled && (
        <section className="settings_group">
          <div className="settings_group_title">
            <h2>{t("ui.overlay.topology_title")}</h2>
          </div>
          <OverlayTopology
            laneTitle={t("ui.overlay.topology_lane_overlay")}
            selfName={view.fqdn}
            selfAddress={view.netbird_ip}
            subnets={view.lan_subnets}
            peers={view.peers.map(netbirdRow)}
            devices={devices.data?.devices ?? []}
          />
        </section>
      )}

      <NetbirdSettingsPanel
        view={view}
        isJoining={isJoining}
        onChanged={resource.setData}
        onReload={resource.reload}
        onJoining={setIsJoining}
      />

      <RoutesSection view={view} />
      <PeersSection view={view} />
    </>
  );
}

interface DaemonBadgeProps {
  view: NetbirdView;
  isJoining: boolean;
}

function DaemonBadge({ view, isJoining }: DaemonBadgeProps) {
  const badge = daemonBadge(view, isJoining);
  return (
    <span className={`badge ${badge.tone}`.trim()}>
      {badge.isPulsing && <StatusDot tone="warn" isPulsing />}
      {t(badge.key)}
    </span>
  );
}

interface NetbirdSettingsPanelProps {
  view: NetbirdView;
  isJoining: boolean;
  onChanged: (view: NetbirdView) => void;
  onReload: () => void;
  /** Told when a join is sent and when it has been answered. */
  onJoining: (isJoining: boolean) => void;
}

/**
 * NetBird's settings in one frame: where this gateway stands, the key kept
 * for clients, and the join itself, which the apply bar sends. Leaving is
 * the one action in the title.
 */
function NetbirdSettingsPanel({
  view,
  isJoining,
  onChanged,
  onReload,
  onJoining,
}: NetbirdSettingsPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const confirm = useConfirm();
  const [setupKey, setSetupKey] = useState("");
  const [managementUrl, setManagementUrl] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEnrolled = view.is_enrolled && !isJoining;
  const isReady = view.is_installed && view.is_active;
  const isDirty = setupKey.trim() !== "";

  const join = async () => {
    setIsBusy(true);
    onJoining(true);
    setError(null);
    try {
      onChanged(
        await apiPost<NetbirdView>("/hub/overlay/netbird/join", {
          setup_key: setupKey.trim(),
          management_url: managementUrl.trim(),
        }),
      );
      setSetupKey("");
    } catch (cause: unknown) {
      setError(describeError(cause));
      onReload();
    } finally {
      setIsBusy(false);
      onJoining(false);
    }
  };

  const leave = async () => {
    setIsBusy(true);
    setError(null);
    try {
      onChanged(await apiPost<NetbirdView>("/hub/overlay/netbird/leave", {}));
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const askLeave = () => {
    confirm.ask({
      title: t("ui.overlay.leave_title"),
      body: t("ui.overlay.leave_body"),
      confirmLabel: t("ui.overlay.leave"),
      onConfirm: () => void leave(),
    });
  };

  return (
    <section
      className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t("ui.overlay.settings_title")}</h2>
        {view.is_enrolled && (
          <button
            type="button"
            className="button button--small button--danger netbird_reconfigure"
            disabled={isBusy}
            onClick={askLeave}
          >
            {t("ui.overlay.leave")}
          </button>
        )}
      </div>
      {isEnrolled ? (
        <div className="netbird_identity">
          <div className="netbird_fact">
            <span className="field_label">{t("ui.overlay.address_label")}</span>
            <span className="netbird_fact_value">
              {view.netbird_ip || t("ui.overlay.address_assigning")}
            </span>
          </div>
          <div className="netbird_fact">
            <span className="field_label">{t("ui.overlay.name_label")}</span>
            <span className="netbird_fact_value">{view.fqdn || "—"}</span>
          </div>
          <div className="netbird_fact">
            <span className="field_label">
              {t("ui.overlay.management_label")}
            </span>
            <span className="netbird_fact_value">{view.management_url}</span>
          </div>
        </div>
      ) : (
        <ol className="netbird_steps">
          <li>{t("ui.overlay.join_step_network")}</li>
          <li>{t("ui.overlay.join_step_peer")}</li>
          <li>{t("ui.overlay.join_step_key")}</li>
        </ol>
      )}
      <SetupKeyRow hasSetupKey={view.has_setup_key} onChanged={onReload} />
      <p className="field_hint">{t("ui.overlay.setup_key_hint")}</p>
      <div className="netbird_join">
        <PasswordInput
          value={setupKey}
          onChange={setSetupKey}
          placeholder={t("ui.overlay.setup_key_placeholder")}
        />
        <input
          className="input"
          placeholder={t("ui.overlay.management_url_placeholder")}
          value={managementUrl}
          onChange={(event) => setManagementUrl(event.target.value)}
        />
      </div>
      <p className="field_hint">{t("ui.overlay.exposure_hint")}</p>
      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={isEnrolled ? t("ui.overlay.reenroll") : t("ui.overlay.join")}
        hint={t("ui.overlay.apply_join_hint")}
        warning={isEnrolled ? t("ui.overlay.reenroll_warning") : undefined}
        blockedHint={isReady ? null : t("ui.overlay.service_first")}
        error={error}
        onReset={() => {
          setSetupKey("");
          setManagementUrl("");
        }}
        onApply={() => void join()}
      />
      {confirm.modal}
    </section>
  );
}

interface SetupKeyRowProps {
  hasSetupKey: boolean;
  onChanged: () => void;
}

/** Whether a setup key is kept for clients, with Replace and Forget. */
function SetupKeyRow({ hasSetupKey, onChanged }: SetupKeyRowProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const confirm = useConfirm();
  const [isReplacing, setIsReplacing] = useState(false);
  const [setupKey, setSetupKey] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const store = async (value: string) => {
    setIsBusy(true);
    setError(null);
    try {
      await apiPost("/hub/overlay/netbird/setup_key/set", {
        setup_key: value,
      });
      setSetupKey("");
      setIsReplacing(false);
      onChanged();
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const askForget = () => {
    confirm.ask({
      title: t("ui.overlay.setup_key_forget_title"),
      body: t("ui.overlay.setup_key_forget_body"),
      confirmLabel: t("ui.overlay.setup_key_forget"),
      onConfirm: () => void store(""),
    });
  };

  return (
    <>
      <div className="netbird_fact netbird_setup_key">
        <span className="field_label">{t("ui.overlay.setup_key_label")}</span>
        <span className="netbird_fact_value">
          {hasSetupKey
            ? t("ui.overlay.setup_key_kept")
            : t("ui.overlay.setup_key_missing")}
        </span>
        {isReplacing ? (
          <>
            <PasswordInput
              value={setupKey}
              onChange={setSetupKey}
              placeholder={t("ui.overlay.setup_key_placeholder")}
            />
            <button
              type="button"
              className="button button--small button--primary"
              disabled={isBusy || setupKey.trim() === ""}
              onClick={() => void store(setupKey.trim())}
            >
              {t("ui.overlay.setup_key_save")}
            </button>
            <button
              type="button"
              className="button button--small"
              disabled={isBusy}
              onClick={() => {
                setSetupKey("");
                setIsReplacing(false);
              }}
            >
              {t("ui.overlay.setup_key_cancel")}
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className="button button--small"
              disabled={isBusy}
              onClick={() => setIsReplacing(true)}
            >
              {t("ui.overlay.setup_key_replace")}
            </button>
            {hasSetupKey && (
              <button
                type="button"
                className="button button--small button--danger"
                disabled={isBusy}
                onClick={askForget}
              >
                {t("ui.overlay.setup_key_forget")}
              </button>
            )}
          </>
        )}
      </div>
      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
      {confirm.modal}
    </>
  );
}

function RoutesSection({ view }: { view: NetbirdView }) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [copied, setCopied] = useState<string | null>(null);

  const copy = (subnet: string) => {
    void copyText(subnet);
    setCopied(subnet);
    window.setTimeout(() => setCopied(null), 1600);
  };

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.overlay.routes_title")}</h2>
      </div>
      <p className="field_hint">{t("ui.overlay.routes_hint")}</p>
      <div className="netbird_subnets">
        {view.lan_subnets.map((subnet) => (
          <button
            key={subnet}
            type="button"
            className="netbird_subnet_chip"
            title={t("ui.overlay.copy")}
            onClick={() => copy(subnet)}
          >
            {subnet}
            <Icon name={copied === subnet ? "check" : "link"} size={12} />
          </button>
        ))}
        {view.lan_subnets.length === 0 && (
          <span className="field_hint">{t("ui.overlay.routes_empty")}</span>
        )}
      </div>
    </section>
  );
}

function PeersSection({ view }: { view: NetbirdView }) {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.overlay.peers_title")}</h2>
        <span className="badge">
          <StatusDot tone="ok" isPulsing />
          {t("state.live")}
        </span>
      </div>
      <OverlayPeers
        peers={view.peers.map(netbirdRow)}
        emptyHint={t("ui.overlay.peers_empty")}
      />
    </section>
  );
}

/**
 * One NetBird peer as the shared table draws it.
 *
 * The detail line is the handshake's age: NetBird reports no protocol, and
 * how long ago a tunnel last spoke is what an idle row is actually saying.
 */
function netbirdRow(peer: NetbirdPeer): OverlayPeerRow {
  return {
    key: peer.fqdn,
    name: peer.fqdn,
    address: peer.netbird_ip,
    link: peer.connection_type === "P2P" ? "direct" : "relayed",
    detail:
      peer.last_handshake_s === null
        ? ""
        : t("ui.overlay.peer_handshake", {
            duration: formatDuration(peer.last_handshake_s),
          }),
    latencyMs: peer.latency_ms,
    lossRatio: null,
    rxBytes: peer.rx_bytes,
    txBytes: peer.tx_bytes,
    isConnected: peer.is_connected,
  };
}
