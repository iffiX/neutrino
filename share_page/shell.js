"use strict";
// The shell of a Web share. It owns the connection to the hub. It opens a
// WebRTC data channel from the link's facts, sends the share's ticket in the
// open record, and runs a yamux client. Its streams are the control stream,
// the app's HTTP requests and the app's WebSockets, all to the share's entry.
// The service worker sends it every request of the app's frame.

const PROTOCOL = 4;
const LINK_FORM = 1;
const RECORD = { open: 1, accept: 2, data: 3, close: 8 };
const YAMUX = {
  data: 0, window: 1, ping: 2, goaway: 3,
  SYN: 1, ACK: 2, FIN: 4, RST: 8,
  headerBytes: 12, initialWindow: 256 * 1024, frameMax: 65507, receiveWindow: 4 * 1024 * 1024,
};
const CHANNEL = { label: "neutrino", bufferedHigh: 4 * 1024 * 1024, bufferedLow: 1024 * 1024 };
// Every interval of web_share.md, "The connection", in milliseconds.
const TIMING = { open: 30000, slow: 10000, retry: 10000, ping: 3000, silent: 15000, quiet: 10000 };
const HTTP = { host: "127.0.0.1", streamsMax: 8 };
// The query parameter that tags a navigation of the app's frame with its tab.
const TAB_PARAM = "__neutrino_tab";
// The query parameter that names the tab a new tab was opened from.
const FROM_PARAM = "__neutrino_from";
const KEPT_FACTS = "neutrino_share";
const WORDS = {
  en: {
    opening: "Opening {app}…",
    slow: "The line is slow, still connecting…",
    link: ["This link is no longer valid.", "Ask the person who shared it for a new one."],
    hub: ["The hub is offline.", "The computer that shares this app cannot be reached right now."],
    unavailable: ["The app cannot be opened right now.", "It opens by itself once it is back."],
  },
  zh: {
    opening: "正在打开 {app}…",
    slow: "线路较慢，仍在连接…",
    link: ["这个链接已失效。", "请向分享给你的人要一个新链接。"],
    hub: ["中枢已离线。", "分享这个应用的电脑现在连不上。"],
    unavailable: ["应用暂时打不开。", "恢复后会自动打开。"],
  },
};
// The codes that show the app-unavailable screen, and those that end the share.
// A connect close names one of APP_DOWN_CODES while the shared app itself is down.
const MACHINE_CODES = ["agent_offline", "service_unknown"];
const APP_DOWN_CODES = ["connect_failed", "port_not_published"];
const SHARE_CODES = ["share_unknown"];
// Refusals of a hello that a later try can pass.
const PASSING_CODES = ["channel_full", "control_unavailable"];

const encoder = new TextEncoder();
const decoder = new TextDecoder();
const stats = { startedAt: performance.now() };
window.__neutrinoStats = stats;

// --- bytes ---------------------------------------------------------------

class ByteQueue {
  constructor() { this.chunks = []; this.length = 0; this.offset = 0; }
  push(u8) { if (u8.length) { this.chunks.push(u8); this.length += u8.length; } }
  peek(n) { return this.read(n, false); }
  take(n) { return this.read(n, true); }
  read(n, isTaking) {
    const out = new Uint8Array(n);
    let copied = 0, i = 0, offset = this.offset;
    while (copied < n) {
      const chunk = this.chunks[i];
      const piece = chunk.subarray(offset, offset + Math.min(n - copied, chunk.length - offset));
      out.set(piece, copied);
      copied += piece.length;
      offset += piece.length;
      if (offset === chunk.length) { i++; offset = 0; }
    }
    if (isTaking) { this.chunks.splice(0, i); this.offset = offset; this.length -= n; }
    return out;
  }
  takeAll() { return this.take(this.length); }
  indexOf(pattern, from = 0) {
    const all = this.peek(this.length);
    outer: for (let i = from; i + pattern.length <= all.length; i++) {
      for (let j = 0; j < pattern.length; j++) if (all[i + j] !== pattern[j]) continue outer;
      return i;
    }
    return -1;
  }
}

function latin1(u8) { let s = ""; for (let i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]); return s; }
function json(object) { return encoder.encode(JSON.stringify(object)); }
function base64urlDecode(text) {
  const binary = atob(text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - text.length % 4) % 4));
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
}
function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

// A refusal the page acts on: the screen it shows and the code behind it.
class Refusal extends Error {
  constructor(screen, code) { super(screen + ":" + code); this.screen = screen; this.code = code || ""; }
}

// The screen for a refusal code from the hub.
function screenOf(code) {
  if (SHARE_CODES.includes(code)) return "link";
  if (MACHINE_CODES.includes(code) || APP_DOWN_CODES.includes(code)) return "unavailable";
  return "hub";
}

// --- the link ------------------------------------------------------------

// The share's facts from the link's fragment, else the tab's kept copy.
function readFacts() {
  let facts = null;
  const fragment = location.hash.slice(1);
  try {
    facts = JSON.parse(fragment ? decoder.decode(base64urlDecode(fragment)) : sessionStorage.getItem(KEPT_FACTS) || "null");
  } catch (e) {
    facts = null;
  }
  if (!isFacts(facts)) return null;
  if (fragment) sessionStorage.setItem(KEPT_FACTS, JSON.stringify(facts));
  return facts;
}

// The share's facts from the tab this tab was opened from, through the worker.
async function factsFromOpener() {
  const url = new URL(location.href);
  const from = url.searchParams.get(FROM_PARAM);
  if (!from) return null;
  url.searchParams.delete(FROM_PARAM);
  history.replaceState(null, "", url.pathname + url.search + url.hash);
  const controller = navigator.serviceWorker && navigator.serviceWorker.controller;
  if (!controller) return null;
  const channel = new MessageChannel();
  const answer = new Promise((resolve) => { channel.port1.onmessage = (event) => resolve(event.data); setTimeout(() => resolve(null), 3000); });
  controller.postMessage({ type: "facts", from }, [channel.port2]);
  const facts = await answer;
  if (!isFacts(facts)) return null;
  sessionStorage.setItem(KEPT_FACTS, JSON.stringify(facts));
  stats.isFromOpener = true;
  return facts;
}

function isFacts(facts) {
  return !!facts && facts.v === LINK_FORM && !!facts.hub && typeof facts.hub.ip === "string" && Number.isInteger(facts.hub.port) &&
    typeof facts.hub.fp === "string" && !!facts.ice && typeof facts.ice.ufrag === "string" && typeof facts.ice.pwd === "string" &&
    typeof facts.ticket === "string" && !!facts.app && typeof facts.app.entry === "string";
}

// The Cache Storage cache of a hub's app.
function cacheName(facts) { return "neutrino:" + facts.hub.fp + ":" + facts.app.entry; }

// --- screens ---------------------------------------------------------------

const words = WORDS[/^zh/i.test(navigator.language || "") ? "zh" : "en"];
if (words === WORDS.zh) document.documentElement.lang = "zh-CN";

