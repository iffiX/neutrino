"use strict";
// The shell of a Web share. It holds the one connection to the hub: a WebRTC
// data channel opened with static signalling from the link, the guest's open
// record with the share ticket, and a yamux client whose streams carry the
// control stream, HTTP requests and WebSockets to the one shared entry. The
// service worker hands it every request the app's iframe makes.

const PROTOCOL = 4;
const RECORD = { open: 1, accept: 2, data: 3, eof: 5, close: 8 };
const YAMUX = {
  data: 0, window: 1, ping: 2, goaway: 3,
  SYN: 1, ACK: 2, FIN: 4, RST: 8,
  headerBytes: 12, initialWindow: 256 * 1024, frameMax: 65507, receiveWindow: 4 * 1024 * 1024,
};
const CHANNEL = { label: "neutrino", messageMax: 64 * 1024, bufferedHigh: 4 * 1024 * 1024, bufferedLow: 1024 * 1024, openTimeoutMs: 15000 };
const HTTP = { host: "127.0.0.1", streamsMax: 8 };
const SCREENS = {
  link: ["This link is no longer valid.", "Ask the person who shared it for a new one."],
  hub: ["The hub is offline.", "The computer that shares this app cannot be reached right now."],
  machine: ["This machine is offline.", "The app's machine is not connected to its hub right now."],
};

const encoder = new TextEncoder();
const stats = { t0: performance.now(), requests: 0, bytesIn: 0, bytesOut: 0, routedByMapping: 0, routedByFallback: 0, wsTrace: [] };
const WS_TRACE_MAX = 400;
function traceWs(direction, data) {
  if (stats.wsTrace.length >= WS_TRACE_MAX) stats.wsTrace.shift();
  stats.wsTrace.push({ t: performance.now(), direction, text: typeof data === "string" ? data.slice(0, 160) : "<" + data.byteLength + " bytes>" });
}
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
  const padded = text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - text.length % 4) % 4);
  const binary = atob(padded);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
}

// --- the link --------------------------------------------------------------

function readPayload() {
  const fragment = location.hash.slice(1);
  let payload = null;
  if (fragment) {
    try { payload = JSON.parse(new TextDecoder().decode(base64urlDecode(fragment))); } catch (e) { payload = null; }
    if (payload) sessionStorage.setItem("neutrino_share", JSON.stringify(payload));
  }
  if (!payload) {
    const kept = sessionStorage.getItem("neutrino_share");
    if (kept) payload = JSON.parse(kept);
  }
  return payload;
}

// --- screens ---------------------------------------------------------------

const screen = {
  elements: null,
  bind() {
    this.elements = { screen: document.getElementById("screen"), spinner: document.getElementById("spinner"), title: document.getElementById("title"), detail: document.getElementById("detail"), app: document.getElementById("app") };
  },
  loading(title) {
    this.elements.spinner.classList.remove("hidden");
    this.elements.title.textContent = title ? "Loading " + title : "Loading";
    this.elements.detail.textContent = "";
    this.elements.screen.classList.remove("hidden");
    this.elements.app.style.display = "none";
  },
  refuse(kind) {
    const [title, detail] = SCREENS[kind] || SCREENS.hub;
    this.elements.spinner.classList.add("hidden");
    this.elements.title.textContent = title;
    this.elements.detail.textContent = detail;
    this.elements.screen.classList.remove("hidden");
    this.elements.app.style.display = "none";
    document.title = title;
    stats.refusal = kind;
  },
  app() {
    this.elements.screen.classList.add("hidden");
    this.elements.app.style.display = "block";
  },
};

// --- the channel -----------------------------------------------------------

function hubOffer(payload) {
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
    "a=ice-ufrag:" + payload.ice.ufrag,
    "a=ice-pwd:" + payload.ice.pwd,
    "a=fingerprint:sha-256 " + payload.hub.fp,
    "a=setup:actpass",
    "a=sctp-port:5000",
    "a=max-message-size:262144",
    "a=candidate:1 1 tcp 2130706431 " + payload.hub.ip + " " + payload.hub.port + " typ host tcptype passive",
    "a=end-of-candidates",
    "",
  ].join("\r\n");
}

