// The client page at phone width, in the demo only: what a phone has in place
// of the desktop's rows, design/client.md "Phone differences". It loads after
// app.js and replaces that page's functions and its file row.

Object.assign(ICON_SHAPES, {
  keyboard: [
    [
      "path",
      {
        d: "M4 6h16a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z",
      },
    ],
    ["path", { d: "M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8" }],
  ],
  command: [
    [
      "path",
      {
        d: "M15 6v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3",
      },
    ],
  ],
  close: [["path", { d: "m6 6 12 12M18 6 6 18" }]],
  chevron_left: [["path", { d: "m15 6-6 6 6 6" }]],
  chevron_right: [["path", { d: "m9 6 6 6-6 6" }]],
});

// One round button, as the remote desktop viewer and the terminal draw it.
function roundButton(
  iconName,
  label,
  isOn,
  onPress,
  size,
  isDanger,
  isEnabled,
) {
  const button = document.createElement("button");
  button.type = "button";
  button.className =
    "round_btn" + (isOn ? " on" : "") + (isDanger ? " danger" : "");
  button.style.width = size + "px";
  button.style.height = size + "px";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.disabled = isEnabled === false;
  button.appendChild(icon(iconName, Math.round(size / 2)));
  button.onmousedown = (event) => event.preventDefault();
  button.onclick = onPress;
  return button;
}

// --- the bar and the scroll of the page ---

const desktopTabButton = tabButton;
tabButton = function (tab) {
  const button = desktopTabButton(tab);
  if (tab === "rdp") {
    button.querySelector("span").textContent = t("demo.bar_desktop");
  }
  if (tab === "hubs" && openTab === "join") button.classList.add("on");
  return button;
};

let drawnTab = "";
const desktopDraw = draw;
draw = function (state) {
  const content = document.getElementById("content");
  const top = content.scrollTop;
  desktopDraw(state);
  if (drawnTab === openTab) content.scrollTop = top;
  drawnTab = openTab;
};

// --- the Files page ---

function drawPhoneFileEntry(card, state, hub, entry) {
  const payload = entry.payload || {};
  const open = document.createElement("button");
  open.type = "button";
  open.textContent = t("ui.open_in_files");
  open.disabled = !isEntryFree(hub, entry);
  open.onclick = () =>
    serviceAction("file", {
      action: "open_in_files",
      hub_id: entry.hub_id,
      id: entry.id,
    });
  card.appendChild(
    entryRow(
      hub,
      entry,
      "//" + (payload.host || "") + "/" + (payload.share || ""),
      "",
      [open],
      mountReason(hub, entry, undefined, open),
      [],
      fileTitle(entry),
    ),
  );
}

KINDS.find((kind) => kind[0] === "file")[2] = drawPhoneFileEntry;

// --- the Settings page: About, then the language and the theme ---

const PHONE_SOURCE_URL = "https://cnb.cool/iffi-X/neutrino";
const PHONE_BLOB_URL = "https://cnb.cool/iffi-X/neutrino/-/blob";
const PHONE_LICENCE = "AGPL-3.0";
const PHONE_PLATFORM_TAIL = " · Android 15";
// What the Android app carries, its About card's rows. A mirror where the
// mainland edition links one, and a patch where the app patches the core.
const PHONE_CORES = [
  [
    "NetBird",
    "0.78.1",
    "BSD-3-Clause",
    "https://github.com/netbirdio/netbird/tree/v0.78.1",
    "",
  ],
  [
    "EasyTier",
    "2.6.4",
    "LGPL-3.0",
    "https://gitee.com/easytier/EasyTier/tree/v2.6.4",
    "build_core_easytier.patch",
  ],
  [
    "RustDesk",
    "1.4.9",
    "AGPL-3.0",
    "https://gitee.com/mirrors/rustdesk/tree/1.4.9",
    "build_core_rustdesk.patch",
  ],
  [
    "flynn/noise",
    "1.1.0",
    "BSD-3-Clause",
    "https://github.com/flynn/noise/tree/v1.1.0",
    "",
  ],
  [
    "libp2p/go-buffer-pool",
    "0.0.2",
    "MIT",
    "https://github.com/libp2p/go-buffer-pool/tree/v0.0.2",
    "",
  ],
  [
    "libp2p/go-yamux",
    "4.0.2",
    "MPL-2.0",
    "https://github.com/libp2p/go-yamux/tree/v4.0.2",
    "",
  ],
  [
    "golang.org/x/crypto",
    "0.58.0",
    "BSD-3-Clause",
    "https://go.googlesource.com/crypto/+/v0.58.0",
    "",
  ],
  [
    "golang.org/x/sys",
    "0.49.0",
    "BSD-3-Clause",
    "https://go.googlesource.com/sys/+/v0.49.0",
    "",
  ],
];

