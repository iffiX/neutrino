"use strict";
// The service worker of a Web share. It takes every request the app's
// iframe makes, finds the shell window of that tab and hands the request to
// it; the shell answers over the data channel and the worker builds the
// Response. The shell's own files under /__neutrino/ go to the network.

const SHELL_PREFIX = "/__neutrino/";
const DROPPED_HEADERS = new Set(["set-cookie", "content-security-policy", "content-security-policy-report-only", "transfer-encoding", "connection", "keep-alive", "x-frame-options"]);

const shells = new Map();
const clientTabs = new Map();
const pending = new Map();
let nextID = 1;
let shimText = null;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type !== "shell" || !event.ports[0]) return;
  const port = event.ports[0];
  shells.set(data.tab, port);
  if (event.source && event.source.id) clientTabs.set(event.source.id, data.tab);
  port.onmessage = (message) => onShellMessage(message.data);
  port.postMessage({ type: "ready" });
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith(SHELL_PREFIX)) return;
  if (event.request.destination === "serviceworker") { event.respondWith(new Response("", { status: 403 })); return; }
  event.respondWith(route(event, url));
});

async function route(event, url) {
  const request = event.request;
  const isNavigation = request.mode === "navigate";
  let tab = clientTabs.get(event.clientId);
  let routedBy = "mapping";
  if (isNavigation && request.destination === "document") {
    const shellPage = await fetch(SHELL_PREFIX);
    return new Response(await shellPage.text(), { status: 200, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
  }
  if (!tab) {
    if (shells.size === 0) return new Response("no shell", { status: 503 });
    tab = [...shells.keys()].pop();
    routedBy = "fallback";
  }
  if (isNavigation && event.resultingClientId) clientTabs.set(event.resultingClientId, tab);
  const port = shells.get(tab);
  const id = nextID++;
  const headers = [];
  request.headers.forEach((value, name) => headers.push([name, value]));
  const body = request.method === "GET" || request.method === "HEAD" ? null : await request.arrayBuffer();
  return new Promise((resolve) => {
    const entry = { resolve, controller: null, chunks: [], isHtml: false, isGzip: false, head: null, isSettled: false };
    pending.set(id, entry);
    port.postMessage({ type: "fetch", id, method: request.method, url: url.pathname + url.search, headers, body, routedBy }, body ? [body] : []);
  });
}

function onShellMessage(message) {
  const entry = pending.get(message.id);
  if (!entry) return;
  switch (message.type) {
    case "head": onHead(entry, message); break;
    case "chunk": onChunk(entry, new Uint8Array(message.data)); break;
    case "end": onEnd(message.id, entry); break;
    case "error":
      pending.delete(message.id);
      if (!entry.isSettled) { entry.isSettled = true; entry.resolve(new Response("The app did not answer: " + (message.code || "error"), { status: 502, headers: { "Content-Type": "text/plain; charset=utf-8" } })); }
      else if (entry.controller) { try { entry.controller.error(new Error(message.code || "error")); } catch (e) { /* already closed */ } }
      break;
  }
}

function onHead(entry, message) {
  const headers = new Headers();
  let contentType = "", contentEncoding = "";
  for (const [name, value] of message.headers) {
    const lower = name.toLowerCase();
    if (lower === "content-type") contentType = value.toLowerCase();
    if (lower === "content-encoding") contentEncoding = value.toLowerCase();
    if (DROPPED_HEADERS.has(lower)) continue;
    headers.append(name, value);
  }
  entry.isGzip = contentEncoding === "gzip" || contentEncoding === "deflate";
  entry.encoding = contentEncoding;
  entry.isHtml = contentType.includes("text/html") && message.status >= 200 && message.status < 300;
  if (entry.isGzip || entry.isHtml) { headers.delete("Content-Encoding"); headers.delete("Content-Length"); }
  entry.head = { status: message.status, statusText: message.statusText, headers };
  const hasBody = !(message.status === 204 || message.status === 304 || message.status === 101 || message.status < 200);
  if (!hasBody) { settle(entry, new Response(null, entry.head)); return; }
  if (entry.isHtml) return;
  let stream = new ReadableStream({ start(controller) { entry.controller = controller; } });
  if (entry.isGzip && typeof DecompressionStream === "function") stream = stream.pipeThrough(new DecompressionStream(entry.encoding));
  settle(entry, new Response(stream, entry.head));
}

function onChunk(entry, chunk) {
  if (entry.isHtml || !entry.controller) { entry.chunks.push(chunk); return; }
  entry.controller.enqueue(chunk);
}

async function onEnd(id, entry) {
  pending.delete(id);
  if (entry.isHtml) {
    let blob = new Blob(entry.chunks);
    if (entry.isGzip && typeof DecompressionStream === "function") blob = await new Response(blob.stream().pipeThrough(new DecompressionStream(entry.encoding))).blob();
    const text = await blob.text();
    settle(entry, new Response(injectShim(text, await shim()), entry.head));
    return;
  }
  if (entry.controller) { try { entry.controller.close(); } catch (e) { /* already closed */ } }
  else if (!entry.isSettled) settle(entry, new Response(new Blob(entry.chunks), entry.head));
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
  const head = html.match(/<head[^>]*>/i);
  if (head) return html.slice(0, head.index + head[0].length) + tag + html.slice(head.index + head[0].length);
  const root = html.match(/<html[^>]*>/i);
  if (root) return html.slice(0, root.index + root[0].length) + tag + html.slice(root.index + root[0].length);
  return tag + html;
}