const screen = {
  kind: "",
  // Counts every change of screen.
  serial: 0,
  element(id) { return document.getElementById(id); },
  // The tab of a screen of the page's own: the screen's first line as its title, and no icon.
  tab(line) {
    document.title = line;
    this.element("icon").href = "data:,";
  },
  loading(title) {
    this.kind = "loading";
    this.serial++;
    const line = words.opening.replace(title ? "{app}" : " {app}", title || "");
    this.element("box").classList.add("loading");
    this.element("title").textContent = line;
    this.element("screen").classList.remove("hidden");
    this.tab(line);
  },
  slow() {
    if (this.kind !== "loading") return;
    this.element("title").textContent = words.slow;
    this.tab(words.slow);
  },
  refuse(kind) {
    const [title, detail] = words[kind];
    this.kind = kind;
    this.serial++;
    this.element("box").classList.remove("loading");
    this.element("title").textContent = title;
    this.element("detail").textContent = detail;
    this.element("screen").classList.remove("hidden");
    this.tab(title);
    stats.screen = kind;
  },
  app() {
    this.kind = "app";
    this.serial++;
    this.element("screen").classList.add("hidden");
    stats.screen = "app";
    mirror.apply();
  },
};

// --- the channel -----------------------------------------------------------

// The hub's side of the session description, written from the link.
function hubOffer(facts) {
  return [
    "v=0",
    "o=- 0 0 IN IP4 127.0.0.1",
    "s=-",
    "t=0 0",
    "a=ice-lite",
    "a=group:BUNDLE 0",
    "a=msid-semantic: WMS",
    "m=application 9 UDP/DTLS/SCTP webrtc-datachannel",
    "c=IN IP4 0.0.0.0",
    "a=mid:0",
    "a=ice-ufrag:" + facts.ice.ufrag,
    "a=ice-pwd:" + facts.ice.pwd,
    "a=fingerprint:sha-256 " + facts.hub.fp,
    "a=setup:actpass",
    "a=sctp-port:5000",
    "a=max-message-size:262144",
    "a=candidate:1 1 tcp 2130706431 " + facts.hub.ip + " " + facts.hub.port + " typ host tcptype passive",
    "a=end-of-candidates",
    "",
  ].join("\r\n");
}

// Waits for a promise until the deadline, else fails as the hub being out of reach.
function within(promise, deadline) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Refusal("hub", "timeout")), Math.max(0, deadline - performance.now()));
    promise.then((value) => { clearTimeout(timer); resolve(value); }, (error) => { clearTimeout(timer); reject(error); });
  });
}

async function openChannel(facts, deadline) {
  const pc = new RTCPeerConnection({ iceServers: [] });
  const dc = pc.createDataChannel(CHANNEL.label, { negotiated: true, id: 0 });
  dc.binaryType = "arraybuffer";
  dc.bufferedAmountLowThreshold = CHANNEL.bufferedLow;
  try {
    await pc.setRemoteDescription({ type: "offer", sdp: hubOffer(facts) });
    await pc.setLocalDescription(await pc.createAnswer());
    await within(new Promise((resolve, reject) => {
      dc.onopen = resolve;
      pc.onconnectionstatechange = () => {
        if (pc.connectionState === "failed" || pc.connectionState === "closed") reject(new Refusal("hub", "channel"));
      };
    }), deadline);
  } catch (error) {
    pc.close();
    throw error instanceof Refusal ? error : new Refusal("hub", "channel");
  }
  return { pc, dc };
}

// Sends the open record with the ticket, and returns the share's id from the
// accept and any bytes that came after it.
function admit(dc, facts, deadline) {
  return within(new Promise((resolve, reject) => {
    const records = new RecordReader();
    dc.onmessage = (event) => {
      const [record] = records.feed(new Uint8Array(event.data));
      if (!record) return;
      dc.onmessage = null;
      if (record.type !== RECORD.accept) {
        const refusal = parseRefusal(record.payload);
        reject(new Refusal(refusal.code === "control_unavailable" ? "hub" : "link", refusal.code));
        return;
      }
      try { resolve({ id: JSON.parse(decoder.decode(record.payload)).id, rest: records.rest() }); } catch (e) { reject(new Refusal("link", "malformed")); }
    };
    dc.onclose = () => reject(new Refusal("hub", "closed"));
    dc.send(encodeRecord(RECORD.open, json({ protocol: PROTOCOL, ticket: facts.ticket })));
  }), deadline);
}

// --- yamux -----------------------------------------------------------------

class Yamux {
  constructor(channel) {
    this.channel = channel;
    this.queue = new ByteQueue();
    this.streams = new Map();
    this.nextID = 1;
    this.lastByteAt = performance.now();
    this.onEnd = null;
    this.isEnded = false;
    channel.onmessage = (event) => this.feed(new Uint8Array(event.data));
    channel.onbufferedamountlow = () => this.pumpAll();
    channel.onclose = () => this.end();
    channel.onerror = () => this.end();
  }
  sendFrame(type, flags, id, length, payload) {
    if (this.isEnded) return;
    const frame = new Uint8Array(YAMUX.headerBytes + (payload ? payload.length : 0));
    const view = new DataView(frame.buffer);
    frame[1] = type;
    view.setUint16(2, flags);
    view.setUint32(4, id);
    view.setUint32(8, length);
    if (payload) frame.set(payload, YAMUX.headerBytes);
    try { this.channel.send(frame); } catch (e) { this.end(); }
  }
  feed(u8) {
    this.lastByteAt = performance.now();
    this.queue.push(u8);
    while (this.queue.length >= YAMUX.headerBytes) {
      const head = this.queue.peek(YAMUX.headerBytes);
      const view = new DataView(head.buffer);
      if (head[0] !== 0) { this.end(); return; }
      const type = head[1], flags = view.getUint16(2), id = view.getUint32(4), length = view.getUint32(8);
      let payload = null;
      if (type === YAMUX.data) {
        if (this.queue.length < YAMUX.headerBytes + length) return;
        this.queue.take(YAMUX.headerBytes);
        payload = this.queue.take(length);
      } else {
        this.queue.take(YAMUX.headerBytes);
      }
      this.dispatch(type, flags, id, length, payload);
    }
  }
  dispatch(type, flags, id, length, payload) {
    if (type === YAMUX.ping) { if (flags & YAMUX.SYN) this.sendFrame(YAMUX.ping, YAMUX.ACK, 0, length); return; }
    if (type === YAMUX.goaway) { this.end(); return; }
    const stream = this.streams.get(id);
    if (!stream) return;
    if (type === YAMUX.window) stream.onWindow(flags, length);
    else stream.onData(flags, payload);
  }
  open() {
    const id = this.nextID;
    this.nextID += 2;
    const stream = new YamuxStream(this, id);
    this.streams.set(id, stream);
    this.sendFrame(YAMUX.window, YAMUX.SYN, id, YAMUX.receiveWindow - YAMUX.initialWindow);
    return stream;
  }
  canSend() { return this.channel.bufferedAmount < CHANNEL.bufferedHigh; }
  pumpAll() { for (const stream of this.streams.values()) stream.pump(); }
  end() {
    if (this.isEnded) return;
    this.isEnded = true;
    for (const stream of [...this.streams.values()]) stream.fail();
    this.streams.clear();
    if (this.onEnd) this.onEnd();
  }
}

