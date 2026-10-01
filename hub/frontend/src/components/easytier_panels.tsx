import { useEffect, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { OverlayPeers } from "./overlay_peers";
import type { OverlayPeerRow } from "./overlay_peers";
import { OverlayTopology } from "./overlay_topology";
import { PasswordInput } from "./password_input";
import { StatusDot } from "./status_dot";
import { ToggleSwitch } from "./toggle_switch";
import { apiGet, apiPost, describeError } from "../api_client";
import { copyText } from "../copy_text";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useDraftSeeding } from "../use_draft_seeding";
import type {
  DevicesResponse,
  EasyTierInstance,
  EasyTierMode,
  EasyTierPeer,
  EasyTierSecret,
  EasyTierSettingsRequest,
  EasyTierSuggestion,
  EasyTierView,
} from "../api_types";

import "./easytier_panels.css";
import "./overlay_mode_panel.css";

/**
 * EasyTier: where the network comes from, who is on it, and what it reaches.
 *
 * In manual mode a name and a secret are the whole network, so this screen
 * mints them and the commands at the bottom tell another machine. In console
 * mode EasyTier's own console pushes the network, and this screen keeps only
 * the console's address and shows what the engine then runs.
 */

/** The product's own name, which is the same in every language. */
const EASYTIER_PRODUCT_NAME = "EasyTier";

/** The two modes, by the key `config/` names them. */
const MODE_MANUAL: EasyTierMode = "manual";
const MODE_CONSOLE: EasyTierMode = "console";
const MODES: EasyTierMode[] = [MODE_CONSOLE, MODE_MANUAL];

const MODE_LABEL_KEYS: Record<EasyTierMode, string> = {
  console: "ui.overlay.mode_console",
  manual: "ui.overlay.mode_manual",
};

const MODE_SUMMARY_KEYS: Record<EasyTierMode, string> = {
  console: "ui.overlay.mode_console_summary",
  manual: "ui.overlay.mode_manual_summary",
};

/** The instance fields the console may withhold, in the order they show. */
const INSTANCE_FACTS: {
  field: "network_name" | "address" | "hostname";
  labelKey: string;
}[] = [
  { field: "network_name", labelKey: "ui.overlay.network_name" },
  { field: "address", labelKey: "ui.overlay.address_label" },
  { field: "hostname", labelKey: "ui.overlay.name_label" },
];

/**
 * Where a console-mode engine stands: not running, running with no network
 * from the console yet, or running the console's networks.
 */
type ConsoleState = "stopped" | "waiting" | "joined";

function consoleStateOf(view: EasyTierView): ConsoleState {
  if (!view.is_active) {
    return "stopped";
  }
  return view.instances.length > 0 ? "joined" : "waiting";
}

/** The port the engine's own peers knock on, as the panel renders it. */
const EASYTIER_PEER_PORT = 11010;

/** How often the peer table is read; peers connect and drop on their own. */
const PEER_RELOAD_MS = 5000;

