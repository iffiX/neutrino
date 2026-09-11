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
  port_count: number;
  is_wire_needed: boolean;
  /** Whether this mode sets the machine's addresses, or answers on what is
   * already there. */
  is_addressing_owned: boolean;
  /** Whether this shape costs something the machine cannot be checked for. */
  has_caution: boolean;
}

/** One thing installing a module does that is agreed to first. */
export interface SetupConsent {
  code: string;
  params: Record<string, string | number>;
}

/** One optional module the first run can install. */
export interface SetupService {
  name: string;
  is_installed: boolean;
  /** What installing it does beyond installing it. */
  consents: SetupConsent[];
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
}

/** One installation step, as the terminal reports it. */
export interface SetupStep {
  /** What the step is; the page words it from its own catalog. */
  id: string;
  /** The values that wording names. */
  params: Record<string, string | number>;
  /** Three and no more: a step is running, it succeeded, or it did not.
   * "Already so" is a note beside a step that succeeded. */
  status: "running" | "done" | "failed";
  /** What the step itself reported, in the terminal's own words. */
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
  /** The language the panel is drawn in, asked first. */
  language: string;
  password: string;
  vault_passphrase: string;
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

/** The route asked for to tell the two servers apart. Any of them would do;
 * this one is the wizard's first call anyway. */
const SETUP_PROBE_ROUTE = "context";

/** The token this page was opened with, `""` when it was opened without one. */
export function setupToken(): string {
  return new URLSearchParams(window.location.search).get("token") ?? "";
}

/**
 * Whether this page is being served by `nhub setup` rather than by the panel.
 *
 * Asked of the server rather than inferred from the address, because the two
 * serve the same bundle and a link without its token is the one case where
 * guessing gets it wrong: the panel's own login card would be drawn over a
 * box that has no panel yet, and its first request would fail on a route that
 * does not exist.
 */
export async function isSetupWaiting(): Promise<boolean> {
  try {
    const response = await fetch(`/api/setup/${SETUP_PROBE_ROUTE}`);
    // 404 is the panel, which has no such route. Anything else — 200 with a
    // good token, 403 without one — is the wizard's own server answering.
    return response.status !== 404;
  } catch {
    // Nothing answered at all, which is not something the setup server does.
    return false;
  }
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