class YamuxStream {
  constructor(mux, id) {
    this.mux = mux; this.id = id;
    this.sendWindow = YAMUX.initialWindow;
    this.consumed = 0;
    this.pending = [];
    this.isWriteClosed = false; this.isReadClosed = false; this.isCloseQueued = false; this.isFailed = false;
    this.onDataHandler = null; this.onEnd = null; this.onError = null;
  }
  write(u8) {
    if (this.isWriteClosed || this.isFailed) return;
    if (u8.length) this.pending.push(u8);
    this.pump();
  }
  pump() {
    while (this.pending.length && this.sendWindow > 0 && this.mux.canSend()) {
      const chunk = this.pending[0];
      const n = Math.min(chunk.length, this.sendWindow, YAMUX.frameMax);
      this.mux.sendFrame(YAMUX.data, 0, this.id, n, chunk.subarray(0, n));
      this.sendWindow -= n;
      if (n === chunk.length) this.pending.shift(); else this.pending[0] = chunk.subarray(n);
    }
    if (!this.pending.length && this.isCloseQueued && !this.isWriteClosed) {
      this.isWriteClosed = true;
      this.mux.sendFrame(YAMUX.window, YAMUX.FIN, this.id, 0);
      this.forgetIfDone();
    }
  }
  onData(flags, payload) {
    if (payload && payload.length) {
      this.consumed += payload.length;
      if (this.consumed >= YAMUX.receiveWindow / 2) { this.mux.sendFrame(YAMUX.window, 0, this.id, this.consumed); this.consumed = 0; }
      if (this.onDataHandler) this.onDataHandler(payload);
    }
    this.flags(flags);
  }
  onWindow(flags, delta) {
    this.sendWindow += delta;
    this.flags(flags);
    this.pump();
  }
  flags(flags) {
    if (flags & YAMUX.RST) { this.fail(); return; }
    if (flags & YAMUX.FIN && !this.isReadClosed) {
      this.isReadClosed = true;
      if (this.onEnd) this.onEnd();
      this.forgetIfDone();
    }
  }
  set handlers(h) { this.onDataHandler = h.data || null; this.onEnd = h.end || null; this.onError = h.error || null; }
  close() { this.isCloseQueued = true; this.pump(); }
  reset() {
    if (this.isFailed) return;
    this.isFailed = true;
    this.mux.sendFrame(YAMUX.window, YAMUX.RST, this.id, 0);
    this.mux.streams.delete(this.id);
  }
  forgetIfDone() { if (this.isWriteClosed && this.isReadClosed) this.mux.streams.delete(this.id); }
  fail() {
    if (this.isFailed) return;
    this.isFailed = true;
    this.mux.streams.delete(this.id);
    if (this.onError) this.onError();
  }
}

// --- records ---------------------------------------------------------------

function encodeRecord(type, payload) {
  const body = payload || new Uint8Array(0);
  const record = new Uint8Array(5 + body.length);
  record[0] = type;
  new DataView(record.buffer).setUint32(1, body.length);
  record.set(body, 5);
  return record;
}

class RecordReader {
  constructor() { this.queue = new ByteQueue(); }
  feed(u8) {
    this.queue.push(u8);
    const records = [];
    while (this.queue.length >= 5) {
      const head = this.queue.peek(5);
      const length = new DataView(head.buffer).getUint32(1);
      if (this.queue.length < 5 + length) break;
      this.queue.take(5);
      records.push({ type: head[0], payload: this.queue.take(length) });
    }
    return records;
  }
  rest() { return this.queue.takeAll(); }
}

function parseRefusal(payload) {
  try { const parsed = JSON.parse(decoder.decode(payload)); return { code: parsed.code || "", params: parsed.params || {} }; } catch (e) { return { code: "malformed", params: {} }; }
}

// --- the control stream ----------------------------------------------------

// The control stream's frames, each passed to a waiter of its type or to onFrame.
class ControlStream {
  constructor(mux) {
    this.stream = mux.open();
    this.records = new RecordReader();
    this.text = "";
    this.waiters = [];
    this.onFrame = null;
    this.accepted = new Promise((resolve, reject) => { this.resolveAccept = resolve; this.rejectAccept = reject; });
    this.stream.handlers = {
      data: (u8) => {
        for (const record of this.records.feed(u8)) {
          if (record.type === RECORD.accept) this.resolveAccept();
          else if (record.type === RECORD.close) { const refusal = parseRefusal(record.payload); this.rejectAccept(new Refusal("hub", refusal.code)); }
          else if (record.type === RECORD.data) this.lines(decoder.decode(record.payload));
        }
      },
      end: () => this.take({ type: "ended" }),
      error: () => this.take({ type: "ended" }),
    };
    this.stream.write(encodeRecord(RECORD.open, json({ kind: "control" })));
  }
  lines(text) {
    this.text += text;
    let index;
    while ((index = this.text.indexOf("\n")) >= 0) {
      const line = this.text.slice(0, index);
      this.text = this.text.slice(index + 1);
      if (line) { try { this.take(JSON.parse(line)); } catch (e) { /* a line that is not JSON is dropped */ } }
    }
  }
  take(frame) {
    const index = this.waiters.findIndex((waiter) => waiter.matches(frame));
    if (index >= 0) { this.waiters.splice(index, 1)[0].resolve(frame); return; }
    if (frame.type === "ended" || frame.type === "refused") for (const waiter of this.waiters.splice(0)) waiter.resolve(frame);
    if (this.onFrame) this.onFrame(frame);
  }
  write(frame) { this.stream.write(encodeRecord(RECORD.data, encoder.encode(JSON.stringify(frame) + "\n"))); }
  // The next frame that matches, or a refused or ended frame, by the deadline.
  next(matches, deadline) {
    return within(new Promise((resolve) => this.waiters.push({ matches, resolve })), deadline);
  }
}

// --- cookies ---------------------------------------------------------------

class CookieJar {
  constructor() { this.cookies = new Map(); }
  set(setCookie, requestPath) {
    const parts = setCookie.split(";").map((part) => part.trim());
    const [name, ...valueParts] = parts[0].split("=");
    if (!name) return;
    const cookie = { name: name.trim(), value: valueParts.join("=").trim(), path: this.defaultPath(requestPath), expires: null, isHttpOnly: false };
    for (const attribute of parts.slice(1)) {
      const [key, ...rest] = attribute.split("=");
      const lower = key.trim().toLowerCase(), value = rest.join("=").trim();
      if (lower === "path" && value.startsWith("/")) cookie.path = value;
      else if (lower === "expires") { const when = Date.parse(value); if (!Number.isNaN(when)) cookie.expires = when; }
      else if (lower === "max-age") { const seconds = Number(value); if (!Number.isNaN(seconds)) cookie.expires = Date.now() + seconds * 1000; }
      else if (lower === "httponly") cookie.isHttpOnly = true;
    }
    const key = cookie.name + "|" + cookie.path;
    if (cookie.expires !== null && cookie.expires <= Date.now()) this.cookies.delete(key);
    else this.cookies.set(key, cookie);
  }
  defaultPath(requestPath) {
    if (!requestPath || !requestPath.startsWith("/")) return "/";
    const cut = requestPath.lastIndexOf("/");
    return cut <= 0 ? "/" : requestPath.slice(0, cut);
  }
  header(requestPath, isScript = false) {
    const now = Date.now();
    const matched = [];
    for (const [key, cookie] of this.cookies) {
      if (cookie.expires !== null && cookie.expires <= now) { this.cookies.delete(key); continue; }
      if (isScript && cookie.isHttpOnly) continue;
      if (requestPath === cookie.path || (requestPath.startsWith(cookie.path) && (cookie.path.endsWith("/") || requestPath[cookie.path.length] === "/"))) matched.push(cookie);
    }
    matched.sort((a, b) => b.path.length - a.path.length);
    return matched.map((cookie) => cookie.name + "=" + cookie.value).join("; ");
  }
}

