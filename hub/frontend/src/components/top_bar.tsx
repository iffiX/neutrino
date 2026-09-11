import { useLocation } from "react-router-dom";

import { StatusDot } from "./status_dot";
import type { StatusTone } from "./status_dot";
import { computeActiveExits, primaryExitTag } from "../active_exits";
import { formatCompact } from "../format_compact";
import { t, useLanguage } from "../i18n";
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

const SOCKET_KEYS: Record<string, string> = {
  open: "state.live",
  connecting: "state.connecting",
  closed: "state.offline",
};

/** What each mode is called wherever a person reads it. */
const MODE_KEYS: Record<string, string> = {
  server: "ui.shell.mode_server",
  side_gateway: "ui.shell.mode_side_gateway",
  router: "ui.shell.mode_router",
};

/** The chip keys the strip names, which are the API's own words. */
const CHIP_NETWORK_KEY = "ui.shell.chip_network";
const CHIP_PROXY_KEY = "ui.shell.chip_proxy";
const CHIP_AI_KEY = "ui.shell.chip_ai";
const CHIP_DEVICES_KEY = "ui.shell.chip_devices";

/** What a chip shows when nothing has answered yet. */
const CHIP_NOTHING = "—";

export function TopBar() {
  // Redrawn when the panel's language changes.
  useLanguage();
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
          {currentItem === undefined
            ? t("ui.shell.page_fallback")
            : t(currentItem.labelKey)}
        </span>
        <span className="top_bar_page_sub">
          {currentItem === undefined ? "" : t(currentItem.descriptionKey)}
        </span>
      </div>

      <div className="top_bar_meta">
        <span className="top_bar_chip">
          <StatusDot
            tone={SOCKET_TONES[status] ?? "idle"}
            isPulsing={status === "open"}
          />
          <span className="top_bar_chip_value">
            {SOCKET_KEYS[status] === undefined
              ? status
              : t(SOCKET_KEYS[status])}
          </span>
        </span>

        <span className="top_bar_chip">
          <span className="top_bar_chip_key">{t(CHIP_NETWORK_KEY)}</span>
          <span className="top_bar_chip_value">{describeMode(mode)}</span>
        </span>

        <span className={`top_bar_chip top_bar_chip--${proxy.tone}`}>
          <span className="top_bar_chip_key">{t(CHIP_PROXY_KEY)}</span>
          <span className="top_bar_chip_value">{proxy.label}</span>
        </span>

        <span className="top_bar_chip">
          <span className="top_bar_chip_key">{t(CHIP_AI_KEY)}</span>
          <span className="top_bar_chip_value">{describeAi(ai.data)}</span>
        </span>

        <span className="top_bar_chip">
          <span className="top_bar_chip_key">{t(CHIP_DEVICES_KEY)}</span>
          <span className="top_bar_chip_value">
            {describeAgents(agentCount)}
          </span>
        </span>
      </div>
    </header>
  );
}

/** What the network chip says: the mode this machine is in. */
function describeMode(mode: string | null): string {
  if (mode === null) {
    return CHIP_NOTHING;
  }
  const key = MODE_KEYS[mode];
  return key === undefined ? mode : t(key);
}

/** What the devices chip says: how many machines report in. */
function describeAgents(count: number | null): string {
  if (count === null) {
    return CHIP_NOTHING;
  }
  return count === 1
    ? t("ui.shell.agents_one")
    : t("ui.shell.agents", { count });
}

/**
 * What the AI chip says: what the gateway has served today.
 *
 * The count falls back to how many providers are behind the gateway while
 * usage is absent or zero — a hub that served nothing today has nothing to
 * report but is still worth a thumbnail.
 */
function describeAi(status: CliproxyApiStatusView | null): string {
  if (status === null) {
    return CHIP_NOTHING;
  }
  if (!status.is_installed) {
    return t("state.not_installed");
  }
  if (!status.is_active) {
    return t("state.stopped");
  }
  const tokensToday = status.tokens_today ?? 0;
  if (tokensToday > 0) {
    return t("ui.shell.ai_tokens_today", { count: formatCompact(tokensToday) });
  }
  const count = status.enabled_provider_count;
  return count === 1
    ? t("ui.shell.ai_providers_one")
    : t("ui.shell.ai_providers", { count });
}
