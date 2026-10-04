import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { AuthorityInstall } from "./authority_install";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import type { PanelHttpsResetView, PanelHttpsView } from "../api_types";

import "./apply_bar.css";
import { httpOrigin, httpsOrigin } from "../origins";

import "./https_panel.css";

/**
 * Whether the HTTP port sends browsers to the HTTPS port, and the
 * certificates behind it.
 *
 * Both ports are always served, so turning HTTPS on or off is one press with
 * no draft and no restart. A page on HTTP fetches the probe from the HTTPS
 * port to learn whether this browser trusts the certificate, and offers
 * Enable only once it does. A page reached on another port than the hub's
 * port for its scheme comes through a forward, where the hub's other port is
 * not this host's: nothing is probed, Enable is offered, and a switch in
 * either direction leaves the page where it is and names the port the
 * forward must reach. Regenerating is an HTTP-only action, and the new
 * authority downloads from the answer itself.
 */

/** Where the authority downloads, with or without a session. */
const AUTHORITY_DOWNLOAD_PATH = "/api/hub/setting/https/authority";
/** What a page on HTTP fetches from the HTTPS port. */
const PROBE_PATH = "/api/hub/setting/https/probe";
/** How long a probe waits before the certificate counts as untrusted. */
const PROBE_TIMEOUT_MS = 5000;
const AUTHORITY_MEDIA_TYPE = "application/x-x509-ca-cert";
/** The port a page is on when its address names none. */
const HTTP_SCHEME_PORT = 80;
const HTTPS_SCHEME_PORT = 443;

type Trust = "checking" | "trusted" | "untrusted";

/** Where a switch through a forward left the panel. */
interface SwitchedScheme {
  isOn: boolean;
  port: number;
  origin: string;
}

