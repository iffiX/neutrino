import { useEffect, useRef, useState } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { PasswordInput } from "./password_input";
import { Spinner } from "./spinner";
import { StatusDot } from "./status_dot";
import type { StatusTone } from "./status_dot";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import { useDraft } from "../use_draft";
import { HUB_EVENT_CONFIG } from "../use_hub_events";
import type { HubEventMatch } from "../use_hub_events";
import type {
  FrpAccessKeySetRequest,
  FrpRegion,
  FrpState,
  FrpTunnelListView,
  FrpTunnelSetRequest,
  FrpView,
  OpenFrpLoginState,
  OpenFrpView,
  SettingsView,
} from "../api_types";

import "./relay_panels.css";
import "./frp_panels.css";

/**
 * SakuraFrp and OpenFrp: a node at the vendor forwards its public port to the
 * hub through frpc. Each section reads where the way in stands, signs the hub
 * in to the person's account, and lists the account's tunnels to pick one.
 */

type FrpVendor = "sakurafrp" | "openfrp";

const FRP_PATHS: Record<FrpVendor, string> = {
  sakurafrp: "/hub/overlay/sakurafrp",
  openfrp: "/hub/overlay/openfrp",
};

/** The vendor's name, which every sentence of the section names it by. */
const FRP_TITLE_KEYS: Record<FrpVendor, string> = {
  sakurafrp: "ui.overlay.sakurafrp_title",
  openfrp: "ui.overlay.openfrp_title",
};

// The card's switch and the section's own writes move the vendor's file.
const FRP_INVALIDATE_ON: Record<FrpVendor, HubEventMatch[]> = {
  sakurafrp: [{ type: HUB_EVENT_CONFIG, key: "overlay/sakurafrp.json" }],
  openfrp: [{ type: HUB_EVENT_CONFIG, key: "overlay/openfrp.json" }],
};

const FRP_EMPTY_KEYS: Record<FrpVendor, string> = {
  sakurafrp: "ui.overlay.frp_empty",
  openfrp: "ui.overlay.openfrp_empty",
};

/** How often the status is read; the check runs on the hub's own clock. */
const FRP_RELOAD_MS = 10000;
/** How often the status is read while OpenFrp's login waits for the person. */
const OPENFRP_LOGIN_RELOAD_MS = 5000;

const STATE_TONES: Record<FrpState, StatusTone> = {
  disabled: "idle",
  not_signed_in: "idle",
  vault_locked: "error",
  no_tunnel: "idle",
  loopback_port_taken: "error",
  config_failed: "error",
  connecting: "warn",
  connected: "ok",
  proxy_refused: "error",
  port_closed: "error",
  login_failed: "error",
  unreachable: "error",
};

const REGION_KEYS: Record<FrpRegion, string> = {
  mainland: "ui.overlay.frp_region_mainland",
  hk_mo_tw: "ui.overlay.frp_region_hk_mo_tw",
  abroad: "ui.overlay.frp_region_abroad",
  outside_mainland: "ui.overlay.frp_region_outside_mainland",
};

// The sentence under Log in for a login that ended without one.
const LOGIN_END_KEYS: Record<OpenFrpLoginState, string | null> = {
  idle: null,
  waiting: null,
  timed_out: "ui.overlay.openfrp_login_timed_out",
  failed: "ui.overlay.openfrp_login_failed",
};

const LATENCY_PRECISE_BELOW_MS = 10;

interface FrpSectionProps {
  vendor: FrpVendor;
  /** Called when the state moves, so the page's card, whose "active" is the
   * state `connected`, is read again at the same moment. */
  onStateChange?: (state: FrpState) => void;
}

