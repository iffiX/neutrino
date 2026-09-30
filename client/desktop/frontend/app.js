// Every word this surface says comes from the two catalogs the loader
// inlines above; the wire carries only codes.
const CATALOGS = JSON.parse(document.getElementById('words').textContent);
const LANGUAGES = ['en', 'zh-CN'];
const DEFAULT_LANGUAGE = 'en';
const THEMES = ['system', 'dark', 'light'];
const DEFAULT_THEME = 'dark';
// What the page words itself in, until a pushed state names another.
let language = DEFAULT_LANGUAGE;
// What the page draws itself in, likewise.
let theme = DEFAULT_THEME;
// The desktop's own scheme, which 'system' resolves through.
const DARK_SCHEME = window.matchMedia('(prefers-color-scheme: dark)');
DARK_SCHEME.addEventListener('change', () => setTheme(theme));

// Codes worded through their params' own detail text when they carry one.
const DETAIL_CODES = [
  'switch_failed', 'reconcile_failed', 'mount_failed', 'unmount_failed',
  'forward_failed',
];
// The mount states that are a step on the way, each with its own word.
const MOUNT_BUSY_STATES = ['queued', 'mounting', 'pending'];

// Claude Code's four role slots and Codex's reasoning scale, as the client
// stores them.
const CLAUDE_SLOTS = ['default', 'opus', 'sonnet', 'haiku'];
const REASONING_EFFORTS = ['minimal', 'low', 'medium', 'high'];

function fill(template, params) {
  return template.replace(/\{(\w+)\}/g, (whole, key) =>
    params && params[key] !== undefined ? params[key] : '');
}

// One key's word: the language in hand, English behind it, the key itself
// when neither carries it.
function catalogWord(key) {
  const chosen = CATALOGS[language] || {};
  const english = CATALOGS[DEFAULT_LANGUAGE] || {};
  return chosen[key] !== undefined ? chosen[key] : english[key];
}

function hasWord(key) {
  return catalogWord(key) !== undefined;
}

function t(key, params) {
  const word = catalogWord(key);
  return word === undefined ? key : fill(word, params);
}

// The language every word is taken in; anything but the two reads as English.
function setLanguage(chosen) {
  language = LANGUAGES.indexOf(chosen) >= 0 ? chosen : DEFAULT_LANGUAGE;
  document.documentElement.lang = language;
}

// The palette every rule is drawn in; anything but the three reads as dark.
function setTheme(chosen) {
  theme = THEMES.indexOf(chosen) >= 0 ? chosen : DEFAULT_THEME;
  document.documentElement.dataset.theme = theme === 'system'
    ? (DARK_SCHEME.matches ? 'dark' : 'light') : theme;
}

function wordCode(code, params) {
  if (!code) return '';
  const p = params || {};
  if (DETAIL_CODES.indexOf(code) >= 0) return p.detail || t('state.failed');
  return hasWord('code.' + code) ? t('code.' + code, p) : code;
}

function wordError(e) {
  if (!e || !e.code) return '';
  const p = e.params || {};
  if (e.code === 'hub_unreachable' && p.detail) return p.detail;
  return wordCode(e.code, p);
}

let lastState = null;
let lastSerialized = '';
let pendingState = null;
// Notes a refusal left on one entry, by type and service key.
let serviceNotes = {};
// What each AI tool points with, as the Config dialog left it; sent with
// the next switch, and null rebuilds it from the next server state.
let aiStaged = null;
// Records whose unmount is in flight, so the button greys at once.
const fileAsked = {};
// Hubs whose Leave is in flight, by hub key: the button greys and spins
// until the state push that drops the row.
const leaveAsked = {};
// A refused join or leave of a hub's virtual network, by hub key, worded
// under its row until the next press.
const overlayNotes = {};
// Whether a refresh is in flight: the refresh button spins until the next
// pushed state or REFRESH_SPIN_MS, whichever comes first.
let isRefreshing = false;
let refreshTimer = null;
const REFRESH_SPIN_MS = 3000;
// The staged file configs, one per service key: {is_open, username,
// password, path}. The password lives only here and in the one request
// that sends it.
let fileStaged = {};

// What one hub is keyed by on this page: its id once its welcome named
// it, its binding's id before that.
function hubKey(hub) {
  return hub.hub_id || hub.binding_id;
}

// What one entry is keyed by: its hub and its id, as the resident keys it.
function serviceKey(entry) {
  return entry.hub_id + '/' + entry.id;
}
// Dialogs are built outside draw() and counted here, so a poll never
// redraws under one.
let openDialogs = 0;

function renderHint(text) {
  document.getElementById('content').innerHTML =
    '<div class="card"><span class="muted">' + text + '</span></div>';
}

// --- the bridge: the shell carries every request over the channel ---

let requestCounter = 0;
const pendingReplies = {};

// A WebKitGTK shell answers a posted request by calling this with the reply.
function neutrinoReply(reply) {
  const resolve = pendingReplies[reply.id];
  if (!resolve) return;
  delete pendingReplies[reply.id];
  resolve(reply.body);
}
window.neutrinoReply = neutrinoReply;

function api(path, body) {
  const request = {
    id: ++requestCounter,
    method: body === undefined ? 'GET' : 'POST',
    path: path,
    body: body === undefined ? null : body,
  };
  if (window.pywebview)
    return window.pywebview.api.request(request).then((reply) => reply.body);
  return new Promise((resolve) => {
    pendingReplies[request.id] = resolve;
    window.webkit.messageHandlers.neutrino.postMessage(JSON.stringify(request));
  });
}

// pywebview announces its api after the page loads; WebKitGTK registers its
// handler before it.
function bridgeReady() {
  if (window.webkit || window.pywebview) return Promise.resolve();
  return new Promise((resolve) =>
    window.addEventListener('pywebviewready', resolve, { once: true }));
}

// --- redraw discipline ---

function canRedraw() {
  if (openDialogs > 0) return false;
  if (openPicker) return false;
  const selection = window.getSelection ? window.getSelection() : null;
  if (selection && selection.type === 'Range') return false;
  const active = document.activeElement;
  if (active && ['INPUT', 'TEXTAREA', 'SELECT'].indexOf(active.tagName) >= 0)
    return false;
  return true;
}

// Draws a state that is news; says whether it drew.
function present(state) {
  const serialized = JSON.stringify(state);
  if (serialized === lastSerialized) return false;
  if (!canRedraw()) { pendingState = state; return false; }
  lastSerialized = serialized;
  pendingState = null;
  draw(state);
  return true;
}

// A redraw the person caused: it always happens, whatever is open.
function redraw() {
  if (lastState !== null) draw(lastState);
}

// The resident pushes every change of state here; nothing polls for it.
// A push ends a refresh in flight, and the button stops spinning even when
// the state is the one already drawn. A shell's output comes the same way,
// as a piece naming its terminal.
window.neutrinoState = (state) => {
  if (!state) return;
  if (state.terminal) { takeShellPiece(state.terminal); return; }
  if (state.code) { renderHint(wordCode(state.code, state.params)); return; }
  const wasRefreshing = isRefreshing;
  settleRefresh();
  if (!present(state) && wasRefreshing) redraw();
};

// The refresh in flight is over: the timer is dropped and the flag cleared.
function settleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = null;
  isRefreshing = false;
}

// A press on the refresh button: every hub is asked again, and the button
// spins until the next pushed state or the timer.
function askRefresh() {
  if (isRefreshing) return;
  isRefreshing = true;
  redraw();
  refreshTimer = setTimeout(() => { settleRefresh(); redraw(); }, REFRESH_SPIN_MS);
  api('/api/refresh', {});
}

async function firstFrame() {
  const state = await api('/api/state');
  window.neutrinoState(state);
}

async function send(path, body) {
  const reply = await api(path, body || {});
  if (reply && !reply.code) { lastSerialized = JSON.stringify(reply); draw(reply); }
  return reply;
}

async function serviceAction(type, body, noteKey) {
  const reply = await api('/api/services/' + type, body);
  if (!reply) return false;
  if (reply.code) {
    serviceNotes[noteKey] = wordCode(reply.code, reply.params);
    redraw();
    return false;
  }
  delete serviceNotes[noteKey];
  lastSerialized = JSON.stringify(reply);
  draw(reply);
  return true;
}

