// The phone's terminals: one xterm.js pane per tab, driven by the app through
// window.neutrino and answering through window.NeutrinoBridge.
(function () {
  "use strict";

  const FONT = '"MesloLGS NF", ui-monospace, monospace';
  const SCROLLBACK_LINES = 5000;
  const SETTLE_MS = 150;
  const LONG_PRESS_MS = 500;
  const MOVE_SLOP_PX = 10;
  const BAR_MIN_PX = 24;
  const BAR_INSET_PX = 6;
  const MENU_EDGE_PX = 8;
  const panes = {};
  let active = "";
  let isCtrl = false;
  let theme = {};
  let labels = { copy: "Copy", paste: "Paste", selectAll: "Select all", clear: "Clear" };

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

  // A key typed while Ctrl is held on the key row becomes its control code.
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
      drawBar(pane);
      const size = pane.term.cols + "x" + pane.term.rows;
      if (size === pane.sent) return;
      pane.sent = size;
      window.NeutrinoBridge.resize(id, pane.term.cols, pane.term.rows);
    }, SETTLE_MS);
  }

  // The thin bar at the right edge: where the view is in the scrollback.
  function drawBar(pane) {
    const buffer = pane.term.buffer.active;
    const total = buffer.length;
    const rows = pane.term.rows;
    if (total <= rows) {
      pane.bar.hidden = true;
      return;
    }
    const track = pane.element.clientHeight - BAR_INSET_PX * 2;
    const height = Math.max(BAR_MIN_PX, (track * rows) / total);
    const top = BAR_INSET_PX + ((track - height) * buffer.viewportY) / (total - rows);
    pane.bar.hidden = false;
    pane.bar.style.height = height + "px";
    pane.bar.style.top = top + "px";
  }

  // One finger moves through the scrollback; a long press opens the menu.
  function followTouch(pane) {
    const element = pane.element;
    let startX = 0;
    let startY = 0;
    let lastY = 0;
    let carry = 0;
    let isMoved = false;
    let isLong = false;
    let timer = 0;
    element.addEventListener(
      "touchstart",
      (event) => {
        if (event.touches.length !== 1) return;
        const touch = event.touches[0];
        startX = touch.clientX;
        startY = touch.clientY;
        lastY = startY;
        carry = 0;
        isMoved = false;
        isLong = false;
        timer = window.setTimeout(() => {
          isLong = true;
          openMenu(touch.clientX, touch.clientY);
        }, LONG_PRESS_MS);
      },
      { passive: true },
    );
    element.addEventListener(
      "touchmove",
      (event) => {
        const touch = event.touches[0];
        if (!isMoved && Math.hypot(touch.clientX - startX, touch.clientY - startY) > MOVE_SLOP_PX) {
          isMoved = true;
          window.clearTimeout(timer);
        }
        if (!isMoved || isLong) return;
        event.preventDefault();
        const cell = element.clientHeight / Math.max(1, pane.term.rows);
        carry += lastY - touch.clientY;
        lastY = touch.clientY;
        const lines = Math.trunc(carry / cell);
        if (lines !== 0) {
          pane.term.scrollLines(lines);
          carry -= lines * cell;
        }
      },
      { passive: false },
    );
    element.addEventListener(
      "touchend",
      (event) => {
        window.clearTimeout(timer);
        if (isLong || isMoved) event.preventDefault();
      },
      { passive: false },
    );
  }

  const menu = document.createElement("div");
  menu.className = "menu";
  menu.hidden = true;

  function closeMenu() {
    menu.hidden = true;
  }

  function openMenu(x, y) {
    const pane = panes[active];
    if (!pane) return;
    const items = [
      [labels.copy, pane.term.hasSelection(), () => window.NeutrinoBridge.copy(pane.term.getSelection())],
      [
        labels.paste,
        true,
        () => {
          const text = window.NeutrinoBridge.paste();
          if (text) pane.term.paste(text);
        },
      ],
      [labels.selectAll, true, () => pane.term.selectAll()],
      [labels.clear, true, () => pane.term.clear()],
    ];
    menu.replaceChildren();
    for (const [label, isEnabled, act] of items) {
      const item = document.createElement("button");
      item.textContent = label;
      item.disabled = !isEnabled;
      item.addEventListener("click", () => {
        closeMenu();
        act();
        pane.term.focus();
      });
      menu.appendChild(item);
    }
    menu.hidden = false;
    const left = Math.min(x, window.innerWidth - menu.offsetWidth - MENU_EDGE_PX);
    const top = Math.min(y, window.innerHeight - menu.offsetHeight - MENU_EDGE_PX);
    menu.style.left = Math.max(MENU_EDGE_PX, left) + "px";
    menu.style.top = Math.max(MENU_EDGE_PX, top) + "px";
  }

  document.addEventListener(
    "touchstart",
    (event) => {
      if (!menu.hidden && !menu.contains(event.target)) closeMenu();
    },
    true,
  );

  function paint() {
    const style = document.documentElement.style;
    for (const [name, value] of Object.entries(theme.chrome || {})) style.setProperty("--" + name, value);
  }

  window.neutrino = {
    open(id) {
      if (panes[id]) return;
      const element = document.createElement("div");
      element.className = "pane";
      element.hidden = true;
      document.body.appendChild(element);
      const bar = document.createElement("div");
      bar.className = "bar";
      bar.hidden = true;
      const term = new Terminal({
        fontFamily: FONT,
        fontSize: 13,
        lineHeight: 1.2,
        cursorBlink: true,
        scrollback: SCROLLBACK_LINES,
        theme: theme.terminal || {},
      });
      const fit = new FitAddon.FitAddon();
      term.loadAddon(fit);
      term.open(element);
      element.appendChild(bar);
      const pane = { element: element, bar: bar, term: term, fit: fit, timer: 0, sent: "" };
      new ResizeObserver(() => report(id)).observe(element);
      term.onData((data) => window.NeutrinoBridge.input(id, toBase64(withCtrl(data))));
      term.onScroll(() => drawBar(pane));
      term.onWriteParsed(() => drawBar(pane));
      followTouch(pane);
      panes[id] = pane;
    },
    show(id) {
      active = id;
      closeMenu();
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
      paint();
      for (const key of Object.keys(panes)) panes[key].term.options.theme = theme.terminal || {};
    },
    labels(json) {
      labels = JSON.parse(json);
    },
  };

  window.addEventListener("load", () => {
    document.body.appendChild(menu);
    window.NeutrinoBridge.ready();
  });
})();