export function FrpSection({ vendor, onStateChange }: FrpSectionProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const path = FRP_PATHS[vendor];
  const resource = useApiResource<FrpView | OpenFrpView>(path, {
    invalidateOn: FRP_INVALIDATE_ON[vendor],
  });
  const settings = useApiResource<SettingsView>("/hub/setting");
  const view = resource.data;
  const state = view?.state ?? null;
  const onStateChangeRef = useRef(onStateChange);
  onStateChangeRef.current = onStateChange;
  const seenStateRef = useRef<FrpState | null>(null);
  useEffect(() => {
    if (state === null) {
      return;
    }
    if (seenStateRef.current !== null && seenStateRef.current !== state) {
      onStateChangeRef.current?.(state);
    }
    seenStateRef.current = state;
  }, [state]);

  const isWaiting =
    view !== null && isOpenFrpView(view) && view.login.state === "waiting";
  const reload = resource.reload;
  useEffect(() => {
    const timer = window.setInterval(
      () => {
        if (!document.hidden) {
          reload();
        }
      },
      isWaiting ? OPENFRP_LOGIN_RELOAD_MS : FRP_RELOAD_MS,
    );
    return () => window.clearInterval(timer);
  }, [reload, isWaiting]);

  if (resource.error !== null && view === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }

  if (view === null) {
    return <div className="skeleton" style={{ height: 320 }} />;
  }

  const port = settings.data?.agent_listen_port ?? null;

  return (
    <>
      <div className="overlay_product_header">
        <div className="page_title_row">
          <h2>{t(FRP_TITLE_KEYS[vendor])}</h2>
        </div>
      </div>
      <FrpStatusPanel vendor={vendor} view={view} port={port} />
      {isOpenFrpView(view) ? (
        <OpenFrpAccountPanel view={view} onChanged={resource.setData} />
      ) : (
        <SakuraFrpAccountPanel view={view} onChanged={resource.setData} />
      )}
      {view.is_signed_in && (
        <FrpTunnelsPanel
          vendor={vendor}
          view={view}
          port={port}
          onChanged={resource.setData}
        />
      )}
    </>
  );
}

function isOpenFrpView(view: FrpView | OpenFrpView): view is OpenFrpView {
  return "login" in view;
}

interface FrpStatusPanelProps {
  vendor: FrpVendor;
  view: FrpView;
  /** The connection port; null until the settings load. */
  port: number | null;
}

/** Where the way in stands: the state, the node and the address it adds. */
function FrpStatusPanel({ vendor, view, port }: FrpStatusPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const isPortMismatched =
    view.tunnel_id !== "" && port !== null && view.local_port !== port;

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.overlay.frp_status_title")}</h2>
        <span className="badge">
          <StatusDot tone={STATE_TONES[view.state]} />
          {t(`state.frp_${view.state}`)}
        </span>
      </div>
      {view.last_error !== "" && (
        <p className="relay_error">{view.last_error}</p>
      )}
      {isPortMismatched && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            {t("ui.overlay.frp_port_mismatch", {
              port: port ?? 0,
              vendor: t(FRP_TITLE_KEYS[vendor]),
            })}
          </div>
        </div>
      )}
      <div className="relay_facts">
        <div className="relay_fact">
          <span className="field_label">{t("ui.overlay.frp_node")}</span>
          <span>{view.node_name || "—"}</span>
        </div>
        <div className="relay_fact">
          <span className="field_label">{t("ui.overlay.frp_address")}</span>
          <span className="relay_fact_value">{view.url || "—"}</span>
        </div>
      </div>
    </section>
  );
}

interface SakuraFrpAccountPanelProps {
  view: FrpView;
  onChanged: (view: FrpView) => void;
}