// --- HTTP ------------------------------------------------------------------

const CRLF2 = new Uint8Array([13, 10, 13, 10]);
const CRLF = new Uint8Array([13, 10]);

class HttpParser {
  constructor(method, handlers) {
    this.method = method; this.handlers = handlers;
    this.queue = new ByteQueue();
    this.state = "head"; this.remaining = 0; this.searchFrom = 0; this.isDone = false;
  }
  feed(u8) {
    this.queue.push(u8);
    for (;;) {
      if (this.isDone) { const rest = this.queue.takeAll(); if (rest.length && this.handlers.raw) this.handlers.raw(rest); return; }
      if (this.state === "head") {
        const end = this.queue.indexOf(CRLF2, this.searchFrom);
        if (end < 0) { this.searchFrom = Math.max(0, this.queue.length - 3); return; }
        const head = latin1(this.queue.take(end + 4));
        this.searchFrom = 0;
        if (!this.head(head)) return;
        continue;
      }
      if (this.state === "fixed" || this.state === "chunk-data") {
        if (!this.queue.length) return;
        const piece = this.queue.take(Math.min(this.remaining, this.queue.length));
        this.remaining -= piece.length;
        this.handlers.body(piece);
        if (this.remaining === 0) { if (this.state === "fixed") this.finish(); else this.state = "chunk-end"; }
        continue;
      }
      if (this.state === "chunk-size") {
        const end = this.queue.indexOf(CRLF);
        if (end < 0) return;
        const size = parseInt(latin1(this.queue.take(end + 2)).trim().split(";")[0], 16);
        if (Number.isNaN(size)) { this.isDone = true; this.handlers.error(); return; }
        if (size === 0) { this.state = "trailer"; continue; }
        this.remaining = size; this.state = "chunk-data";
        continue;
      }
      if (this.state === "chunk-end") {
        if (this.queue.length < 2) return;
        this.queue.take(2);
        this.state = "chunk-size";
        continue;
      }
      if (this.state === "trailer") {
        const end = this.queue.indexOf(CRLF);
        if (end < 0) return;
        if (this.queue.take(end + 2).length === 2) this.finish();
        continue;
      }
      if (this.state === "until-close" && this.queue.length) this.handlers.body(this.queue.takeAll());
      return;
    }
  }
  head(text) {
    const lines = text.split("\r\n");
    const [version, statusText, ...rest] = lines[0].split(" ");
    const status = Number(statusText);
    if (!version.startsWith("HTTP/") || Number.isNaN(status)) { this.isDone = true; this.handlers.error(); return false; }
    const headers = [];
    for (const line of lines.slice(1)) {
      const cut = line.indexOf(":");
      if (cut > 0) headers.push([line.slice(0, cut).trim(), line.slice(cut + 1).trim()]);
    }
    if (status >= 100 && status < 200 && status !== 101) return true;
    const header = (name) => { const found = headers.find(([key]) => key.toLowerCase() === name); return found ? found[1] : ""; };
    const connection = header("connection").toLowerCase().split(",").map((token) => token.trim());
    const isClosing = connection.includes("close") || (version === "HTTP/1.0" && !connection.includes("keep-alive"));
    this.handlers.head({ status, statusText: rest.join(" "), headers, isClosing });
    if (status === 101) { this.isDone = true; return true; }
    if (this.method === "HEAD" || status === 204 || status === 304) { this.finish(); return true; }
    if (header("transfer-encoding").toLowerCase().includes("chunked")) { this.state = "chunk-size"; return true; }
    const length = header("content-length");
    if (length !== "") { this.remaining = Number(length); this.state = "fixed"; if (this.remaining === 0) this.finish(); return true; }
    this.state = "until-close";
    return true;
  }
  finish() { this.state = "head"; this.remaining = 0; this.handlers.end(); }
  // The stream ended while a request waits for its response.
  end() {
    if (this.isDone) return;
    this.isDone = true;
    if (this.state === "until-close") this.handlers.end();
    else this.handlers.error();
  }
}

function requestHead(method, path, headers) {
  let text = method + " " + path + " HTTP/1.1\r\n";
  for (const [name, value] of headers) text += name + ": " + value + "\r\n";
  return encoder.encode(text + "\r\n");
}

// A connect stream to the entry that sends HTTP/1.1 requests one at a time.
class HttpConnection {
  constructor(pool) {
    this.pool = pool;
    this.stream = pool.mux.open();
    this.records = new RecordReader();
    this.isRaw = false; this.isUsable = true; this.current = null;
    this.served = 0;
    this.stream.handlers = {
      data: (u8) => {
        if (this.isRaw) { if (this.current) this.current.parser.feed(u8); return; }
        for (const record of this.records.feed(u8)) {
          if (record.type === RECORD.accept) { this.isRaw = true; const rest = this.records.rest(); if (rest.length && this.current) this.current.parser.feed(rest); break; }
          if (record.type === RECORD.close) { this.fail(parseRefusal(record.payload).code); return; }
        }
      },
      end: () => { this.isUsable = false; if (this.current) this.current.parser.end(); else this.pool.forget(this); },
      error: () => this.fail(""),
    };
    this.stream.write(encodeRecord(RECORD.open, json({ kind: "connect", id: pool.entry })));
  }
  send(request, sink) {
    const parser = new HttpParser(request.method, {
      head: (head) => { this.isClosingAfter = head.isClosing; this.current.hasHead = true; sink.head(head); },
      body: (piece) => sink.body(piece),
      end: () => {
        this.current = null;
        this.served++;
        sink.end();
        if (this.isClosingAfter || !this.isUsable) { this.isUsable = false; this.stream.close(); this.pool.forget(this); } else this.pool.release(this);
      },
      error: () => this.fail(""),
    });
    this.current = { request, sink, parser };
    this.stream.write(requestHead(request.method, request.path, request.headers));
    if (request.body && request.body.length) this.stream.write(request.body);
  }
  // Ends the connection. The code is the hub's close code, empty for a broken
  // stream. A GET or HEAD on a reused stream that ended before its response
  // is sent again on a new stream.
  fail(code) {
    if (!this.isUsable && !this.current) return;
    this.isUsable = false;
    const current = this.current;
    this.current = null;
    this.stream.reset();
    this.pool.forget(this);
    if (current && !code && !current.hasHead && this.served > 0 && ["GET", "HEAD"].includes(current.request.method)) this.pool.resend(current.request, current.sink);
    else if (current) current.sink.fail(code);
    if (code) this.pool.onCode(code);
  }
}

