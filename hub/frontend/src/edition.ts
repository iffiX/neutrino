import type { ComponentType } from "react";

/**
 * The panel's edition table: the one way the rest of the panel reaches a
 * page or a card the mainland edition leaves out.
 *
 * The mainland tree is this one with the proxy's and NetBird's files
 * deleted. Each is found here by `import.meta.glob` over its own file, and
 * a file the glob does not find adds nothing: no route, no sidebar row, no
 * card, no screen.
 */

/** The features a tree may leave out, by the names the hub uses. */
export type EditionFeature = "proxy" | "netbird";

interface ProxyPageModule {
  ProxyPage: ComponentType;
}

interface NetbirdCardModule {
  NetbirdCard: ComponentType;
}

const proxyPages = import.meta.glob<ProxyPageModule>("./pages/proxy_page.tsx", {
  eager: true,
});
const netbirdCards = import.meta.glob<NetbirdCardModule>(
  "./components/netbird_card.tsx",
  { eager: true },
);

/** The Proxy page, or null in a tree without the proxy. */
export const ProxyPage: ComponentType | null =
  Object.values(proxyPages)[0]?.ProxyPage ?? null;

/** NetBird's card on the Access page, or null in a tree without NetBird. */
export const NetbirdCard: ComponentType | null =
  Object.values(netbirdCards)[0]?.NetbirdCard ?? null;

/**
 * Whether this tree carries a left-out feature.
 *
 * Args:
 *   name: `proxy` or `netbird`.
 *
 * Returns:
 *   True when the feature's own file is in the tree.
 */
export function hasFeature(name: EditionFeature): boolean {
  return name === "proxy" ? ProxyPage !== null : NetbirdCard !== null;
}
