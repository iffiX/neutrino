import type { ComponentType } from "react";

/**
 * The panel's edition table: the one way the rest of the panel reaches a
 * page the mainland edition leaves out.
 *
 * The mainland tree is this one with the proxy's files deleted. Each is
 * found here by `import.meta.glob` over its own file, and a file the glob
 * does not find adds nothing: no route, no sidebar row, no screen.
 */

/** The features a tree may leave out, by the names the hub uses. */
export type EditionFeature = "proxy";

interface ProxyPageModule {
  ProxyPage: ComponentType;
}

const proxyPages = import.meta.glob<ProxyPageModule>("./pages/proxy_page.tsx", {
  eager: true,
});

/** The Proxy page, or null in a tree without the proxy. */
export const ProxyPage: ComponentType | null =
  Object.values(proxyPages)[0]?.ProxyPage ?? null;

/**
 * Whether this tree carries a left-out feature.
 *
 * Args:
 *   name: `proxy`.
 *
 * Returns:
 *   True when the feature's own file is in the tree.
 */
export function hasFeature(name: EditionFeature): boolean {
  return name === "proxy" && ProxyPage !== null;
}
