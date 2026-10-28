import { useEffect, useRef, useState } from "react";

import { CopyButton } from "./copy_button";
import { Icon } from "./icon";
import { StatusDot } from "./status_dot";
import type { StatusTone } from "./status_dot";
import { apiGet, apiPost, describeCode, describeError } from "../api_client";
import { codeParams } from "../code_params";
import { t, useLanguage } from "../i18n";
import { useConfirm } from "../use_confirm";
import type {
  ClientListView,
  WebShareRevokeRequest,
  WebShareState,
  WebShareView,
} from "../api_types";

import "./web_shares_panel.css";

/**
 * The Clients page's **Web shares** panel: one row per share, newest first,
 * with its app, when it ends, its state, how many pages are open on it and
 * the guest account's e-mail, and Revoke, which ends it at once. A visitor
 * has no row. The panel reads the list on its own cadence, so the count and
 * the state move by themselves.
 */

const CLIENTS_PATH = "/hub/client";
const REVOKE_PATH = "/hub/client/web_share/revoke";

/** How often the panel reads the list while the tab is in front. */
const WEB_SHARES_POLL_INTERVAL_MS = 10000;

const SECONDS_PER_DAY = 86400;

const STATE_TONES: Record<WebShareState, StatusTone> = {
  active: "ok",
  preparing: "warn",
  unavailable: "idle",
  failed: "error",
};

const STATE_KEYS: Record<WebShareState, string> = {
  active: "state.share_active",
  preparing: "state.share_preparing",
  unavailable: "state.share_unavailable",
  failed: "state.share_failed",
};

interface WebSharesPanelProps {
  listView: ClientListView | null;
  /** Called with the list after a revoke, and after a read that moved a
   * share. */
  onChanged: (view: ClientListView) => void;
}

export function WebSharesPanel({ listView, onChanged }: WebSharesPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const confirm = useConfirm();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The latest list and its taker, read by the timer without restarting it.
  const latest = useRef({ listView, onChanged });
  latest.current = { listView, onChanged };

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.hidden) {
        return;
      }
      void apiGet<ClientListView>(CLIENTS_PATH)
        .then((fresh) => {
          const { listView: shown, onChanged: take } = latest.current;
          if (shown === null || !hasSharesMoved(shown, fresh)) {
            return;
          }
          take({
            ...shown,
            web_shares: fresh.web_shares,
            web_share_entries: fresh.web_share_entries,
            web_share_sites: fresh.web_share_sites,
          });
        })
        .catch(() => {
          // The next tick reads again; the last good list stays on screen.
        });
    }, WEB_SHARES_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  const revoke = async (share: WebShareView) => {
    setBusyId(share.id);
    setError(null);
    const request: WebShareRevokeRequest = { share_id: share.id };
    try {
      onChanged(await apiPost<ClientListView>(REVOKE_PATH, request));
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setBusyId(null);
    }
  };

  const askRevoke = (share: WebShareView) =>
    confirm.ask({
      title: t("ui.web_shares.revoke_title", { name: share.name }),
      body: revokeBody(share),
      confirmLabel: t("ui.web_shares.revoke"),
      onConfirm: () => void revoke(share),
    });

  const shares = listView?.web_shares ?? [];

  return (
    <section className="card web_shares_panel">
      <div className="card_header">
        <div className="card_title">
          <h2>{t("ui.web_shares.title")}</h2>
        </div>
      </div>
      {error !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{error}</div>
        </div>
      )}
      {listView === null ? (
        <div className="skeleton" style={{ height: 96 }} />
      ) : shares.length === 0 ? (
        <div className="placeholder">
          <span>{t("ui.web_shares.empty")}</span>
          <span className="faint">{t("ui.web_shares.empty_hint")}</span>
        </div>
      ) : (
        <div className="web_shares_rows">
          {shares.map((share) => (
            <WebShareRow
              key={share.id}
              share={share}
              isBusy={busyId === share.id}
              onRevoke={() => askRevoke(share)}
            />
          ))}
        </div>
      )}
      {confirm.modal}
    </section>
  );
}

interface WebShareRowProps {
  share: WebShareView;
  isBusy: boolean;
  onRevoke: () => void;
}

/** One share: its name, its app, when it ends, its state and its pages. */
function WebShareRow({ share, isBusy, onRevoke }: WebShareRowProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  return (
    <div className="web_shares_row">
      <div className="web_shares_row_main">
        <span className="web_shares_row_name">{share.name}</span>
        <span className="web_shares_row_app">
          {share.app_title}
          {share.device_name !== "" && (
            <span className="mono faint"> · {share.device_name}</span>
          )}
        </span>
        <span className="web_shares_row_expires faint">
          {expiresWords(share)}
        </span>
        <StatusDot
          tone={STATE_TONES[share.state]}
          label={t(STATE_KEYS[share.state])}
        />
        <span className="web_shares_row_online">
          {t("ui.web_shares.online", { count: share.online_count })}
        </span>
        {share.guest_email !== "" && (
          <span className="web_shares_row_guest">
            <code>{share.guest_email}</code>
            <CopyButton text={share.guest_email} />
          </span>
        )}
        <button
          type="button"
          className="button button--small button--ghost button--danger web_shares_row_revoke"
          disabled={isBusy}
          onClick={onRevoke}
        >
          <Icon name="trash" size={13} />
          {t("ui.web_shares.revoke")}
        </button>
      </div>
      {share.code !== "" && (
        <span
          className={`web_shares_row_detail ${
            share.state === "failed" ? "web_shares_row_detail--error" : ""
          }`}
        >
          {describeCode({ code: share.code, params: codeParams(share.params) })}
        </span>
      )}
    </div>
  );
}

/** When a share ends, in days, or that it lasts until it is revoked. */
function expiresWords(share: WebShareView): string {
  if (share.expires_in_s === null) {
    return t("ui.web_shares.until_revoked");
  }
  const days = Math.ceil(Math.max(0, share.expires_in_s) / SECONDS_PER_DAY);
  return t("ui.web_shares.expires_in", { days });
}

/** The revoke dialog's body, the guest account's fate after it. */
function revokeBody(share: WebShareView): string {
  const body = t("ui.web_shares.revoke_body");
  if (share.guest_email === "") {
    return body;
  }
  return `${body} ${t("ui.web_shares.revoke_guest", { email: share.guest_email })}`;
}

/** Whether a read brought shares other than those on screen, a share's
 * seconds left counted in the days its row shows. */
function hasSharesMoved(shown: ClientListView, fresh: ClientListView): boolean {
  return sharesDrawn(shown) !== sharesDrawn(fresh);
}

/** What the panel and its dialog draw of a list, as one text. */
function sharesDrawn(view: ClientListView): string {
  return JSON.stringify([
    view.web_shares.map((share) => ({
      ...share,
      expires_in_s: null,
      expires: expiresWords(share),
    })),
    view.web_share_entries,
    view.web_share_sites,
  ]);
}
