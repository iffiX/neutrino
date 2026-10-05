import { t } from "./i18n";
import { useApiResource } from "./use_api_resource";
import type { PanelSettings } from "./api_types";

/**
 * The hub's addresses as this page can name them.
 *
 * A page opened on one of the panel's own ports names the hub by the host in
 * its address bar. A page on another port came through a forward, where that
 * host is not where the hub's ports are, so the hub is named by a
 * placeholder. A forward to a loopback host is a client's Panel button: the
 * client opens `panel-<hub id>.localhost` or `127.0.0.1` on a port of its
 * own. Any other host on a foreign port is a port forward, such as a
 * router's.
 */

const HTTP_SCHEME_PORT = 80;
const HTTPS_SCHEME_PORT = 443;
const LOOPBACK_HOSTS = ["127.0.0.1", "localhost", "[::1]"];
const LOOPBACK_SUFFIX = ".localhost";

/** The panel's two ports, as the hub reports them. */
type PanelPorts = Pick<PanelSettings, "listen_port" | "https_listen_port">;

/** Whether this page is on a port other than the panel's own for its scheme. */
export function isOffPanelPort(ports: PanelPorts | null): boolean {
  if (ports === null) {
    return false;
  }
  const isOnHttps = window.location.protocol === "https:";
  const { port } = window.location;
  const pagePort =
    port !== ""
      ? Number(port)
      : isOnHttps
        ? HTTPS_SCHEME_PORT
        : HTTP_SCHEME_PORT;
  return pagePort !== (isOnHttps ? ports.https_listen_port : ports.listen_port);
}

/** Whether this page came through a client's Panel button. */
export function isThroughClient(ports: PanelPorts | null): boolean {
  const { hostname } = window.location;
  const isLoopbackHost =
    LOOPBACK_HOSTS.includes(hostname) || hostname.endsWith(LOOPBACK_SUFFIX);
  return isLoopbackHost && isOffPanelPort(ports);
}

/** The hub's host for an address: the page's own, or the placeholder. */
export function hubHost(isForwarded: boolean): string {
  return isForwarded ? t("ui.api.hub_address") : window.location.hostname;
}

/** The hub's host, from the panel's ports read once. */
export function useHubHost(): string {
  const settings = useApiResource<PanelSettings>("/hub/setting");
  return hubHost(isOffPanelPort(settings.data));
}

export function httpOrigin(port: number, host: string): string {
  const suffix = port === HTTP_SCHEME_PORT ? "" : `:${port}`;
  return `http://${host}${suffix}`;
}

export function httpsOrigin(port: number, host: string): string {
  const suffix = port === HTTPS_SCHEME_PORT ? "" : `:${port}`;
  return `https://${host}${suffix}`;
}