class HttpPool {
  constructor(mux, entry, jar, onCode) {
    this.mux = mux; this.entry = entry; this.jar = jar; this.onCode = onCode;
    this.idle = []; this.active = new Set(); this.waiting = [];
    this.byRequest = new Map();
  }
  // Sends a request. The sink takes head, body, end and fail(code).
  request(request, sink) {
    const headers = [["Host", HTTP.host]];
    let hasAcceptEncoding = false;
    for (const [name, value] of request.headers || []) {
      const lower = name.toLowerCase();
      if (["host", "cookie", "connection", "content-length", "transfer-encoding", "keep-alive"].includes(lower)) continue;
      if (lower === "origin") { headers.push(["Origin", "http://" + HTTP.host]); continue; }
      if (lower === "referer") { headers.push(["Referer", onHost(value)]); continue; }
      if (lower === "accept-encoding") { hasAcceptEncoding = true; headers.push([name, "gzip, deflate"]); continue; }
      headers.push([name, value]);
    }
    if (!hasAcceptEncoding && typeof DecompressionStream === "function") headers.push(["Accept-Encoding", "gzip, deflate"]);
    const path = request.path.split("?")[0];
    const cookie = this.jar.header(path);
    if (cookie) headers.push(["Cookie", cookie]);
    if (request.body && request.body.length) headers.push(["Content-Length", String(request.body.length)]);
    else if (request.method !== "GET" && request.method !== "HEAD") headers.push(["Content-Length", "0"]);
    const wrapped = {
      head: (head) => {
        const kept = [];
        let hasSetCookie = false;
        for (const [name, value] of head.headers) {
          const lower = name.toLowerCase();
          if (lower === "set-cookie") { hasSetCookie = true; this.jar.set(value, path); continue; }
          kept.push([name, lower === "location" ? relativeLocation(value) : value]);
        }
        sink.head({ status: head.status, statusText: head.statusText, headers: kept, hasSetCookie });
      },
      body: sink.body,
      end: () => { this.byRequest.delete(request.id); sink.end(); },
      fail: (code) => { this.byRequest.delete(request.id); sink.fail(code); },
    };
    this.acquire((connection) => {
      if (request.id !== undefined) this.byRequest.set(request.id, connection);
      connection.send({ method: request.method, path: request.path, headers, body: request.body }, wrapped);
    }, () => wrapped.fail(""));
  }
  resend(request, sink) {
    if (this.mux.isEnded) { sink.fail(""); return; }
    const connection = new HttpConnection(this);
    this.active.add(connection);
    connection.send(request, sink);
  }
  // Drops the connection of a request the page no longer reads.
  abort(id) {
    const connection = this.byRequest.get(id);
    if (connection && connection.current) { connection.current.sink = { head() {}, body() {}, end() {}, fail() {} }; connection.fail(""); }
  }
  // Gives a request a connection, or fails it once the session ended.
  acquire(use, fail) {
    if (this.mux.isEnded) { fail(); return; }
    while (this.idle.length) { const connection = this.idle.pop(); if (connection.isUsable) { this.active.add(connection); use(connection); return; } }
    if (this.active.size < HTTP.streamsMax) { const connection = new HttpConnection(this); this.active.add(connection); use(connection); return; }
    this.waiting.push([use, fail]);
  }
  release(connection) {
    this.active.delete(connection);
    if (this.waiting.length) { this.active.add(connection); this.waiting.shift()[0](connection); return; }
    this.idle.push(connection);
  }
  forget(connection) {
    this.active.delete(connection);
    const index = this.idle.indexOf(connection);
    if (index >= 0) this.idle.splice(index, 1);
    while (this.waiting.length && (this.mux.isEnded || this.active.size < HTTP.streamsMax)) this.acquire(...this.waiting.shift());
  }
  fetchWhole(method, path) {
    return new Promise((resolve, reject) => {
      let head = null;
      this.request({ method, path, headers: [] }, {
        head: (h) => { head = h; },
        body: () => {},
        end: () => resolve(head),
        fail: (code) => reject(new Refusal(screenOf(code), code)),
      });
    });
  }
}

// An absolute Location on the app's own host, as a path.
function relativeLocation(value) {
  try {
    const url = new URL(value, "http://" + HTTP.host + "/");
    if (url.hostname === HTTP.host || url.hostname === "localhost") return url.pathname + url.search + url.hash;
  } catch (e) { /* a Location that is not a URL passes unchanged */ }
  return value;
}

// A Referer of the page's origin, on the app's own host.
function onHost(value) {
  try {
    const url = new URL(value);
    if (url.origin === location.origin) return "http://" + HTTP.host + url.pathname + url.search;
  } catch (e) { /* a Referer that is not a URL passes unchanged */ }
  return value;
}

// --- WebSockets --------------------------------------------------------------

const WS = { text: 1, binary: 2, close: 8, ping: 9, pong: 10 };

