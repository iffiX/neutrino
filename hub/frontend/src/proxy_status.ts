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
 * which the gateway reports from the applied ruleset; the modes differ in what
 * there is to divert, so a server's proxy is its SOCKS ports and saying
 * `direct` there would claim traffic is bypassing a proxy every pointed
 * application is using.
 *
 * The exit half keeps its old care. Under leastPing there is one exit and it
 * can be named — but only once one has actually carried bytes, because these
 * nodes sit within a few milliseconds of each other and naming the fastest
 * would cycle through names while nothing was happening. Under roundRobin and
 * random there deliberately is no single exit, so those say how traffic is
 * spread and over how many.
 */

export type ProxyTone = "direct" | "proxy" | "offline";

export interface ProxyStatus {
  /** The scope half: whose traffic is being taken, or why none is. */
  scope: string;
  /** The exit half, empty when nothing is being taken. */
  exit: string;
  /** Both halves as the strip shows them. */
  label: string;
  tone: ProxyTone;
}

const SINGLE_EXIT_STRATEGY = "leastPing";

const SCOPE_KEYS: Record<string, string> = {
  ports: "state.ports",
  lan: "state.lan",
  overlay: "state.overlay",
  hub: "state.hub",
};
const SCOPE_JOINER = "+";

/**
 * Describe the current scope and exit.
 *
 * Args:
 *   frame: The newest stats frame, or null before the first arrives.
 *   activeExit: The tag actually moving bytes, when one is, as measured
 *     across the retained frame window.
 *
 * Returns:
 *   The two halves, a label joining them, and the tone to show it in.
 */
export function describeProxy(
  frame: StatsFrame | null,
  activeExit: string | null,
): ProxyStatus {
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
  if (frame.enabled_node_count === 0) {
    const noExit = t("state.no_exit");
    return {
      scope,
      exit: noExit,
      label: `${scope} → ${noExit}`,
      tone: "offline",
    };
  }
  const exit = describeExit(frame, activeExit);
  return { scope, exit, label: `${scope} → ${exit}`, tone: "proxy" };
}

/** The exit half: one nameable node, or how traffic is spread. */
function describeExit(frame: StatsFrame, activeExit: string | null): string {
  if (frame.balancer_strategy !== SINGLE_EXIT_STRATEGY) {
    return `${frame.balancer_strategy} ×${frame.enabled_node_count}`;
  }
  if (activeExit === null) {
    return SINGLE_EXIT_STRATEGY;
  }
  return nodeIdFromTag(activeExit) ?? activeExit;
}
