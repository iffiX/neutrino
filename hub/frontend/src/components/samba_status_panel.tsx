import { ErrorPanel } from "./error_panel";
import { StatusDot } from "./status_dot";
import { apiPath } from "../api_client";
import { formatBytes } from "../format_bytes";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import type { SambaStatus } from "../api_types";

import "./samba_status_panel.css";

/**
 * Who is connected to a machine's file share now, and how full each
 * share's disk is, as the machine last reported. It reads again on each of
 * the machine's reports.
 */

interface SambaStatusPanelProps {
  deviceId: string;
  /** Where the file share answers: `/agent/module/samba`. */
  basePath: string;
}

export function SambaStatusPanel({
  deviceId,
  basePath,
}: SambaStatusPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const status = useApiResource<SambaStatus>(
    apiPath(`${basePath}/status`, { device_id: deviceId }),
    { invalidateOn: [{ type: HUB_EVENT_DEVICE_REPORT, key: deviceId }] },
  );
  const view = status.data;
  return (
    <section className="settings_group">
      <div className="settings_group_title">
        <h2>{t("ui.samba.status_title")}</h2>
      </div>
      {status.error !== null && view === null ? (
        <ErrorPanel message={status.error} onRetry={status.reload} />
      ) : view === null ? (
        <div className="skeleton" style={{ height: 60 }} />
      ) : (
        <>
          {view.sessions.length === 0 ? (
            <p className="field_hint">{t("ui.samba.status_empty")}</p>
          ) : (
            <div className="samba_sessions">
              {view.sessions.map((session, index) => (
                <div key={index} className="samba_session">
                  <span className="samba_session_user">
                    <StatusDot tone="ok" />
                    {session.username}
                  </span>
                  <span className="samba_session_from">
                    {session.hostname || session.remote_address}
                  </span>
                  <span className="samba_session_shares">
                    {session.shares.join(", ") || t("ui.samba.status_no_share")}
                  </span>
                </div>
              ))}
            </div>
          )}
          {view.disks.length > 0 && (
            <div className="samba_disks">
              {view.disks.map((disk) => {
                const used = disk.total_bytes - disk.free_bytes;
                const fraction =
                  disk.total_bytes > 0 ? used / disk.total_bytes : 0;
                return (
                  <div key={disk.share} className="samba_disk">
                    <div className="samba_disk_row">
                      <span>{disk.share}</span>
                      <span className="samba_disk_numbers">
                        {t("ui.samba.status_used", {
                          used: formatBytes(used),
                          total: formatBytes(disk.total_bytes),
                        })}
                      </span>
                    </div>
                    <div className="samba_disk_bar">
                      <div
                        className="samba_disk_fill"
                        style={{ width: `${Math.round(fraction * 100)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </section>
  );
}
