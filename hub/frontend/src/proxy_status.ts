import { nodeIdFromTag } from "./node_tag";
import type { StatsFrame } from "./api_types";

/**
 * What the status strip says traffic is doing.
 *
 * The strip answers one question — where is my traffic going — and the answer
 * has two halves: whose traffic the proxy is taking (the scope the gateway
 * reports from the applied ruleset), and which exit carries what it takes.
 *
 * The scope comes first because the modes differ in what there is to divert.
 * A server forwards nobody, so its proxy is its SOCKS ports; calling that
 * "direct" would claim traffic is bypassing a proxy every pointed application
 * is using, and calling it "proxied" would claim a diversion the mode never
 * poses. Off and unused are also different states: unused means the switch is
 * on and nothing at all is sent to the proxy, which is the page's cue to say
 * why rather than look healthy.
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
  label: string;
  tone: ProxyTone;
}

const SINGLE_EXIT_STRATEGY = "leastPing";

const SCOPE_PREFIXES: Record<string, string> = {
  ports: "ports",
  lan: "LAN",
  hub: "hub",
  lan_and_hub: "LAN+hub",
};

/**
 * Describe the current scope and exit for the status strip.
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
  if (frame.proxy_scope === "off") {
    return { label: "direct", tone: "direct" };
  }
  if (frame.proxy_scope === "unused") {
    return { label: "unused", tone: "direct" };
  }
  if (frame.enabled_node_count === 0) {
    return { label: "no exit", tone: "offline" };
  }
  const prefix = SCOPE_PREFIXES[frame.proxy_scope] ?? frame.proxy_scope;
  return {
    label: `${prefix} → ${describeExit(frame, activeExit)}`,
    tone: "proxy",
  };
}

/** The exit half of the label: one nameable node, or how traffic is spread. */
function describeExit(frame: StatsFrame, activeExit: string | null): string {
  if (frame.balancer_strategy !== SINGLE_EXIT_STRATEGY) {
    return `${frame.balancer_strategy} ×${frame.enabled_node_count}`;
  }
  if (activeExit === null) {
    return SINGLE_EXIT_STRATEGY;
  }
  return nodeIdFromTag(activeExit) ?? activeExit;
}
