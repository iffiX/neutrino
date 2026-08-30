import { nodeIdFromTag } from "./node_tag";
import type { StatsFrame } from "./api_types";

/**
 * What the status strip says traffic is doing.
 *
 * The strip answers one question — where is my traffic going — and there are
 * genuinely several answers, which is why this is not a single string lookup.
 *
 * Three things it has to get right.
 *
 * "The proxy is off" and "the proxy is on but nothing has gone through it yet"
 * are different states and must not share a word. Applying anything restarts
 * xray, which zeroes the byte counters, so the second state follows every
 * apply; calling it `direct` there would claim traffic is bypassing a proxy
 * that is very much in the path.
 *
 * Under leastPing there is one exit and it can be named. Under roundRobin and
 * random there deliberately is not, and naming the busiest would pick a winner
 * where the whole point is that there is not one — so those say how traffic is
 * being spread and over how many.
 *
 * And it names an exit only once one has actually carried bytes. The obvious
 * alternative — show whichever node is answering fastest — flickers: these
 * nodes sit within a few milliseconds of each other and the ordering changes
 * between probes, so the strip would cycle through names every couple of
 * seconds while nothing at all was happening.
 */

export type ProxyTone = "direct" | "proxy" | "offline";

export interface ProxyStatus {
  label: string;
  tone: ProxyTone;
}

const SINGLE_EXIT_STRATEGY = "leastPing";

/**
 * Describe the current exit for the status strip.
 *
 * Args:
 *   frame: The newest stats frame, or null before the first arrives.
 *   activeExit: The tag actually moving bytes, when one is, as measured
 *     across the retained frame window.
 *
 * Returns:
 *   The label to show and the tone to show it in.
 */
export function describeProxy(
  frame: StatsFrame | null,
  activeExit: string | null,
): ProxyStatus {
  if (frame === null) {
    return { label: "—", tone: "offline" };
  }
  if (!frame.is_proxy_enabled) {
    return { label: "direct", tone: "direct" };
  }
  if (frame.enabled_node_count === 0) {
    return { label: "no exit", tone: "offline" };
  }
  if (frame.balancer_strategy !== SINGLE_EXIT_STRATEGY) {
    return {
      label: `${frame.balancer_strategy} ×${frame.enabled_node_count}`,
      tone: "proxy",
    };
  }
  if (activeExit === null) {
    return { label: SINGLE_EXIT_STRATEGY, tone: "proxy" };
  }
  return { label: nodeIdFromTag(activeExit) ?? activeExit, tone: "proxy" };
}