aboutSection = function (state) {
  const card = document.createElement("div");
  card.className = "card";
  const header = document.createElement("div");
  header.className = "card_header";
  const title = document.createElement("h2");
  title.textContent = t("ui.about");
  header.appendChild(title);
  card.appendChild(header);
  const about = document.createElement("div");
  about.className = "about";
  const platform = state.platform || {};
  aboutGroup(about, t("ui.about_this_machine"), [
    [t("ui.about_machine"), state.hostname, []],
    [
      t("ui.about_platform"),
      platform.os + "/" + platform.arch + PHONE_PLATFORM_TAIL,
      [],
    ],
  ]);
  const source = t("ui.about_source_link");
  const patch = t("ui.about_patch_link");
  aboutGroup(about, t("ui.about_carried"), [
    [
      t("ui.window.title") + " " + state.version,
      PHONE_LICENCE,
      [[source, PHONE_SOURCE_URL]],
    ],
    ...PHONE_CORES.map(([name, version, licence, url, patchFile]) => [
      name + " " + version,
      licence,
      patchFile
        ? [
            [source, url],
            [
              patch,
              PHONE_BLOB_URL +
                "/v" +
                state.version +
                "/packaging/build/" +
                patchFile,
            ],
          ]
        : [[source, url]],
    ]),
  ]);
  card.appendChild(about);
  return card;
};

drawSettings = function (state) {
  const page = document.createElement("div");
  page.className = "settings_page";
  page.appendChild(aboutSection(state));
  const saved = { language: language, theme: theme };
  const draft = settingsDraft || saved;
  const isDirty =
    draft.language !== saved.language || draft.theme !== saved.theme;
  const card = document.createElement("div");
  card.className = isDirty ? "card settings dirty" : "card settings";
  function stage(key, value) {
    settingsDraft = Object.assign({}, draft, { [key]: value });
    redraw();
  }
  function field(label, id, options, value, key) {
    const heading = document.createElement("label");
    heading.textContent = label;
    card.appendChild(heading);
    card.appendChild(
      picker(id, options, value, (chosen) => stage(key, chosen), false),
    );
  }
  field(
    t("ui.language"),
    "language",
    LANGUAGES.map((code) => ({
      value: code,
      label: t("ui.language_name." + code),
    })),
    draft.language,
    "language",
  );
  field(
    t("ui.theme"),
    "theme",
    THEMES.map((code) => ({ value: code, label: t("ui.theme_name." + code) })),
    draft.theme,
    "theme",
  );
  const actions = document.createElement("div");
  actions.className = "form_actions";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "ghost";
  cancel.textContent = t("ui.cancel");
  cancel.disabled = !isDirty;
  cancel.onclick = () => {
    settingsDraft = null;
    redraw();
  };
  const save = document.createElement("button");
  save.type = "button";
  save.textContent = t("ui.save");
  save.disabled = !isDirty;
  save.onclick = () => {
    settingsDraft = null;
    send("/api/settings/set", { language: draft.language, theme: draft.theme });
    redraw();
  };
  actions.appendChild(cancel);
  actions.appendChild(save);
  card.appendChild(actions);
  page.appendChild(card);
  return page;
};

// --- the Terminals page: the two round buttons and the key row ---

