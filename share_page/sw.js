"use strict";
// The service worker of a Web share. It passes every request of an app's
// frame to the shell of the frame's own tab, builds the response from what the
// shell sends back, and keeps the app's static files in Cache Storage. The
// shell's own files under /__neutrino/ go to the network.

const SHELL_PREFIX = "/__neutrino/";
const TAB_PARAM = "__neutrino_tab";
const DROPPED_HEADERS = new Set(["set-cookie", "content-security-policy", "content-security-policy-report-only", "x-frame-options", "transfer-encoding", "connection", "keep-alive"]);
const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308]);
const REDIRECTS_MAX = 20;
// How long a request waits for the pages to announce their tabs to a worker that started again.
const ANNOUNCE_WAIT_MS = 3000;
const CACHE_BYTES_MAX = 50 * 1024 * 1024;
const STORED_BYTES_HEADER = "x-neutrino-stored-bytes";
const STORED_AT_HEADER = "x-neutrino-stored-at";
const KEPT_DESTINATIONS = new Set(["script", "style", "font", "image"]);
const KEPT_TYPES = /^(text\/css|text\/javascript|application\/(x-)?javascript|application\/ecmascript|font\/|application\/(x-)?font|image\/)/;

// Every shell, by tab: {port, cache}.
const shells = new Map();
// The tab of every client the worker has routed, by client id.
const clientTabs = new Map();
// Requests in flight, by id.
const pending = new Map();
// Checks run at each announcement.
const announced = new Set();
// The bytes stored in each cache, by cache name: {total, entries, queue}, entries a Map of url to bytes in the order stored.
const ledgers = new Map();
let nextID = 1;
let shimText = null;
let lastBroadcast = 0;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("message", (event) => {
  const data = event.data || {};
  const clientId = event.source && event.source.id;
  if (data.type === "shell" && event.ports[0]) {
    const port = event.ports[0];
    shells.set(data.tab, { port, cache: String(data.cache || "") });
    if (clientId) clientTabs.set(clientId, data.tab);
    port.onmessage = (message) => onShellMessage(message.data);
    port.postMessage({ type: "ready" });
  } else if (data.type === "client" && clientId && data.tab) {
    clientTabs.set(clientId, data.tab);
  } else if (data.type === "claim") {
    event.waitUntil(self.clients.claim());
    return;
  } else if (data.type === "facts" && event.ports[0]) {
    const opener = shells.get(data.from);
    if (opener) opener.port.postMessage({ type: "facts" }, [event.ports[0]]);
    else event.ports[0].postMessage(null);
    return;
  } else {
    // An awake message does nothing more. Its event alone keeps the worker running.
    return;
  }
  for (const check of [...announced]) check();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith(SHELL_PREFIX)) return;
  if (event.request.destination === "serviceworker") { event.respondWith(new Response("", { status: 403 })); return; }
  event.respondWith(route(event, url).catch(() => failure("The app did not answer.")));
});

// --- routing -------------------------------------------------------------

async function route(event, url) {
  const request = event.request;
  const isNavigation = request.mode === "navigate";
  if (isNavigation && request.destination === "document") return shellPage();
  let tab = url.searchParams.get(TAB_PARAM);
  if (tab !== null) {
    url.searchParams.delete(TAB_PARAM);
  } else if (isNavigation) {
    tab = await soleTab();
    if (!tab) return request.method === "GET" ? retagPage() : failure("This page could not be routed. Reload it.");
  } else {
    tab = await tabOfClient(event.clientId);
  }
  const shell = tab ? await shellOf(tab) : null;
  if (!shell) return failure("This page could not be routed. Reload it.");
  if (isNavigation && event.resultingClientId) clientTabs.set(event.resultingClientId, tab);
  const body = request.method === "GET" || request.method === "HEAD" ? null : await request.arrayBuffer();
  const sent = { method: request.method, url, headers: headerList(request.headers), body, destination: request.destination };
  if (request.method === "GET" && !isNavigation && !request.headers.has("range") && shell.cache) {
    const hit = await caches.open(shell.cache).then((cache) => cache.match(url.href)).catch(() => null);
    if (hit) {
      if (!isFresh(hit)) event.waitUntil(revalidate(shell, sent, hit).catch(() => {}));
      return fromCache(hit);
    }
  }
  if (isNavigation || request.redirect !== "follow") return send(shell, sent, false);
  return follow(shell, sent);
}

