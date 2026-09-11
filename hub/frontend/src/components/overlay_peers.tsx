import { StatusDot } from "./status_dot";
import { formatBytes } from "../format_bytes";
import { t, useLanguage } from "../i18n";

import "./overlay_peers.css";

/**
 * Who else is on the overlay, drawn the same way whichever engine runs it.
 *
 * The engines report the same four things about a peer in their own words —
 * where it is, how it is reached, how far away it is, and how much has passed
 * — so the row is one shape and each engine's section fills it in. A person
 * reading two overlays should not have to learn two tables.
 */

/** How a peer is reached, as the row draws it. */
export const OVERLAY_LINK_DIRECT = "direct";
export const OVERLAY_LINK_RELAYED = "relayed";

export interface OverlayPeerRow {
  key: string;
  name: string;
  address: string;
  /** local, direct, relayed or unknown. */
  link: string;
  /** The engine's own word for the path: a protocol, a relay, an age. */
  detail: string;
  latencyMs: number | null;
  /** Share of packets lost, 0 to 1, or null where the engine reports none. */
  lossRatio: number | null;
  rxBytes: number | null;
  txBytes: number | null;
  isConnected: boolean;
}

interface OverlayPeersProps {
  peers: OverlayPeerRow[];
  emptyHint: string;
}

export function OverlayPeers({ peers, emptyHint }: OverlayPeersProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  if (peers.length === 0) {
    return <p className="field_hint">{emptyHint}</p>;
  }
  return (
    <div className="overlay_peers">
      {peers.map((peer) => (
        <div key={peer.key} className="overlay_peer">
          <span className="overlay_peer_name">
            <StatusDot
              tone={peer.isConnected ? "ok" : "idle"}
              isPulsing={peer.isConnected}
            />
            <span className="overlay_peer_label">{peer.name}</span>
          </span>
          <span className="overlay_peer_address">{peer.address}</span>
          <span className="overlay_peer_link">
            {peer.isConnected && (
              <span
                className={`badge ${
                  peer.link === OVERLAY_LINK_DIRECT
                    ? "badge--ok"
                    : "badge--warn"
                }`}
              >
                {peer.link === OVERLAY_LINK_DIRECT
                  ? t("state.direct")
                  : t("state.relayed")}
              </span>
            )}
          </span>
          <span className="overlay_peer_detail">{peer.detail}</span>
          <span className="overlay_peer_loss">
            {peer.lossRatio !== null && peer.lossRatio > 0
              ? t("ui.overlay.peer_loss", {
                  share: (peer.lossRatio * 100).toFixed(1),
                })
              : ""}
          </span>
          <span className="overlay_peer_traffic">
            {peer.rxBytes !== null || peer.txBytes !== null
              ? `↓ ${formatBytes(peer.rxBytes ?? 0)}  ↑ ${formatBytes(
                  peer.txBytes ?? 0,
                )}`
              : ""}
          </span>
          <span className="overlay_peer_latency">
            {peer.latencyMs === null
              ? ""
              : `${
                  peer.latencyMs < 10
                    ? peer.latencyMs.toFixed(1)
                    : Math.round(peer.latencyMs)
                } ms`}
          </span>
        </div>
      ))}
    </div>
  );
}
