// The phone's terminals: one xterm.js pane per tab, driven by the app through
// window.neutrino and answering through window.NeutrinoBridge.
(function () {
  "use strict";

  const FONT = '"MesloLGS NF", ui-monospace, monospace';
  const SCROLLBACK_LINES = 5000;
  const SETTLE_MS = 150;
  const panes = {};
  let active = "";
  let isCtrl = false;
  let theme = {};

  function toBase64(text) {
    let binary = "";
    for (const byte of new TextEncoder().encode(text)) binary += String.fromCharCode(byte);
    return btoa(binary);
  }

  function fromBase64(encoded) {
    const binary = atob(encoded);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  // A key typed while Ctrl is held on the extra-keys row becomes its control code.
  function withCtrl(data) {
    if (!isCtrl || data.length !== 1) return data;
    isCtrl = false;
    window.NeutrinoBridge.ctrlUsed();
    const code = data.toUpperCase().charCodeAt(0);
    if (code >= 64 && code <= 95) return String.fromCharCode(code - 64);
    if (data === "?") return "\x7f";
    return data;
  }

  // The size is read once the pane has been laid out and has stopped
  // changing, and sent only when it differs from the last one sent.
  function report(id) {
    const pane = panes[id];
    if (!pane) return;
    window.clearTimeout(pane.timer);
    pane.timer = window.setTimeout(() => {
      if (id !== active || pane.element.clientHeight === 0) return;
      pane.fit.fit();
      const size = pane.term.cols + "x" + pane.term.rows;
      if (size === pane.sent) return;
      pane.sent = size;
      window.NeutrinoBridge.resize(id, pane.term.cols, pane.term.rows);
    }, SETTLE_MS);
  }

  window.neutrino = {
    open(id) {
      if (panes[id]) return;
      const element = document.createElement("div");
      element.className = "pane";
      element.hidden = true;
      document.body.appendChild(element);
      const term = new Terminal({
        fontFamily: FONT,
        fontSize: 13,
        lineHeight: 1.2,
        cursorBlink: true,
        scrollback: SCROLLBACK_LINES,
        theme: theme,
      });
      const fit = new FitAddon.FitAddon();
      term.loadAddon(fit);
      term.open(element);
      new ResizeObserver(() => report(id)).observe(element);
      term.onData((data) => window.NeutrinoBridge.input(id, toBase64(withCtrl(data))));
      panes[id] = { element: element, term: term, fit: fit, timer: 0, sent: "" };
    },
    show(id) {
      active = id;
      for (const key of Object.keys(panes)) panes[key].element.hidden = key !== id;
      if (panes[id]) {
        report(id);
        panes[id].term.focus();
      }
    },
    write(id, encoded) {
      if (panes[id]) panes[id].term.write(fromBase64(encoded));
    },
    close(id) {
      const pane = panes[id];
      if (!pane) return;
      pane.term.dispose();
      pane.element.remove();
      delete panes[id];
    },
    ctrl(isHeld) {
      isCtrl = isHeld;
      if (panes[active]) panes[active].term.focus();
    },
    focus() {
      if (panes[active]) panes[active].term.focus();
    },
    theme(json) {
      theme = JSON.parse(json);
      for (const key of Object.keys(panes)) panes[key].term.options.theme = theme;
    },
  };

  window.addEventListener("load", () => window.NeutrinoBridge.ready());
})();
