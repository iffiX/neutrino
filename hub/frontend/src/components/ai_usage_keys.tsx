import {
  cacheShareOf,
  formatShare,
  successShareOf,
  tokensOf,
} from "../ai_usage";
import { formatCompact } from "../format_compact";
import { formatTimeAgo } from "../format_duration";
import type { AiUsageKey } from "../api_types";

/**
 * The per-key activity table on the AI page: which machine is doing the
 * talking, one row per client key. Styles live in ai_page.css beside the
 * page.
 */

const WORDING = {
  headerKey: "Key",
  headerRequests: "Requests",
  headerSuccess: "Success",
  headerTokens: "Tokens",
  headerCache: "Cache",
  headerFirstSeen: "First seen",
  headerLastSeen: "Last seen",
  noDevice: "no device",
  empty: "No key activity yet",
  emptyHint: "A key shows up here once its machine talks to the gateway.",
} as const;

interface AiUsageKeysProps {
  keys: AiUsageKey[];
}

export function AiUsageKeys({ keys }: AiUsageKeysProps) {
  if (keys.length === 0) {
    return (
      <div className="placeholder">
        <span>{WORDING.empty}</span>
        <span className="faint">{WORDING.emptyHint}</span>
      </div>
    );
  }

  const sorted = [...keys].sort((a, b) => b.requests - a.requests);

  return (
    <div className="usage_table_scroll">
      <table className="usage_table">
        <thead>
          <tr>
            <th>{WORDING.headerKey}</th>
            <th className="num">{WORDING.headerRequests}</th>
            <th className="num">{WORDING.headerSuccess}</th>
            <th className="num">{WORDING.headerTokens}</th>
            <th className="num">{WORDING.headerCache}</th>
            <th>{WORDING.headerFirstSeen}</th>
            <th>{WORDING.headerLastSeen}</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((key) => (
            <tr key={key.key_id}>
              <td>
                <div className="usage_name">{key.name}</div>
                <span
                  className={`usage_device ${key.device_name === null ? "faint" : ""}`}
                >
                  {key.device_name ?? WORDING.noDevice}
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
