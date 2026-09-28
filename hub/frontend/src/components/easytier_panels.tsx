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
import { useConfirm } from "../use_confirm";
import type {
  DevicesResponse,
  EasyTierInstance,
  EasyTierMode,
  EasyTierPeer,
  EasyTierSecret,
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

      <ModePanel view={view} onApplied={resource.setData} />

      {isConsole ? (
        <>
          <ConsolePanel view={view} onApplied={resource.setData} />
          <InstancesPanel view={view} state={consoleState} />
        </>
      ) : (
        <>
          <NetworkPanel view={view} onApplied={resource.setData} />
          <BootstrapPanel view={view} onApplied={resource.setData} />
          <ExportPanel view={view} onApplied={resource.setData} />
          {isJoined && <CommandPanel view={view} />}
        </>
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

interface PanelProps {
  view: EasyTierView;
  onApplied: (view: EasyTierView) => void;
}

/** Where the network comes from: EasyTier's console or manual meeting points. */
function ModePanel({ view, onApplied }: PanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [chosen, setChosen] = useState<EasyTierMode>(view.mode);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A mode picked but not applied stays picked.
  const isReseedable = useDraftSeeding(chosen, view.mode);
  useEffect(() => {
    if (!isReseedable(view.mode)) {
      return;
    }
    setChosen(view.mode);
  }, [view, isReseedable]);

  const isDirty = chosen !== view.mode;

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    try {
      onApplied(
        await apiPost<EasyTierView>("/hub/overlay/easytier/mode/set", {
          mode: chosen,
        }),
      );
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
        <h2>{t("ui.overlay.mode_title")}</h2>
      </div>
      <div className="overlay_choices">
        {MODES.map((mode) => (
          <button
            key={mode}
            type="button"
            className={`overlay_choice ${mode === chosen ? "overlay_choice--on" : ""}`}
            aria-pressed={mode === chosen}
            onClick={() => {
              setError(null);
              setChosen(mode);
            }}
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
      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.overlay.apply_mode")}
        hint={t("ui.overlay.apply_mode_hint")}
        warning={view.is_active ? t("ui.overlay.warning_mode") : undefined}
        error={error}
        onReset={() => setChosen(view.mode)}
        onApply={() => void apply()}
      />
    </section>
  );
}

/** The console's address and whether the engine runs its network securely. */
function ConsolePanel({ view, onApplied }: PanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [isSecure, setIsSecure] = useState(view.is_secure_mode);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stored = String(view.is_secure_mode);
  const isReseedable = useDraftSeeding(String(isSecure), stored);
  useEffect(() => {
    if (!isReseedable(stored)) {
      return;
    }
    setIsSecure(view.is_secure_mode);
  }, [view, stored, isReseedable]);

  const isDirty = isSecure !== view.is_secure_mode;

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    try {
      onApplied(
        await apiPost<EasyTierView>("/hub/overlay/easytier/secure_mode/set", {
          is_secure_mode: isSecure,
        }),
      );
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
        <h2>{t("ui.overlay.console_title")}</h2>
      </div>
      <ConfigServerRow
        hasConfigServer={view.has_config_server}
        onApplied={onApplied}
      />
      <ToggleSwitch
        isOn={isSecure}
        onChange={setIsSecure}
        label={t("ui.overlay.secure_mode")}
        description={t("ui.overlay.secure_mode_description")}
        isDisabled={isBusy}
      />
      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.overlay.apply_secure_mode")}
        hint={t("ui.overlay.apply_secure_mode_hint")}
        error={error}
        onReset={() => setIsSecure(view.is_secure_mode)}
        onApply={() => void apply()}
      />
    </section>
  );
}

interface ConfigServerRowProps {
  hasConfigServer: boolean;
  onApplied: (view: EasyTierView) => void;
}

/** Whether a console address is kept, with Replace and Forget. */
function ConfigServerRow({ hasConfigServer, onApplied }: ConfigServerRowProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const confirm = useConfirm();
  const [isReplacing, setIsReplacing] = useState(false);
  const [address, setAddress] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const store = async (value: string) => {
    setIsBusy(true);
    setError(null);
    try {
      onApplied(
        await apiPost<EasyTierView>("/hub/overlay/easytier/config_server/set", {
          config_server: value,
        }),
      );
      setAddress("");
      setIsReplacing(false);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const askForget = () => {
    confirm.ask({
      title: t("ui.overlay.config_server_forget_title"),
      body: t("ui.overlay.config_server_forget_body"),
      confirmLabel: t("ui.overlay.setup_key_forget"),
      onConfirm: () => void store(""),
    });
  };

  return (
    <>
      <div className="easytier_fact easytier_config_server">
        <span className="field_label">
          {t("ui.overlay.config_server_label")}
        </span>
        <span className="easytier_fact_value">
          {hasConfigServer
            ? t("ui.overlay.setup_key_kept")
            : t("ui.overlay.setup_key_missing")}
        </span>
        {isReplacing ? (
          <>
            <PasswordInput
              value={address}
              onChange={setAddress}
              placeholder={t("ui.overlay.config_server_placeholder")}
            />
            <button
              type="button"
              className="button button--small button--primary"
              disabled={isBusy || address.trim() === ""}
              onClick={() => void store(address.trim())}
            >
              {t("ui.overlay.setup_key_save")}
            </button>
            <button
              type="button"
              className="button button--small"
              disabled={isBusy}
              onClick={() => {
                setAddress("");
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
            {hasConfigServer && (
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
      <p className="field_hint">{t("ui.overlay.config_server_hint")}</p>
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

/** The network itself: what identifies it, what opens it, where this box is. */
function NetworkPanel({ view, onApplied }: PanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [name, setName] = useState(view.network_name);
  const [secret, setSecret] = useState("");
  const [address, setAddress] = useState(view.address);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stored = `${view.network_name} ${view.address}`;
  const isReseedable = useDraftSeeding(`${name} ${address}`, stored);
  useEffect(() => {
    if (!isReseedable(stored)) {
      return;
    }
    setName(view.network_name);
    setAddress(view.address);
  }, [view, stored, isReseedable]);

  const isDirty =
    name !== view.network_name || address !== view.address || secret !== "";

  const suggest = async () => {
    setError(null);
    try {
      const suggestion = await apiPost<EasyTierSuggestion>(
        "/hub/overlay/easytier/suggestion/create",
        {},
      );
      setName(suggestion.network_name);
      setSecret(suggestion.network_secret);
      setAddress(suggestion.address);
    } catch (cause: unknown) {
      setError(describeError(cause));
    }
  };

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    try {
      onApplied(
        await apiPost<EasyTierView>("/hub/overlay/easytier/set", {
          network_name: name,
          network_secret: secret,
          address,
          hostname: view.hostname,
        }),
      );
      setSecret("");
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
        <h2>{t("ui.overlay.network_title")}</h2>
        <button type="button" className="button" onClick={() => void suggest()}>
          <Icon name="refresh" size={14} />
          {t("ui.overlay.generate")}
        </button>
      </div>
      <p className="field_hint">{t("ui.overlay.network_hint")}</p>

      <div className="easytier_fields">
        <label className="field">
          <span className="field_label">{t("ui.overlay.network_name")}</span>
          <input
            className="input"
            value={name}
            spellCheck={false}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field_label">{t("ui.overlay.network_secret")}</span>
          <PasswordInput
            value={secret}
            onChange={setSecret}
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
            value={address}
            spellCheck={false}
            placeholder="10.0.0.1/24"
            onChange={(event) => setAddress(event.target.value)}
          />
        </label>
      </div>

      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.overlay.apply_network")}
        hint={t("ui.overlay.apply_network_hint")}
        warning={
          view.is_secret_set && secret !== ""
            ? t("ui.overlay.warning_new_secret")
            : undefined
        }
        error={error}
        onReset={() => {
          setName(view.network_name);
          setAddress(view.address);
          setSecret("");
        }}
        onApply={() => void apply()}
      />
    </section>
  );
}

/** What this box dials when it starts, since nothing is listening for it. */
function BootstrapPanel({ view, onApplied }: PanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [peers, setPeers] = useState<string[]>(view.peers);
  const [typed, setTyped] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stored = view.peers.join(" ");
  const isReseedable = useDraftSeeding(peers.join(" "), stored);
  useEffect(() => {
    if (!isReseedable(stored)) {
      return;
    }
    setPeers(view.peers);
  }, [view, stored, isReseedable]);

  const isDirty = peers.join(" ") !== stored;

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    try {
      onApplied(
        await apiPost<EasyTierView>("/hub/overlay/easytier/peer/set", {
          peers,
        }),
      );
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const add = () => {
    const entry = typed.trim();
    if (entry === "" || peers.includes(entry)) {
      return;
    }
    setPeers([...peers, entry]);
    setTyped("");
  };

  return (
    <section
      className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t("ui.overlay.bootstrap_title")}</h2>
      </div>
      <p className="field_hint">{t("ui.overlay.bootstrap_hint")}</p>

      <div className="easytier_rows">
        {peers.map((peer) => (
          <div key={peer} className="easytier_row">
            <span className="easytier_row_text">{peer}</span>
            <button
              type="button"
              className="button button--ghost"
              onClick={() => setPeers(peers.filter((entry) => entry !== peer))}
            >
              <Icon name="trash" size={14} />
              {t("ui.overlay.remove")}
            </button>
          </div>
        ))}
        {peers.length === 0 && (
          <p className="field_hint">{t("ui.overlay.bootstrap_empty")}</p>
        )}
      </div>

      <div className="easytier_add">
        <input
          className="input"
          value={typed}
          spellCheck={false}
          placeholder="tcp://198.51.100.7:11010"
          onChange={(event) => setTyped(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              add();
            }
          }}
        />
        <button type="button" className="button" onClick={add}>
          <Icon name="plus" size={14} />
          {t("ui.overlay.add")}
        </button>
      </div>

      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.overlay.apply_bootstrap")}
        hint={t("ui.overlay.apply_bootstrap_hint")}
        error={error}
        onReset={() => setPeers(view.peers)}
        onApply={() => void apply()}
      />
    </section>
  );
}

/** The networks behind this box that the others may reach through it. */
function ExportPanel({ view, onApplied }: PanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [networks, setNetworks] = useState<string[]>(view.exported_networks);
  const [typed, setTyped] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stored = view.exported_networks.join(" ");
  const isReseedable = useDraftSeeding(networks.join(" "), stored);
  useEffect(() => {
    if (!isReseedable(stored)) {
      return;
    }
    setNetworks(view.exported_networks);
  }, [view, stored, isReseedable]);

  const isDirty = networks.join(" ") !== stored;
  const suggested = view.suggested_networks.map((entry) => entry.cidr);
  const extra = networks.filter((cidr) => !suggested.includes(cidr));

  const toggle = (cidr: string, isOn: boolean) => {
    setNetworks(
      isOn ? [...networks, cidr] : networks.filter((entry) => entry !== cidr),
    );
  };

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    try {
      onApplied(
        await apiPost<EasyTierView>("/hub/overlay/easytier/network/set", {
          exported_networks: networks,
        }),
      );
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
        <h2>{t("ui.overlay.export_title")}</h2>
      </div>
      <p className="field_hint">{t("ui.overlay.export_hint")}</p>

      <div className="easytier_rows">
        {view.suggested_networks.map((entry) => (
          <label key={entry.cidr} className="easytier_choice">
            <input
              type="checkbox"
              checked={networks.includes(entry.cidr)}
              onChange={(event) => toggle(entry.cidr, event.target.checked)}
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
              onClick={() =>
                setNetworks(networks.filter((entry) => entry !== cidr))
              }
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
          value={typed}
          spellCheck={false}
          placeholder="10.20.0.0/24"
          onChange={(event) => setTyped(event.target.value)}
        />
        <button
          type="button"
          className="button"
          onClick={() => {
            const entry = typed.trim();
            if (entry !== "" && !networks.includes(entry)) {
              setNetworks([...networks, entry]);
              setTyped("");
            }
          }}
        >
          <Icon name="plus" size={14} />
          {t("ui.overlay.add")}
        </button>
      </div>

      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.overlay.apply_export")}
        hint={t("ui.overlay.apply_export_hint")}
        error={error}
        onReset={() => setNetworks(view.exported_networks)}
        onApply={() => void apply()}
      />
    </section>
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
