import {
  cacheShareOf,
  formatShare,
  successShareOf,
  tokensOf,
} from "../ai_usage";
import { formatCompact } from "../format_compact";
import { formatTimeAgo } from "../format_duration";
import { t, useLanguage } from "../i18n";
import type { AiUsageKey } from "../api_types";

/**
 * The per-key activity table on the AI page: which machine is doing the
 * talking, one row per client key. Styles live in ai_page.css beside the
 * page.
 */

interface AiUsageKeysProps {
  keys: AiUsageKey[];
}

export function AiUsageKeys({ keys }: AiUsageKeysProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  if (keys.length === 0) {
    return (
      <div className="placeholder">
        <span>{t("ui.usage.keys_empty")}</span>
        <span className="faint">{t("ui.usage.keys_empty_hint")}</span>
      </div>
    );
  }

  const sorted = [...keys].sort((a, b) => b.requests - a.requests);

  return (
    <div className="usage_table_scroll">
      <table className="usage_table">
        <thead>
          <tr>
            <th>{t("ui.usage.header_key")}</th>
            <th className="num">{t("ui.usage.header_requests")}</th>
            <th className="num">{t("ui.usage.header_success")}</th>
            <th className="num">{t("ui.usage.header_tokens")}</th>
            <th className="num">{t("ui.usage.header_cache")}</th>
            <th>{t("ui.usage.header_first_seen")}</th>
            <th>{t("ui.usage.header_last_seen")}</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((key) => (
            <tr key={key.key_id}>
              <td>
                <div className="usage_name">{key.name}</div>
                <span
                  className={`usage_device ${key.client_name === null ? "faint" : ""}`}
                >
                  {key.client_name ?? t("ui.usage.no_client")}
                </span>
              </td>
              <td className="num">
                <div className="mono">{formatCompact(key.requests)}</div>
                <div className="usage_split mono">
                  <span className="usage_ok">
                    {formatCompact(key.requests - key.failed)}
                  </span>
                  <span className="faint">/</span>
                  <span className={key.failed > 0 ? "usage_bad" : "faint"}>
                    {formatCompact(key.failed)}
                  </span>
                </div>
              </td>
              <td className="num mono">{formatShare(successShareOf(key))}</td>
              <td className="num mono">{formatCompact(tokensOf(key))}</td>
              <td className="num mono">{formatShare(cacheShareOf(key))}</td>
              <td className="mono">{formatTimeAgo(key.first_seen_at)}</td>
              <td className="mono">{formatTimeAgo(key.last_seen_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