// Follows the 3xx answers to a request that is not a navigation, by the Fetch standard's rules.
async function follow(shell, sent) {
  for (let count = 0; ; count++) {
    const response = await send(shell, sent, true);
    const location = response.headers.get("location");
    if (!REDIRECT_STATUSES.has(response.status) || !location) return response;
    if (response.body) response.body.cancel().catch(() => {});
    if (count + 1 > REDIRECTS_MAX) return failure("Too many redirects.");
    const next = new URL(location, sent.url);
    if (next.origin !== self.location.origin) return Response.redirect(next.href, response.status);
    const isGet = response.status === 303 ? sent.method !== "HEAD" : response.status <= 302 && sent.method === "POST";
    const headers = isGet ? sent.headers.filter(([name]) => !/^content-/i.test(name)) : sent.headers;
    sent = { ...sent, url: next, method: isGet ? "GET" : sent.method, body: isGet ? null : sent.body, headers };
  }
}

// The tab of the one shell open, else null.
async function soleTab() {
  const windows = await self.clients.matchAll({ type: "window" });
  const tops = windows.filter((client) => client.frameType === "top-level");
  return tops.length === 1 ? tabOfClient(tops[0].id, false) : null;
}

// The tab a client belongs to. A client missing from clientTabs makes the worker ask the pages to announce themselves first.
async function tabOfClient(clientId, isSoleTried = true) {
  if (clientId && !clientTabs.has(clientId)) await waitFor(() => clientTabs.has(clientId));
  if (clientId && clientTabs.has(clientId)) return clientTabs.get(clientId);
  return isSoleTried ? soleTab() : null;
}

async function shellOf(tab) {
  if (!shells.has(tab)) await waitFor(() => shells.has(tab));
  return shells.get(tab) || null;
}

// Asks every page to announce its tab, and waits until done() is true or the wait runs out.
function waitFor(done) {
  if (Date.now() - lastBroadcast > ANNOUNCE_WAIT_MS) {
    lastBroadcast = Date.now();
    self.clients.matchAll({ type: "window" }).then((windows) => { for (const client of windows) client.postMessage({ type: "announce" }); });
  }
  return new Promise((resolve) => {
    const finish = () => { announced.delete(check); clearTimeout(timer); resolve(); };
    const check = () => { if (done()) finish(); };
    const timer = setTimeout(finish, ANNOUNCE_WAIT_MS);
    announced.add(check);
  });
}

// --- answers of the worker's own ---------------------------------------------