const TERMINAL_CONTROL_SIZE = 30;
const TERMINAL_LONG_PRESS_MS = 500;
const TERMINAL_TAP_SLOP_PX = 10;
const TERMINAL_ESCAPE = "\x1b";
// The key row, in the row's order: its label, and for a key that sends the
// xterm letter of an arrow or the name of a modifier.
const TERMINAL_KEYS = [
  { label: "Esc", kind: "escape" },
  { label: "Tab", kind: "tab" },
  { label: "Ctrl", kind: "modifier", name: "ctrl" },
  { label: "Shift", kind: "modifier", name: "shift" },
  { label: "Alt", kind: "modifier", name: "alt" },
  { label: "←", kind: "arrow", letter: "D" },
  { label: "↑", kind: "arrow", letter: "A" },
  { label: "↓", kind: "arrow", letter: "B" },
  { label: "→", kind: "arrow", letter: "C" },
];

let isKeyRowShown = true;
let heldKeys = { ctrl: false, shift: false, alt: false };

function keySequence(key) {
  const alt = heldKeys.alt ? TERMINAL_ESCAPE : "";
  if (key.kind === "escape") return alt + TERMINAL_ESCAPE;
  if (key.kind === "tab") {
    return alt + (heldKeys.shift ? TERMINAL_ESCAPE + "[Z" : "\t");
  }
  const parameter =
    1 +
    (heldKeys.shift ? 1 : 0) +
    (heldKeys.alt ? 2 : 0) +
    (heldKeys.ctrl ? 4 : 0);
  return parameter === 1
    ? TERMINAL_ESCAPE + "[" + key.letter
    : TERMINAL_ESCAPE + "[1;" + parameter + key.letter;
}

// A typed key with the row's held modifiers on it: Shift makes it upper case,
// Ctrl its control code, Alt puts Escape before it.
function withHeldKeys(data) {
  if (!(heldKeys.ctrl || heldKeys.shift || heldKeys.alt) || data.length !== 1) {
    return data;
  }
  let typed = heldKeys.shift ? data.toUpperCase() : data;
  if (heldKeys.ctrl) {
    const code = typed.toUpperCase().charCodeAt(0);
    if (code >= 64 && code <= 95) typed = String.fromCharCode(code - 64);
    else if (typed === "?") typed = "\x7f";
  }
  if (heldKeys.alt) typed = TERMINAL_ESCAPE + typed;
  return typed;
}

function letGoOfKeys() {
  heldKeys = { ctrl: false, shift: false, alt: false };
  for (const button of document.querySelectorAll(".term_key.held")) {
    button.classList.remove("held");
  }
}

const desktopSendShellKeys = sendShellKeys;
sendShellKeys = function (tab, data) {
  const typed = withHeldKeys(data);
  if (data.length === 1) letGoOfKeys();
  desktopSendShellKeys(tab, typed);
};

function pressTerminalKey(key, button) {
  if (key.kind === "modifier") {
    heldKeys[key.name] = !heldKeys[key.name];
    button.classList.toggle("held", heldKeys[key.name]);
    return;
  }
  const tab = activeTab();
  if (tab) desktopSendShellKeys(tab, keySequence(key));
  letGoOfKeys();
}

function terminalKeyRow() {
  const row = document.createElement("div");
  row.className = "term_keys";
  row.hidden = !isKeyRowShown;
  for (const key of TERMINAL_KEYS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className =
      "term_key" +
      (key.kind === "modifier" && heldKeys[key.name] ? " held" : "");
    button.textContent = key.label;
    button.onmousedown = (event) => event.preventDefault();
    button.onclick = () => pressTerminalKey(key, button);
    row.appendChild(button);
  }
  return row;
}

function scrollTerminalToEnd() {
  const content = document.getElementById("content");
  content.scrollTop = content.scrollHeight;
}

function setTerminalKeyboard(isUp) {
  if (isUp) {
    phoneKeyboard.show(document.body, (text) => {
      const tab = activeTab();
      if (tab) sendShellKeys(tab, text);
    });
  } else {
    phoneKeyboard.hide();
  }
  document.body.classList.toggle("kb_up", isUp);
  document.documentElement.style.setProperty(
    "--kb-height",
    phoneKeyboard.height() + "px",
  );
  drawTerminalControls();
  window.requestAnimationFrame(scrollTerminalToEnd);
}

