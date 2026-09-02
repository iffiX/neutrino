/**
 * Typed fetch wrapper for the panel API.
 *
 * Every call goes through `request`, which turns a non-2xx response into an
 * `ApiError` carrying the status so callers can render a real error state
 * instead of a blank page. A 401 additionally fires the registered
 * unauthorized handler, which the auth provider uses to drop back to the login
 * screen no matter which page triggered the call.
 */

const API_PREFIX = "/api";

type UnauthorizedHandler = () => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;

/** One failed API call, with the HTTP status that caused it. */
export class ApiError extends Error {
  readonly status: number;
  /** The response's `detail` payload; an object for code-shaped errors. */
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  /** Whether this error means the session is gone and login is required. */
  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

/**
 * Register the callback fired whenever the API answers 401.
 *
 * The auth provider owns this; registering twice replaces the previous
 * handler, and passing null clears it.
 */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  unauthorizedHandler = handler;
}

export async function apiGet<T>(path: string): Promise<T> {
  return request<T>(path, { method: "GET" });
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "POST", ...jsonBody(body) });
}

export async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "PUT", ...jsonBody(body) });
}

export async function apiDelete<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

/** POST a multipart upload, used by the config restore form. */
export async function apiUpload<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  return request<T>(path, { method: "POST", body: form });
}

/**
 * Trigger a browser download of an API endpoint that answers with a file.
 *
 * The blob is fetched rather than linked directly so a 401 still routes
 * through the shared error handling instead of navigating away from the app.
 */
export async function apiDownload(path: string, filename: string) {
  const response = await fetch(`${API_PREFIX}${path}`, {
    method: "GET",
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw await toApiError(response);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Absolute websocket URL for a `/ws/...` path on the serving origin. */
export function websocketUrl(path: string): string {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}${path}`;
}

/** Human-readable message for anything thrown by the API layer. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown error";
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      credentials: "same-origin",
      ...init,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the gateway API");
  }

  if (response.status === 401) {
    unauthorizedHandler?.();
  }
  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  if (text.length === 0) {
    return undefined as T;
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(response.status, "Malformed response from the API");
  }
}

function jsonBody(body: unknown): RequestInit {
  if (body === undefined) {
    return {};
  }
  return {
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

async function toApiError(response: Response): Promise<ApiError> {
  const fallback = `${response.status} ${response.statusText}`.trim();
  let message = "";
  let detail: unknown = null;
  try {
    const parsed: unknown = JSON.parse(await response.text());
    message = readDetail(parsed);
    if (typeof parsed === "object" && parsed !== null) {
      detail = (parsed as Record<string, unknown>).detail ?? null;
    }
  } catch {
    message = "";
  }
  return new ApiError(response.status, message || fallback, detail);
}

function readDetail(parsed: unknown): string {
  if (typeof parsed !== "object" || parsed === null) {
    return "";
  }
  const record = parsed as Record<string, unknown>;
  if (typeof record.detail === "string") {
    return record.detail;
  }
  if (typeof record.message === "string") {
    return record.message;
  }
  return "";
}