// --- the sidebar and its entries ---

// The sidebar's entries, in order: the hubs, then each kind of service with
// the terminals among them. The one open is kept across redraws.
const TABS = ['hubs', 'web', 'port', 'ai', 'file', 'terminals', 'rdp'];
let openTab = 'hubs';

// Every kind of service in the order the sidebar lists it: the type on the
// wire, its title's key, the function that draws one entry into the kind's
// panel, and the key of the line the panel carries while nothing is there.
const KINDS = [
  ['web', 'ui.panel_web', drawWebEntry, 'ui.empty_web'],
  ['port', 'ui.panel_ports', drawPortEntry, 'ui.empty_ports'],
  ['ai', 'ui.panel_ai', drawAiEntry, 'ui.empty_ai'],
  ['file', 'ui.panel_files', drawFileEntry, 'ui.empty_files'],
  ['rdp', 'ui.panel_desktops', drawDesktopEntry, 'ui.empty_desktops'],
];

// What each code a hub row or a virtual network chip carries means for its
// colour: amber is unreachable with nothing broken, red needs a person to
// change something. A code outside the table reads as amber.
const CODE_TONES = {
  hub_unreachable: 'wait',
  client_disabled: 'wait',
  overlay_other_network: 'wait',
  overlay_not_authorized: 'wait',
  overlay_missing: 'wait',
  busy: 'wait',
  hub_untrusted: 'bad',
  binding_unknown: 'bad',
  protocol_too_old: 'bad',
  protocol_too_new: 'bad',
  hub_refused: 'bad',
  hub_reply_unreadable: 'bad',
  hello_invalid: 'bad',
  role_mismatch: 'bad',
  bundle_missing: 'bad',
  overlay_daemon_down: 'bad',
  overlay_join_failed: 'bad',
  overlay_leave_failed: 'bad',
  overlay_network_invalid: 'bad',
  overlay_peer_invalid: 'bad',
  overlay_secret_missing: 'bad',
  overlay_restart_failed: 'bad',
  overlay_console_invalid: 'bad',
  overlay_request_invalid: 'bad',
  overlay_wish_unsaved: 'bad',
  unsupported_platform: 'bad',
  crashed: 'bad',
};
// The words a virtual network's state takes, as the resident names them.
const OVERLAY_STATES = ['off', 'joining', 'waiting', 'on', 'leaving', 'failed'];
// The states in which a press on the chip leaves the network.
const OVERLAY_HELD_STATES = ['waiting', 'on'];
// The name each virtual network's provider goes by in the picker.
const OVERLAY_TITLES = { netbird: 'NetBird', easytier: 'EasyTier' };

function codeTone(code) {
  return CODE_TONES[code] || 'wait';
}

// A status mark: a dot in its tone, or an amber spinner for a step in flight.
function marker(tone) {
  return tone === 'spin' ? '<span class="spin warn"></span>'
    : '<span class="dot ' + tone + '"></span>';
}

function draw(state) {
  lastState = state;
  setLanguage(state.language);
  setTheme(state.theme);
  document.title = t('ui.window.title');
  document.querySelector('h1').textContent = t('ui.window.title');
  drawRefresh();
  document.getElementById('ident').textContent =
    state.hostname + ' · ' + state.platform.os + '/' + state.platform.arch +
    ' · client ' + state.version;
  drawTabs();
  document.getElementById('page_title').textContent = tabTitle(openTab);
  dropStaleFileStages(state);

  const content = document.getElementById('content');
  content.innerHTML = '';
  if (openTab === 'hubs') {
    content.appendChild(drawHubs(state));
  } else if (openTab === 'terminals') {
    content.appendChild(drawTerminals(state));
  } else if (openTab === 'settings') {
    content.appendChild(drawSettings());
  } else {
    content.appendChild(kindTab(state, KINDS.filter((kind) => kind[0] === openTab)[0]));
  }
}

// One entry per tab down the sidebar, then a rule and the settings entry;
// the open one is washed in the accent.
function drawTabs() {
  const nav = document.getElementById('tabs');
  nav.innerHTML = '';
  for (const tab of TABS) nav.appendChild(tabButton(tab));
  const rule = document.createElement('div');
  rule.className = 'tab_rule';
  nav.appendChild(rule);
  nav.appendChild(tabButton('settings'));
}

function tabButton(tab) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = tab === openTab ? 'tab on' : 'tab';
  button.innerHTML = icon(TAB_ICONS[tab], 17);
  const label = document.createElement('span');
  label.textContent = tabTitle(tab);
  button.appendChild(label);
  button.onclick = () => { openTab = tab; redraw(); };
  return button;
}

function tabTitle(tab) {
  if (tab === 'hubs') return t('ui.section_hubs');
  if (tab === 'terminals') return t('ui.panel_terminals');
  if (tab === 'settings') return t('ui.settings');
  return t(KINDS.filter((kind) => kind[0] === tab)[0][1]);
}

// The sidebar's glyph for each entry, drawn from the hub panel's icon set.
const TAB_ICONS = {
  hubs: 'server', web: 'globe', port: 'plug', ai: 'sparkles', file: 'folder',
  terminals: 'terminal', rdp: 'desktop', settings: 'settings',
};

// The hub panel's glyphs, each a 24x24 stroke drawing in currentColor, with
// the plug drawn for the ports in the same hand.
const ICON_SHAPES = {
  server: '<rect x="3" y="3" width="18" height="7" rx="2"/>' +
    '<rect x="3" y="14" width="18" height="7" rx="2"/>' +
    '<path d="M7 6.5h.01M7 17.5h.01"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>' +
    '<path d="M12 3c2.6 2.5 3.9 5.5 3.9 9s-1.3 6.5-3.9 9c-2.6-2.5-3.9-5.5-3.9-9S9.4 5.5 12 3z"/>',
  plug: '<path d="M9 3v5M15 3v5"/><path d="M6 8h12v3a6 6 0 0 1-12 0z"/>' +
    '<path d="M12 17v4"/>',
  sparkles: '<path d="m10 4 1.7 4.3L16 10l-4.3 1.7L10 16l-1.7-4.3L4 10l4.3-1.7z"/>' +
    '<path d="m18 13 .9 2.1 2.1.9-2.1.9L18 19l-.9-2.1-2.1-.9 2.1-.9z"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  terminal: '<path d="m4 17 6-5-6-5"/><path d="M12 19h8"/>',
  desktop: '<rect x="3" y="4" width="18" height="12" rx="2"/>' +
    '<path d="M9 20h6"/><path d="M12 16v4"/>',
  settings: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/>' +
    '<path d="M1 14h6M9 8h6M17 16h6"/>',
};

function icon(name, size) {
  return '<svg class="icon" width="' + size + '" height="' + size +
    '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"' +
    ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"' +
    ' focusable="false">' + ICON_SHAPES[name] + '</svg>';
}

// The refresh button in the top bar: every hub is asked again, and it spins
// until the next pushed state or the timer.
function drawRefresh() {
  const button = document.getElementById('refresh');
  button.title = t('ui.refresh');
  button.setAttribute('aria-label', t('ui.refresh'));
  if (isRefreshing) {
    button.innerHTML = '<span class="spin"></span>';
    button.disabled = true;
  } else {
    button.textContent = '↻';
    button.disabled = false;
  }
  button.onclick = askRefresh;
}

// --- one kind's panel: every hub's entries of that kind, in hub order ---

function kindTab(state, kind) {
  const [type, titleKey, build, emptyKey] = kind;
  const hubs = state.hubs || [];
  if (hubs.length === 0) return waitCard();
  const card = panelCard(t(titleKey), false);
  let count = 0;
  for (const hub of hubs) {
    if (hub.connection_state !== 'connected') {
      card.appendChild(downRow(hub));
    } else {
      for (const entry of entriesOf(state, hub, type)) {
        build(card, state, hub, entry);
        count += 1;
      }
    }
  }
  if (count === 0) card.appendChild(emptyRow(t(emptyKey)));
  const work = state.rdp_work || {};
  if (type === 'rdp' && work.code) card.appendChild(errorLine(wordCode(work.code, work.params)));
  return card;
}

