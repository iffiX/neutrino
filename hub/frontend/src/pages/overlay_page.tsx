import { useEffect, useState } from "react";
import { copyText } from "../copy_text";

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
import { HUB_EVENT_CONFIG } from "../use_hub_events";
import type {
  DevicesResponse,
  NetbirdPeer,
  NetbirdView,
  OverlayChoiceView,
} from "../api_types";

import "./overlay_page.css";

/**
 * How this box is reached from outside: which overlay it is on, and that
 * overlay's own screen below the choice.
 *
 * No leave button on the NetBird half — from abroad that is a lockout; a local
 * shell has `netbird down`, and the chooser above is the deliberate way out.
 */

/** The engines by the key `config/` names them. */
const PROVIDER_NONE = "none";
const PROVIDER_NETBIRD = "netbird";
const PROVIDER_EASYTIER = "easytier";

/** The product's own name, which is the same in every language. */
const NETBIRD_PRODUCT_NAME = "NetBird";

// What moves the choice: any write to the hub's own configuration.
const OVERLAY_INVALIDATE_ON = [{ type: HUB_EVENT_CONFIG }];

export function OverlayPage() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<OverlayChoiceView>("/overlay", {
    invalidateOn: OVERLAY_INVALIDATE_ON,
  });

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

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>{t("ui.overlay.title")}</h1>
        </div>
      </div>

      <OverlayModePanel choice={choice} onApplied={resource.setData} />

      {choice.provider === PROVIDER_NONE && (
        <div className="notice">
          <Icon name="blocked" size={15} />
          <div className="notice_body">{t("ui.overlay.none_body")}</div>
        </div>
      )}

      {choice.provider === PROVIDER_NETBIRD && <NetbirdSection />}

      {choice.provider === PROVIDER_EASYTIER && <EasyTierSection />}
    </div>
  );
}

/**
 * NetBird: enrollment, LAN route guidance, and live peers.
 */
function NetbirdSection() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<NetbirdView>("/netbird");
  const devices = useApiResource<DevicesResponse>("/devices");

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
          {view.is_installed &&
            (!view.is_enrolled ? (
              <span className="badge badge--warn">
                {t("ui.overlay.badge_not_joined")}
              </span>
            ) : view.is_management_connected ? (
              <span className="badge badge--ok">
                {t("ui.overlay.badge_connected")}
              </span>
            ) : (
              <span className="badge badge--error">
                {t("ui.overlay.badge_unreachable")}
              </span>
            ))}
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

      {!view.is_installed && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">{t("ui.overlay.install_first")}</div>
        </div>
      )}

      {view.is_enrolled && !view.is_management_connected && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            {t("ui.overlay.management_unreachable")}
          </div>
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

      {view.is_enrolled ? (
        <IdentitySection
          view={view}
          isReady={view.is_installed && view.is_active}
          onJoined={resource.reload}
        />
      ) : (
        <JoinSection
          isReady={view.is_installed && view.is_active}
          onJoined={resource.reload}
        />
      )}

      <RoutesSection view={view} />
      <PeersSection view={view} />
    </>
  );
}

interface IdentitySectionProps {
  view: NetbirdView;
  isReady: boolean;
  onJoined: () => void;
}

function IdentitySection({ view, isReady, onJoined }: IdentitySectionProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [isReconfiguring, setIsReconfiguring] = useState(false);
  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.overlay.identity_title")}</h2>
        <button
          type="button"
          className="button button--small netbird_reconfigure"
          onClick={() => setIsReconfiguring((current) => !current)}
        >
          <Icon name="refresh" size={12} />
          {t("ui.overlay.reenroll")}
        </button>
      </div>
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
      <p className="field_hint">{t("ui.overlay.exposure_hint")}</p>
      {isReconfiguring && (
        <JoinForm
          isReady={isReady}
          submitLabel={t("ui.overlay.reenroll")}
          warning={t("ui.overlay.reenroll_warning")}
          onJoined={() => {
            setIsReconfiguring(false);
            onJoined();
          }}
        />
      )}
    </section>
  );
}

interface JoinSectionProps {
  isReady: boolean;
  onJoined: () => void;
}

function JoinSection({ isReady, onJoined }: JoinSectionProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.overlay.join_title")}</h2>
      </div>
      <ol className="netbird_steps">
        <li>{t("ui.overlay.join_step_network")}</li>
        <li>{t("ui.overlay.join_step_peer")}</li>
        <li>{t("ui.overlay.join_step_key")}</li>
      </ol>
      {!isReady && (
        <p className="field_hint">{t("ui.overlay.service_first")}</p>
      )}
      <JoinForm
        isReady={isReady}
        submitLabel={t("ui.overlay.join")}
        onJoined={onJoined}
      />
    </section>
  );
}

interface JoinFormProps {
  isReady: boolean;
  submitLabel: string;
  warning?: string;
  onJoined: () => void;
}

function JoinForm({ isReady, submitLabel, warning, onJoined }: JoinFormProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [setupKey, setSetupKey] = useState("");
  const [managementUrl, setManagementUrl] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const join = async () => {
    setIsBusy(true);
    setError(null);
    try {
      await apiPost("/netbird/join", {
        setup_key: setupKey.trim(),
        management_url: managementUrl.trim(),
      });
      setSetupKey("");
      onJoined();
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <>
      {warning !== undefined && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">{warning}</div>
        </div>
      )}
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
        <button
          type="button"
          className="button button--primary"
          disabled={!isReady || isBusy || setupKey.trim() === ""}
          onClick={() => void join()}
        >
          {isBusy ? t("ui.overlay.joining") : submitLabel}
        </button>
      </div>
      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
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