// Opens a WebSocket of the app over a connect stream, framed by RFC 6455.
function openWebSocket(session, url, protocols, handlers) {
  const target = new URL(url, location.href);
  const stream = session.mux.open();
  const records = new RecordReader();
  const frames = new ByteQueue();
  const key = btoa(latin1(crypto.getRandomValues(new Uint8Array(16))));
  const headers = [["Host", HTTP.host], ["Upgrade", "websocket"], ["Connection", "Upgrade"], ["Sec-WebSocket-Key", key], ["Sec-WebSocket-Version", "13"], ["Origin", "http://" + HTTP.host]];
  const wanted = Array.isArray(protocols) ? protocols : (protocols ? [protocols] : []);
  if (wanted.length) headers.push(["Sec-WebSocket-Protocol", wanted.join(", ")]);
  const cookie = session.jar.header(target.pathname);
  if (cookie) headers.push(["Cookie", cookie]);
  let isRaw = false, isOpen = false, isClosed = false;
  let fragments = [], fragmentOpcode = 0;
  const finish = (code, reason, wasClean) => {
    if (isClosed) return;
    isClosed = true;
    stream.close();
    handlers.close(code, reason, wasClean);
  };
  const sendFrame = (opcode, payload) => {
    if (isClosed) return;
    const mask = crypto.getRandomValues(new Uint8Array(4));
    const headerLength = payload.length >= 65536 ? 10 : (payload.length >= 126 ? 4 : 2);
    const frame = new Uint8Array(headerLength + 4 + payload.length);
    const view = new DataView(frame.buffer);
    frame[0] = 0x80 | opcode;
    if (headerLength === 2) frame[1] = 0x80 | payload.length;
    else if (headerLength === 4) { frame[1] = 0x80 | 126; view.setUint16(2, payload.length); }
    else { frame[1] = 0x80 | 127; view.setUint32(2, Math.floor(payload.length / 4294967296)); view.setUint32(6, payload.length >>> 0); }
    frame.set(mask, headerLength);
    for (let i = 0; i < payload.length; i++) frame[headerLength + 4 + i] = payload[i] ^ mask[i & 3];
    stream.write(frame);
  };
  const readFrames = (u8) => {
    frames.push(u8);
    while (frames.length >= 2) {
      const head = frames.peek(Math.min(14, frames.length));
      const view = new DataView(head.buffer);
      const isFinal = (head[0] & 0x80) !== 0, opcode = head[0] & 0x0f, isMasked = (head[1] & 0x80) !== 0;
      let length = head[1] & 0x7f, offset = 2;
      if (length === 126) { if (head.length < 4) return; length = view.getUint16(2); offset = 4; }
      else if (length === 127) { if (head.length < 10) return; length = view.getUint32(2) * 4294967296 + view.getUint32(6); offset = 10; }
      if (isMasked) offset += 4;
      if (frames.length < offset + length) return;
      const whole = frames.take(offset + length);
      const payload = whole.subarray(offset);
      if (isMasked) { const mask = whole.subarray(offset - 4, offset); for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i & 3]; }
      if (opcode === WS.ping) { sendFrame(WS.pong, payload); continue; }
      if (opcode === WS.pong) continue;
      if (opcode === WS.close) {
        const code = payload.length >= 2 ? (payload[0] << 8) | payload[1] : 1005;
        sendFrame(WS.close, payload.subarray(0, Math.min(payload.length, 2)));
        finish(code, payload.length > 2 ? decoder.decode(payload.subarray(2)) : "", true);
        return;
      }
      if (opcode === 0) fragments.push(payload); else { fragmentOpcode = opcode; fragments = [payload]; }
      if (!isFinal) continue;
      let message = fragments[0];
      if (fragments.length > 1) {
        message = new Uint8Array(fragments.reduce((sum, part) => sum + part.length, 0));
        let at = 0;
        for (const part of fragments) { message.set(part, at); at += part.length; }
      }
      fragments = [];
      handlers.message(fragmentOpcode === WS.text ? decoder.decode(message) : message.slice());
    }
  };
  const parser = new HttpParser("GET", {
    head: (head) => {
      if (head.status !== 101) { handlers.error(); finish(1006, "", false); return; }
      const accepted = head.headers.find(([name]) => name.toLowerCase() === "sec-websocket-protocol");
      isOpen = true;
      handlers.open(accepted ? accepted[1] : "");
    },
    body: () => {}, end: () => {},
    error: () => { handlers.error(); finish(1006, "", false); },
    raw: readFrames,
  });
  stream.handlers = {
    data: (u8) => {
      if (isRaw) { parser.feed(u8); return; }
      for (const record of records.feed(u8)) {
        if (record.type === RECORD.accept) { isRaw = true; const rest = records.rest(); if (rest.length) parser.feed(rest); break; }
        if (record.type === RECORD.close) { handlers.error(); finish(1006, "", false); session.onCode(parseRefusal(record.payload).code); return; }
      }
    },
    end: () => finish(1006, "", false),
    error: () => finish(1006, "", false),
  };
  stream.write(encodeRecord(RECORD.open, json({ kind: "connect", id: session.entry })));
  stream.write(requestHead("GET", target.pathname + target.search, headers));
  return {
    send: (data) => {
      if (!isOpen || isClosed) return;
      if (typeof data === "string") sendFrame(WS.text, encoder.encode(data));
      else sendFrame(WS.binary, ArrayBuffer.isView(data) ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength) : new Uint8Array(data));
    },
    close: (code, reason) => {
      if (isClosed) return;
      const reasonBytes = encoder.encode(reason || "");
      const payload = new Uint8Array(2 + reasonBytes.length);
      payload[0] = (code || 1000) >> 8; payload[1] = (code || 1000) & 255; payload.set(reasonBytes, 2);
      sendFrame(WS.close, payload);
      setTimeout(() => finish(code || 1000, reason || "", true), 1000);
    },
  };
}

// --- a session -------------------------------------------------------------

// An admitted connection to the hub: the channel, yamux, the control stream
// and the pool of connect streams.
class Session {
  constructor({ pc, dc, mux, control, entry, jar, onCode }) {
    this.pc = pc; this.dc = dc; this.mux = mux; this.control = control;
    this.entry = entry; this.jar = jar; this.onCode = onCode;
    this.pool = new HttpPool(mux, entry, jar, onCode);
    this.pingSentAt = 0; this.pongAt = 0; this.nonce = 0;
    this.isClosed = false;
  }
  // The service frame's reply for the share's entry.
  async service(deadline) {
    const request = "service-" + (++this.nonce);
    this.control.write({ type: "service", request, id: this.entry });
    const reply = await this.control.next((frame) => frame.type === "reply" && frame.request === request, deadline);
    if (reply.type === "refused") throw new Refusal(screenOf(reply.code) === "link" ? "link" : "hub", reply.code);
    if (reply.type !== "reply") throw new Refusal("hub", "ended");
    return reply;
  }
  // Opens a connect stream to the entry and resets it once the hub accepts or closes it.
  // The code is empty when the hub accepted the stream, else its close's code.
  probe(deadline) {
    const stream = this.mux.open();
    const records = new RecordReader();
    const answer = new Promise((resolve) => {
      stream.handlers = {
        data: (u8) => {
          for (const record of records.feed(u8)) {
            if (record.type === RECORD.accept) { resolve(""); return; }
            if (record.type === RECORD.close) { resolve(parseRefusal(record.payload).code || "ended"); return; }
          }
        },
        end: () => resolve("ended"),
        error: () => resolve("ended"),
      };
    });
    stream.write(encodeRecord(RECORD.open, json({ kind: "connect", id: this.entry })));
    return within(answer, deadline).finally(() => stream.reset());
  }
  ping() {
    const nonce = "p" + (++this.nonce);
    if (this.pingSentAt <= this.pongAt) this.pingSentAt = performance.now();
    this.control.write({ type: "ping", nonce });
  }
  // Whether the line counts as dropped: a ping with no pong and no byte for the silent span.
  isSilent() {
    return this.pingSentAt > this.pongAt && performance.now() - this.mux.lastByteAt >= TIMING.silent;
  }
  close() {
    if (this.isClosed) return;
    this.isClosed = true;
    this.mux.onEnd = null;
    this.mux.end();
    try { this.pc.close(); } catch (e) { /* already closed */ }
  }
}

// Opens a session by the deadline: the channel, the open record, yamux and the hello.
async function openSession(facts, jar, deadline, onCode) {
  const { pc, dc } = await openChannel(facts, deadline);
  try {
    const admitted = await admit(dc, facts, deadline);
    const mux = new Yamux(dc);
    if (admitted.rest.length) mux.feed(admitted.rest);
    const control = new ControlStream(mux);
    await within(control.accepted, deadline);
    control.write({ type: "hello", protocol: PROTOCOL, role: "guest", id: admitted.id, name: "guest", software: "neutrino_share_page/" + LINK_FORM });
    const welcome = await control.next((frame) => frame.type === "welcome", deadline);
    if (welcome.type === "refused") throw new Refusal(PASSING_CODES.includes(welcome.code) ? "hub" : "link", welcome.code);
    if (welcome.type !== "welcome") throw new Refusal("hub", "ended");
    return new Session({ pc, dc, mux, control, entry: facts.app.entry, jar, onCode });
  } catch (error) {
    pc.close();
    throw error instanceof Refusal ? error : new Refusal("hub", "session");
  }
}

// --- the tab's title and icon ---------------------------------------------

