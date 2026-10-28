"use strict";
// The shim the service worker puts at the top of every page of the app: the
// app's cookies live in the shell's jar, its WebSockets ride the shell's
// streams, and its own service worker is never installed. The page sends the
// worker its tab, and the shim removes the tab's tag from the address before
// the app reads it.
(function () {
  const TAB_PARAM = "__neutrino_tab";
  let shell = null, tab = "";
  try { shell = window.top !== window ? window.top.__neutrino : null; tab = window.top.__neutrinoTab; } catch (e) { shell = null; }
  if (!shell) return;

  const url = new URL(location.href);
  if (url.searchParams.has(TAB_PARAM)) {
    url.searchParams.delete(TAB_PARAM);
    history.replaceState(history.state, "", url.pathname + url.search + url.hash);
  }
  const worker = navigator.serviceWorker;
  if (worker) {
    const announce = () => { if (worker.controller) worker.controller.postMessage({ type: "client", tab }); };
    worker.addEventListener("message", (event) => { if (event.data && event.data.type === "announce") announce(); });
    worker.startMessages();
    announce();
  }

  // A form sent in the frame by any method but GET gets this tab added to its
  // action. A GET form loses its query, and the worker tags its page again.
  const tagAction = (element, attribute) => {
    const target = new URL(element[attribute] || location.href, location.href);
    if (target.origin !== location.origin) return;
    target.searchParams.set(TAB_PARAM, tab);
    element[attribute] = target.href;
  };
  const tagForm = (form, submitter) => {
    const method = String((submitter && submitter.getAttribute("formmethod")) || form.method || "get").toLowerCase();
    if (method === "get" || method === "dialog") return;
    if (submitter && submitter.hasAttribute("formaction")) tagAction(submitter, "formAction");
    else tagAction(form, "action");
  };
  document.addEventListener("submit", (event) => { if (event.target instanceof HTMLFormElement) tagForm(event.target, event.submitter); }, true);
  const submit = HTMLFormElement.prototype.submit;
  HTMLFormElement.prototype.submit = function () { tagForm(this, null); return submit.call(this); };

  // A same-origin address opened in another tab gets this tab added. The new
  // tab's shell takes the share's facts from this tab through the worker.
  const FROM_PARAM = "__neutrino_from";
  const tagged = (address) => {
    try {
      const target = new URL(address, location.href);
      if (target.origin !== location.origin) return address;
      target.searchParams.set(FROM_PARAM, tab);
      return target.href;
    } catch (e) { return address; }
  };
  const open = window.open;
  window.open = function (address, ...rest) { return open.call(window, address ? tagged(String(address)) : address, ...rest); };
  const tagAnchor = (event) => {
    const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
    const isOtherTab = event.button === 1 || event.ctrlKey || event.metaKey || event.shiftKey || (anchor && anchor.target && !/^_(self|parent|top)$/i.test(anchor.target));
    if (!anchor || !isOtherTab) return;
    const original = anchor.getAttribute("href");
    anchor.href = tagged(anchor.href);
    setTimeout(() => anchor.setAttribute("href", original), 0);
  };
  document.addEventListener("click", tagAnchor, true);
  document.addEventListener("auxclick", tagAnchor, true);

  Object.defineProperty(document, "cookie", {
    configurable: true,
    get() { return shell.cookieGet(); },
    set(text) { shell.cookieSet(String(text)); },
  });

  if (worker) {
    try {
      Object.defineProperty(worker, "register", { configurable: true, value: () => new Promise(() => {}) });
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
