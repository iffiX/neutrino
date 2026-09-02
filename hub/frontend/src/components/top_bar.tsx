import { useLocation } from "react-router-dom";

import { StatusDot } from "./status_dot";
import type { StatusTone } from "./status_dot";
import { computeActiveExits, primaryExitTag } from "../active_exits";
import { describeProxy } from "../proxy_status";
import type { CliproxyApiStatusView, NetworkView } from "../api_types";
import { NAV_ITEMS } from "../nav_items";
import { useApiResource } from "../use_api_resource";
import { useLiveStats } from "../use_live_stats";

import "./top_bar.css";

/**
 * The always-visible status strip above the page body.
 *
 * One chip per core page, in the sidebar's own order, each a thumbnail of the
 * page behind it: what this machine is, where its traffic goes, what the AI
 * gateway is serving, how many devices report in. Opening the page is how you
 * get the rest; none of this should need a page open to be seen.
 *
 * It used to show `wan`, `lan` and `proxy`, which was a router's summary on a
 * panel with three modes: a server has no uplink to name and serves no
 * network, so two of the three chips answered questions that mode does not
 * pose. The mode itself was the one thing never shown, and every other chip's
 * meaning depends on it.
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

/** What each mode is called wherever a person reads it. */
const MODE_LABELS: Record<string, string> = {
  server: "server",
  side_gateway: "side gateway",
  router: "router",
};

export function TopBar() {
  const location = useLocation();
  const { frames, latestFrame, status } = useLiveStats();
  // The socket takes a moment to deliver its first frame. Reading the mode
  // once over HTTP as well means the strip names it immediately rather than
  // starting on a default that is wrong for most machines.
  const network = useApiResource<NetworkView>("/network");
  const ai = useApiResource<CliproxyApiStatusView>("/cliproxyapi");

  const currentItem = NAV_ITEMS.find((item) =>
    item.path === "/"
      ? location.pathname === "/"
      : location.pathname.startsWith(item.path),
  );
  const activeExit = primaryExitTag(computeActiveExits(frames));
  const proxy = describeProxy(latestFrame, activeExit);
  const mode = latestFrame?.network_mode ?? network.data?.mode ?? null;
  const agentCount = latestFrame?.agent_device_count ?? null;

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

        <span className="top_bar_chip">
          <span className="top_bar_chip_key">network</span>
          <span className="top_bar_chip_value">
            {mode === null ? "—" : (MODE_LABELS[mode] ?? mode)}
          </span>
        </span>

        <span className={`top_bar_chip top_bar_chip--${proxy.tone}`}>
          <span className="top_bar_chip_key">proxy</span>
          <span className="top_bar_chip_value">{proxy.label}</span>
        </span>

        <span className="top_bar_chip">
          <span className="top_bar_chip_key">ai</span>
          <span className="top_bar_chip_value">{describeAi(ai.data)}</span>
        </span>

        <span className="top_bar_chip">
          <span className="top_bar_chip_key">devices</span>
          <span className="top_bar_chip_value">
            {agentCount === null
              ? "—"
              : `${agentCount} agent${agentCount === 1 ? "" : "s"}`}
          </span>
        </span>
      </div>
    </header>
  );
}

/**
 * What the AI chip says.
 *
 * A placeholder for the number this chip is meant to carry: what the gateway
 * has served. CLIProxyAPI publishes only the chat endpoints — no usage, no
 * metrics — so a token count has to be counted here first, and until it is,
 * the honest thumbnail of that page is how many providers are behind it.
 */
function describeAi(status: CliproxyApiStatusView | null): string {
  if (status === null) {
    return "—";
  }
  if (!status.is_installed) {
    return "not installed";
  }
  if (!status.is_active) {
    return "stopped";
  }
  const count = status.enabled_provider_count;
  return `${count} provider${count === 1 ? "" : "s"}`;
}