const mirror = {
  frame: null,
  observer: null,
  // The link's app title, the tab's title while the app's page has none.
  title: "",
  watch(frame, title) {
    this.frame = frame;
    this.title = title;
    frame.addEventListener("load", () => {
      if (this.observer) this.observer.disconnect();
      try {
        this.observer = new MutationObserver(() => this.apply());
        this.observer.observe(frame.contentDocument.head || frame.contentDocument.documentElement, { subtree: true, childList: true, characterData: true, attributes: true });
      } catch (e) { /* a document the shell cannot read keeps the last title */ }
      this.apply();
      if (!stats.appLoadMs) stats.appLoadMs = performance.now() - stats.startedAt;
    });
  },
  apply() {
    if (screen.kind !== "app" || !this.frame) return;
    try {
      const doc = this.frame.contentDocument;
      document.title = doc.title || this.title;
      const icon = doc.querySelector("link[rel~='icon']");
      document.getElementById("icon").href = icon ? icon.href : "/favicon.ico";
    } catch (e) { /* a document the shell cannot read keeps the last title */ }
  },
};

// --- the service worker ----------------------------------------------------

const worker = {
  tab: crypto.randomUUID(),
  onRequest: null,
  // Registers the worker and announces this tab once it controls the page.
  async start(cache) {
    this.cache = cache;
    window.__neutrinoTab = this.tab;
    await navigator.serviceWorker.register("/__neutrino/sw.js", { scope: "/" });
    const registration = await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) {
      const changed = new Promise((resolve) => navigator.serviceWorker.addEventListener("controllerchange", resolve, { once: true }));
      registration.active.postMessage({ type: "claim" });
      await within(changed, performance.now() + TIMING.open);
    }
    navigator.serviceWorker.addEventListener("message", (event) => {
      if (event.data && event.data.type === "announce") this.announce();
    });
    navigator.serviceWorker.addEventListener("controllerchange", () => this.announce());
    navigator.serviceWorker.startMessages();
    await this.announce();
  },
  // Gives the worker a port for this tab's requests. A restarted worker asks again.
  announce() {
    const target = navigator.serviceWorker.controller;
    if (!target) return Promise.resolve();
    const channel = new MessageChannel();
    return new Promise((resolve) => {
      channel.port1.onmessage = (event) => {
        if (event.data && event.data.type === "ready") { resolve(); return; }
        if (this.onRequest) this.onRequest(event.data, channel.port1, event.ports[0]);
      };
      target.postMessage({ type: "shell", tab: this.tab, cache: this.cache }, [channel.port2]);
    });
  },
};

// --- the page ----------------------------------------------------------------

