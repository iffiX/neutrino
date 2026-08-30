import { formatLogClock } from "../format_duration";
import type { DnsLogEntry } from "../api_types";

import "./dns_log_list.css";

/**
 * The live DNS query tail.
 *
 * The socket hook already caps its buffer, so the list renders everything it
 * holds — a few hundred rows of plain grid cells is cheaper than a virtualised
 * scroller and keeps the markup selectable. What each row is really for is the
 * outbound tag: it shows at a glance whether the split routing sent a name
 * direct or through an exit.
 */

const DIRECT_TAGS = new Set(["direct", "direct-dns", "local"]);

interface DnsLogListProps {
  entries: DnsLogEntry[];
}

export function DnsLogList({ entries }: DnsLogListProps) {
  if (entries.length === 0) {
    return (
      <div className="placeholder">
        <span>No DNS queries yet</span>
        <span className="faint">
          Queries appear here as soon as a LAN client resolves a name.
        </span>
      </div>
    );
  }

  return (
    <div className="dns_log_scroll">
      <div className="dns_log_list">
        {entries.map((entry, index) => (
          <div
            key={`${entry.timestamp}-${entry.domain}-${index}`}
            className={`dns_log_row ${index === 0 ? "dns_log_row--newest" : ""}`}
          >
            <span className="dns_log_time">
              {formatLogClock(entry.timestamp)}
            </span>
            <span className="dns_log_domain" title={entry.domain}>
              {entry.domain}
              <span className="dns_log_client"> · {entry.client}</span>
            </span>
            <span className={outboundClassName(entry.outbound)}>
              {entry.outbound ?? "pending"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function outboundClassName(outbound: string | null): string {
  if (outbound === null) {
    return "dns_log_outbound";
  }
  if (DIRECT_TAGS.has(outbound.toLowerCase())) {
    return "dns_log_outbound dns_log_outbound--direct";
  }
  return "dns_log_outbound dns_log_outbound--proxy";
}
