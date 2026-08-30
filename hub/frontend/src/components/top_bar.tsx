import { useLocation } from "react-router-dom";

import { StatusDot } from "./status_dot";
import type { StatusTone } from "./status_dot";
import { computeActiveExits, primaryExitTag } from "../active_exits";
import { describeProxy } from "../proxy_status";
import type { NetworkView } from "../api_types";
import { NAV_ITEMS } from "../nav_items";
import { useApiResource } from "../use_api_resource";
import { useLiveStats } from "../use_live_stats";

import "./top_bar.css";

/**
 * The always-visible status strip above the page body.
 *
 * It answers what someone opens this panel to ask, in the order traffic runs
 * through the box: is the panel still talking to the gateway, what the uplink
 * holds, how many machines are behind it, and where their traffic is going.
 * None of it should need a particular page to be open.
 */

const SOCKET_TONES: Record<string, StatusTone> = {
  open: "ok",
  connecting: "warn",
  closed: "error",
};

const SOCKET_LABELS: Record<string, string> = {
  open: "live",
  connecting: "connecting",
  closed: "offline",
};

export function TopBar() {
  const location = useLocation();
  const { frames, latestFrame, status } = useLiveStats();
  // The socket takes a moment to deliver its first frame. Reading the
  // interfaces once over HTTP as well means the strip shows the real address
  // immediately instead of claiming there is none, which reads as a fault.
  const network = useApiResource<NetworkView>("/network");

  const currentItem = NAV_ITEMS.find((item) =>
    item.path === "/"
      ? location.pathname === "/"
      : location.pathname.startsWith(item.path),
  );
  const activeExit = primaryExitTag(computeActiveExits(frames));
  const wanAddress =
    latestFrame?.wan_address ?? firstUplinkAddress(network.data);
  const proxy = describeProxy(latestFrame, activeExit);
  const deviceCount = latestFrame?.lan_device_count ?? null;

  return (
    <header className="top_bar">
      <div className="top_bar_page">
        <span className="top_bar_page_title">
          {currentItem?.label ?? "Panel"}
        </span>
        <span className="top_bar_page_sub">
          {currentItem?.description ?? ""}
        </span>
      </div>

      <div className="top_bar_meta">
        <span className="top_bar_chip">
          <StatusDot
            tone={SOCKET_TONES[status] ?? "idle"}
            isPulsing={status === "open"}
          />
          <span className="top_bar_chip_value">
            {SOCKET_LABELS[status] ?? status}
          </span>
        </span>

        <span
          className={`top_bar_chip ${wanAddress === null ? "top_bar_chip--offline" : ""}`}
        >
          <span className="top_bar_chip_key">wan</span>
          <span className="top_bar_chip_value">
            {wanAddress ?? "no address"}
          </span>
        </span>

        <span className="top_bar_chip">
          <span className="top_bar_chip_key">lan</span>
          <span className="top_bar_chip_value">
            {deviceCount === null
              ? "—"
              : `${deviceCount} device${deviceCount === 1 ? "" : "s"}`}
          </span>
        </span>

        <span className={`top_bar_chip top_bar_chip--${proxy.tone}`}>
          <span className="top_bar_chip_key">proxy</span>
          <span className="top_bar_chip_value">{proxy.label}</span>
        </span>
      </div>
    </header>
  );
}

/**
 * The address the strip shows as "wan".
 *
 * With more than one uplink there is no single answer, so it names the first
 * one holding an address — the same one the gateway itself reports.
 */
function firstUplinkAddress(view: NetworkView | null): string | null {
  if (view === null) {
    return null;
  }
  const uplink = view.interfaces.find(
    (entry) =>
      entry.settings.role === "wan" && entry.link.ipv4_address !== null,
  );
  return uplink?.link.ipv4_address ?? null;
}