// A hub whose socket is down publishes nothing; its row in a panel says why.
function downRow(hub) {
  const row = document.createElement('div');
  row.className = 'feat greyed';
  row.innerHTML = marker('off') + '<div class="body"><div class="title">' +
    hubName(hub) + '</div><div class="note">' +
    (hub.connection_state === 'replaced' ? t('state.replaced') : t('ui.reconnecting')) +
    '</div></div>';
  return row;
}

function hubName(hub) {
  return hub.hub_name || hub.gateway_url;
}

function waitCard() {
  const wait = document.createElement('div');
  wait.className = 'card';
  wait.innerHTML = '<span class="muted">' + t('ui.services_wait_join') + '</span>';
  return wait;
}

// --- the terminals page: a strip of machines, one tab per open shell ---

// Every shell open in this window, in the order opened: {key, terminal_id,
// hub_id, name, term, fit, pane, state, note, isRefused, typed, isSending}.
// The panes live in one surface that outlives every redraw, so a redraw
// moves them rather than rebuilding them and the shells keep running.
const shellTabs = [];
let activeShell = '';
let shellCounter = 0;
// The machine the strip has picked, by hub and device.
let shellPick = null;
// The surface the panes live in, made once.
let shellSurface = null;
// Whether the next fit also puts the keyboard on the active shell.
let shouldFocusShell = false;
// The palette the shells were last drawn in.
let shellThemeKey = '';
// Output that arrived for a terminal before its open answered, by its id.
const earlyOutput = {};
// Lines a shell keeps above its window.
const TERMINAL_SCROLLBACK_LINES = 5000;
const TERMINAL_FONT = 'ui-monospace, "Cascadia Mono", Consolas, Menlo, monospace';

function drawTerminals(state) {
  const hubs = state.hubs || [];
  if (hubs.length === 0) return waitCard();
  const themeKey = document.documentElement.dataset.theme;
  if (themeKey !== shellThemeKey) {
    shellThemeKey = themeKey;
    for (const tab of shellTabs) tab.term.options.theme = terminalTheme();
  }
  const page = document.createElement('div');
  page.className = 'term_page';
  page.appendChild(machineStrip(state));
  page.appendChild(shellPanel(state));
  window.requestAnimationFrame(fitActiveShell);
  return page;
}

// Every machine a connected hub offers a terminal on, one chip each with its
// presence dot, and the button that opens a new shell on the picked one.
function machineStrip(state) {
  const card = document.createElement('div');
  card.className = 'card term_pick';
  const chips = document.createElement('div');
  chips.className = 'term_chips';
  const picked = pickedMachine(state);
  let count = 0;
  for (const hub of state.hubs || []) {
    if (hub.connection_state !== 'connected') continue;
    const machines = (state.terminals || []).filter(
      (machine) => machine.hub_id === hub.hub_id);
    for (const machine of machines) {
      count += 1;
      const isPicked = !!picked && picked.machine === machine;
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = isPicked ? 'chip on' : 'chip';
      chip.title = t('ui.machine_provided_by', { hub: hubName(hub), device: machine.name });
      chip.disabled = isHeld(hub);
      chip.innerHTML = marker(machine.is_online ? 'ok' : 'off');
      chip.appendChild(document.createTextNode(machine.name));
      chip.onclick = () => {
        shellPick = { hub_id: hub.hub_id, device_id: machine.device_id };
        redraw();
      };
      chips.appendChild(chip);
    }
  }
  if (count === 0) {
    card.appendChild(emptyRow(t('ui.empty_terminals')));
    return card;
  }
  const line = document.createElement('div');
  line.className = 'term_pick_line';
  line.appendChild(chips);
  line.appendChild(newShellButton(picked));
  card.appendChild(line);
  if (picked) {
    const provider = document.createElement('div');
    provider.className = 'note muted';
    provider.textContent = t('ui.machine_provided_by',
      { hub: hubName(picked.hub), device: picked.machine.name });
    card.appendChild(provider);
  }
  return card;
}

// The machine the strip has picked, while a connected hub still offers it.
function pickedMachine(state) {
  if (!shellPick) return null;
  for (const hub of state.hubs || []) {
    if (hub.connection_state !== 'connected' || hub.hub_id !== shellPick.hub_id) continue;
    const machine = (state.terminals || []).filter((each) =>
      each.hub_id === hub.hub_id && each.device_id === shellPick.device_id)[0];
    if (machine) return { hub: hub, machine: machine };
  }
  return null;
}

// The button that opens a new shell on the picked machine.
function newShellButton(picked) {
  const open = document.createElement('button');
  open.type = 'button';
  open.textContent = t('ui.terminal_new');
  open.disabled = !picked || !picked.machine.is_online || isHeld(picked.hub);
  open.onclick = () => openShell(picked.hub, picked.machine);
  return open;
}

// The open shells: their tabs in a head, the active one's pane, and a line
// saying where the keys go. With none open, a dashed frame says so and
// offers the button that opens one.
function shellPanel(state) {
  if (shellTabs.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'term_empty';
    empty.innerHTML = '<span>' + t('ui.terminal_none') + '</span>' +
      '<span class="faint">' + t('ui.terminal_pick_hint') + '</span>';
    const open = newShellButton(pickedMachine(state));
    open.className = 'with_icon';
    open.innerHTML = icon('terminal', 14);
    open.appendChild(document.createTextNode(t('ui.terminal_new')));
    empty.appendChild(open);
    return empty;
  }
  const panel = document.createElement('section');
  panel.className = 'term_panel';
  const head = document.createElement('div');
  head.className = 'term_head';
  for (const tab of shellTabs) head.appendChild(shellTabButton(tab));
  panel.appendChild(head);
  panel.appendChild(shellSurfaceElement());
  const active = activeTab();
  const status = document.createElement('div');
  status.className = 'term_status';
  status.textContent = active && active.state === 'closed'
    ? (active.note || t('ui.terminal_ended')) : t('ui.terminal_keys');
  panel.appendChild(status);
  return panel;
}

function shellTabButton(tab) {
  const wrap = document.createElement('div');
  wrap.className = tab.key === activeShell ? 'term_tab on' : 'term_tab';
  const label = document.createElement('button');
  label.type = 'button';
  label.className = 'term_tab_label';
  label.innerHTML = marker(shellTone(tab));
  label.appendChild(document.createTextNode(tab.name));
  label.onclick = () => { activeShell = tab.key; shouldFocusShell = true; redraw(); };
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'term_tab_close';
  close.textContent = '×';
  close.title = t('ui.terminal_close', { name: tab.name });
  close.setAttribute('aria-label', close.title);
  close.onclick = () => closeShell(tab);
  wrap.appendChild(label);
  wrap.appendChild(close);
  return wrap;
}

// A shell's dot: an amber spinner while it opens, green while open, red for
// a refusal, grey once it ended.
function shellTone(tab) {
  if (tab.state === 'connecting') return 'spin';
  if (tab.state === 'open') return 'ok';
  return tab.isRefused ? 'bad' : 'off';
}

function activeTab() {
  return shellTabs.filter((tab) => tab.key === activeShell)[0] || null;
}

// The surface every pane lives in; only the active pane shows.
function shellSurfaceElement() {
  if (!shellSurface) {
    shellSurface = document.createElement('div');
    shellSurface.className = 'term_surface';
    // A state held back while a shell had the keyboard draws once it lets go.
    shellSurface.addEventListener('focusout', () => setTimeout(settle, 0));
    new ResizeObserver(fitActiveShell).observe(shellSurface);
  }
  for (const tab of shellTabs) {
    tab.pane.className = tab.key === activeShell ? 'term_pane' : 'term_pane hidden';
  }
  return shellSurface;
}

