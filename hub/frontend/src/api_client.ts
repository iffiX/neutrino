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
  /** The name the API gave the failure, empty when it named none. */
  readonly code: string;

  constructor(status: number, message: string, detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    const detailRecord = asRecord(detail);
    this.code = typeof detailRecord?.code === "string" ? detailRecord.code : "";
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

/**
 * POST a multipart upload, used by the config restore form.
 *
 * `fields` carries the text parts that travel beside the file.
 */
export async function apiUpload<T>(
  path: string,
  file: File,
  fields: Record<string, string> = {},
): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  for (const [name, value] of Object.entries(fields)) {
    form.append(name, value);
  }
  return request<T>(path, { method: "POST", body: form });
}

/**
 * POST a JSON body and save the file the API answers with.
 *
 * The blob is fetched rather than linked directly so a 401 still routes
 * through the shared error handling instead of navigating away from the app.
 * The name comes from `Content-Disposition`, falling back to the caller's.
 */
export async function apiPostDownload(
  path: string,
  body: unknown,
  fallbackFilename: string,
) {
  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      method: "POST",
      credentials: "same-origin",
      ...jsonBody(body),
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
  const filename =
    filenameFromDisposition(response.headers.get("Content-Disposition")) ??
    fallbackFilename;
  saveBlob(await response.blob(), filename);
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

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function filenameFromDisposition(header: string | null): string | null {
  if (header === null) {
    return null;
  }
  const match = /filename="([^"]+)"/.exec(header);
  return match?.[1] ?? null;
}

async function toApiError(response: Response): Promise<ApiError> {
  const fallback = `${response.status} ${response.statusText}`.trim();
  let message = "";
  let detail: unknown = null;
  try {
    const parsed: unknown = JSON.parse(await response.text());
    message = readDetail(parsed);
    detail = asRecord(parsed)?.detail ?? null;
  } catch {
    message = "";
  }
  return new ApiError(response.status, message || fallback, detail);
}

function readDetail(parsed: unknown): string {
  const record = asRecord(parsed);
  if (record === null) {
    return "";
  }
  if (typeof record.detail === "string") {
    return record.detail;
  }
  if (typeof record.message === "string") {
    return record.message;
  }
  return "";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  return value as Record<string, unknown>;
}