function terminalControls() {
  const controls = document.createElement("div");
  controls.className = "term_controls";
  controls.appendChild(
    roundButton(
      "keyboard",
      t("ui.rdp_keyboard"),
      phoneKeyboard.isShown(),
      () => setTerminalKeyboard(!phoneKeyboard.isShown()),
      TERMINAL_CONTROL_SIZE,
    ),
  );
  controls.appendChild(
    roundButton(
      "command",
      t("ui.rdp_keys"),
      isKeyRowShown,
      () => {
        isKeyRowShown = !isKeyRowShown;
        const row = document.querySelector(".term_keys");
        if (row) row.hidden = !isKeyRowShown;
        drawTerminalControls();
      },
      TERMINAL_CONTROL_SIZE,
    ),
  );
  return controls;
}

function drawTerminalControls() {
  const held = document.querySelector(".term_controls");
  if (held) held.replaceWith(terminalControls());
}

const desktopStatusLine = statusLine;
statusLine = function (tab) {
  const status = desktopStatusLine(tab);
  status.prepend(terminalControls());
  return status;
};

const desktopShellPanel = shellPanel;
shellPanel = function (state) {
  const panel = desktopShellPanel(state);
  if (shellTabs.length > 0) panel.appendChild(terminalKeyRow());
  return panel;
};

// A tab reads as `name · 1` on a phone, with no dot before it.
const desktopShellTabButton = shellTabButton;
shellTabButton = function (tab) {
  const wrap = desktopShellTabButton(tab);
  const label = wrap.querySelector(".term_tab_label");
  const dot = label.querySelector(".dot");
  if (dot) dot.remove();
  if (tab.state !== "ended") {
    label.firstChild.textContent =
      tab.name + " · " + (shellTabs.indexOf(tab) + 1);
  }
  return wrap;
};

// The page draws the keyboard itself, so a tap on a terminal raises that one,
// and a long press opens the menu a right click opens on a desktop.
const desktopWireShell = wireShell;
wireShell = function (tab) {
  desktopWireShell(tab);
  tab.term.textarea.setAttribute("inputmode", "none");
  let press = null;
  let timer = 0;
  let isMenuJustOpened = false;
  function letGo() {
    window.clearTimeout(timer);
    press = null;
  }
  tab.pane.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "touch") return;
    press = { x: event.clientX, y: event.clientY };
    timer = window.setTimeout(() => {
      press = null;
      isMenuJustOpened = true;
      openTerminalMenu(tab, event.clientX, event.clientY);
    }, TERMINAL_LONG_PRESS_MS);
  });
  tab.pane.addEventListener("pointermove", (event) => {
    if (!press) return;
    const moved = Math.hypot(event.clientX - press.x, event.clientY - press.y);
    if (moved > TERMINAL_TAP_SLOP_PX) letGo();
  });
  tab.pane.addEventListener("pointercancel", letGo);
  tab.pane.addEventListener("pointerup", () => {
    if (press && !phoneKeyboard.isShown()) setTerminalKeyboard(true);
    letGo();
  });
  // The finger's lift after a long press is no tap: the menu stays open.
  tab.pane.addEventListener(
    "touchend",
    (event) => {
      if (isMenuJustOpened) event.preventDefault();
      isMenuJustOpened = false;
    },
    { passive: false },
  );
};

const desktopOpenShell = openShell;
openShell = function (hub, machine, account) {
  desktopOpenShell(hub, machine, account);
  window.requestAnimationFrame(scrollTerminalToEnd);
};

const desktopDropShell = dropShell;
dropShell = function (tab) {
  desktopDropShell(tab);
  if (shellTabs.length === 0 && phoneKeyboard.isShown()) {
    setTerminalKeyboard(false);
  }
};

const desktopAskPersist = askPersist;
askPersist = function (tab, isPersistent, isShared) {
  shouldFocusShell = true;
  desktopAskPersist(tab, isPersistent, isShared);
};

// --- the Remote desktops page: Configure beside Connect ---

