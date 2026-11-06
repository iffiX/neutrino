import { nodeIdFromTag } from "./node_tag";
import { t } from "./i18n";
import type { StatsFrame } from "./api_types";

/**
 * Where traffic is going, in one line.
 *
 * One describer, two readers: the status strip's chip and the Proxy page's
 * own heading. They used to disagree — the page said on or off, which was
 * really "is a node enabled", while the strip said where traffic went — so a
 * server could read `on` beside `direct` and both be telling the truth about
 * different questions. There is one question now, and the chip is a thumbnail
 * of the page rather than a second opinion.
 *
 * The answer has two halves. The scope is whose traffic the proxy is taking,
 * which the gateway reports from the applied ruleset.
 *
 * The exit half is one name: the hub pins one exit, and the frame carries its
 * name for the chip to read.
 */

export type ProxyTone = "direct" | "proxy" | "offline" | "dead";

export interface ProxyStatus {
  /** The scope half: whose traffic is being taken, or why none is. */
  scope: string;
  /** The exit half, empty when nothing is being taken. */
  exit: string;
  /** Both halves as the strip shows them. */
  label: string;
  tone: ProxyTone;
}

const SCOPE_KEYS: Record<string, string> = {
  lan: "state.lan",
  overlay: "state.overlay",
  hub: "state.hub",
};
const SCOPE_JOINER = "+";

/** The `exit_tag` of a hub falling back to direct. */
export const DIRECT_EXIT_TAG = "direct";

/**
 * Whether a scope takes traffic and every enabled exit node is down.
 *
 * Args:
 *   frame: The newest stats frame.
 *
 * Returns:
 *   True while traffic sent to the proxy has no node to leave through.
 */
export function isEveryExitDown(frame: StatsFrame): boolean {
  const isScoped =
    frame.proxy_scope !== "off" && frame.proxy_scope !== "unused";
  // Every node is measured, switched off included, so the switched-off ones
  // come out first.
  const probes = frame.nodes.filter((probe) => probe.is_enabled);
  return (
    isScoped && probes.length > 0 && probes.every((probe) => !probe.is_alive)
  );
}

/**
 * Describe the current scope and exit.
 *
 * Args:
 *   frame: The newest stats frame, or null before the first arrives.
 *
 * Returns:
 *   The two halves, a label joining them, and the tone to show it in.
 */
export function describeProxy(frame: StatsFrame | null): ProxyStatus {
  if (frame === null) {
    return { scope: "—", exit: "", label: "—", tone: "offline" };
  }
  if (frame.proxy_scope === "off") {
    const direct = t("state.direct");
    return { scope: direct, exit: "", label: direct, tone: "direct" };
  }
  if (frame.proxy_scope === "unused") {
    const unused = t("state.unused");
    return { scope: unused, exit: "", label: unused, tone: "direct" };
  }
  const scope = frame.proxy_scope
    .split(SCOPE_JOINER)
    .map((part) => {
      const key = SCOPE_KEYS[part];
      return key === undefined ? part : t(key);
    })
    .join(SCOPE_JOINER);
  // Nothing to pin, or nothing pinned yet: either way no traffic has an exit.
  if (frame.enabled_node_count === 0 || frame.exit_tag === "") {
    const noExit = t("state.no_exit");
    return {
      scope,
      exit: noExit,
      label: `${scope} → ${noExit}`,
      tone: "offline",
    };
  }
  if (isEveryExitDown(frame) || frame.exit_tag === DIRECT_EXIT_TAG) {
    const down = t(
      frame.exit_tag === DIRECT_EXIT_TAG
        ? "state.exit_down_direct"
        : "state.exit_down_cut",
    );
    return { scope, exit: down, label: `${scope} → ${down}`, tone: "dead" };
  }
  const exit =
    frame.exit_name || (nodeIdFromTag(frame.exit_tag) ?? frame.exit_tag);
  return { scope, exit, label: `${scope} → ${exit}`, tone: "proxy" };
}
