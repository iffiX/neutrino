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
 * The exit half is one name: the hub pins one exit, and the frame carries its
 * tag for the chip to read.
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
  const exit = nodeIdFromTag(frame.exit_tag) ?? frame.exit_tag;
  return { scope, exit, label: `${scope} → ${exit}`, tone: "proxy" };
}
