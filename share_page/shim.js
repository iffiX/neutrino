"use strict";
// The shim the service worker puts at the top of every page of the app: the
// app's cookies live in the shell's jar, its WebSockets ride the shell's
// streams, and its own service worker is never installed.
(function () {
  const shell = window.parent !== window ? window.parent.__neutrino : null;
  if (!shell) return;

  Object.defineProperty(document, "cookie", {
    configurable: true,
    get() { return shell.cookieGet(); },
    set(text) { shell.cookieSet(String(text)); },
  });

  if (navigator.serviceWorker) {
    try {
      Object.defineProperty(navigator.serviceWorker, "register", { configurable: true, value: () => new Promise(() => {}) });
    } catch (e) { /* a browser that keeps register read-only still refuses the app's worker in the shell's worker */ }
  }

  class NeutrinoWebSocket extends EventTarget {
    constructor(url, protocols) {
      super();
      this.url = String(url);
      this.readyState = NeutrinoWebSocket.CONNECTING;
      this.binaryType = "blob";
      this.protocol = "";
      this.extensions = "";
      this.bufferedAmount = 0;
      this.onopen = null; this.onmessage = null; this.onclose = null; this.onerror = null;
      this.handle = shell.wsOpen(this.url, protocols, {
        open: (protocol) => { this.readyState = NeutrinoWebSocket.OPEN; this.protocol = protocol; this.emit("open"); },
        message: (data) => {
          let payload = data;
          if (data instanceof Uint8Array) payload = this.binaryType === "arraybuffer" ? data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) : new Blob([data]);
          this.emit("message", { data: payload });
        },
        close: (code, reason, wasClean) => { this.readyState = NeutrinoWebSocket.CLOSED; this.emit("close", { code, reason, wasClean }); },
        error: () => this.emit("error"),
      });
    }
    send(data) {
      if (this.readyState !== NeutrinoWebSocket.OPEN) throw new DOMException("The WebSocket is not open", "InvalidStateError");
      if (typeof data === "string") { this.handle.send(data); return; }
      if (data instanceof Blob) { data.arrayBuffer().then((buffer) => this.handle.send(new Uint8Array(buffer))); return; }
      if (ArrayBuffer.isView(data)) { this.handle.send(new Uint8Array(data.buffer, data.byteOffset, data.byteLength)); return; }
      this.handle.send(new Uint8Array(data));
    }
    close(code, reason) {
      if (this.readyState === NeutrinoWebSocket.CLOSING || this.readyState === NeutrinoWebSocket.CLOSED) return;
      this.readyState = NeutrinoWebSocket.CLOSING;
      this.handle.close(code, reason);
    }
    emit(type, init) {
      let event;
      if (type === "message") event = new MessageEvent("message", init);
      else if (type === "close") event = new CloseEvent("close", init);
      else event = new Event(type);
      this.dispatchEvent(event);
      const handler = this["on" + type];
      if (typeof handler === "function") handler.call(this, event);
    }
  }
  NeutrinoWebSocket.CONNECTING = 0; NeutrinoWebSocket.OPEN = 1; NeutrinoWebSocket.CLOSING = 2; NeutrinoWebSocket.CLOSED = 3;
  NeutrinoWebSocket.prototype.CONNECTING = 0; NeutrinoWebSocket.prototype.OPEN = 1; NeutrinoWebSocket.prototype.CLOSING = 2; NeutrinoWebSocket.prototype.CLOSED = 3;
  window.WebSocket = NeutrinoWebSocket;
})();
