import type { DemoHub } from "./demo_hub";
import type { DemoWindow } from "./demo_window";

/**
 * The panel's transport in the demo. The top window's fake hub serves `fetch`
 * under `/api` and every `WebSocket`.
 */

const API_PREFIX = "/api";
const SOCKET_OPEN_MS = 30;

const hub: DemoHub = (window.parent as DemoWindow).neutrinoDemoHub;
const realFetch = window.fetch.bind(window);

/** A socket whose frames come from the fake hub. */
class DemoSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState = DemoSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  private stop: (() => void) | null = null;

  constructor(url: string) {
    const { pathname, search } = new URL(url);
    window.setTimeout(() => this.open(`${pathname}${search}`), SOCKET_OPEN_MS);
  }

  send(): void {}

  close(): void {
    this.stop?.();
    this.stop = null;
    this.readyState = DemoSocket.CLOSED;
  }

  private open(path: string): void {
    if (this.readyState !== DemoSocket.CONNECTING) {
      return;
    }
    this.readyState = DemoSocket.OPEN;
    this.onopen?.();
    this.stop = hub.openSocket(path, (frame) => {
      if (this.readyState === DemoSocket.OPEN) {
        this.onmessage?.({ data: JSON.stringify(frame) });
      }
    });
  }
}

async function demoFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const url = String(input);
  if (!url.startsWith(API_PREFIX)) {
    return realFetch(input, init);
  }
  const body =
    typeof init?.body === "string"
      ? (JSON.parse(init.body) as Record<string, unknown>)
      : {};
  const answer = await hub.answer(
    init?.method ?? "GET",
    url.slice(API_PREFIX.length),
    body,
  );
  return new Response(JSON.stringify(answer.body), {
    status: answer.status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Puts the fake hub in place of the panel's network. */
export function installDemoTransport(): void {
  window.fetch = demoFetch;
  window.WebSocket = DemoSocket as unknown as typeof WebSocket;
}