const DESKTOP_CODECS = [
  ["auto", ""],
  ["vp8", "VP8"],
  ["vp9", "VP9"],
  ["av1", "AV1"],
  ["h264", "H264"],
  ["h265", "H265"],
];
const DESKTOP_QUALITIES = [
  ["balanced", "ui.rdp_quality_balanced"],
  ["low", "ui.rdp_quality_low"],
  ["best", "ui.rdp_quality_best"],
];
// The choice each entry's next Connect asks for, by entry.
const desktopChoices = {};

function openDesktopDialog(entry) {
  const key = serviceKey(entry);
  const draft = Object.assign(
    { codec: "auto", quality: "balanced" },
    desktopChoices[key],
  );
  const overlay = document.createElement("div");
  overlay.className = "overlay";
  const modal = document.createElement("div");
  modal.className = "card modal";
  const heading = document.createElement("div");
  heading.className = "panel_title";
  heading.textContent = t("ui.rdp_configure_title");
  modal.appendChild(heading);
  const subject = document.createElement("div");
  subject.className = "note";
  subject.textContent = entry.title;
  modal.appendChild(subject);
  function field(label, id, options, chosen, name) {
    const title = document.createElement("label");
    title.textContent = label;
    modal.appendChild(title);
    modal.appendChild(
      picker(
        id,
        options,
        chosen,
        (value) => {
          draft[name] = value;
        },
        false,
      ),
    );
  }
  field(
    t("ui.rdp_codec"),
    "rdp_codec",
    DESKTOP_CODECS.map(([value, title]) => ({
      value: value,
      label: title || t("ui.rdp_codec_auto"),
    })),
    draft.codec,
    "codec",
  );
  field(
    t("ui.rdp_quality"),
    "rdp_quality",
    DESKTOP_QUALITIES.map(([value, word]) => ({
      value: value,
      label: t(word),
    })),
    draft.quality,
    "quality",
  );
  const actions = document.createElement("div");
  actions.className = "form_actions";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "ghost";
  cancel.textContent = t("ui.cancel");
  cancel.onclick = () => {
    closeDialog(overlay);
    redraw();
  };
  const save = document.createElement("button");
  save.type = "button";
  save.textContent = t("ui.save");
  save.onclick = () => {
    desktopChoices[key] = draft;
    closeDialog(overlay);
    redraw();
  };
  actions.appendChild(cancel);
  actions.appendChild(save);
  modal.appendChild(actions);
  overlay.appendChild(modal);
  overlay.onclick = (event) => {
    if (event.target === overlay) {
      closeDialog(overlay);
      redraw();
    }
  };
  openDialog(overlay);
}

function drawPhoneDesktopEntry(card, state, hub, entry) {
  const payload = entry.payload || {};
  const isOpen = !!((state.viewers || {})[serviceKey(entry)] || {}).is_running;
  const isViewerOpen = Object.values(state.viewers || {}).some(
    (viewer) => viewer.is_running,
  );
  const configure = document.createElement("button");
  configure.type = "button";
  configure.textContent = t("ui.configure");
  configure.disabled = isUnhealthy(entry) || isRefreshing(hub);
  configure.onclick = () => openDesktopDialog(entry);
  const connect = jobButton(t("ui.rdp_connect"), entry.job);
  if (!entry.job) {
    connect.disabled =
      isUnhealthy(entry) || !isEntryFree(hub, entry) || isViewerOpen;
    connect.onclick = () =>
      serviceAction("rdp", {
        action: "connect",
        hub_id: entry.hub_id,
        id: entry.id,
      });
  }
  const reason = isViewerOpen
    ? t("ui.reason_viewer_open")
    : connect.disabled && !entryWork(hub, entry)
      ? entryReason(hub, entry, true)
      : "";
  const extras =
    payload.platform_os === "darwin" ? [noteLine(t("ui.rdp_mac_hint"))] : [];
  card.appendChild(
    entryRow(
      hub,
      entry,
      (payload.host || "") + ":" + (payload.port || ""),
      isOpen ? t("ui.rdp_open") : t("ui.healthy"),
      [configure, connect],
      reason,
      extras,
    ),
  );
}

KINDS.find((kind) => kind[0] === "rdp")[2] = drawPhoneDesktopEntry;