async function openChannel(payload) {
  const pc = new RTCPeerConnection({ iceServers: [] });
  const dc = pc.createDataChannel(CHANNEL.label, { negotiated: true, id: 0 });
  dc.binaryType = "arraybuffer";
  dc.bufferedAmountLowThreshold = CHANNEL.bufferedLow;
  const started = performance.now();
  await pc.setRemoteDescription({ type: "offer", sdp: hubOffer(payload) });
  const answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("hub")), CHANNEL.openTimeoutMs);
    dc.onopen = () => { clearTimeout(timer); resolve(); };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "failed" || pc.connectionState === "closed") { clearTimeout(timer); reject(new Error("hub")); }
    };
  });
  stats.channelOpenMs = performance.now() - started;
  return { pc, dc };
}

// --- yamux -----------------------------------------------------------------

class Yamux {
  constructor(channel) {
    this.channel = channel;
    this.queue = new ByteQueue();
    this.streams = new Map();
    this.nextID = 1;
    this.pings = new Map();
    this.nextPing = 1;
    this.onEnd = null;
    this.isEnded = false;
    channel.onmessage = (event) => { stats.bytesIn += event.data.byteLength; this.feed(new Uint8Array(event.data)); };
    channel.onbufferedamountlow = () => this.pumpAll();
    channel.onclose = () => this.end(new Error("hub"));
    channel.onerror = () => this.end(new Error("hub"));
  }
  sendFrame(type, flags, id, length, payload) {
    const frame = new Uint8Array(YAMUX.headerBytes + (payload ? payload.length : 0));
    const view = new DataView(frame.buffer);
    frame[0] = 0; frame[1] = type;
    view.setUint16(2, flags);
    view.setUint32(4, id);
    view.setUint32(8, length);
    if (payload) frame.set(payload, YAMUX.headerBytes);
    stats.bytesOut += frame.length;
    this.channel.send(frame);
  }
  feed(u8) {
    this.queue.push(u8);
    while (this.queue.length >= YAMUX.headerBytes) {
      const head = this.queue.peek(YAMUX.headerBytes);
      const view = new DataView(head.buffer);
      if (head[0] !== 0) { this.end(new Error("yamux version")); return; }
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
    if (type === YAMUX.ping) {
      if (flags & YAMUX.SYN) this.sendFrame(YAMUX.ping, YAMUX.ACK, 0, length);
      else { const waiter = this.pings.get(length); if (waiter) { this.pings.delete(length); waiter(); } }
      return;
    }
    if (type === YAMUX.goaway) { this.end(new Error("goaway " + length)); return; }
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
  ping() {
    return new Promise((resolve) => {
      const id = this.nextPing++;
      const started = performance.now();
      this.pings.set(id, () => resolve(performance.now() - started));
      this.sendFrame(YAMUX.ping, YAMUX.SYN, 0, id);
    });
  }
  end(error) {
    if (this.isEnded) return;
    this.isEnded = true;
    for (const stream of this.streams.values()) stream.fail(error);
    this.streams.clear();
    if (this.onEnd) this.onEnd(error);
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
    if (flags & YAMUX.RST) { this.fail(new Error("stream reset")); return; }
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
    this.mux.sendFrame(YAMUX.window, YAMUX.RST, this.id, 0);
    this.isWriteClosed = this.isReadClosed = true;
    this.mux.streams.delete(this.id);
  }
  forgetIfDone() { if (this.isWriteClosed && this.isReadClosed) this.mux.streams.delete(this.id); }
  fail(error) {
    if (this.isFailed) return;
    this.isFailed = true;
    this.mux.streams.delete(this.id);
    if (this.onError) this.onError(error);
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
  try { const parsed = JSON.parse(new TextDecoder().decode(payload)); return { code: parsed.code || "", params: parsed.params || {} }; } catch (e) { return { code: "malformed", params: {} }; }
}

// --- the control stream ----------------------------------------------------

class ControlStream {
  constructor(mux) {
    this.stream = mux.open();
    this.records = new RecordReader();
    this.decoder = new TextDecoder();
    this.text = "";
    this.frames = [];
    this.waiters = [];
    this.accepted = new Promise((resolve, reject) => { this.resolveAccept = resolve; this.rejectAccept = reject; });
    this.stream.handlers = {
      data: (u8) => {
        for (const record of this.records.feed(u8)) {
          if (record.type === RECORD.accept) this.resolveAccept();
          else if (record.type === RECORD.close) { const refusal = parseRefusal(record.payload); this.rejectAccept(refusal); this.push({ type: "refused", code: refusal.code, params: refusal.params }); }
          else if (record.type === RECORD.data) this.lines(this.decoder.decode(record.payload, { stream: true }));
        }
      },
      end: () => this.push({ type: "ended" }),
      error: () => this.push({ type: "ended" }),
    };
    this.stream.write(encodeRecord(RECORD.open, json({ kind: "control" })));
  }
  lines(text) {
    this.text += text;
    let index;
    while ((index = this.text.indexOf("\n")) >= 0) {
      const line = this.text.slice(0, index);
      this.text = this.text.slice(index + 1);
      if (line) { try { this.push(JSON.parse(line)); } catch (e) { /* a line that is not JSON is dropped */ } }
    }
  }
  push(frame) {
    this.frames.push(frame);
    for (const waiter of this.waiters.splice(0)) waiter();
  }
  writeFrame(frame) { this.stream.write(encodeRecord(RECORD.data, encoder.encode(JSON.stringify(frame) + "\n"))); }
  async next(types, timeoutMs = 15000) {
    const deadline = performance.now() + timeoutMs;
    for (;;) {
      const index = this.frames.findIndex((frame) => types.includes(frame.type));
      if (index >= 0) return this.frames.splice(index, 1)[0];
      const remaining = deadline - performance.now();
      if (remaining <= 0) throw new Error("hub");
      await new Promise((resolve) => { this.waiters.push(resolve); setTimeout(resolve, remaining); });
    }
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
      if (this.state === "fixed") {
        if (!this.queue.length) return;
        const piece = this.queue.take(Math.min(this.remaining, this.queue.length));
        this.remaining -= piece.length;
        this.handlers.body(piece);
        if (this.remaining === 0) this.finish();
        continue;
      }
      if (this.state === "chunk-size") {
        const end = this.queue.indexOf(CRLF);
        if (end < 0) return;
        const line = latin1(this.queue.take(end + 2)).trim();
        const size = parseInt(line.split(";")[0], 16);
        if (Number.isNaN(size)) { this.handlers.error(new Error("chunk size")); return; }
        if (size === 0) { this.state = "trailer"; continue; }
        this.remaining = size; this.state = "chunk-data";
        continue;
      }
      if (this.state === "chunk-data") {
        if (!this.queue.length) return;
        const piece = this.queue.take(Math.min(this.remaining, this.queue.length));
        this.remaining -= piece.length;
        this.handlers.body(piece);
        if (this.remaining === 0) this.state = "chunk-end";
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
        const line = this.queue.take(end + 2);
        if (line.length === 2) this.finish();
        continue;
      }
      if (this.state === "until-close") {
        if (this.queue.length) this.handlers.body(this.queue.takeAll());
        return;
      }
      return;
    }
  }
  head(text) {
    const lines = text.split("\r\n");
    const [version, statusText, ...rest] = lines[0].split(" ");
    const status = Number(statusText);
    if (!version.startsWith("HTTP/") || Number.isNaN(status)) { this.handlers.error(new Error("status line")); return false; }
    const headers = [];
    for (const line of lines.slice(1)) {
      if (!line) continue;
      const cut = line.indexOf(":");
      if (cut < 0) continue;
      headers.push([line.slice(0, cut).trim(), line.slice(cut + 1).trim()]);
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
  end() {
    if (this.isDone) return;
    if (this.state === "until-close") { this.isDone = true; this.handlers.end(); }
    else if (this.state !== "head") { this.isDone = true; this.handlers.error(new Error("response cut short")); }
  }
}

function requestHead(method, path, headers) {
  let text = method + " " + path + " HTTP/1.1\r\n";
  for (const [name, value] of headers) text += name + ": " + value + "\r\n";
  return encoder.encode(text + "\r\n");
}

class HttpConnection {
  constructor(pool) {
    this.pool = pool;
    this.stream = pool.mux.open();
    this.records = new RecordReader();
    this.isRaw = false; this.isUsable = true; this.current = null;
    this.stream.handlers = {
      data: (u8) => {
        if (this.isRaw) { if (this.current) this.current.parser.feed(u8); return; }
        for (const record of this.records.feed(u8)) {
          if (record.type === RECORD.accept) { this.isRaw = true; const rest = this.records.rest(); if (rest.length && this.current) this.current.parser.feed(rest); break; }
          if (record.type === RECORD.close) { this.fail(parseRefusal(record.payload)); return; }
        }
      },
      end: () => { this.isUsable = false; if (this.current) this.current.parser.end(); this.pool.forget(this); },
      error: () => { this.isUsable = false; this.fail({ code: "stream", params: {} }); this.pool.forget(this); },
    };
    this.stream.write(encodeRecord(RECORD.open, json({ kind: "connect", id: pool.entry })));
  }
  send(request, sink) {
    const parser = new HttpParser(request.method, {
      head: (head) => { this.closeAfter = head.isClosing || request.isClosing; sink.head(head); },
      body: (piece) => sink.body(piece),
      end: () => { const closeAfter = this.closeAfter; this.current = null; sink.end(); if (closeAfter) { this.isUsable = false; this.stream.close(); this.pool.forget(this); } else this.pool.release(this); },
      error: (error) => { this.isUsable = false; this.current = null; sink.fail({ code: "stream", params: { detail: String(error) } }); this.stream.reset(); this.pool.forget(this); },
    });
    this.current = { request, sink, parser };
    this.stream.write(requestHead(request.method, request.path, request.headers));
    if (request.body && request.body.length) this.stream.write(request.body);
  }
  fail(refusal) {
    this.isUsable = false;
    const current = this.current;
    this.current = null;
    if (current) current.sink.fail(refusal);
    this.pool.forget(this);
  }
}

class HttpPool {
  constructor(mux, entry, jar) {
    this.mux = mux; this.entry = entry; this.jar = jar;
    this.idle = []; this.active = new Set(); this.waiting = [];
  }
  request(request, sink) {
    const headers = [["Host", HTTP.host]];
    let hasAcceptEncoding = false;
    for (const [name, value] of request.headers || []) {
      const lower = name.toLowerCase();
      if (lower === "host" || lower === "cookie" || lower === "connection" || lower === "content-length" || lower === "transfer-encoding") continue;
      if (lower === "origin") { headers.push(["Origin", "http://" + HTTP.host]); continue; }
      if (lower === "accept-encoding") hasAcceptEncoding = true;
      headers.push([name, value]);
    }
    if (!hasAcceptEncoding && typeof DecompressionStream === "function") headers.push(["Accept-Encoding", "gzip"]);
    const cookie = this.jar.header(request.path.split("?")[0]);
    if (cookie) headers.push(["Cookie", cookie]);
    if (request.body && request.body.length) headers.push(["Content-Length", String(request.body.length)]);
    else if (request.method !== "GET" && request.method !== "HEAD") headers.push(["Content-Length", "0"]);
    stats.requests++;
    const path = request.path;
    const wrapped = {
      head: (head) => {
        const kept = [];
        for (const [name, value] of head.headers) {
          const lower = name.toLowerCase();
          if (lower === "set-cookie") { this.jar.set(value, path.split("?")[0]); continue; }
          if (lower === "location") { kept.push([name, relativeLocation(value)]); continue; }
          kept.push([name, value]);
        }
        sink.head({ status: head.status, statusText: head.statusText, headers: kept });
      },
      body: sink.body, end: sink.end, fail: sink.fail,
    };
    this.acquire((connection) => connection.send({ method: request.method, path, headers, body: request.body, isClosing: false }, wrapped));
  }
  acquire(use) {
    while (this.idle.length) { const connection = this.idle.pop(); if (connection.isUsable) { this.active.add(connection); use(connection); return; } }
    if (this.active.size < HTTP.streamsMax) { const connection = new HttpConnection(this); this.active.add(connection); use(connection); return; }
    this.waiting.push(use);
  }
  release(connection) {
    this.active.delete(connection);
    if (this.waiting.length) { const use = this.waiting.shift(); this.active.add(connection); use(connection); return; }
    this.idle.push(connection);
  }
  forget(connection) {
    this.active.delete(connection);
    const index = this.idle.indexOf(connection);
    if (index >= 0) this.idle.splice(index, 1);
    if (this.waiting.length && this.active.size < HTTP.streamsMax) this.acquire(this.waiting.shift());
  }
  fetchWhole(method, path, headers = [], body = null) {
    return new Promise((resolve, reject) => {
      const chunks = [];
      let head = null;
      this.request({ method, path, headers, body }, {
        head: (h) => { head = h; },
        body: (piece) => chunks.push(piece),
        end: () => resolve({ ...head, body: chunks }),
        fail: (refusal) => reject(refusal),
      });
    });
  }
}

function relativeLocation(value) {
  try {
    const url = new URL(value, "http://" + HTTP.host + "/");
    if (url.hostname === HTTP.host || url.hostname === "localhost") return url.pathname + url.search + url.hash;
  } catch (e) { /* a Location that is not a URL is passed as it is */ }
  return value;
}

// --- WebSockets --------------------------------------------------------------

const WS = { text: 1, binary: 2, close: 8, ping: 9, pong: 10 };

class WebSocketBridge {
  constructor(mux, entry, jar) { this.mux = mux; this.entry = entry; this.jar = jar; }
  open(url, protocols, handlers) {
    const target = new URL(url, location.href);
    const path = target.pathname + target.search;
    const stream = this.mux.open();
    const records = new RecordReader();
    const frames = new ByteQueue();
    const key = btoa(latin1(crypto.getRandomValues(new Uint8Array(16))));
    const headers = [["Host", HTTP.host], ["Upgrade", "websocket"], ["Connection", "Upgrade"], ["Sec-WebSocket-Key", key], ["Sec-WebSocket-Version", "13"], ["Origin", "http://" + HTTP.host]];
    const wanted = Array.isArray(protocols) ? protocols : (protocols ? [protocols] : []);
    if (wanted.length) headers.push(["Sec-WebSocket-Protocol", wanted.join(", ")]);
    const cookie = this.jar.header(target.pathname);
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
      let headerLength = 2;
      if (payload.length >= 65536) headerLength = 10; else if (payload.length >= 126) headerLength = 4;
      const frame = new Uint8Array(headerLength + 4 + payload.length);
      frame[0] = 0x80 | opcode;
      if (headerLength === 2) frame[1] = 0x80 | payload.length;
      else if (headerLength === 4) { frame[1] = 0x80 | 126; new DataView(frame.buffer).setUint16(2, payload.length); }
      else { frame[1] = 0x80 | 127; new DataView(frame.buffer).setUint32(2, Math.floor(payload.length / 4294967296)); new DataView(frame.buffer).setUint32(6, payload.length >>> 0); }
      frame.set(mask, headerLength);
      for (let i = 0; i < payload.length; i++) frame[headerLength + 4 + i] = payload[i] ^ mask[i & 3];
      stream.write(frame);
    };
    const parser = new HttpParser("GET", {
      head: (head) => {
        if (head.status !== 101) { handlers.error(new Error("upgrade refused " + head.status)); finish(1006, "", false); return; }
        const accepted = head.headers.find(([name]) => name.toLowerCase() === "sec-websocket-protocol");
        isOpen = true;
        handlers.open(accepted ? accepted[1] : "");
      },
      body: () => {}, end: () => {},
      error: () => { handlers.error(new Error("upgrade failed")); finish(1006, "", false); },
      raw: (u8) => readFrames(u8),
    });
    const readFrames = (u8) => {
      frames.push(u8);
      for (;;) {
        if (frames.length < 2) return;
        const head = frames.peek(Math.min(14, frames.length));
        const isFinal = (head[0] & 0x80) !== 0, opcode = head[0] & 0x0f, isMasked = (head[1] & 0x80) !== 0;
        let length = head[1] & 0x7f, offset = 2;
        if (length === 126) { if (head.length < 4) return; length = (head[2] << 8) | head[3]; offset = 4; }
        else if (length === 127) { if (head.length < 10) return; length = new DataView(head.buffer).getUint32(2) * 4294967296 + new DataView(head.buffer).getUint32(6); offset = 10; }
        if (isMasked) offset += 4;
        if (frames.length < offset + length) return;
        const whole = frames.take(offset + length);
        const payload = whole.subarray(offset);
        if (isMasked) { const mask = whole.subarray(offset - 4, offset); for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i & 3]; }
        if (opcode === WS.ping) { sendFrame(WS.pong, payload); continue; }
        if (opcode === WS.pong) continue;
        if (opcode === WS.close) {
          const code = payload.length >= 2 ? (payload[0] << 8) | payload[1] : 1005;
          const reason = payload.length > 2 ? new TextDecoder().decode(payload.subarray(2)) : "";
          sendFrame(WS.close, payload.subarray(0, Math.min(payload.length, 2)));
          finish(code, reason, true);
          return;
        }
        if (opcode === 0) { fragments.push(payload); } else { fragmentOpcode = opcode; fragments = [payload]; }
        if (!isFinal) continue;
        let message;
        if (fragments.length === 1) message = fragments[0];
        else { const total = fragments.reduce((sum, part) => sum + part.length, 0); message = new Uint8Array(total); let at = 0; for (const part of fragments) { message.set(part, at); at += part.length; } }
        fragments = [];
        const delivered = fragmentOpcode === WS.text ? new TextDecoder().decode(message) : message.slice();
        traceWs("in", delivered);
        handlers.message(delivered);
      }
    };
    stream.handlers = {
      data: (u8) => {
        if (isRaw) { parser.feed(u8); return; }
        for (const record of records.feed(u8)) {
          if (record.type === RECORD.accept) { isRaw = true; const rest = records.rest(); if (rest.length) parser.feed(rest); break; }
          if (record.type === RECORD.close) { handlers.error(new Error("refused " + parseRefusal(record.payload).code)); finish(1006, "", false); return; }
        }
      },
      end: () => finish(1006, "", false),
      error: () => finish(1006, "", false),
    };
    stream.write(encodeRecord(RECORD.open, json({ kind: "connect", id: this.entry })));
    stream.write(requestHead("GET", path, headers));
    return {
      send: (data) => {
        if (!isOpen || isClosed) return;
        traceWs("out", data);
        if (typeof data === "string") sendFrame(WS.text, encoder.encode(data));
        else sendFrame(WS.binary, data instanceof Uint8Array ? data : new Uint8Array(data));
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
}

// --- the service worker ------------------------------------------------------

async function startWorker(tab, onRequest) {
  await navigator.serviceWorker.register("/__neutrino/sw.js", { scope: "/" });
  await navigator.serviceWorker.ready;
  if (!navigator.serviceWorker.controller) {
    await new Promise((resolve) => navigator.serviceWorker.addEventListener("controllerchange", resolve, { once: true }));
  }
  const channel = new MessageChannel();
  const ready = new Promise((resolve) => {
    channel.port1.onmessage = (event) => {
      if (event.data && event.data.type === "ready") { resolve(); return; }
      onRequest(event.data, channel.port1);
    };
  });
  navigator.serviceWorker.controller.postMessage({ type: "shell", tab }, [channel.port2]);
  await ready;
}

function serveRequest(pool, message, port) {
  const { id, method, url, headers, body, routedBy } = message;
  if (routedBy === "mapping") stats.routedByMapping++; else stats.routedByFallback++;
  pool.request({ method, path: url, headers, body: body ? new Uint8Array(body) : null }, {
    head: (head) => port.postMessage({ type: "head", id, status: head.status, statusText: head.statusText, headers: head.headers }),
    body: (piece) => { const copy = piece.slice(); port.postMessage({ type: "chunk", id, data: copy.buffer }, [copy.buffer]); },
    end: () => port.postMessage({ type: "end", id }),
    fail: (refusal) => {
      port.postMessage({ type: "error", id, code: refusal.code });
      if (refusal.code === "agent_offline") screen.refuse("machine");
    },
  });
}

// --- the app's title -------------------------------------------------------

function mirrorTitle(frame, fallback) {
  const apply = () => { try { document.title = frame.contentDocument.title || fallback; } catch (e) { document.title = fallback; } };
  frame.addEventListener("load", () => {
    apply();
    try {
      const head = frame.contentDocument.head;
      if (head) new MutationObserver(apply).observe(head, { subtree: true, childList: true, characterData: true });
    } catch (e) { /* a document the shell cannot read keeps the fallback */ }
    if (!stats.appLoadMs) stats.appLoadMs = performance.now() - stats.t0;
    try {
      const paint = frame.contentWindow.performance.getEntriesByType("paint").find((entry) => entry.name === "first-contentful-paint" || entry.name === "first-paint");
      if (paint && !stats.appFirstPaintMs) stats.appFirstPaintMs = paint.startTime + frame.contentWindow.performance.timeOrigin - performance.timeOrigin;
    } catch (e) { /* no paint timing */ }
  });
}

// --- main --------------------------------------------------------------------

async function main() {
  screen.bind();
  if (window.top !== window) { screen.refuse("link"); return; }
  const payload = readPayload();
  if (!payload || !payload.hub || !payload.ice || !payload.ticket || !payload.app) { screen.refuse("link"); return; }
  const title = payload.app.title || "";
  screen.loading(title);
  document.title = title || "Loading";
  const tab = crypto.randomUUID();
  const jar = new CookieJar();
  let pool = null;
  let bridge = null;
  const pendingRequests = [];
  const worker = startWorker(tab, (message, port) => {
    if (!message || message.type !== "fetch") return;
    if (pool) serveRequest(pool, message, port); else pendingRequests.push([message, port]);
  }).catch((error) => { stats.workerError = String(error); });

  let channel;
  try { channel = await openChannel(payload); } catch (e) { screen.refuse("hub"); return; }
  const { pc, dc } = channel;
  window.__neutrinoConnection = pc;

  const admitted = await new Promise((resolve) => {
    const timer = setTimeout(() => resolve({ code: "hub" }), CHANNEL.openTimeoutMs);
    dc.onmessage = (event) => {
      clearTimeout(timer);
      const reader = new RecordReader();
      const [record] = reader.feed(new Uint8Array(event.data));
      if (!record) { resolve({ code: "malformed" }); return; }
      if (record.type === RECORD.accept) { try { resolve({ id: JSON.parse(new TextDecoder().decode(record.payload)).id }); } catch (e) { resolve({ code: "malformed" }); } return; }
      resolve(parseRefusal(record.payload));
    };
    dc.send(encodeRecord(RECORD.open, json({ protocol: PROTOCOL, ticket: payload.ticket })));
  });
  if (!admitted.id) { stats.refusalCode = admitted.code; screen.refuse(admitted.code === "hub" ? "hub" : "link"); return; }
  stats.admitMs = performance.now() - stats.t0;

  const mux = new Yamux(dc);
  mux.onEnd = () => { if (!stats.refusal) screen.refuse("hub"); };
  const control = new ControlStream(mux);
  try { await control.accepted; } catch (e) { screen.refuse("link"); return; }
  control.writeFrame({ type: "hello", protocol: PROTOCOL, role: "guest", id: admitted.id, name: "guest", software: "neutrino_web/0.6.0" });
  const welcome = await control.next(["welcome", "refused", "ended"]).catch(() => ({ type: "ended" }));
  if (welcome.type !== "welcome") { screen.refuse(welcome.type === "refused" ? "link" : "hub"); return; }
  stats.welcomeMs = performance.now() - stats.t0;

  control.writeFrame({ type: "service", request: "token-1", id: payload.app.entry });
  const reply = await control.next(["reply", "refused", "ended"]).catch(() => ({ type: "ended" }));
  if (reply.type !== "reply") { screen.refuse(reply.type === "refused" ? "link" : "hub"); return; }
  if (reply.code) { screen.refuse(reply.code === "agent_offline" ? "machine" : "link"); return; }
  const token = reply.params && reply.params.token;
  stats.tokenMs = performance.now() - stats.t0;

  pool = new HttpPool(mux, payload.app.entry, jar);
  bridge = new WebSocketBridge(mux, payload.app.entry, jar);
  for (const [message, port] of pendingRequests.splice(0)) serveRequest(pool, message, port);

  let startPath = location.pathname.startsWith("/__neutrino") ? (payload.app.path || "/") : location.pathname + location.search;
  if (token) {
    try {
      const first = await pool.fetchWhole("GET", "/?tkn=" + encodeURIComponent(token));
      stats.loginStatus = first.status;
      const where = first.headers.find(([name]) => name.toLowerCase() === "location");
      if (where && startPath === "/" && !payload.app.path) startPath = where[1];
    } catch (refusal) {
      screen.refuse(refusal.code === "agent_offline" ? "machine" : "hub");
      return;
    }
  }
  stats.loginMs = performance.now() - stats.t0;

  window.__neutrino = {
    cookieGet: () => jar.header("/", true),
    cookieSet: (text) => jar.set(text, "/"),
    wsOpen: (url, protocols, handlers) => bridge.open(url, protocols, handlers),
    ping: () => mux.ping(),
  };
  await worker;
  if (stats.workerError) { screen.refuse("hub"); return; }
  const frame = screen.elements.app;
  mirrorTitle(frame, title);
  frame.src = startPath;
  screen.app();
  stats.appStartMs = performance.now() - stats.t0;
  setInterval(() => { mux.ping().then((rtt) => { stats.rttMs = rtt; }); }, 20000);
  if (payload.report) reportTo(payload.report, frame);
}

// reportTo posts the shell's measurements to a same-origin test endpoint every
// two seconds for a minute; a test host reads them where no driver can.
function reportTo(path, frame) {
  let sent = 0;
  const timer = setInterval(() => {
    let bench = null, frameTitle = "", frameURL = "";
    try { bench = frame.contentWindow.__bench || null; frameTitle = frame.contentDocument.title; frameURL = frame.contentWindow.location.href; } catch (e) { /* not readable yet */ }
    const body = JSON.stringify({ at: Date.now(), userAgent: navigator.userAgent, stats: { ...stats, wsTrace: stats.wsTrace.length }, bench, frameTitle, frameURL });
    fetch(path, { method: "POST", body, headers: { "Content-Type": "application/json" }, keepalive: true }).catch(() => {});
    if (++sent >= 30) clearInterval(timer);
  }, 2000);
}

main().catch((error) => { stats.error = String(error); screen.refuse("hub"); });