// A new shell on one machine: its tab and pane at once, the shell once the
// resident has opened it at the pane's size.
function openShell(hub, machine) {
  shellCounter += 1;
  const pane = document.createElement('div');
  pane.className = 'term_pane';
  shellSurfaceElement().appendChild(pane);
  const term = new Terminal({
    fontFamily: TERMINAL_FONT,
    fontSize: 13,
    lineHeight: 1.2,
    cursorBlink: true,
    theme: terminalTheme(),
    scrollback: TERMINAL_SCROLLBACK_LINES,
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  const tab = {
    key: 'shell' + shellCounter, terminal_id: '', hub_id: hub.hub_id,
    name: machine.name, term: term, fit: fit, pane: pane, state: 'connecting',
    note: '', isRefused: false, typed: '', isSending: false,
  };
  shellTabs.push(tab);
  activeShell = tab.key;
  shouldFocusShell = true;
  redraw();
  term.open(pane);
  fitShell(tab);
  term.onData((data) => sendShellKeys(tab, data));
  term.onResize((size) => {
    if (tab.state !== 'open') return;
    api('/api/terminal/resize',
      { terminal_id: tab.terminal_id, cols: size.cols, rows: size.rows });
  });
  api('/api/terminal/open', {
    hub_id: hub.hub_id, device_id: machine.device_id,
    cols: term.cols, rows: term.rows,
  }).then((reply) => {
    if (!reply || reply.code || !reply.terminal_id) {
      endShell(tab, reply && reply.code ? wordCode(reply.code, reply.params) : '', true);
      return;
    }
    tab.terminal_id = reply.terminal_id;
    tab.state = 'open';
    const early = earlyOutput[reply.terminal_id] || [];
    delete earlyOutput[reply.terminal_id];
    for (const piece of early) takeShellPiece(piece);
    redraw();
  });
}

// One piece the resident pushed: output for a shell, or how it ended.
function takeShellPiece(piece) {
  const tab = shellTabs.filter((each) => each.terminal_id === piece.id)[0];
  if (!tab) {
    if (shellTabs.some((each) => each.state === 'connecting')) {
      (earlyOutput[piece.id] = earlyOutput[piece.id] || []).push(piece);
    }
    return;
  }
  if (piece.data !== undefined) {
    tab.term.write(base64Bytes(piece.data));
    return;
  }
  const end = piece.end || {};
  if (!end.code) { dropShell(tab); return; }
  endShell(tab, wordCode(end.code, end.params), true);
}

// A shell that ended or was refused keeps its tab, saying why.
function endShell(tab, note, isRefused) {
  tab.state = 'closed';
  tab.note = note;
  tab.isRefused = isRefused;
  if (note) tab.term.write('\r\n' + note + '\r\n');
  redraw();
}

// Keys go in the order typed: one request at a time, whatever was typed
// meanwhile riding the next.
function sendShellKeys(tab, data) {
  if (tab.state !== 'open') return;
  tab.typed += data;
  if (!tab.isSending) flushShellKeys(tab);
}

function flushShellKeys(tab) {
  if (!tab.typed || tab.state !== 'open') { tab.isSending = false; return; }
  const text = tab.typed;
  tab.typed = '';
  tab.isSending = true;
  api('/api/terminal/input', { terminal_id: tab.terminal_id, data: textBase64(text) })
    .then(() => flushShellKeys(tab));
}

// Closing a tab ends its shell.
function closeShell(tab) {
  if (tab.state === 'open') api('/api/terminal/close', { terminal_id: tab.terminal_id });
  dropShell(tab);
}

// A tab goes; the one that took its place, else the one before it, shows.
function dropShell(tab) {
  const index = shellTabs.indexOf(tab);
  if (index < 0) return;
  shellTabs.splice(index, 1);
  tab.state = 'closed';
  tab.term.dispose();
  tab.pane.remove();
  if (activeShell === tab.key) {
    const next = shellTabs[index] || shellTabs[index - 1];
    activeShell = next ? next.key : '';
  }
  redraw();
}

// A pane fits its surface only when the answer changed: fitting redraws the
// terminal, and the observer that noticed would bring it straight back.
function fitShell(tab) {
  if (!tab || tab.pane.className !== 'term_pane' || tab.pane.clientWidth === 0) return;
  const proposed = tab.fit.proposeDimensions();
  if (!proposed || (proposed.cols === tab.term.cols && proposed.rows === tab.term.rows)) return;
  tab.fit.fit();
}

function fitActiveShell() {
  const tab = activeTab();
  if (!tab) return;
  fitShell(tab);
  if (shouldFocusShell) {
    shouldFocusShell = false;
    tab.term.focus();
  }
}

// The palette the shells draw in, read from the page's own tokens.
function terminalTheme() {
  const style = window.getComputedStyle(document.documentElement);
  const token = (name) => style.getPropertyValue(name).trim();
  return {
    background: token('--color-bg'),
    foreground: token('--color-text'),
    cursor: token('--color-accent'),
    cursorAccent: token('--color-bg'),
    selectionBackground: token('--color-terminal-selection'),
    red: token('--color-error'),
    green: token('--color-ok'),
    yellow: token('--color-warn'),
    blue: token('--color-accent'),
    cyan: token('--color-accent'),
  };
}

function textBase64(text) {
  let binary = '';
  for (const byte of new TextEncoder().encode(text)) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function base64Bytes(encoded) {
  const binary = atob(encoded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

// --- the Hubs tab: one row per hub, and the row that joins another ---

function drawHubs(state) {
  const card = document.createElement('div');
  card.className = 'card';
  const hubs = state.hubs || [];
  for (const hub of hubs) card.appendChild(hubRow(hub));
  if (hubs.length === 0) {
    const none = document.createElement('div');
    none.className = 'feat';
    none.innerHTML = marker('off') + '<div class="body"><div>' +
      t('ui.no_hubs') + '</div></div>';
    card.appendChild(none);
  }
  card.appendChild(joinRow(state));
  return card;
}

// Where one hub stands, as a colour: green connected; an amber spinner
// while reconnecting to a hub that answered before; amber unreachable with
// nothing broken; red for a refusal a person has to act on; grey for a hub
// not reached yet.
function hubTone(hub) {
  if (hub.connection_state === 'connected' && !hub.is_disabled) return 'ok';
  if (hub.is_disabled || hub.connection_state === 'replaced') return 'wait';
  const code = hub.last_error ? hub.last_error.code : '';
  if (code) return codeTone(code);
  return hub.hub_software ? 'spin' : 'off';
}

// Bound is not the same as reached: the socket may be down, or another
// client's may hold the binding, while the binding stands, and the row
// says which.
function hubRow(hub) {
  const row = document.createElement('div');
  row.className = 'feat';
  const isReplaced = hub.connection_state === 'replaced';
  const isReaching = hub.connection_state === 'reconnecting';
  const tone = hubTone(hub);
  const word = isReplaced ? t('state.replaced')
    : hub.is_disabled ? t('ui.disabled')
    : isReaching ? (tone === 'off' ? t('ui.not_reached') : t('ui.reconnecting'))
    : t('ui.connected');
  const software = hub.hub_software
    ? ' · ' + t('ui.hub_software', { software: hub.hub_software }) : '';
  const body = document.createElement('div');
  body.className = 'body';
  body.innerHTML = '<div class="title">' + hubName(hub) +
    '</div><div class="note">' + word + '</div>' +
    '<div class="sub">' + hub.gateway_url + software + '</div>' +
    (hub.is_exit ? '<div class="note muted">' + t('ui.hub_is_exit') + '</div>' : '');
  const lastError = wordError(hub.last_error);
  if (lastError) body.appendChild(errorLine(lastError));
  const overlay = hub.overlay || {};
  if (overlay.code) body.appendChild(errorLine(wordCode(overlay.code, overlay.params)));
  if (overlay.state === 'waiting') body.appendChild(noteLine(t('ui.overlay_waiting_hint')));
  if (overlayNotes[hubKey(hub)]) body.appendChild(errorLine(overlayNotes[hubKey(hub)]));
  row.innerHTML = marker(tone);
  row.appendChild(body);
  const chip = overlayChip(hub);
  if (chip) row.appendChild(chip);
  const networkPicker = overlayPicker(hub);
  if (networkPicker) row.appendChild(networkPicker);
  if (isReplaced) {
    const reconnect = document.createElement('button');
    reconnect.textContent = t('ui.reconnect');
    reconnect.onclick = () => send('/api/session/start', { hub_id: hubKey(hub) });
    row.appendChild(reconnect);
  }
  const leave = document.createElement('button');
  leave.className = 'danger';
  if (leaveAsked[hubKey(hub)]) {
    leave.innerHTML = '<span class="spin"></span>' + t('ui.disconnect');
    leave.disabled = true;
  } else {
    leave.textContent = t('ui.disconnect');
  }
  leave.onclick = () => askLeave(hub);
  row.appendChild(leave);
  return row;
}

// The virtual network's chip on a hub row: the current network's state and
// address, pressed to want the hub's virtual network or not. It stands
// whatever the socket's state, since the virtual network is what can bring
// a hub back.
function overlayChip(hub) {
  const overlay = hub.overlay;
  if (!overlay) return null;
  const isOn = overlay.state === 'on';
  const isHeldNetwork = overlay.is_wanted
    || OVERLAY_HELD_STATES.indexOf(overlay.state) >= 0;
  const isMoving = overlay.state === 'joining' || overlay.state === 'leaving';
  const isWorking = (overlay.work || {}).state === 'working';
  const chip = document.createElement('button');
  chip.type = 'button';
  chip.className = isOn ? 'chip on' : 'chip';
  chip.disabled = isMoving || isWorking || isHeld(hub);
  chip.innerHTML = marker(isMoving ? 'spin' : overlayTone(overlay));
  chip.appendChild(document.createTextNode(overlayWords(overlay)));
  chip.onclick = () => askOverlay(hub, isHeldNetwork);
  return chip;
}

// Beside the chip, when the hub publishes more than one virtual network: the
// one this machine is on or aims at, and a pick moves it to another.
function overlayPicker(hub) {
  const overlay = hub.overlay;
  const networks = (overlay && overlay.networks) || [];
  if (networks.length < 2) return null;
  const isMoving = overlay.state === 'joining' || overlay.state === 'leaving';
  const isWorking = (overlay.work || {}).state === 'working';
  const options = networks.map((network) => ({
    value: network.provider,
    label: OVERLAY_TITLES[network.provider] || network.provider,
  }));
  const key = hubKey(hub);
  const wrap = picker('overlay_' + key, options, overlay.provider, (provider) => {
    delete overlayNotes[key];
    send('/api/overlay/pick', { hub_id: key, provider: provider }).then((reply) => {
      if (reply && reply.code) {
        overlayNotes[key] = wordCode(reply.code, reply.params);
        redraw();
      }
    });
  }, isMoving || isWorking || isHeld(hub));
  wrap.classList.add('overlay_pick');
  wrap.title = t('ui.overlay_pick');
  return wrap;
}

function overlayTone(overlay) {
  if (overlay.state === 'on') return 'ok';
  if (overlay.state === 'waiting') return 'wait';
  if (overlay.code) return codeTone(overlay.code);
  return 'off';
}

function overlayWords(overlay) {
  const state = OVERLAY_STATES.indexOf(overlay.state) >= 0 ? overlay.state : 'off';
  const parts = [t('ui.overlay'), t('ui.overlay_' + state)];
  if (overlay.address) parts.push(overlay.address);
  return parts.join(' · ');
}

// A press on the chip: leave when the network is wanted or held, join
// otherwise; a
// refusal is worded under the row until the next press.
function askOverlay(hub, isHeldNetwork) {
  const key = hubKey(hub);
  delete overlayNotes[key];
  send(isHeldNetwork ? '/api/overlay/leave' : '/api/overlay/join', { hub_id: key })
    .then((reply) => {
      if (reply && reply.code) {
        overlayNotes[key] = wordCode(reply.code, reply.params);
        redraw();
      }
    });
}

// Leave greys and spins at once; the row goes with the state that answers,
// and a refused leave puts the button back.
function askLeave(hub) {
  const key = hubKey(hub);
  leaveAsked[key] = true;
  redraw();
  send('/api/leave', { hub_id: key }).then((reply) => {
    delete leaveAsked[key];
    if (reply && reply.code) redraw();
  });
}

// The row that is always there: paste a link, join one more hub.
function joinRow(state) {
  const wrap = document.createElement('div');
  wrap.className = 'feat';
  const body = document.createElement('div');
  body.className = 'body';
  body.innerHTML = '<div class="title">' + t('ui.add_hub') + '</div>' +
    '<div class="note">' + t('ui.paste_hint') + '</div>';
  const row = document.createElement('div');
  row.className = 'row';
  row.style.marginTop = '8px';
  const input = document.createElement('input');
  input.placeholder = 'neutrino://enroll/...';
  input.onkeydown = (e) => { if (e.key === 'Enter') join(); };
  input.onblur = settle;
  const button = document.createElement('button');
  button.textContent = t('ui.connect');
  button.onclick = join;
  function join() { send('/api/join', { link: input.value }); }
  row.appendChild(input);
  row.appendChild(button);
  body.appendChild(row);
  const refusal = state.error ? wordCode(state.error.code, state.error.params) : '';
  if (refusal) body.appendChild(errorLine(refusal));
  wrap.appendChild(body);
  return wrap;
}

// What the settings page holds before Save: {language, theme}, or null while
// it holds what the window already uses.
let settingsDraft = null;

// The settings page: what this window keeps for itself, the language and
// the palette. Nothing is sent until Save, and the frame is lit while the
// page holds a change.
function drawSettings() {
  const draft = settingsDraft || { language: language, theme: theme };
  const isDirty = draft.language !== language || draft.theme !== theme;
  const card = panelCard(t('ui.settings_title'), isDirty);
  card.classList.add('settings');
  function stage(key, value) {
    settingsDraft = Object.assign({}, draft, { [key]: value });
    redraw();
  }
  const languageLabel = document.createElement('label');
  languageLabel.textContent = t('ui.language');
  card.appendChild(languageLabel);
  const languageOptions = LANGUAGES.map(
    (code) => ({ value: code, label: t('ui.language_name.' + code) }));
  card.appendChild(picker('language', languageOptions, draft.language,
    (value) => stage('language', value), false));
  const themeLabel = document.createElement('label');
  themeLabel.textContent = t('ui.theme');
  card.appendChild(themeLabel);
  const themeOptions = THEMES.map(
    (code) => ({ value: code, label: t('ui.theme_name.' + code) }));
  card.appendChild(picker('theme', themeOptions, draft.theme,
    (value) => stage('theme', value), false));
  const actions = document.createElement('div');
  actions.className = 'row';
  actions.style.marginTop = '8px';
  const save = document.createElement('button');
  save.textContent = t('ui.save');
  save.disabled = !isDirty;
  save.onclick = () => {
    settingsDraft = null;
    if (draft.language !== language) {
      send('/api/language', { language: draft.language });
    }
    if (draft.theme !== theme) {
      send('/api/theme', { theme: draft.theme });
    }
    redraw();
  };
  const cancel = document.createElement('button');
  cancel.className = 'ghost';
  cancel.textContent = t('ui.cancel');
  cancel.disabled = !isDirty;
  cancel.onclick = () => { settingsDraft = null; redraw(); };
  actions.appendChild(save);
  actions.appendChild(cancel);
  card.appendChild(actions);
  return card;
}

function noteLine(text) {
  const note = document.createElement('div');
  note.className = 'note muted';
  note.textContent = text;
  return note;
}

function errorLine(text) {
  const err = document.createElement('div');
  err.className = 'err';
  err.style.marginTop = '10px';
  err.textContent = text;
  return err;
}

function entriesOf(state, hub, type) {
  return (state.services || []).filter(
    (entry) => entry.hub_id === hub.hub_id && entry.type === type);
}

// The line a panel carries while no hub has anything of its kind.
function emptyRow(line) {
  const row = document.createElement('div');
  row.className = 'feat';
  row.innerHTML = '<div class="body"><div class="note muted">' + line +
    '</div></div>';
  return row;
}

function panelCard(title, isDirty) {
  const card = document.createElement('div');
  card.className = isDirty ? 'card dirty' : 'card';
  const heading = document.createElement('div');
  heading.className = 'panel_title';
  heading.textContent = title;
  card.appendChild(heading);
  return card;
}

function entryRow(hub, entry, payloadText, extraNote) {
  const row = document.createElement('div');
  row.className = entry.is_healthy ? 'feat' : 'feat greyed';
  const note = (entry.is_healthy ? '' : t('ui.unhealthy')) +
    (extraNote ? (entry.is_healthy ? '' : ' — ') + extraNote : '');
  row.innerHTML = '<span class="dot ' + (entry.is_healthy ? 'ok' : 'off') +
    '"></span>' +
    '<div class="body"><div class="title">' + entry.title + '</div>' +
    '<div class="note">' + payloadText + (note ? ' — ' + note : '') + '</div>' +
    '<div class="note muted">' + providerLine(hub, entry) + '</div>' +
    '</div>';
  return row;
}

// Which hub, which of its machines and which module an entry comes from; a
// hub that names no machine leaves the address the entry points at.
function providerLine(hub, entry) {
  return t('ui.provided_by', {
    hub: hubName(hub), device: entry.device_name || entryHost(entry),
    module: entryModule(entry),
  });
}

// The module names an origin code stands for; the AI gateway is worded in
// the page's language.
const ENTRY_MODULES = {
  gitea_module: 'Gitea', samba_module: 'Samba', device_share: 'RustDesk',
};

// The module an entry comes from, by its origin code: a container by its
// image, without the registry or the path in front; a hand-declared record,
// and an entry from a hub that sends no code, by its own title.
function entryModule(entry) {
  const code = entry.description_code;
  if (code === 'ai_gateway') return t('ui.module_ai_gateway');
  if (code === 'container') {
    const image = (entry.description_params || {}).image || '';
    return image.split('/').pop() || entry.title;
  }
  return ENTRY_MODULES[code] || entry.title;
}

// The host an entry's payload points at, wherever its type keeps it.
function entryHost(entry) {
  const payload = entry.payload || {};
  const url = payload.url || payload.endpoint;
  if (url) {
    const match = /^[a-z][a-z0-9+.-]*:\/\/(\[[^\]]+\]|[^/:?#]+)/i.exec(url);
    return match ? match[1] : url;
  }
  return payload.host || '';
}

// Every button of a hub greys while that hub has this client switched off.
function isHeld(hub) {
  return !!hub.is_disabled;
}

function drawWebEntry(card, state, hub, entry) {
  const payload = entry.payload || {};
  const noteKey = 'web_' + serviceKey(entry);
  const row = entryRow(hub, entry, payload.url || '', serviceNotes[noteKey] || '');
  const open = document.createElement('button');
  open.textContent = t('ui.open');
  open.disabled = !entry.is_healthy || isHeld(hub);
  open.onclick = () => serviceAction('web',
    { hub_id: entry.hub_id, id: entry.id }, noteKey);
  row.appendChild(open);
  card.appendChild(row);
}

function drawPortEntry(card, state, hub, entry) {
  const payload = entry.payload || {};
  const forward = (state.forwards || {})[serviceKey(entry)] || {};
  const isOn = !!forward.is_active;
  const noteKey = 'port_' + serviceKey(entry);
  const local = isOn
    ? ' → ' + t('ui.forwarding_to', { port: forward.local_port }) : '';
  const note = serviceNotes[noteKey] || '';
  const row = entryRow(
    hub, entry, (payload.host || '') + ':' + (payload.port || '') + local, note);
  const button = document.createElement('button');
  button.className = isOn ? 'danger' : '';
  button.textContent = isOn ? t('ui.port_disconnect') : t('ui.port_connect');
  button.disabled = (!entry.is_healthy && !isOn) || isHeld(hub);
  button.onclick = () => serviceAction('port',
    { hub_id: entry.hub_id, id: entry.id, is_enabled: !isOn }, noteKey);
  row.appendChild(button);
  card.appendChild(row);
}

// --- the remote desktops panel: connect there ---

function drawDesktopEntry(card, state, hub, entry) {
  const work = state.rdp_work || {};
  const isWorking = work.state === 'working';
  const payload = entry.payload || {};
  const noteKey = 'rdp_' + serviceKey(entry);
  const viewer = (state.viewers || {})[serviceKey(entry)] || {};
  const open = viewer.is_running ? ' — ' + t('ui.rdp_open') : '';
  const isThisOne = work.step === 'connecting:' + serviceKey(entry);
  const row = entryRow(
    hub, entry, (payload.host || '') + ':' + (payload.port || '') + open,
    serviceNotes[noteKey] || '');
  const connect = document.createElement('button');
  if (isWorking && isThisOne) {
    connect.innerHTML = '<span class="spin"></span>' + t('ui.rdp_connecting');
  } else {
    connect.textContent = t('ui.rdp_connect');
  }
  connect.disabled = isWorking || !entry.is_healthy || isHeld(hub);
  connect.onclick = () => serviceAction('rdp',
    { action: 'connect', hub_id: entry.hub_id, id: entry.id }, noteKey);
  row.appendChild(connect);
  card.appendChild(row);
}

// --- the AI panel: one gateway per hub, one of them the tools' ---

// What each tool points with, staged by the Config dialog and sent with
// the next switch; rebuilt from the server state once a switch lands.
function ensureAiStaged(state) {
  if (aiStaged) return aiStaged;
  aiStaged = {
    tool_configs: JSON.parse(JSON.stringify(state.ai_tool_configs || {})),
  };
  return aiStaged;
}

// A gateway is in use while its hub is the exit and the tools are pointed;
// switching one on points the tools at it and leaves every other off.
function drawAiEntry(card, state, hub, entry) {
  const staged = ensureAiStaged(state);
  const ai = state.ai || {};
  const work = ai.work || {};
  const isWorking = work.state === 'working';
  const isExit = !!hub.is_exit;
  const isInUse = isExit && !!ai.is_enabled;
  const payload = entry.payload || {};
  const noteKey = 'ai_' + serviceKey(entry);
  const note = isExit && isWorking ? t('ui.ai_switching')
    : isInUse && ai.is_active ? t('ui.ai_on') : '';
  const row = entryRow(hub, entry, payload.endpoint || '', note);
  const config = document.createElement('button');
  config.className = 'ghost';
  config.textContent = t('ui.config');
  config.disabled = !entry.is_healthy || isHeld(hub) || isWorking;
  config.onclick = () => openConfigDialog(staged, payload.models || [],
    () => { if (isInUse) askAiUse(hub, entry, true, noteKey); });
  row.appendChild(config);
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = isInUse ? 'chip on' : 'chip';
  toggle.disabled = !entry.is_healthy || isHeld(hub) || isWorking;
  toggle.innerHTML = isExit && isWorking ? marker('spin')
    : marker(isInUse && ai.is_active ? 'ok' : 'off');
  toggle.appendChild(document.createTextNode(t('ui.ai_use')));
  toggle.onclick = () => askAiUse(hub, entry, !isInUse, noteKey);
  row.appendChild(toggle);
  card.appendChild(row);

  const notes = [];
  if (isExit && ai.code) notes.push(wordCode(ai.code, ai.params));
  if (isExit && work.code) notes.push(wordCode(work.code, work.params));
  for (const text of notes) card.appendChild(errorLine(text));
}

// Switching a gateway on makes its hub the exit first, then points the
// tools; switching the one in use off puts the tools back.
async function askAiUse(hub, entry, isOn, noteKey) {
  const isEnabled = !!(lastState && (lastState.ai || {}).is_enabled);
  if (isOn && !hub.is_exit) {
    const reply = await send('/api/exit/set', { hub_id: hubKey(hub) });
    if (!reply || reply.code) {
      serviceNotes[noteKey] = reply ? wordCode(reply.code, reply.params) : '';
      redraw();
      return;
    }
    delete serviceNotes[noteKey];
    if (isEnabled) return;
  }
  const isSent = await serviceAction('ai', {
    hub_id: entry.hub_id,
    is_enabled: isOn,
    tool_configs: ensureAiStaged(lastState).tool_configs,
  }, noteKey);
  if (isSent) { aiStaged = null; redraw(); }
}

// Which picker is open, by the id the caller gave it. Kept outside the
// element so a redraw finds it again.
let openPicker = '';

// The page's one dropdown: a field that opens a list of at most five rows
// and scrolls past that, after the hub's own credential picker. The list
// opens and closes inside the field's own element, so it works the same on
// the page and inside a dialog, and no redraw is needed to show it.
function picker(id, options, chosen, onPick, isDisabled) {
  const wrap = document.createElement('div');
  wrap.className = 'picker';
  let current = options.filter((option) => option.value === chosen)[0]
    || options[0];
  const field = document.createElement('button');
  field.type = 'button';
  field.className = 'picker_field';
  field.disabled = !!isDisabled;
  const label = document.createElement('span');
  label.textContent = current ? current.label : '';
  const caret = document.createElement('span');
  caret.className = 'caret';
  caret.textContent = '▾';
  field.appendChild(label);
  field.appendChild(caret);
  wrap.appendChild(field);

  function close() {
    const open = wrap.querySelector('.picker_list');
    if (open) open.remove();
    if (openPicker === id) openPicker = '';
  }
  function open() {
    closeEveryPicker();
    openPicker = id;
    const list = document.createElement('div');
    list.className = 'picker_list';
    for (const option of options) {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'picker_row' +
        (current && option.value === current.value ? ' on' : '');
      row.textContent = option.label;
      row.onclick = (event) => {
        event.stopPropagation();
        current = option;
        label.textContent = option.label;
        close();
        onPick(option.value);
        settle();
      };
      list.appendChild(row);
    }
    wrap.appendChild(list);
  }
  field.onclick = (event) => {
    event.stopPropagation();
    if (wrap.querySelector('.picker_list')) { close(); settle(); } else open();
  };
  if (openPicker === id && !isDisabled) open();
  return wrap;
}

// A click anywhere else closes whichever list is open.
function closeEveryPicker() {
  for (const list of document.querySelectorAll('.picker_list')) list.remove();
  openPicker = '';
}
document.addEventListener('click', () => {
  if (openPicker) { closeEveryPicker(); settle(); }
});

function modelSelect(id, models, chosen, onPick) {
  const options = [{ value: '', label: '(' + t('ui.gateway_default') + ')' }];
  for (const model of models) options.push({ value: model, label: model });
  const value = models.indexOf(chosen) >= 0 ? chosen : '';
  return picker(id, options, value, onPick, false);
}

// Save keeps what each tool points with, and hands on to onSave, which
// sends it at once when the gateway is in use.
function openConfigDialog(staged, models, onSave) {
  const draft = JSON.parse(JSON.stringify(staged.tool_configs || {}));
  for (const tool of ['claude', 'codex', 'gemini']) {
    if (!draft[tool]) draft[tool] = {};
  }
  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  const modal = document.createElement('div');
  modal.className = 'card modal';
  const heading = document.createElement('div');
  heading.className = 'panel_title';
  heading.textContent = t('ui.config_title');
  modal.appendChild(heading);

  function field(labelText, control) {
    const label = document.createElement('label');
    label.textContent = labelText;
    modal.appendChild(label);
    modal.appendChild(control);
  }
  function toolTitle(text) {
    const title = document.createElement('div');
    title.className = 'title';
    title.style.marginTop = '8px';
    title.textContent = text;
    modal.appendChild(title);
  }

  toolTitle(t('ui.tool_claude'));
  const slotLabels = {
    default: t('ui.slot_default'), opus: t('ui.slot_opus'),
    sonnet: t('ui.slot_sonnet'), haiku: t('ui.slot_haiku'),
  };
  for (const slot of CLAUDE_SLOTS) {
    field(slotLabels[slot], modelSelect('claude_' + slot, models,
      draft.claude[slot] || '',
      (value) => { draft.claude[slot] = value; }));
  }

  toolTitle(t('ui.tool_codex'));
  field(t('ui.codex_model'), modelSelect('codex_model', models,
    draft.codex.model || '', (value) => { draft.codex.model = value; }));
  const effortOptions = [
    { value: '', label: '(' + t('ui.gateway_default') + ')' }];
  for (const level of REASONING_EFFORTS)
    effortOptions.push({ value: level, label: level });
  const effortValue = REASONING_EFFORTS.indexOf(
    draft.codex.model_reasoning_effort) >= 0
    ? draft.codex.model_reasoning_effort : '';
  field(t('ui.codex_effort'), picker(
    'codex_effort', effortOptions, effortValue,
    (value) => { draft.codex.model_reasoning_effort = value; }, false));

  toolTitle(t('ui.tool_gemini'));
  field(t('ui.gemini_model'), modelSelect('gemini_model', models,
    draft.gemini.model || '', (value) => { draft.gemini.model = value; }));

  const actions = document.createElement('div');
  actions.className = 'row';
  actions.style.marginTop = '8px';
  const save = document.createElement('button');
  save.textContent = t('ui.save');
  save.onclick = () => {
    staged.tool_configs = draft;
    closeDialog(overlay);
    redraw();
    onSave();
  };
  const cancel = document.createElement('button');
  cancel.className = 'ghost';
  cancel.textContent = t('ui.cancel');
  cancel.onclick = () => { closeDialog(overlay); redraw(); };
  actions.appendChild(save);
  actions.appendChild(cancel);
  modal.appendChild(actions);

  overlay.appendChild(modal);
  overlay.onclick = (event) => {
    if (event.target === overlay) { closeDialog(overlay); redraw(); }
  };
  openDialog(overlay);
}

function openDialog(overlay) {
  openDialogs += 1;
  document.body.appendChild(overlay);
}

function settle() {
  if (pendingState !== null && canRedraw()) present(pendingState);
}

function closeDialog(overlay) {
  openDialogs -= 1;
  overlay.remove();
  settle();
}

// --- the Files panel: Config, then Mount / Unmount ---

function mountDefaultPath(payload, state) {
  // A drive letter where that is the shape, the platform's own free one.
  if ((state.mount_location_shape || 'path') === 'drive_letter') {
    return state.mount_location_suggestion || 'N:';
  }
  return (state.home || '') + '/nas/' + (payload.share || '');
}

// A form staged for an entry no hub carries any more is gone.
function dropStaleFileStages(state) {
  const present = new Set((state.services || []).map(serviceKey));
  for (const key of Object.keys(fileStaged)) {
    if (!present.has(key)) delete fileStaged[key];
  }
}

// The panel is marked dirty while any entry's form is open.
function drawFileEntry(card, state, hub, entry) {
  const key = serviceKey(entry);
  const payload = entry.payload || {};
  const records = (state.mounts || []).filter(
    (record) => record.hub_id === entry.hub_id && record.entry_id === entry.id);
  const noteKey = 'file_' + key;
  const note = serviceNotes[noteKey] || '';
  const row = entryRow(
    hub, entry, '//' + (payload.host || '') + '/' + (payload.share || ''), note);

  const staged = fileStaged[key];
  if (staged && staged.is_open) card.classList.add('dirty');
  const config = document.createElement('button');
  config.className = 'ghost';
  config.textContent = t('ui.config');
  config.disabled = isHeld(hub);
  config.onclick = () => {
    if (staged && staged.is_open) {
      delete fileStaged[key];
    } else {
      const kept = records[0];
      fileStaged[key] = {
        is_open: true, username: kept ? (kept.username || '') : '',
        password: '',
        path: kept ? kept.path : mountDefaultPath(payload, state),
      };
    }
    redraw();
  };
  row.appendChild(config);

  const mount = mountButton(entry, records[0], staged, noteKey);
  if (isHeld(hub)) mount.disabled = true;
  row.appendChild(mount);
  card.appendChild(row);

  for (const record of records)
    card.appendChild(drawMountRecord(record, state, noteKey));
  if (staged && staged.is_open)
    card.appendChild(drawFileForm(staged, state));
}

// A record on its way says which step it is on; anywhere else, nothing.
function mountBusyWord(state) {
  return MOUNT_BUSY_STATES.indexOf(state) >= 0 ? t('ui.mount_' + state) : '';
}

// The codes a record can only leave with a new login: mounting it again as
// it stands would be refused again, so Mount opens the form instead.
const LOGIN_CODES = ['share_login_rejected', 'credentials_missing'];

// The one button position beside Config: Mount morphs through the
// transients and into Unmount, never a second button anywhere. An open
// form always wins: what it holds is sent as a fresh mount, whether or not
// a record already stands, and the hub-side record and its saved login are
// replaced by it.
function mountButton(entry, record, staged, noteKey) {
  const button = document.createElement('button');
  const key = serviceKey(entry);
  const isBusy = record !== undefined && (fileAsked[record.record_id] ||
    mountBusyWord(record.state));
  if (!isBusy && staged && staged.is_open) {
    button.textContent = t('ui.mount');
    button.disabled = !entry.is_healthy || !staged.path;
    button.onclick = async () => {
      const sent = {
        action: 'mount', hub_id: entry.hub_id, id: entry.id,
        username: staged.username, password: staged.password, path: staged.path,
      };
      staged.password = '';
      if (await serviceAction('file', sent, noteKey)) {
        delete fileStaged[key];
        redraw();
      }
    };
    return button;
  }
  if (record === undefined) {
    button.textContent = t('ui.mount');
    button.disabled = true;
    return button;
  }
  const askedStep = fileAsked[record.record_id];
  const busyWord = askedStep ? t('ui.unmounting')
    : mountBusyWord(record.state);
  if (busyWord) {
    button.textContent = busyWord;
    button.disabled = true;
    return button;
  }
  if (LOGIN_CODES.indexOf(record.code) >= 0) {
    // Nothing to retry with: the press opens the form, the login prefilled.
    button.textContent = t('ui.mount');
    button.onclick = () => {
      fileStaged[key] = {
        is_open: true, username: record.username || '', password: '',
        path: record.path,
      };
      redraw();
    };
    return button;
  }
  if (record.state === 'detached' || record.code) {
    button.textContent = t('ui.mount');
    button.onclick = () => serviceAction('file',
      { action: 'mount', hub_id: entry.hub_id, record_id: record.record_id },
      noteKey);
    return button;
  }
  button.className = 'danger';
  button.textContent = t('ui.unmount');
  button.onclick = () => {
    fileAsked[record.record_id] = 'unmounting';
    redraw();
    serviceAction('file',
      { action: 'unmount', hub_id: entry.hub_id, record_id: record.record_id },
      noteKey
    ).then(() => { delete fileAsked[record.record_id]; redraw(); });
  };
  return button;
}

// A record's own line carries only where it stands: the words, never a
// button.
function drawMountRecord(record, state, noteKey) {
  const line = document.createElement('div');
  line.className = 'rec';
  const askedStep = fileAsked[record.record_id];
  const busyWord = askedStep ? t('ui.unmounting')
    : mountBusyWord(record.state);
  const status = busyWord ? busyWord
    : record.code ? wordCode(record.code, record.params)
    : record.is_attached ? '' : t('ui.not_attached');
  const marker = busyWord ? '<span class="spin"></span>'
    : '<span class="dot ' +
      (record.is_attached ? 'ok' : record.code ? 'bad' : 'off') + '"></span>';
  line.innerHTML = marker +
    '<span class="path">' + record.path +
    (status ? ' — ' + status : '') + '</span>';
  return line;
}

function drawFileForm(staged, state) {
  const form = document.createElement('div');
  form.className = 'form';
  const fields = [
    ['username', t('ui.username_hint'), 'text'],
    ['password', t('ui.password_hint'), 'password'],
  ];
  for (const [name, hint, type] of fields) {
    const line = document.createElement('div');
    line.className = 'row';
    const input = document.createElement('input');
    input.type = type;
    input.placeholder = hint;
    input.value = staged[name];
    input.oninput = () => { staged[name] = input.value; };
    // Leaving the field lets a state that arrived while typing draw.
    input.onblur = settle;
    line.appendChild(input);
    form.appendChild(line);
  }
  if ((state.mount_location_shape || 'path') === 'drive_letter') {
    form.appendChild(driveLetterLine(staged, state));
  } else {
    form.appendChild(mountPathLine(staged));
  }
  return form;
}

// A directory under the home, with a Browse button that lists it as this
// person.
function mountPathLine(staged) {
  const pathLine = document.createElement('div');
  pathLine.className = 'row';
  const path = document.createElement('input');
  path.placeholder = t('ui.path_hint');
  path.value = staged.path;
  path.oninput = () => { staged.path = path.value; };
  path.onblur = settle;
  const browse = document.createElement('button');
  browse.className = 'ghost';
  browse.textContent = t('ui.browse');
  browse.onclick = () => openBrowser(staged.path, (chosen) => {
    staged.path = chosen;
    redraw();
  });
  pathLine.appendChild(path);
  pathLine.appendChild(browse);
  return pathLine;
}

// A drive letter picked from the ones still free, with a caption naming
// where the share turns up.
function driveLetterLine(staged, state) {
  const wrap = document.createElement('div');
  const letters = (state.mount_location_choices || []).slice();
  if (staged.path && letters.indexOf(staged.path) < 0) letters.unshift(staged.path);
  const options = letters.map((letter) => (
    { value: letter, label: t('ui.mount_drive_label') + ' ' + letter }));
  staged.path = staged.path || (letters[0] || '');
  const select = picker('mount_drive', options, staged.path,
    (value) => { staged.path = value; }, false);
  const caption = document.createElement('div');
  caption.className = 'feat';
  const note = document.createElement('div');
  note.className = 'note';
  note.textContent = t('ui.mount_drive_caption');
  caption.appendChild(note);
  wrap.appendChild(select);
  wrap.appendChild(caption);
  return wrap;
}

// --- the browse dialog, fed by the client as this person ---

function parentPath(path) {
  const trimmed = path.replace(/\/+$/, '');
  const cut = trimmed.slice(0, trimmed.lastIndexOf('/'));
  return cut || '/';
}

function joinPath(path, name) {
  return (path === '/' ? '' : path) + '/' + name;
}

function openBrowser(startPath, onChoose) {
  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  const modal = document.createElement('div');
  modal.className = 'card modal';
  const where = document.createElement('div');
  where.className = 'sub';
  const list = document.createElement('div');
  list.className = 'dirlist';
  const note = document.createElement('div');
  note.className = 'err';
  modal.appendChild(where);
  modal.appendChild(list);
  modal.appendChild(note);
  let current = '/';

  async function browseTo(path) {
    const reply = await api('/api/fs?path=' + encodeURIComponent(path));
    if (!reply) return;
    if (reply.code) {
      note.textContent = wordCode(reply.code, reply.params);
      return;
    }
    current = reply.path;
    where.textContent = current;
    note.textContent = '';
    list.innerHTML = '';
    if (current !== '/') {
      const up = document.createElement('button');
      up.textContent = t('ui.up');
      up.onclick = () => browseTo(parentPath(current));
      list.appendChild(up);
    }
    for (const name of reply.dirs) {
      const item = document.createElement('button');
      item.textContent = name + '/';
      item.onclick = () => browseTo(joinPath(current, name));
      list.appendChild(item);
    }
  }

  const actions = document.createElement('div');
  actions.className = 'row';
  const create = document.createElement('button');
  create.className = 'ghost';
  create.textContent = t('ui.new_folder');
  create.onclick = async () => {
    const name = prompt(t('ui.new_folder_name'));
    if (!name) return;
    const reply = await api('/api/fs', { path: joinPath(current, name) });
    if (!reply) return;
    if (reply.code) {
      note.textContent = wordCode(reply.code, reply.params);
      return;
    }
    browseTo(current);
  };
  const choose = document.createElement('button');
  choose.textContent = t('ui.choose');
  choose.onclick = () => { closeDialog(overlay); onChoose(current); };
  const cancel = document.createElement('button');
  cancel.className = 'ghost';
  cancel.textContent = t('ui.cancel');
  cancel.onclick = () => { closeDialog(overlay); };
  actions.appendChild(create);
  actions.appendChild(choose);
  actions.appendChild(cancel);
  modal.appendChild(actions);

  overlay.appendChild(modal);
  overlay.onclick = (event) => {
    if (event.target === overlay) closeDialog(overlay);
  };
  openDialog(overlay);
  browseTo(parentPath(startPath || '/'));
}

bridgeReady().then(firstFrame);
