import type { ComponentType } from "react";

import type { EditionFeature } from "../hub/frontend/src/edition";
import { ProxyPage as CarriedProxyPage } from "../hub/frontend/src/edition";
import type { DemoWindow } from "./demo_window";

/**
 * The panel's edition table in the demo. The build puts it in place of
 * `hub/frontend/src/edition.ts`. It reads the top window's edition once, as
 * this frame loads, so a frame is one edition for its whole life.
 */

const hub = (window.parent as DemoWindow).neutrinoDemoHub;
const IS_PROXY_CARRIED =
  CarriedProxyPage !== null && window.parent !== window && hub.isProxyCarried();

export const ProxyPage: ComponentType | null = IS_PROXY_CARRIED
  ? CarriedProxyPage
  : null;

export function hasFeature(name: EditionFeature): boolean {
  return name === "proxy" && IS_PROXY_CARRIED;
}
