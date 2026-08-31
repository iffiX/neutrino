/**
 * The wizard's own API, which exists only before there is a panel.
 *
 * `nhub setup` serves these while it waits for the questions to be answered
 * in a browser. Every call carries the one-time token the terminal printed;
 * there is no session yet, because the password is one of the answers.
 */

/** One of this machine's network ports, as the box sees it right now. */
export interface SetupInterface {
  name: string;
  is_wired: boolean;
  /** Address with its prefix, `""` when the port carries none. */
  ipv4_address: string;
  /** Whether a default route leaves by this port. */
  has_route: boolean;
  /** The next hop on this port, `""` when there is none. */
  upstream_gateway: string;
}

/** One shape this machine can be set up as. */
export interface SetupMode {
  key: string;
  summary: string;
  port_count: number;
  is_wire_needed: boolean;
  caution: string;
}

/** One optional module the first run can install. */
export interface SetupService {
  name: string;
  install_note: string;
  is_installed: boolean;
  /** What installing it does beyond installing it, one sentence each. */
  consents: string[];
}

/** What every question starts at. */
export interface SetupDefaults {
  address: string;
  prefix_len: number;
  lan_vlan_id: number;
  socks_proxy_port: number;
  socks_direct_port: number;
  listen_port: number;
}

/** The facts the questions are asked against. */
export interface SetupContext {
  interfaces: SetupInterface[];
  modes: SetupMode[];
  services: SetupService[];
  defaults: SetupDefaults;
  /** What the router screen says about the ports it does not ask for. */
  router_note: string;
}

/** One installation step, as the terminal reports it. */
export interface SetupStep {
  description: string;
  status: "running" | "done" | "skipped" | "failed";
  note: string;
}

/** How far the run has got. */
export interface SetupState {
  state: "asking" | "rejected" | "running" | "done" | "failed";
  message: string;
  panel_url: string;
  steps: SetupStep[];
  notes: string[];
}

/** The network half of the answers, exactly as `nhub setup --stdin` reads it. */
export interface SetupNetworkAnswers {
  mode: string;
  wan?: string[];
  lan?: string[];
  trunk?: string;
  address?: string;
  prefix_len?: number;
  upstream_gateway?: string;
  lan_vlan_id?: number;
}

/** The proxy half. An empty `links` is what skipping the screen means. */
export interface SetupProxyAnswers {
  links?: string[];
  is_local?: boolean;
  socks_proxy_port?: number;
  is_socks_direct_enabled?: boolean;
  socks_direct_port?: number;
}

/** Everything the wizard asks for. */
export interface SetupAnswers {
  password: string;
  network: SetupNetworkAnswers;
  proxy?: SetupProxyAnswers;
  services?: string[];
  listen_port?: number;
}

/** What the hub made of one share link. */
export interface SetupLinkReading {
  /** What the node is called, empty when the link could not be read. */
  name: string;
  /** Why it could not be read, empty when it could. */
  detail: string;
}

/** The token this page was opened with, `""` when it was opened without one. */
export function setupToken(): string {
  return new URLSearchParams(window.location.search).get("token") ?? "";
}

export async function readSetupContext(token: string): Promise<SetupContext> {
  return call<SetupContext>("context", token);
}

export async function readSetupState(token: string): Promise<SetupState> {
  return call<SetupState>("state", token);
}

export async function readSetupLink(
  token: string,
  link: string,
): Promise<SetupLinkReading> {
  return call<SetupLinkReading>("link", token, { link });
}

export async function sendSetupAnswers(
  token: string,
  answers: SetupAnswers,
): Promise<SetupState> {
  return call<SetupState>("answers", token, answers);
}

async function call<T>(
  route: string,
  token: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(
    `/api/setup/${route}?token=${encodeURIComponent(token)}`,
    body === undefined
      ? { method: "GET" }
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status}: ${detail}`);
  }
  return (await response.json()) as T;
}