export function EasyTierSection() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<EasyTierView>("/hub/overlay/easytier");
  const devices = useApiResource<DevicesResponse>("/hub/device");

  const reload = resource.reload;
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) {
        reload();
      }
    }, PEER_RELOAD_MS);
    return () => window.clearInterval(timer);
  }, [reload]);

  const view = resource.data;

  if (resource.error !== null && view === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }

  if (view === null) {
    return <div className="skeleton" style={{ height: 320 }} />;
  }

  const isConsole = view.mode === MODE_CONSOLE;
  const isJoined = isConsole
    ? view.has_config_server
    : view.network_name !== "" && view.is_secret_set;
  const instance = view.instances.length > 0 ? view.instances[0] : null;
  const consoleState = consoleStateOf(view);

  return (
    <>
      <div className="overlay_product_header">
        <div className="page_title_row">
          <h2>{EASYTIER_PRODUCT_NAME}</h2>
          {!isJoined ? (
            <span className="badge badge--warn">
              {t("ui.overlay.badge_not_joined")}
            </span>
          ) : isConsole && consoleState === "stopped" ? (
            <span className="badge badge--error">
              {t("ui.overlay.badge_not_running")}
            </span>
          ) : isConsole && consoleState === "waiting" ? (
            <span className="badge badge--warn">
              {t("ui.overlay.console_waiting")}
            </span>
          ) : view.node !== null && view.node.is_connected ? (
            <span className="badge badge--ok">
              {t("ui.overlay.badge_connected")}
            </span>
          ) : (
            <span className="badge badge--warn">
              {t("ui.overlay.badge_alone")}
            </span>
          )}
          {view.version !== "" && (
            <span className="badge">v{view.version}</span>
          )}
        </div>
      </div>

      {!view.is_installed && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">{t("ui.overlay.engine_absent")}</div>
        </div>
      )}

      {isJoined && (
        <section className="settings_group">
          <div className="settings_group_title">
            <h2>{t("ui.overlay.topology_title")}</h2>
          </div>
          <OverlayTopology
            laneTitle={t("ui.overlay.topology_lane_easytier")}
            selfName={
              isConsole
                ? (instance?.hostname ?? "")
                : (view.node?.hostname ?? view.hostname)
            }
            selfAddress={isConsole ? (instance?.address ?? "") : view.address}
            subnets={
              isConsole
                ? (instance?.subnet_routes ?? [])
                : view.exported_networks
            }
            peers={view.live_peers.map(easytierRow)}
            devices={devices.data?.devices ?? []}
          />
        </section>
      )}

      <SettingsPanel view={view} onApplied={resource.setData} />

      {isConsole ? (
        <InstancesPanel view={view} state={consoleState} />
      ) : (
        isJoined && <CommandPanel view={view} />
      )}

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>{t("ui.overlay.peers_title")}</h2>
          <span className="badge">
            <StatusDot tone="ok" isPulsing />
            {t("state.live")}
          </span>
        </div>
        <OverlayPeers
          peers={view.live_peers.map(easytierRow)}
          emptyHint={t("ui.overlay.easytier_peers_empty")}
        />
      </section>
    </>
  );
}

interface SettingsPanelProps {
  view: EasyTierView;
  onApplied: (view: EasyTierView) => void;
}

/** Every EasyTier setting as the draft holds it. */
interface EasyTierDraft {
  mode: EasyTierMode;
  /** A console address typed to replace the kept one; empty keeps it. */
  configServer: string;
  isConsoleForgotten: boolean;
  isSecureMode: boolean;
  networkName: string;
  /** A secret typed to replace the kept one; empty keeps it. */
  networkSecret: string;
  address: string;
  peers: string[];
  exportedNetworks: string[];
}

function storedDraft(view: EasyTierView): EasyTierDraft {
  return {
    mode: view.mode,
    configServer: "",
    isConsoleForgotten: false,
    isSecureMode: view.is_secure_mode,
    networkName: view.network_name,
    networkSecret: "",
    address: view.address,
    peers: view.peers,
    exportedNetworks: view.exported_networks,
  };
}

function draftSignature(draft: EasyTierDraft): string {
  return JSON.stringify(draft);
}

/**
 * Every EasyTier setting in one frame with one apply bar: where the network
 * comes from, and in each mode what the engine is started with.
 */
