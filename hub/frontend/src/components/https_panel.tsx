import { useState } from "react";

import { AuthorityInstall } from "./authority_install";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { MovingOverlay } from "./panel_port_panel";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import type { PanelHttpsView } from "../api_types";

import "./https_panel.css";

/**
 * Whether the panel speaks HTTPS, and the certificates behind it.
 *
 * Turning HTTPS on or off restarts the panel onto the other scheme, so it is
 * one press with no draft. The authority installs while HTTPS is off too, so
 * a browser trusts the panel before the first HTTPS page loads. The served
 * certificate follows the box's addresses by itself; regenerating replaces
 * the authority, which every browser then installs again.
 */

/** How long a scheme change waits before it goes to the new origin anyway. */
const SCHEME_FOLLOW_MS = 8000;
/** Where the authority downloads, with or without a session. */
const AUTHORITY_DOWNLOAD_PATH = "/api/hub/setting/https/authority";

export function HttpsPanel() {
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<PanelHttpsView>("/hub/setting/https");
  const confirm = useConfirm();
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [destination, setDestination] = useState<string | null>(null);
  const view = resource.data;

  const switchScheme = async (isOn: boolean) => {
    setIsBusy(true);
    setError(null);
    try {
      const next = await apiPost<PanelHttpsView>(
        isOn ? "/hub/setting/https/enable" : "/hub/setting/https/disable",
      );
      resource.setData(next);
      setDestination(originOf(isOn));
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
      resource.setData(
        await apiPost<PanelHttpsView>("/hub/setting/https/authority/reset"),
      );
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
        <div className="skeleton" style={{ height: 220 }} />
      ) : (
        <div className="settings_form">
          <p className="muted">{t("ui.settings.https_hint")}</p>

          <dl className="https_status">
            <StatusLine
              label={t("ui.settings.https_scheme")}
              value={view.is_https_enabled ? "HTTPS" : "HTTP"}
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

          {error !== null && (
            <div className="notice notice--error">
              <Icon name="alert" size={15} />
              <div className="notice_body">{error}</div>
            </div>
          )}

          <div className="settings_actions">
            <button
              type="button"
              className="button button--primary"
              disabled={isBusy || destination !== null}
              onClick={() => void switchScheme(!view.is_https_enabled)}
            >
              <Icon name="lock" size={14} />
              {view.is_https_enabled
                ? t("ui.settings.https_disable")
                : t("ui.settings.https_enable")}
            </button>
            {view.has_authority && (
              <button
                type="button"
                className="button button--danger"
                disabled={isBusy || destination !== null}
                onClick={askRegenerate}
              >
                <Icon name="refresh" size={14} />
                {t("ui.settings.https_regenerate")}
              </button>
            )}
          </div>

          {view.has_authority && (
            <AuthorityInstall
              href={AUTHORITY_DOWNLOAD_PATH}
              fileName={view.authority_file_name}
            />
          )}
        </div>
      )}

      {destination !== null && (
        <MovingOverlay destination={destination} goAfterMs={SCHEME_FOLLOW_MS} />
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
  value: string;
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

/** This page's origin on the other scheme, same host and port. */
function originOf(isHttps: boolean): string {
  const { hostname, port } = window.location;
  return `${isHttps ? "https" : "http"}://${hostname}${port ? `:${port}` : ""}`;
}

/** A hex fingerprint as colon-separated uppercase pairs, as systems show it. */
function fingerprintPairs(hex: string): string {
  return (hex.toUpperCase().match(/../g) ?? []).join(":");
}

function formatMoment(isoTimestamp: string | null): string {
  return isoTimestamp === null ? "—" : new Date(isoTimestamp).toLocaleString();
}