/** The account's access key: pasted and saved, or forgotten. */
function SakuraFrpAccountPanel({
  view,
  onChanged,
}: SakuraFrpAccountPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const confirm = useConfirm();
  const [accessKey, setAccessKey] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isDirty = accessKey.trim() !== "";
  const vendorTitle = t(FRP_TITLE_KEYS.sakurafrp);

  const store = async (value: string) => {
    setIsBusy(true);
    setError(null);
    const request: FrpAccessKeySetRequest = { access_key: value };
    try {
      onChanged(
        await apiPost<FrpView>(
          `${FRP_PATHS.sakurafrp}/access_key/set`,
          request,
        ),
      );
      setAccessKey("");
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const askForget = () => {
    confirm.ask({
      title: t("ui.overlay.frp_access_key_forget"),
      body:
        view.state === "connected"
          ? t("ui.overlay.frp_apply_warning", { vendor: vendorTitle })
          : "",
      confirmLabel: t("ui.overlay.frp_access_key_forget"),
      onConfirm: () => void store(""),
    });
  };

  return (
    <section
      className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t("ui.overlay.frp_account_title")}</h2>
        {view.is_signed_in && (
          <button
            type="button"
            className="button button--small button--danger frp_header_action"
            disabled={isBusy}
            onClick={askForget}
          >
            {t("ui.overlay.frp_access_key_forget")}
          </button>
        )}
      </div>
      <label className="field">
        <span className="field_label">{t("ui.overlay.frp_access_key")}</span>
        <PasswordInput
          value={accessKey}
          onChange={(value) => {
            setError(null);
            setAccessKey(value);
          }}
        />
        <span className="field_hint">
          {t("ui.overlay.frp_access_key_hint")}
        </span>
      </label>
      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.overlay.frp_access_key_save")}
        hint={t("ui.overlay.frp_access_key_save_hint")}
        error={error}
        onReset={() => {
          setError(null);
          setAccessKey("");
        }}
        onApply={() => void store(accessKey.trim())}
      />
      {confirm.modal}
    </section>
  );
}

interface OpenFrpAccountPanelProps {
  view: OpenFrpView;
  onChanged: (view: OpenFrpView) => void;
}

/** The account's browser login: Log in, the wait for it, and Log out. */
function OpenFrpAccountPanel({ view, onChanged }: OpenFrpAccountPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const confirm = useConfirm();
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isWaiting = view.login.state === "waiting";
  const isLoginShown = !view.is_signed_in || view.is_login_expired;
  const loginEndKey = LOGIN_END_KEYS[view.login.state];
  const vendorTitle = t(FRP_TITLE_KEYS.openfrp);

  const logIn = async () => {
    // Opened within the press and sent on once the hub has the address.
    const tab = window.open("", "_blank");
    if (tab !== null) {
      tab.opener = null;
    }
    setIsBusy(true);
    setError(null);
    try {
      const next = await apiPost<OpenFrpView>(
        `${FRP_PATHS.openfrp}/login/start`,
        {},
      );
      onChanged(next);
      if (tab !== null && next.login.authorization_url !== "") {
        tab.location.href = next.login.authorization_url;
      } else {
        tab?.close();
      }
    } catch (cause: unknown) {
      tab?.close();
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const logOut = async () => {
    setIsBusy(true);
    setError(null);
    try {
      onChanged(await apiPost<OpenFrpView>(`${FRP_PATHS.openfrp}/logout`, {}));
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const askLogOut = () => {
    confirm.ask({
      title: t("ui.overlay.openfrp_logout"),
      body:
        view.state === "connected"
          ? t("ui.overlay.frp_apply_warning", { vendor: vendorTitle })
          : "",
      confirmLabel: t("ui.overlay.openfrp_logout"),
      onConfirm: () => void logOut(),
    });
  };

  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.overlay.frp_account_title")}</h2>
        {view.is_signed_in && (
          <button
            type="button"
            className="button button--small button--danger frp_header_action"
            disabled={isBusy}
            onClick={askLogOut}
          >
            {t("ui.overlay.openfrp_logout")}
          </button>
        )}
      </div>
      {view.is_login_expired && (
        <div className="notice notice--warn">
          <Icon name="alert" size={15} />
          <div className="notice_body">
            {t("ui.overlay.openfrp_login_expired")}
          </div>
        </div>
      )}
      {isWaiting ? (
        <div className="frp_login_wait">
          <Spinner size={13} />
          <span>{t("ui.overlay.openfrp_login_waiting")}</span>
          <a
            className="button button--small"
            href={view.login.authorization_url}
            target="_blank"
            rel="noreferrer"
          >
            {t("ui.overlay.openfrp_login_open")}
          </a>
        </div>
      ) : (
        isLoginShown && (
          <div className="frp_login">
            <button
              type="button"
              className="button button--primary"
              disabled={isBusy}
              onClick={() => void logIn()}
            >
              {isBusy ? <Spinner size={13} /> : <Icon name="key" size={14} />}
              {t("ui.overlay.openfrp_login")}
            </button>
            {loginEndKey !== null && (
              <span className="field_hint">{t(loginEndKey)}</span>
            )}
          </div>
        )
      )}
      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
      <div className="frp_terms">
        <span>{t("ui.overlay.openfrp_openapi")}</span>
        <span>{t("ui.overlay.openfrp_notice")}</span>
      </div>
      {confirm.modal}
    </section>
  );
}

interface FrpTunnelsPanelProps {
  vendor: FrpVendor;
  view: FrpView;
  /** The connection port; null until the settings load. */
  port: number | null;
  onChanged: (view: FrpView) => void;
}

/** The picked tunnel as the form holds it. */
interface TunnelDraft {
  tunnelId: string;
}

function tunnelDraftOf(view: FrpView): TunnelDraft {
  return { tunnelId: view.tunnel_id };
}

/** The account's tunnels to the connection port, one of them picked. */
function FrpTunnelsPanel({
  vendor,
  view,
  port,
  onChanged,
}: FrpTunnelsPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const path = FRP_PATHS[vendor];
  const list = useApiResource<FrpTunnelListView>(`${path}/tunnel`);
  const { draft, setDraft, isDirty, reset } = useDraft(view, tunnelDraftOf);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const vendorTitle = t(FRP_TITLE_KEYS[vendor]);

  if (draft === null) {
    return null;
  }

  const apply = async () => {
    setIsBusy(true);
    setError(null);
    const request: FrpTunnelSetRequest = { tunnel_id: draft.tunnelId };
    try {
      onChanged(await apiPost<FrpView>(`${path}/tunnel/set`, request));
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const tunnels = list.data?.tunnels ?? null;

  return (
    <section
      className={`settings_group ${isDirty ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t("ui.overlay.frp_tunnels")}</h2>
        <button
          type="button"
          className="button button--small frp_header_action"
          disabled={list.isLoading || isBusy}
          onClick={list.reload}
        >
          {list.isLoading ? (
            <Spinner size={12} />
          ) : (
            <Icon name="refresh" size={13} />
          )}
          {t("ui.overlay.frp_refresh")}
        </button>
      </div>
      {list.error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{list.error}</div>
        </div>
      )}
      {tunnels === null ? (
        list.error === null && (
          <div className="skeleton" style={{ height: 120 }} />
        )
      ) : tunnels.length === 0 ? (
        <div className="placeholder">
          <span>
            {t(FRP_EMPTY_KEYS[vendor], {
              port: port ?? "",
              vendor: vendorTitle,
            })}
          </span>
          <a
            className="button button--small"
            href={view.console_url}
            target="_blank"
            rel="noreferrer"
          >
            {t("ui.overlay.frp_console", { vendor: vendorTitle })}
          </a>
        </div>
      ) : (
        <div className="frp_tunnels">
          <div className="frp_tunnel_head">
            <span />
            <span>{t("ui.overlay.frp_node")}</span>
            <span>{t("ui.overlay.frp_region")}</span>
            <span className="frp_tunnel_latency">
              {t("ui.overlay.frp_latency")}
            </span>
          </div>
          <div className="frp_tunnel_list" role="radiogroup">
            {tunnels.map((tunnel) => {
              const isChosen = tunnel.tunnel_id === draft.tunnelId;
              const isApplied = tunnel.tunnel_id === view.tunnel_id;
              return (
                <button
                  key={tunnel.tunnel_id}
                  type="button"
                  role="radio"
                  aria-checked={isChosen}
                  className={`frp_tunnel_row ${isApplied ? "frp_tunnel_row--applied" : ""}`}
                  disabled={isBusy}
                  onClick={() => {
                    setError(null);
                    setDraft({ tunnelId: tunnel.tunnel_id });
                  }}
                >
                  <span
                    className={`frp_radio ${isChosen ? "frp_radio--on" : ""}`}
                  />
                  <span className="frp_tunnel_node">{tunnel.node_name}</span>
                  <span className="frp_tunnel_region">
                    {t(REGION_KEYS[tunnel.region])}
                  </span>
                  <span className="frp_tunnel_latency">
                    {formatLatency(tunnel.latency_ms)}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
      <ApplyBar
        isDirty={isDirty}
        isBusy={isBusy}
        label={t("ui.overlay.frp_apply")}
        hint={t("ui.overlay.frp_apply_hint")}
        warning={
          view.state === "connected"
            ? t("ui.overlay.frp_apply_warning", { vendor: vendorTitle })
            : undefined
        }
        error={error}
        onReset={() => {
          setError(null);
          reset();
        }}
        onApply={() => void apply()}
      />
    </section>
  );
}

/** A node's connect time, empty where no connect finished in time. */
function formatLatency(latencyMs: number | null): string {
  if (latencyMs === null) {
    return "";
  }
  const value =
    latencyMs < LATENCY_PRECISE_BELOW_MS
      ? latencyMs.toFixed(1)
      : String(Math.round(latencyMs));
  return `${value} ms`;
}
