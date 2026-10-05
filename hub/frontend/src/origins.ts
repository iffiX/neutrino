import { t } from "./i18n";
import { useApiResource } from "./use_api_resource";
import type { PanelSettings } from "./api_types";

/**
 * The hub's addresses as this page can name them.
 *
 * A page opened on one of the panel's own ports names the hub by the host in
 * its address bar. A page opened through a client's Panel button sits on a
 * port the client forwarded on its own machine, so that host is the client's
 * loopback; the hub is then named by a placeholder.
 */

const HTTP_SCHEME_PORT = 80;
const HTTPS_SCHEME_PORT = 443;

/** The panel's two ports, as the hub reports them. */
type PanelPorts = Pick<PanelSettings, "listen_port" | "https_listen_port">;

/** Whether this page is on a port other than the panel's own for its scheme. */
export function isThroughClient(ports: PanelPorts | null): boolean {
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

/** The hub's host for an address: the page's own, or the placeholder. */
export function hubHost(isClientPage: boolean): string {
  return isClientPage ? t("ui.api.hub_address") : window.location.hostname;
}

/** The hub's host, from the panel's ports read once. */
export function useHubHost(): string {
  const settings = useApiResource<PanelSettings>("/hub/setting");
  return hubHost(isThroughClient(settings.data));
}

export function httpOrigin(port: number, host: string): string {
  const suffix = port === HTTP_SCHEME_PORT ? "" : `:${port}`;
  return `http://${host}${suffix}`;
}

export function httpsOrigin(port: number, host: string): string {
  const suffix = port === HTTPS_SCHEME_PORT ? "" : `:${port}`;
  return `https://${host}${suffix}`;
}