export function HttpsPanel() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<PanelHttpsView>("/hub/setting/https");
  const confirm = useConfirm();
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trust, setTrust] = useState<Trust>("checking");
  const [isAwaitingInstall, setIsAwaitingInstall] = useState(false);
  const [isRegenerated, setIsRegenerated] = useState(false);
  // The address a switch through a forward left for the person to open.
  const [switchedTo, setSwitchedTo] = useState<SwitchedScheme | null>(null);
  const view = resource.data;
  const isOnHttps = window.location.protocol === "https:";
  const httpsPort = view?.https_listen_port ?? null;
  const isForwarded =
    view !== null &&
    pagePort(isOnHttps) !==
      (isOnHttps ? view.https_listen_port : view.listen_port);

  const probe = useCallback(async () => {
    if (httpsPort === null) {
      return;
    }
    setTrust("checking");
    setTrust(
      (await isTrusted(httpsOrigin(httpsPort))) ? "trusted" : "untrusted",
    );
  }, [httpsPort]);

  useEffect(() => {
    if (!isOnHttps && !isForwarded) {
      void probe();
    }
  }, [isOnHttps, isForwarded, probe]);

  useEffect(() => {
    if (isOnHttps || !isAwaitingInstall) {
      return;
    }
    const probeOnReturn = () => void probe();
    window.addEventListener("focus", probeOnReturn);
    return () => window.removeEventListener("focus", probeOnReturn);
  }, [isOnHttps, isAwaitingInstall, probe]);

  const switchScheme = async (isOn: boolean) => {
    if (view === null) {
      return;
    }
    setIsBusy(true);
    setError(null);
    setSwitchedTo(null);
    try {
      const next = await apiPost<PanelHttpsView>(
        isOn ? "/hub/setting/https/enable" : "/hub/setting/https/disable",
      );
      resource.setData(next);
      if (isForwarded) {
        setSwitchedTo(
          isOn
            ? {
                isOn,
                port: next.https_listen_port,
                origin: httpsOrigin(next.https_listen_port),
              }
            : {
                isOn,
                port: next.listen_port,
                origin: httpOrigin(next.listen_port),
              },
        );
      } else if (isOn && !isOnHttps) {
        window.location.replace(
          `${httpsOrigin(next.https_listen_port)}${here()}`,
        );
      } else if (!isOn && isOnHttps) {
        window.location.replace(`${httpOrigin(next.listen_port)}${here()}`);
      }
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const regenerate = async () => {
    setIsBusy(true);
    setError(null);
    try {
      const next = await apiPost<PanelHttpsResetView>(
        "/hub/setting/https/authority/reset",
      );
      resource.setData(next);
      downloadAuthority(next.authority_der, next.authority_file_name);
      setIsRegenerated(true);
      setIsAwaitingInstall(true);
      setTrust("untrusted");
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsBusy(false);
    }
  };

  const askRegenerate = () =>
    confirm.ask({
      title: t("ui.settings.https_regenerate_title"),
      body: t("ui.settings.https_regenerate_body"),
      confirmLabel: t("ui.settings.https_regenerate_confirm"),
      onConfirm: () => void regenerate(),
    });

  const isTrustedHere =
    isOnHttps || isForwarded || (trust === "trusted" && !isRegenerated);

  return (
    <section className="card">
      <div className="card_header">
        <div className="card_title">
          <h2>{t("ui.settings.https_title")}</h2>
        </div>
        <Icon name="lock" size={15} />
      </div>

      {resource.error !== null ? (
        <ErrorPanel
          title={t("ui.settings.https_unavailable")}
          message={resource.error}
          onRetry={resource.reload}
        />
      ) : view === null ? (
        <div className="skeleton" style={{ height: 320 }} />
      ) : (
        <div className="settings_form">
          <p className="muted">{t("ui.settings.https_hint")}</p>

          <dl className="https_status">
            <StatusLine
              label={t("ui.settings.https_addresses")}
              value={<Addresses view={view} isOnHttps={isOnHttps} />}
            />
            <StatusLine
              label={t("ui.settings.https_fingerprint")}
              value={
                view.has_authority
                  ? fingerprintPairs(view.authority_fingerprint)
                  : t("ui.settings.https_no_authority")
              }
              isMono
            />
            <StatusLine
              label={t("ui.settings.https_created")}
              value={formatMoment(view.authority_created_at)}
            />
            <StatusLine
              label={t("ui.settings.https_names")}
              value={
                view.leaf_names.length > 0 ? view.leaf_names.join(", ") : "—"
              }
              isMono
            />
            <StatusLine
              label={t("ui.settings.https_issued")}
              value={formatMoment(view.leaf_issued_at)}
            />
            <StatusLine
              label={t("ui.settings.https_expires")}
              value={formatMoment(view.leaf_expires_at)}
            />
            <StatusLine
              label={t("ui.settings.https_renewed")}
              value={
                view.renewed_at === null
                  ? t("ui.settings.https_renewed_none")
                  : formatMoment(view.renewed_at)
              }
            />
          </dl>

          {view.has_authority && (
            <AuthorityInstall fileName={view.authority_file_name} />
          )}

          <div className="apply_bar">
            {error !== null && (
              <div className="notice notice--error">
                <Icon name="alert" size={15} />
                <div className="notice_body">{error}</div>
              </div>
            )}
            {switchedTo !== null && (
              <div className="notice notice--ok">
                <Icon name="check" size={15} />
                <div className="notice_body">
                  {t(
                    switchedTo.isOn
                      ? "ui.settings.https_forwarded_on"
                      : "ui.settings.https_forwarded_off",
                    { port: switchedTo.port },
                  )}
                  <a href={`${switchedTo.origin}${here()}`}>
                    {t("ui.settings.https_open_address", {
                      address: switchedTo.origin,
                    })}
                  </a>
                </div>
              </div>
            )}
            <div className="apply_bar_row">
              <span className="field_hint">
                {isForwarded && !isRegenerated
                  ? view.is_https_enabled
                    ? t("ui.settings.https_forwarded_disable", {
                        port: view.listen_port,
                      })
                    : t("ui.settings.https_forwarded", {
                        port: view.https_listen_port,
                      })
                  : t(hintKey(view, isOnHttps, trust, isRegenerated))}
              </span>
              <div className="button_row">
                <button
                  type="button"
                  className="button button--danger"
                  disabled={isBusy || isOnHttps}
                  onClick={askRegenerate}
                >
                  <Icon name="refresh" size={14} />
                  {t("ui.settings.https_regenerate")}
                </button>
                {view.has_authority ? (
                  <a
                    className="button"
                    href={AUTHORITY_DOWNLOAD_PATH}
                    download={view.authority_file_name}
                    onClick={() => setIsAwaitingInstall(true)}
                  >
                    <Icon name="download" size={14} />
                    {t("ui.authority.install")}
                  </a>
                ) : (
                  <button type="button" className="button" disabled>
                    <Icon name="download" size={14} />
                    {t("ui.authority.install")}
                  </button>
                )}
                <button
                  type="button"
                  className="button button--primary"
                  disabled={
                    isBusy || (!view.is_https_enabled && !isTrustedHere)
                  }
                  onClick={() => void switchScheme(!view.is_https_enabled)}
                >
                  <Icon name="lock" size={14} />
                  {view.is_https_enabled
                    ? t("ui.settings.https_disable")
                    : t("ui.settings.https_enable")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {confirm.modal}
    </section>
  );
}

function StatusLine({
  label,
  value,
  isMono = false,
}: {
  label: string;
  value: ReactNode;
  isMono?: boolean;
}) {
  return (
    <div className="https_status_line">
      <dt>{label}</dt>
      <dd className={isMono ? "https_status_value--mono" : undefined}>
        {value}
      </dd>
    </div>
  );
}

/** Both of the panel's addresses on this host, the one in use marked. */
function Addresses({
  view,
  isOnHttps,
}: {
  view: PanelHttpsView;
  isOnHttps: boolean;
}) {
  const addresses = [
    { origin: httpOrigin(view.listen_port), isCurrent: !isOnHttps },
    { origin: httpsOrigin(view.https_listen_port), isCurrent: isOnHttps },
  ];
  return (
    <div className="https_addresses">
      {addresses.map((address) => (
        <span key={address.origin} className="https_address">
          <span className="https_status_value--mono">{address.origin}</span>
          {address.isCurrent && (
            <span className="badge badge--accent">
              {t("ui.settings.https_current")}
            </span>
          )}
        </span>
      ))}
    </div>
  );
}

/** The line left of the buttons: what stands between this page and HTTPS. */
function hintKey(
  view: PanelHttpsView,
  isOnHttps: boolean,
  trust: Trust,
  isRegenerated: boolean,
): string {
  if (isRegenerated) {
    return "ui.settings.https_regenerated";
  }
  if (isOnHttps) {
    return view.is_https_enabled
      ? "ui.settings.https_turn_off_first"
      : "ui.settings.https_open_over_http";
  }
  if (trust === "checking") {
    return "ui.settings.https_checking";
  }
  return trust === "trusted"
    ? "ui.settings.https_trusted"
    : "ui.settings.https_untrusted";
}

/** Whether this browser completes a request to the HTTPS port. */
async function isTrusted(origin: string): Promise<boolean> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    // no-cors: the answer is unreadable across origins, and a completed
    // request is the whole answer; a certificate the browser rejects fails it.
    await fetch(`${origin}${PROBE_PATH}`, {
      mode: "no-cors",
      cache: "no-store",
      signal: controller.signal,
    });
    return true;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timer);
  }
}

/** Hand the browser the new authority from the answer that carried it. */
function downloadAuthority(derBase64: string, fileName: string): void {
  const bytes = Uint8Array.from(atob(derBase64), (character) =>
    character.charCodeAt(0),
  );
  const url = URL.createObjectURL(
    new Blob([bytes], { type: AUTHORITY_MEDIA_TYPE }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** The port this page is on, from its own address. */
function pagePort(isOnHttps: boolean): number {
  const { port } = window.location;
  if (port !== "") {
    return Number(port);
  }
  return isOnHttps ? HTTPS_SCHEME_PORT : HTTP_SCHEME_PORT;
}

/** This page's path, query and fragment, kept across a scheme change. */
function here(): string {
  const { pathname, search, hash } = window.location;
  return `${pathname}${search}${hash}`;
}

/** A hex fingerprint as colon-separated uppercase pairs, as systems show it. */
function fingerprintPairs(hex: string): string {
  return (hex.toUpperCase().match(/../g) ?? []).join(":");
}

function formatMoment(isoTimestamp: string | null): string {
  return isoTimestamp === null ? "—" : new Date(isoTimestamp).toLocaleString();
}