// The shell page, for a navigation of the whole tab.
async function shellPage() {
  const page = await fetch(SHELL_PREFIX, { cache: "no-cache" });
  return new Response(await page.text(), { status: page.status, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}

// A page that loads its own address again with its tab added.
function retagPage() {
  const script = "var u=new URL(location.href);u.searchParams.set(" + JSON.stringify(TAB_PARAM) + ",top.__neutrinoTab);location.replace(u.href)";
  return new Response("<!doctype html><script>" + script + "</script>", { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}

function failure(text) {
  const response = new Response(text, { status: 502, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  response.isFailure = true;
  return response;
}

function headerList(headers) {
  const list = [];
  headers.forEach((value, name) => list.push([name, value]));
  return list;
}

// --- requests through the shell ------------------------------------------------

// Sends a request through a shell. It resolves with the response once its head arrives.
// isNavigation marks a navigation of a frame.
function send(shell, sent, isKept) {
  const id = nextID++;
  const body = sent.body ? sent.body.slice(0) : null;
  const isNavigation = sent.destination === "iframe";
  return new Promise((resolve) => {
    pending.set(id, { id, resolve, shell, sent, isKept, controller: null, chunks: [], isHtml: false, isSettled: false });
    shell.port.postMessage({ type: "fetch", id, method: sent.method, url: sent.url.pathname + sent.url.search, headers: sent.headers, body, isNavigation }, body ? [body] : []);
  });
}

function onShellMessage(message) {
  const entry = pending.get(message.id);
  if (!entry) return;
  if (message.type === "head") onHead(entry, message);
  else if (message.type === "chunk") onChunk(entry, new Uint8Array(message.data));
  else if (message.type === "end") onEnd(entry);
  else if (message.type === "error") {
    pending.delete(entry.id);
    if (!entry.isSettled) settle(entry, failure("The app did not answer: " + (message.code || "error")));
    else if (entry.controller) { try { entry.controller.error(new Error(message.code || "error")); } catch (e) { /* already closed */ } }
  }
}

function onHead(entry, message) {
  const headers = new Headers();
  let contentType = "", contentEncoding = "", contentLength = 0;
  for (const [name, value] of message.headers) {
    const lower = name.toLowerCase();
    if (lower === "content-type") contentType = value.toLowerCase();
    if (lower === "content-encoding") contentEncoding = value.toLowerCase();
    if (lower === "content-length") contentLength = Number(value) || 0;
    if (DROPPED_HEADERS.has(lower)) continue;
    try { headers.append(name, value); } catch (e) { /* a header the Fetch API refuses is dropped */ }
  }
  entry.encoding = contentEncoding;
  entry.isEncoded = (contentEncoding === "gzip" || contentEncoding === "deflate") && typeof DecompressionStream === "function";
  entry.isHtml = contentType.includes("text/html") && message.status >= 200 && message.status < 300;
  if (entry.isEncoded || entry.isHtml) { headers.delete("Content-Encoding"); headers.delete("Content-Length"); }
  entry.head = { status: message.status, statusText: message.statusText, headers };
  const hasBody = message.status >= 200 && ![204, 205, 304].includes(message.status) && entry.sent.method !== "HEAD";
  if (!hasBody) { pending.delete(entry.id); settle(entry, new Response(null, entry.head)); return; }
  if (entry.isHtml) return;
  let stream = new ReadableStream({
    start(controller) { entry.controller = controller; },
    cancel() { if (pending.delete(entry.id)) entry.shell.port.postMessage({ type: "abort", id: entry.id }); },
  });
  if (entry.isEncoded) stream = stream.pipeThrough(new DecompressionStream(contentEncoding));
  let storing = null;
  if (entry.isKept && isKeepable(entry.sent, message, contentType) && contentLength <= CACHE_BYTES_MAX) {
    const [toPage, toCache] = stream.tee();
    stream = toPage;
    storing = store(entry.shell.cache, entry.sent.url.href, toCache, entry.head);
  }
  const response = new Response(stream, entry.head);
  response.storing = storing;
  settle(entry, response);
}

function onChunk(entry, chunk) {
  if (entry.controller) entry.controller.enqueue(chunk);
  else entry.chunks.push(chunk);
}

async function onEnd(entry) {
  pending.delete(entry.id);
  if (!entry.isHtml) {
    if (entry.controller) { try { entry.controller.close(); } catch (e) { /* already closed */ } }
    return;
  }
  let blob = new Blob(entry.chunks);
  if (entry.isEncoded) blob = await new Response(blob.stream().pipeThrough(new DecompressionStream(entry.encoding))).blob();
  settle(entry, new Response(injectShim(await blob.text(), await shim()), entry.head));
}

function settle(entry, response) {
  if (entry.isSettled) return;
  entry.isSettled = true;
  entry.resolve(response);
}

async function shim() {
  if (shimText === null) {
    const response = await fetch(SHELL_PREFIX + "shim.js");
    shimText = response.ok ? await response.text() : "";
  }
  return shimText;
}

function injectShim(html, text) {
  if (!text) return html;
  const tag = "<script>" + text.replace(/<\/script/gi, "<\\/script") + "</script>";
  const head = html.match(/<head[^>]*>/i) || html.match(/<html[^>]*>/i);
  if (head) return html.slice(0, head.index + head[0].length) + tag + html.slice(head.index + head[0].length);
  return tag + html;
}

// --- the cache of the app's files -------------------------------------------------

// Whether the cache keeps a response: the app's code or artwork.
function isKeepable(sent, head, contentType) {
  if (sent.method !== "GET" || head.status !== 200 || head.hasSetCookie) return false;
  if (["document", "iframe", "frame"].includes(sent.destination) || contentType.includes("text/html")) return false;
  const control = (head.headers.find(([name]) => name.toLowerCase() === "cache-control") || ["", ""])[1].toLowerCase();
  if (/(^|[\s,])(no-store|private)\b/.test(control)) return false;
  return KEPT_DESTINATIONS.has(sent.destination) || KEPT_TYPES.test(contentType);
}

// Whether a cached response is served with no check: it has no validator and its max-age has not passed.
function isFresh(hit) {
  if (hit.headers.get("etag") || hit.headers.get("last-modified")) return false;
  const control = (hit.headers.get("cache-control") || "").toLowerCase();
  if (/(^|[\s,])no-cache\b/.test(control)) return false;
  const maxAge = /(?:^|[\s,])max-age=(\d+)/.exec(control);
  const storedAt = Number(hit.headers.get(STORED_AT_HEADER)) || 0;
  return maxAge !== null && Date.now() < storedAt + Number(maxAge[1]) * 1000;
}

// A cached response with the worker's own headers taken off.
function fromCache(hit) {
  const headers = new Headers(hit.headers);
  headers.delete(STORED_BYTES_HEADER);
  headers.delete(STORED_AT_HEADER);
  return new Response(hit.body, { status: hit.status, statusText: hit.statusText, headers });
}

// Sends a cached request again with its validators. A 304 keeps the entry, a
// keepable answer replaces it, and any other answer removes it.
async function revalidate(shell, sent, hit) {
  const headers = sent.headers.filter(([name]) => !/^if-(none-match|modified-since)$/i.test(name));
  const etag = hit.headers.get("etag");
  const modified = hit.headers.get("last-modified");
  if (etag) headers.push(["If-None-Match", etag]);
  if (modified) headers.push(["If-Modified-Since", modified]);
  const response = await send(shell, { ...sent, headers }, true);
  if (response.body) await response.arrayBuffer().catch(() => null);
  if (response.isFailure || response.status === 304 || response.storing) return;
  await change(shell.cache, async (cache, ledger) => {
    await cache.delete(sent.url.href);
    drop(ledger, sent.url.href);
  });
}

// The ledger of a cache, read from its entries the first time.
function ledgerOf(name) {
  if (!ledgers.has(name)) {
    ledgers.set(name, caches.open(name).then(async (cache) => {
      const ledger = { total: 0, entries: new Map(), queue: Promise.resolve() };
      for (const request of await cache.keys()) {
        const response = await cache.match(request);
        const bytes = Number(response && response.headers.get(STORED_BYTES_HEADER)) || 0;
        ledger.entries.set(request.url, bytes);
        ledger.total += bytes;
      }
      return ledger;
    }));
  }
  return ledgers.get(name);
}

// Runs a change of a cache after the changes queued before it.
async function change(name, run) {
  const ledger = await ledgerOf(name);
  const cache = await caches.open(name);
  ledger.queue = ledger.queue.then(() => run(cache, ledger)).catch(() => {});
  return ledger.queue;
}

function drop(ledger, url) {
  if (!ledger.entries.has(url)) return;
  ledger.total -= ledger.entries.get(url);
  ledger.entries.delete(url);
}

// Reads a response branch whole and stores it, removing the entries stored earliest until it fits.
async function store(name, url, stream, head) {
  const reader = stream.getReader();
  const chunks = [];
  let bytes = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    bytes += value.length;
    if (bytes > CACHE_BYTES_MAX) { reader.cancel().catch(() => {}); return false; }
    chunks.push(value);
  }
  await change(name, async (cache, ledger) => {
    drop(ledger, url);
    for (const [stored, size] of ledger.entries) {
      if (ledger.total + bytes <= CACHE_BYTES_MAX) break;
      await cache.delete(stored);
      drop(ledger, stored);
    }
    const headers = new Headers(head.headers);
    headers.set(STORED_BYTES_HEADER, String(bytes));
    headers.set(STORED_AT_HEADER, String(Date.now()));
    await cache.put(url, new Response(new Blob(chunks), { status: head.status, statusText: head.statusText, headers }));
    ledger.entries.set(url, bytes);
    ledger.total += bytes;
  });
  return true;
}