const page = {
  facts: null,
  jar: new CookieJar(),
  session: null,
  isFrameLoaded: false,
  isEnded: false,
  // Requests that wait for a session, as [message, port].
  waiting: [],
  connecting: null,
  unavailableTimer: 0,
  // Whether the shared app is down: a connect close named one of APP_DOWN_CODES,
  // and no connect to the entry was accepted since.
  isAppDown: false,
  // Whether the frame's last navigation failed.
  isFrameFailed: false,
  // Whether the page the shell last loaded into the frame reached its load event.
  isPageLoaded: false,
  // Whether a request of that page failed before its load event.
  isPageBroken: false,

  async start() {
    if (window.top !== window) { screen.refuse("link"); return; }
    this.facts = readFacts() || (await factsFromOpener());
    if (!this.facts) { screen.refuse("link"); return; }
    const title = this.facts.app.title || "";
    screen.loading(title);
    const slowTimer = setTimeout(() => screen.slow(), TIMING.slow);
    mirror.watch(document.getElementById("app"), title);
    worker.onRequest = (message, port, reply) => this.take(message, port, reply);
    const started = worker.start(cacheName(this.facts)).catch(() => { stats.isWorkerFailed = true; });
    const deadline = stats.startedAt + TIMING.open;
    let session = null;
    while (!session && !this.isEnded) {
      try {
        session = await openSession(this.facts, this.jar, deadline, (code) => this.onCode(code));
      } catch (error) {
        if (error.screen === "link") { this.endShare(); return; }
        if (performance.now() >= deadline) break;
        await sleep(Math.min(2000, deadline - performance.now()));
      }
    }
    clearTimeout(slowTimer);
    await started;
    if (stats.isWorkerFailed) { if (session) session.close(); screen.refuse("hub"); return; }
    if (!session) { screen.refuse("hub"); this.reconnect(false); return; }
    stats.admitMs = performance.now() - stats.startedAt;
    this.use(session);
    await this.check(deadline + TIMING.open);
  },

  // Makes a session the live one and watches its line.
  use(session) {
    if (this.session) this.session.close();
    this.session = session;
    session.mux.onEnd = () => this.drop(session);
    session.control.onFrame = (frame) => {
      if (frame.type === "pong") session.pongAt = performance.now();
      else if (frame.type === "refused") { if (SHARE_CODES.includes(frame.code)) this.endShare(); else this.drop(session); }
      else if (frame.type === "ended") this.drop(session);
    };
    clearInterval(this.watcher);
    this.watcher = setInterval(() => { if (this.session === session && session.isSilent()) this.drop(session); }, 1000);
    for (const [message, port] of this.waiting.splice(0)) this.serve(message, port);
  },

  // Asks for the share's entry and shows the app, the app-unavailable screen or the link screen.
  // After the shared app was down, a connect to the entry must be accepted too, and the frame loads again.
  // After the app-unavailable screen, the frame also loads again when its last navigation failed.
  // The frame also loads again when a request of its page failed before the page's load event.
  async check(deadline) {
    const session = this.session;
    if (!session || this.isEnded) return;
    const serial = screen.serial;
    const wasAppDown = this.isAppDown;
    const wasUnavailable = screen.kind === "unavailable";
    let reply, code;
    try {
      reply = await session.service(deadline);
      code = reply.code || (wasAppDown ? await session.probe(deadline) : "");
    } catch (error) {
      if (error.screen === "link") { this.endShare(); return; }
      this.drop(session);
      return;
    }
    if (this.session !== session) return;
    if (code) {
      const kind = screenOf(code);
      if (kind === "link") { this.endShare(); return; }
      if (kind === "hub") { screen.refuse("hub"); this.drop(session, true); return; }
      this.showUnavailable(code);
      return;
    }
    if (screen.serial !== serial) return;
    this.isAppDown = false;
    if (!this.isFrameLoaded) {
      try {
        await this.load(session, reply.params && reply.params.token);
      } catch (error) {
        if (error.screen === "link") { this.endShare(); return; }
        if (error.screen === "unavailable") { this.onCode(error.code); return; }
        this.drop(session);
        return;
      }
    } else if (wasAppDown || (wasUnavailable && this.isFrameFailed) || this.isPageBroken) {
      await this.reload(deadline);
    }
    if (this.session === session && screen.serial === serial) screen.app();
  },

  // Signs the visitor in where the reply has a token, then loads the app in the frame.
  async load(session, token) {
    let start = location.pathname.startsWith("/__neutrino") ? (this.facts.app.path || "/") : location.pathname + location.search;
    if (token) {
      const answer = await session.pool.fetchWhole("GET", "/?tkn=" + encodeURIComponent(token));
      const where = answer.headers.find(([name]) => name.toLowerCase() === "location");
      if (where && start === "/" && !this.facts.app.path) start = where[1];
    }
    const url = new URL(start, location.origin);
    url.searchParams.set(TAB_PARAM, worker.tab);
    const frame = document.getElementById("app");
    const loaded = new Promise((resolve) => frame.addEventListener("load", resolve, { once: true }));
    frame.src = url.pathname + url.search + url.hash;
    this.isFrameLoaded = true;
    stats.appStartMs = performance.now() - stats.startedAt;
    await loaded;
    this.isPageLoaded = true;
  },

  // Loads the frame's page again as a refresh does, and waits for it until the deadline.
  async reload(deadline) {
    const frame = document.getElementById("app");
    const loaded = new Promise((resolve) => frame.addEventListener("load", resolve, { once: true }));
    try {
      frame.contentWindow.location.reload();
    } catch (e) {
      return;
    }
    this.isPageLoaded = false;
    this.isPageBroken = false;
    loaded.then(() => { this.isPageLoaded = true; });
    await within(loaded, deadline).catch(() => {});
  },

  // A close code from a connect stream.
  onCode(code) {
    const kind = screenOf(code);
    if (kind === "link") { this.endShare(); return; }
    if (kind === "unavailable") { this.showUnavailable(code); return; }
    if (this.session) { screen.refuse("hub"); this.drop(this.session, true); }
  },

  // Shows the app-unavailable screen. The page asks for the entry again after
  // TIMING.retry, unless that ask is already scheduled.
  showUnavailable(code) {
    if (this.isEnded) return;
    if (APP_DOWN_CODES.includes(code)) this.isAppDown = true;
    screen.refuse("unavailable");
    if (this.unavailableTimer) return;
    this.unavailableTimer = setTimeout(() => {
      this.unavailableTimer = 0;
      this.check(performance.now() + TIMING.open);
    }, TIMING.retry);
  },

  // The live session ended. The page tries again quietly, then shows the hub-offline screen.
  drop(session, isShown = false) {
    if (this.session !== session || this.isEnded) return;
    this.session = null;
    clearInterval(this.watcher);
    clearTimeout(this.unavailableTimer);
    this.unavailableTimer = 0;
    session.close();
    stats.drops = (stats.drops || 0) + 1;
    this.reconnect(!isShown);
  },

  // Opens sessions until a session is admitted, quietly for a while and then behind the hub-offline screen.
  reconnect(isQuiet) {
    if (this.connecting || this.isEnded) return;
    this.connecting = (async () => {
      const quietUntil = performance.now() + (isQuiet ? TIMING.quiet : 0);
      let session = null;
      while (!session && !this.isEnded && performance.now() < quietUntil) {
        const tryStarted = performance.now();
        try {
          session = await openSession(this.facts, this.jar, Math.max(quietUntil, tryStarted + TIMING.retry), (code) => this.onCode(code));
        } catch (error) {
          if (error.screen === "link") { this.connecting = null; this.endShare(); return; }
          if (performance.now() < quietUntil) await sleep(1000);
        }
      }
      if (!session && !this.isEnded) session = await this.retryShown();
      this.connecting = null;
      if (!session || this.isEnded) { if (session) session.close(); return; }
      stats.reconnects = (stats.reconnects || 0) + 1;
      this.use(session);
      await this.check(performance.now() + TIMING.open);
    })();
  },

  // Starts a try every TIMING.retry behind the hub-offline screen, whatever the tries before it are doing.
  // It resolves with the first session admitted, the others closed, or with null once the share ended.
  retryShown() {
    return new Promise((resolve) => {
      let isSettled = false;
      let timer = 0;
      const settle = (session) => { isSettled = true; clearInterval(timer); resolve(session); };
      const start = () => {
        if (isSettled) return;
        if (this.isEnded) { settle(null); return; }
        if (screen.kind !== "hub") screen.refuse("hub");
        this.failWaiting();
        openSession(this.facts, this.jar, performance.now() + TIMING.open, (code) => this.onCode(code)).then(
          (session) => { if (isSettled) session.close(); else settle(session); },
          (error) => { if (error.screen === "link" && !isSettled) { settle(null); this.endShare(); } },
        );
      };
      timer = setInterval(start, TIMING.retry);
      start();
    });
  },

  // The share ended. The page shows the link screen and deletes the app's cache.
  endShare() {
    if (this.isEnded) return;
    this.isEnded = true;
    clearInterval(this.watcher);
    clearTimeout(this.unavailableTimer);
    this.unavailableTimer = 0;
    if (this.session) { this.session.close(); this.session = null; }
    screen.refuse("link");
    this.failWaiting();
    sessionStorage.removeItem(KEPT_FACTS);
    if (self.caches) caches.delete(cacheName(this.facts)).catch(() => {});
  },

  // A message of the worker: a request of the app's frame, an abort of one, or a new tab's ask for the facts.
  take(message, port, reply) {
    if (!message) return;
    if (message.type === "facts") { if (reply) reply.postMessage(this.isEnded ? null : this.facts); return; }
    if (message.type === "abort") { if (this.session) this.session.pool.abort(message.id); return; }
    if (message.type !== "fetch") return;
    if (this.isEnded) { this.fail(message, port, "share_unknown"); return; }
    if (this.session && !this.connecting) this.serve(message, port);
    else if (screen.kind === "hub") this.fail(message, port, "hub_offline");
    else this.waiting.push([message, port]);
  },

  serve(message, port) {
    const { id, method, url, headers, body } = message;
    this.session.pool.request({ id, method, path: url, headers, body: body ? new Uint8Array(body) : null }, {
      head: (head) => {
        if (message.isNavigation) this.isFrameFailed = false;
        port.postMessage({ type: "head", id, status: head.status, statusText: head.statusText, headers: head.headers, hasSetCookie: head.hasSetCookie });
      },
      body: (piece) => { const copy = piece.slice(); port.postMessage({ type: "chunk", id, data: copy.buffer }, [copy.buffer]); },
      end: () => port.postMessage({ type: "end", id }),
      fail: (code) => this.fail(message, port, code || "stream"),
    });
  },

  // Fails a request of the worker, and marks a failed navigation and a broken page of the frame.
  fail(message, port, code) {
    if (message.isNavigation) this.isFrameFailed = true;
    if (this.isFrameLoaded && !this.isPageLoaded) this.isPageBroken = true;
    port.postMessage({ type: "error", id: message.id, code });
  },

  failWaiting() {
    for (const [message, port] of this.waiting.splice(0)) this.fail(message, port, "hub_offline");
  },
};

// The shell's calls for the shim inside the app's pages.
window.__neutrino = {
  cookieGet: () => page.jar.header("/", true),
  cookieSet: (text) => page.jar.set(text, "/"),
  wsOpen: (url, protocols, handlers) => {
    if (!page.session) { setTimeout(() => { handlers.error(); handlers.close(1006, "", false); }, 0); return { send() {}, close() {} }; }
    return openWebSocket(page.session, url, protocols, handlers);
  },
};

// The heartbeat: a ping frame every TIMING.ping while the app is in use.
setInterval(() => {
  if (page.session && !page.connecting && (screen.kind === "app" || screen.kind === "unavailable")) page.session.ping();
}, TIMING.ping);

page.start().catch(() => { if (!page.isEnded) screen.refuse("hub"); });
