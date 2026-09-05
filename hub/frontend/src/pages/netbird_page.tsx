import { useEffect, useState } from "react";
import { copyText } from "../copy_text";

import { ErrorPanel } from "../components/error_panel";
import { NetbirdTopology } from "../components/netbird_topology";
import { Icon } from "../components/icon";
import { PasswordInput } from "../components/password_input";
import { ModuleStateBadge } from "../components/module_state_badge";
import { StatusDot } from "../components/status_dot";
import { apiPost, describeError } from "../api_client";
import { useApiResource } from "../use_api_resource";
import type { DevicesResponse, NetbirdView } from "../api_types";

import "./netbird_page.css";

/**
 * Remote access: enrollment, LAN route guidance, and live peers.
 *
 * No leave button — from abroad that is a lockout; a local shell has
 * `netbird down`.
 */

export function NetbirdPage() {
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
    return (
      <div className="page">
        <h1>NetBird</h1>
        <ErrorPanel message={resource.error} onRetry={resource.reload} />
      </div>
    );
  }

  if (view === null) {
    return (
      <div className="page">
        <h1>NetBird</h1>
        <div className="skeleton" style={{ height: 320 }} />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>NetBird</h1>
          <ModuleStateBadge name="netbird" />
          {view.is_installed &&
            (!view.is_enrolled ? (
              <span className="badge badge--warn">not joined</span>
            ) : view.is_management_connected ? (
              <span className="badge badge--ok">connected</span>
            ) : (
              <span className="badge badge--error">management unreachable</span>
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
            Open console
          </a>
        </div>
      </div>

      {!view.is_installed && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            Install NetBird from Services first.
          </div>
        </div>
      )}

      {view.is_enrolled && !view.is_management_connected && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            Management plane unreachable. If behind a filter, enable &quot;Route
            this gateway&apos;s own traffic&quot; on the Proxy page.
          </div>
        </div>
      )}

      {view.is_enrolled && (
        <section className="settings_group">
          <div className="settings_group_title">
            <h2>Topology</h2>
          </div>
          <NetbirdTopology view={view} devices={devices.data?.devices ?? []} />
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
    </div>
  );
}

interface IdentitySectionProps {
  view: NetbirdView;
  isReady: boolean;
  onJoined: () => void;
}

function IdentitySection({ view, isReady, onJoined }: IdentitySectionProps) {
  const [isReconfiguring, setIsReconfiguring] = useState(false);
  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>This gateway on the overlay</h2>
        <button
          type="button"
          className="button button--small netbird_reconfigure"
          onClick={() => setIsReconfiguring((current) => !current)}
        >
          <Icon name="refresh" size={12} />
          Re-enroll
        </button>
      </div>
      <div className="netbird_identity">
        <div className="netbird_fact">
          <span className="field_label">Overlay address</span>
          <span className="netbird_fact_value">
            {view.netbird_ip || "assigning…"}
          </span>
        </div>
        <div className="netbird_fact">
          <span className="field_label">Name</span>
          <span className="netbird_fact_value">{view.fqdn || "—"}</span>
        </div>
        <div className="netbird_fact">
          <span className="field_label">Management</span>
          <span className="netbird_fact_value">{view.management_url}</span>
        </div>
      </div>
      <p className="field_hint">
        The panel also answers on the overlay address.
      </p>
      {isReconfiguring && (
        <JoinForm
          isReady={isReady}
          submitLabel="Re-enroll"
          warning="Re-enrolling gives this gateway a new identity on the network. Afterwards, delete the old peer entry in the console."
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
  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>Join a network</h2>
      </div>
      <ol className="netbird_steps">
        <li>
          In the console, open <strong>Networks</strong> and press{" "}
          <strong>Add Network</strong>.
        </li>
        <li>
          On the new network, under <strong>Routing Peers</strong>, press{" "}
          <strong>Add</strong> and choose <strong>Install NetBird</strong>.
        </li>
        <li>Copy the setup key it shows and paste it below.</li>
      </ol>
      {!isReady && (
        <p className="field_hint">Start the netbird service first.</p>
      )}
      <JoinForm isReady={isReady} submitLabel="Join" onJoined={onJoined} />
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
          placeholder="setup key, like AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
        />
        <input
          className="input"
          placeholder="management URL (empty for netbird.io)"
          value={managementUrl}
          onChange={(event) => setManagementUrl(event.target.value)}
        />
        <button
          type="button"
          className="button button--primary"
          disabled={!isReady || isBusy || setupKey.trim() === ""}
          onClick={() => void join()}
        >
          {isBusy ? "Joining…" : submitLabel}
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
  const [copied, setCopied] = useState<string | null>(null);

  const copy = (subnet: string) => {
    void copyText(subnet);
    setCopied(subnet);
    window.setTimeout(() => setCopied(null), 1600);
  };

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>LAN routes</h2>
      </div>
      <p className="field_hint">
        In the console under <strong>Networks</strong>, add each subnet below as
        a <strong>Resource</strong> of your network, and give it an{" "}
        <strong>Access Control Policy</strong> so peers may use the route.
      </p>
      <div className="netbird_subnets">
        {view.lan_subnets.map((subnet) => (
          <button
            key={subnet}
            type="button"
            className="netbird_subnet_chip"
            title="Copy"
            onClick={() => copy(subnet)}
          >
            {subnet}
            <Icon name={copied === subnet ? "check" : "link"} size={12} />
          </button>
        ))}
        {view.lan_subnets.length === 0 && (
          <span className="field_hint">No interface has the LAN role.</span>
        )}
      </div>
    </section>
  );
}

function PeersSection({ view }: { view: NetbirdView }) {
  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>Peers</h2>
        <span className="badge">
          <StatusDot tone="ok" isPulsing />
          live
        </span>
      </div>
      {view.peers.length === 0 ? (
        <p className="field_hint">
          No peers yet. Log in on another device with the NetBird app.
        </p>
      ) : (
        <div className="netbird_peers">
          {view.peers.map((peer) => (
            <div key={peer.fqdn} className="netbird_peer">
              <span className="netbird_peer_name">
                <StatusDot
                  tone={peer.is_connected ? "ok" : "idle"}
                  isPulsing={peer.is_connected}
                />
                {peer.fqdn}
              </span>
              <span className="netbird_peer_ip">{peer.netbird_ip}</span>
              {peer.is_connected && (
                <span
                  className={`badge ${
                    peer.connection_type === "P2P" ? "badge--ok" : "badge--warn"
                  }`}
                >
                  {peer.connection_type === "P2P" ? "direct" : "relayed"}
                </span>
              )}
              {peer.latency_ms !== null && (
                <span className="netbird_peer_latency">
                  {peer.latency_ms} ms
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