function SettingsPanel({ view, onApplied }: SettingsPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [draft, setDraft] = useState<EasyTierDraft>(() => storedDraft(view));
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stored = draftSignature(storedDraft(view));
  const isReseedable = useDraftSeeding(draftSignature(draft), stored);
  useEffect(() => {
    if (!isReseedable(stored)) {
      return;
    }
    setDraft(storedDraft(view));
  }, [view, stored, isReseedable]);

  const isDirty = draftSignature(draft) !== stored;
  const change = (patch: Partial<EasyTierDraft>) => {
    setError(null);
    setDraft({ ...draft, ...patch });
  };

  const suggest = async () => {
    setError(null);
    try {
      const suggestion = await apiPost<EasyTierSuggestion>(
        "/hub/overlay/easytier/suggestion/create",
        {},
      );
      change({
        networkName: suggestion.network_name,
        networkSecret: suggestion.network_secret,
        address: suggestion.address,
      });
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  };

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    const request: EasyTierSettingsRequest = {
      mode: draft.mode,
      config_server: draft.isConsoleForgotten
        ? ""
        : draft.configServer.trim() === ""
          ? null
          : draft.configServer.trim(),
      is_secure_mode: draft.isSecureMode,
      network_name: draft.networkName,
      network_secret: draft.networkSecret,
      address: draft.address,
      hostname: view.hostname,
      peers: draft.peers,
      exported_networks: draft.exportedNetworks,
    };
    try {
      onApplied(
        await apiPost<EasyTierView>("/hub/overlay/easytier/set", request),
      );
      setDraft((current) => ({
        ...current,
        configServer: "",
        isConsoleForgotten: false,
        networkSecret: "",
      }));
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const isConsole = draft.mode === MODE_CONSOLE;

  return (
    <section
      className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t("ui.overlay.settings_title")}</h2>
        {!isConsole && (
          <button
            type="button"
            className="button"
            onClick={() => void suggest()}
          >
            <Icon name="refresh" size={14} />
            {t("ui.overlay.generate")}
          </button>
        )}
      </div>

      <div className="overlay_choices">
        {MODES.map((mode) => (
          <button
            key={mode}
            type="button"
            className={`overlay_choice ${mode === draft.mode ? "overlay_choice--on" : ""}`}
            aria-pressed={mode === draft.mode}
            onClick={() => change({ mode })}
          >
            <span className="overlay_choice_head">
              <strong>{t(MODE_LABEL_KEYS[mode])}</strong>
              {mode === view.mode && (
                <span className="badge">{t("state.active")}</span>
              )}
            </span>
            <span className="overlay_choice_summary">
              {t(MODE_SUMMARY_KEYS[mode])}
            </span>
          </button>
        ))}
      </div>

      {isConsole ? (
        <ConsoleFields view={view} draft={draft} onChange={change} />
      ) : (
        <ManualFields view={view} draft={draft} onChange={change} />
      )}

      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.overlay.apply_settings")}
        hint={t("ui.overlay.apply_settings_hint")}
        warning={settingsWarning(view, draft)}
        error={error}
        onReset={() => setDraft(storedDraft(view))}
        onApply={() => void apply()}
      />
    </section>
  );
}

/** What applying these settings interrupts, or nothing. */
function settingsWarning(
  view: EasyTierView,
  draft: EasyTierDraft,
): string | undefined {
  if (view.is_secret_set && draft.networkSecret !== "") {
    return t("ui.overlay.warning_new_secret");
  }
  if (view.is_active && draft.mode !== view.mode) {
    return t("ui.overlay.warning_mode");
  }
  return undefined;
}

interface FieldsProps {
  view: EasyTierView;
  draft: EasyTierDraft;
  onChange: (patch: Partial<EasyTierDraft>) => void;
}

/** The console's address, kept sealed, and whether it runs in secure mode. */
function ConsoleFields({ view, draft, onChange }: FieldsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const isKept = view.has_config_server && !draft.isConsoleForgotten;
  return (
    <>
      <h3 className="easytier_subtitle">{t("ui.overlay.console_title")}</h3>
      <div className="easytier_fact easytier_config_server">
        <span className="field_label">
          {t("ui.overlay.config_server_label")}
        </span>
        <span className="easytier_fact_value">
          {isKept
            ? t("ui.overlay.setup_key_kept")
            : t("ui.overlay.setup_key_missing")}
        </span>
        <PasswordInput
          value={draft.configServer}
          onChange={(value) =>
            onChange({ configServer: value, isConsoleForgotten: false })
          }
          placeholder={t("ui.overlay.config_server_placeholder")}
        />
        {isKept && (
          <button
            type="button"
            className="button button--small button--danger"
            onClick={() =>
              onChange({ configServer: "", isConsoleForgotten: true })
            }
          >
            {t("ui.overlay.setup_key_forget")}
          </button>
        )}
      </div>
      <p className="field_hint">{t("ui.overlay.config_server_hint")}</p>
      <ToggleSwitch
        isOn={draft.isSecureMode}
        onChange={(isOn) => onChange({ isSecureMode: isOn })}
        label={t("ui.overlay.secure_mode")}
        description={t("ui.overlay.secure_mode_description")}
      />
    </>
  );
}

/** The network, the peers dialled at start, and the networks exported. */
function ManualFields({ view, draft, onChange }: FieldsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [typedPeer, setTypedPeer] = useState("");
  const [typedNetwork, setTypedNetwork] = useState("");

  const addPeer = () => {
    const entry = typedPeer.trim();
    if (entry === "" || draft.peers.includes(entry)) {
      return;
    }
    onChange({ peers: [...draft.peers, entry] });
    setTypedPeer("");
  };
  const addNetwork = () => {
    const entry = typedNetwork.trim();
    if (entry === "" || draft.exportedNetworks.includes(entry)) {
      return;
    }
    onChange({ exportedNetworks: [...draft.exportedNetworks, entry] });
    setTypedNetwork("");
  };
  const suggested = view.suggested_networks.map((entry) => entry.cidr);
  const extra = draft.exportedNetworks.filter(
    (cidr) => !suggested.includes(cidr),
  );
  const toggleNetwork = (cidr: string, isOn: boolean) => {
    onChange({
      exportedNetworks: isOn
        ? [...draft.exportedNetworks, cidr]
        : draft.exportedNetworks.filter((entry) => entry !== cidr),
    });
  };

  return (
    <>
      <h3 className="easytier_subtitle">{t("ui.overlay.network_title")}</h3>
      <p className="field_hint">{t("ui.overlay.network_hint")}</p>
      <div className="easytier_fields">
        <label className="field">
          <span className="field_label">{t("ui.overlay.network_name")}</span>
          <input
            className="input"
            value={draft.networkName}
            spellCheck={false}
            onChange={(event) => onChange({ networkName: event.target.value })}
          />
        </label>
        <label className="field">
          <span className="field_label">{t("ui.overlay.network_secret")}</span>
          <PasswordInput
            value={draft.networkSecret}
            onChange={(value) => onChange({ networkSecret: value })}
            placeholder={
              view.is_secret_set
                ? t("ui.overlay.secret_kept")
                : t("ui.overlay.secret_placeholder")
            }
          />
        </label>
        <label className="field">
          <span className="field_label">{t("ui.overlay.own_address")}</span>
          <input
            className="input"
            value={draft.address}
            spellCheck={false}
            placeholder="10.0.0.1/24"
            onChange={(event) => onChange({ address: event.target.value })}
          />
        </label>
      </div>

      <h3 className="easytier_subtitle">{t("ui.overlay.bootstrap_title")}</h3>
      <p className="field_hint">{t("ui.overlay.bootstrap_hint")}</p>
      <div className="easytier_rows">
        {draft.peers.map((peer) => (
          <div key={peer} className="easytier_row">
            <span className="easytier_row_text">{peer}</span>
            <button
              type="button"
              className="button button--ghost"
              onClick={() =>
                onChange({
                  peers: draft.peers.filter((entry) => entry !== peer),
                })
              }
            >
              <Icon name="trash" size={14} />
              {t("ui.overlay.remove")}
            </button>
          </div>
        ))}
        {draft.peers.length === 0 && (
          <p className="field_hint">{t("ui.overlay.bootstrap_empty")}</p>
        )}
      </div>
      <div className="easytier_add">
        <input
          className="input"
          value={typedPeer}
          spellCheck={false}
          placeholder="tcp://198.51.100.7:11010"
          onChange={(event) => setTypedPeer(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              addPeer();
            }
          }}
        />
        <button type="button" className="button" onClick={addPeer}>
          <Icon name="plus" size={14} />
          {t("ui.overlay.add")}
        </button>
      </div>

      <h3 className="easytier_subtitle">{t("ui.overlay.export_title")}</h3>
      <p className="field_hint">{t("ui.overlay.export_hint")}</p>
      <div className="easytier_rows">
        {view.suggested_networks.map((entry) => (
          <label key={entry.cidr} className="easytier_choice">
            <input
              type="checkbox"
              checked={draft.exportedNetworks.includes(entry.cidr)}
              onChange={(event) =>
                toggleNetwork(entry.cidr, event.target.checked)
              }
            />
            <span className="easytier_row_text">{entry.cidr}</span>
            <span className="field_hint">{entry.interface}</span>
          </label>
        ))}
        {extra.map((cidr) => (
          <div key={cidr} className="easytier_row">
            <span className="easytier_row_text">{cidr}</span>
            <button
              type="button"
              className="button button--ghost"
              onClick={() => toggleNetwork(cidr, false)}
            >
              <Icon name="trash" size={14} />
              {t("ui.overlay.remove")}
            </button>
          </div>
        ))}
      </div>
      <div className="easytier_add">
        <input
          className="input"
          value={typedNetwork}
          spellCheck={false}
          placeholder="10.20.0.0/24"
          onChange={(event) => setTypedNetwork(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              addNetwork();
            }
          }}
        />
        <button type="button" className="button" onClick={addNetwork}>
          <Icon name="plus" size={14} />
          {t("ui.overlay.add")}
        </button>
      </div>
    </>
  );
}

interface InstancesPanelProps {
  view: EasyTierView;
  state: ConsoleState;
}

/** What the engine runs on the console's word; read-only. */
function InstancesPanel({ view, state }: InstancesPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.overlay.instances_title")}</h2>
      </div>
      <p className="field_hint">{t("ui.overlay.instances_hint")}</p>
      {state === "stopped" && (
        <p className="field_hint">{t("ui.overlay.console_not_running")}</p>
      )}
      {state === "waiting" && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            <strong>{t("ui.overlay.console_waiting")}</strong>
            <div>{t("ui.overlay.console_waiting_hint")}</div>
          </div>
        </div>
      )}
      {state === "joined" &&
        view.instances.map((instance) => (
          <InstanceCard
            key={`${instance.instance_name}-${instance.network_name}`}
            instance={instance}
          />
        ))}
    </section>
  );
}

/** One instance's facts; a field the console withheld says so. */
function InstanceCard({ instance }: { instance: EasyTierInstance }) {
  return (
    <div className="easytier_instance">
      {INSTANCE_FACTS.map((fact) => (
        <div key={fact.field} className="easytier_fact">
          <span className="field_label">{t(fact.labelKey)}</span>
          {instance.withheld.includes(fact.field) ? (
            <span className="field_hint">
              {t("ui.overlay.instance_withheld")}
            </span>
          ) : (
            <span className="easytier_fact_value">{instance[fact.field]}</span>
          )}
        </div>
      ))}
      <div className="easytier_fact">
        <span className="field_label">
          {t("ui.overlay.instance_subnet_routes")}
        </span>
        <span className="easytier_fact_value">
          {instance.subnet_routes.length > 0
            ? instance.subnet_routes.join(", ")
            : "—"}
        </span>
      </div>
    </div>
  );
}

/**
 * The two commands another machine needs: one to join this network, one to
 * stand up a rendezvous of your own on a machine that has a public address.
 *
 * The secret is masked on the screen and real in what is copied, because a
 * command is only useful whole and a screen is read by whoever walks past.
 */
function CommandPanel({ view }: { view: EasyTierView }) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [copied, setCopied] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const host = view.join_host === "" ? "<this gateway>" : view.join_host;
  const masked = "•".repeat(12);
  const joinLine = (secret: string) =>
    `easytier-core -d --network-name ${view.network_name} ` +
    `--network-secret ${secret} -p tcp://${host}:${EASYTIER_PEER_PORT}`;
  const serverLine = (secret: string) =>
    `easytier-core --private-mode true --network-name ${view.network_name} ` +
    `--network-secret ${secret} ` +
    `--relay-network-whitelist ${view.network_name} ` +
    `-l tcp://0.0.0.0:${EASYTIER_PEER_PORT} ` +
    `-l udp://0.0.0.0:${EASYTIER_PEER_PORT}`;

  const copy = async (kind: string, line: (secret: string) => string) => {
    setError(null);
    try {
      const secret = await apiGet<EasyTierSecret>(
        "/hub/overlay/easytier/secret",
      );
      await copyText(line(secret.network_secret));
      setCopied(kind);
      window.setTimeout(() => setCopied(null), 1500);
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  };

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.overlay.commands_title")}</h2>
      </div>

      <p className="field_hint">{t("ui.overlay.command_join_hint")}</p>
      <div className="easytier_command">
        <code>{joinLine(masked)}</code>
        <button
          type="button"
          className="button"
          onClick={() => void copy("join", joinLine)}
        >
          <Icon name={copied === "join" ? "check" : "link"} size={14} />
          {t("ui.overlay.copy_with_secret")}
        </button>
      </div>

      <p className="field_hint">{t("ui.overlay.command_server_hint")}</p>
      <div className="easytier_command">
        <code>{serverLine(masked)}</code>
        <button
          type="button"
          className="button"
          onClick={() => void copy("server", serverLine)}
        >
          <Icon name={copied === "server" ? "check" : "link"} size={14} />
          {t("ui.overlay.copy_with_secret")}
        </button>
      </div>

      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
    </section>
  );
}

/** One EasyTier peer as the shared table draws it. */
function easytierRow(peer: EasyTierPeer): OverlayPeerRow {
  return {
    key: `${peer.hostname}-${peer.address}`,
    name: peer.hostname,
    address: peer.address,
    link: peer.link,
    detail: peer.protocol,
    latencyMs: peer.latency_ms,
    lossRatio: peer.loss_ratio,
    rxBytes: peer.rx_bytes,
    txBytes: peer.tx_bytes,
    isConnected: peer.is_connected,
  };
}
