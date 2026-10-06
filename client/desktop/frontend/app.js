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
// What each left-out feature the tree holds adds to the page, from its own
// file inlined before this one; none in a tree without them.
const PARTS = window.NEUTRINO_PARTS || [];

// Codes worded through their params' own detail text when they carry one.
const DETAIL_CODES = [
  'switch_failed', 'reconcile_failed', 'mount_failed', 'unmount_failed',
  'forward_failed',
];
// The mount states that are a step on the way.
const MOUNT_BUSY_STATES = ['queued', 'mounting', 'pending'];

// Claude Code's four role slots and Codex's reasoning scale, as the client
// stores them.
const CLAUDE_SLOTS = ['default', 'opus', 'sonnet', 'haiku'];
const REASONING_EFFORTS = ['minimal', 'low', 'medium', 'high'];

// The licence the client ships under and where its source is, by the edition
// the state names; the programs the package carries, each with the key its
// version is stamped under, its licence, its repository, the mirror the
// mainland edition links instead where one holds the same tags, the tag a
// version is released under and, for one only a system's package carries,
// that system.
const CLIENT_LICENCE = 'MIT';
const CLIENT_SOURCES = {
  intl: 'https://github.com/iffiX/neutrino',
  cn: 'https://gitee.com/iffiX/neutrino',
};
const CARRIED = PARTS.flatMap((part) => part.carried || []).concat([
  { name: 'EasyTier', key: 'easytier', licence: 'LGPL-3.0',
    repository: 'https://github.com/EasyTier/EasyTier',
    mainland: 'https://gitee.com/easytier/EasyTier', tag: 'v{version}' },
  { name: 'RustDesk', key: 'rustdesk', licence: 'AGPL-3.0',
    repository: 'https://github.com/rustdesk/rustdesk',
    mainland: 'https://gitee.com/mirrors/rustdesk', tag: '{version}' },
  { name: 'cc-switch', key: 'cc-switch', licence: 'MIT',
    repository: 'https://github.com/SaladDay/cc-switch-cli', tag: 'v{version}' },
  { name: 'tun2socks', key: 'tun2socks', licence: 'MIT',
    repository: 'https://github.com/xjasonlyu/tun2socks', tag: 'v{version}',
    os: 'windows' },
]);

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
  return wordCode(e.code, e.params);
}

let lastState = null;
let lastSerialized = '';
// How many states the page has drawn, counted on each new one; a redraw of
// the same state does not count.
let stateSerial = 0;
let pendingState = null;
// What each AI tool points with, as the Configure dialog left it; sent with
// the next switch, and null rebuilds it from the next server state.
let aiStaged = null;
// The staged file configs, one per service key: {is_open, username,
// password, path, before, is_sent}. A closed stage is a saved form, sent by
// Mount and kept until the share it sent is mounted; ``before`` is what
// Cancel puts back. The password lives only here and in the requests that
// send it.
let fileStaged = {};
// The join row while its link is checked, and the code a refused link left
// under the input until the next press.
let isJoining = false;
let joinError = null;

// What one hub is keyed by on this page: its id once its welcome named
// it, its binding's id before that.
function hubKey(hub) {
  return hub.hub_id || hub.binding_id;
}

// What one entry is keyed by: its hub and its id, as the resident keys it.
function serviceKey(entry) {
  return entry.hub_id + '/' + entry.id;
}
// Dialogs are built outside draw() and counted here, so a push never
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
  if (openMenu) return false;
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

// The resident pushes every change of state here; nothing polls for it. A
// shell's output comes the same way, as a piece naming its terminal.
window.neutrinoState = (state) => {
  if (!state) return;
  if (state.terminal) { takeShellPiece(state.terminal); return; }
  if (state.code) { renderHint(wordCode(state.code, state.params)); return; }
  present(state);
};

async function firstFrame() {
  const state = await api('/api/state');
  window.neutrinoState(state);
}

// A request whose answer is the whole state draws it at once.
async function send(path, body) {
  const reply = await api(path, body || {});
  if (reply && !reply.code) { lastSerialized = JSON.stringify(reply); draw(reply); }
  return reply;
}

// --- the destructive press: the first arms, the second within 5 s acts ---

const ARM_MS = 5000;
let armedKey = '';
let armTimer = null;

function isArmed(key) {
  return armedKey === key;
}

function arm(key) {
  clearTimeout(armTimer);
  armedKey = key;
  armTimer = setTimeout(disarm, ARM_MS);
  redraw();
}

function disarm() {
  clearTimeout(armTimer);
  armTimer = null;
  if (!armedKey) return;
  armedKey = '';
  redraw();
}

// A press anywhere but on the armed button disarms it.
document.addEventListener('mousedown', (event) => {
  if (!armedKey) return;
  const target = event.target.closest ? event.target.closest('[data-arm]') : null;
  if (!target || target.dataset.arm !== armedKey) disarm();
}, true);

// A red-outlined button that arms on the first press and acts on the second.
function armedButton(key, label, armedLabel, onAct) {
  const button = document.createElement('button');
  button.type = 'button';
  button.dataset.arm = key;
  button.className = isArmed(key) ? 'danger armed' : 'danger';
  button.textContent = isArmed(key) ? armedLabel : label;
  button.onclick = () => {
    if (!isArmed(key)) { arm(key); return; }
    disarm();
    onAct();
  };
  return button;
}

// A button that is its job's indicator while the job runs: a spinner, the
// in-progress word, and no press.
function jobButton(label, job, className) {
  const button = document.createElement('button');
  button.type = 'button';
  if (className) button.className = className;
  if (job) {
    button.innerHTML = '<span class="spin"></span>';
    button.appendChild(document.createTextNode(t('ui.job.' + job)));
    button.disabled = true;
  } else {
    button.textContent = label;
  }
  return button;
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

// The codes on a hub that is down which a person has to act on: its dot is
// red. Any other code leaves it amber.
const PERSON_CODES = [
  'hub_untrusted', 'binding_unknown', 'protocol_too_old', 'protocol_too_new',
];
// The five states of a hub's connection, as the resident names them.
const CONNECTION_STATES = [
  'connected', 'connecting', 'down', 'replaced', 'disabled', 'pending',
];
// The three states of a hub's virtual network.
const OVERLAY_STATES = ['off', 'connecting', 'on'];
// The name each virtual network's engine goes by.
const OVERLAY_TITLES = Object.assign(
  {}, ...PARTS.map((part) => part.overlayTitles || {}), { easytier: 'EasyTier' });

// A status mark: a dot in its tone; 'pulse' is the amber dot of work running.
function marker(tone) {
  return '<span class="dot ' + (tone === 'pulse' ? 'wait pulse' : tone) + '"></span>';
}

function draw(state) {
  if (state !== lastState) stateSerial += 1;
  lastState = state;
  setLanguage(state.language);
  setTheme(state.theme);
  document.title = t('ui.window.title');
  document.querySelector('h1').textContent = t('ui.window.title');
  drawRefresh(state);
  drawTabs();
  document.getElementById('page_title').textContent = tabTitle(openTab);
  dropStaleFileStages(state);
  mergeSessions(state);

  const content = document.getElementById('content');
  content.innerHTML = '';
  if (openTab === 'hubs') {
    content.appendChild(drawHubs(state));
  } else if (openTab === 'terminals') {
    content.appendChild(drawTerminals(state));
  } else if (openTab === 'settings') {
    content.appendChild(drawSettings(state));
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

// Whether any hub waits for the answer to a refresh.
function isAnyRefreshing(state) {
  return (state.hubs || []).some((hub) => isRefreshing(hub));
}

function isRefreshing(hub) {
  return !!(hub.jobs && hub.jobs.is_refreshing);
}

// The refresh button in the top bar: a spinner while any hub refreshes,
// pressed only when none does.
function drawRefresh(state) {
  const button = document.getElementById('refresh');
  button.title = t('ui.refresh');
  button.setAttribute('aria-label', t('ui.refresh'));
  if (isAnyRefreshing(state)) {
    button.innerHTML = '<span class="spin"></span>';
    button.disabled = true;
  } else {
    button.textContent = '↻';
    button.disabled = false;
  }
  button.onclick = () => send('/api/refresh', {});
}

// --- the row every page is made of ---

// A row: the dot, then the body's lines (title, state word, mono line,
// error line, reason line), then the actions, the red-outlined one last.
function rowElement(parts) {
  const row = document.createElement('div');
  row.className = 'feat';
  row.innerHTML = marker(parts.tone);
  const body = document.createElement('div');
  body.className = 'body';
  const lines = [
    ['title', parts.title], ['note', parts.word], ['sub', parts.mono],
    ['note muted', parts.provider],
  ];
  for (const [className, text] of lines) {
    if (!text) continue;
    const line = document.createElement('div');
    line.className = className;
    line.textContent = text;
    body.appendChild(line);
  }
  for (const extra of parts.extras || []) body.appendChild(extra);
  if (parts.error) body.appendChild(errorLine(parts.error));
  if (parts.reason) body.appendChild(reasonLine(parts.reason));
  row.appendChild(body);
  if (parts.actions && parts.actions.length) {
    const actions = document.createElement('div');
    actions.className = 'row_actions';
    for (const action of parts.actions) actions.appendChild(action);
    row.appendChild(actions);
  }
  return row;
}

function errorLine(text) {
  const line = document.createElement('div');
  line.className = 'err';
  line.textContent = text;
  return line;
}

function noteLine(text) {
  const line = document.createElement('div');
  line.className = 'note muted';
  line.textContent = text;
  return line;
}

function reasonLine(text) {
  const line = document.createElement('div');
  line.className = 'reason';
  line.textContent = text;
  return line;
}

// --- one kind's panel: every hub's entries of that kind, in hub order ---

function kindTab(state, kind) {
  const [type, titleKey, build, emptyKey] = kind;
  const hubs = state.hubs || [];
  if (hubs.length === 0) return waitCard();
  const card = panelCard(t(titleKey), false);
  let count = 0;
  for (const hub of hubs) {
    const entries = entriesOf(state, hub, type);
    if (isReachable(hub)) {
      for (const entry of entries) {
        build(card, state, hub, entry);
        count += 1;
      }
    } else {
      card.appendChild(downRow(hub));
    }
  }
  if (count === 0) card.appendChild(emptyRow(t(emptyKey)));
  return card;
}

// Whether a hub's socket is up, so its entries stand.
function isReachable(hub) {
  return hub.connection === 'connected' || hub.connection === 'disabled';
}

// A hub whose socket is down publishes nothing; its row in a panel says why.
function downRow(hub) {
  return rowElement({ tone: hubTone(hub), title: hubName(hub), word: hubWord(hub) });
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

// --- the Hubs page: one row per hub, the join row under them ---

function drawHubs(state) {
  const card = document.createElement('div');
  card.className = 'card';
  for (const notice of state.notices || []) card.appendChild(noticeLine(notice));
  const hubs = state.hubs || [];
  for (const hub of hubs) card.appendChild(hubRow(hub));
  if (hubs.length === 0) {
    card.appendChild(rowElement({ tone: 'off', title: t('ui.no_hubs') }));
  }
  card.appendChild(joinRow());
  return card;
}

// One page-wide notice: its code's wording and the button that closes it.
function noticeLine(notice) {
  const line = document.createElement('div');
  line.className = 'notice';
  line.appendChild(errorLine(wordCode(notice.code, notice.params)));
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'notice_close';
  close.textContent = '×';
  close.title = t('ui.notice_close');
  close.setAttribute('aria-label', close.title);
  close.onclick = () => send('/api/notice/close', { id: notice.id });
  line.appendChild(close);
  return line;
}

// Where one hub stands, as a colour: amber pulsing while anything runs on
// the row or the socket is connecting, green connected, red for a code a
// person has to act on, grey for a hub never reached, amber otherwise.
function hubTone(hub) {
  const jobs = hub.jobs || {};
  if (jobs.is_refreshing || jobs.is_leaving || jobs.overlay_job
    || jobs.is_opening_panel) return 'pulse';
  if (isJoinRefused(hub)) return 'bad';
  if (hub.connection === 'pending') return 'off';
  if (hub.connection === 'connecting') return 'pulse';
  if (hub.connection === 'connected') return 'ok';
  if (hub.connection === 'down') {
    const code = hub.last_error ? hub.last_error.code : '';
    if (PERSON_CODES.indexOf(code) >= 0) return 'bad';
  }
  return 'wait';
}

// The ways the channel reaches a hub, as the hub's state names them. A
// way not in the list reads as the plain connected word.
const THROUGH_WAYS = ['lan', 'direct'].concat(
  ...PARTS.map((part) => part.throughWays || []), ['easytier', 'relay']);

// The hub's state word: the job running on it, else its connection's, with
// the way in once the hub has named it.
function hubWord(hub) {
  const jobs = hub.jobs || {};
  if (jobs.is_leaving) return t('ui.job.leaving');
  if (jobs.is_refreshing) return t('ui.job.refreshing');
  const connection = CONNECTION_STATES.indexOf(hub.connection) >= 0
    ? hub.connection : 'connecting';
  if (connection === 'connected' && THROUGH_WAYS.indexOf(hub.reached_through) >= 0) {
    return t('ui.state.connected_through',
      { way: t('ui.through.' + hub.reached_through) });
  }
  return t('ui.state.' + connection);
}

// One hub: its name, its state word, its address, the AI marker, its
// virtual network's line, the error line; and the picker, the network
// button, Reconnect while replaced, and Leave. A hub that publishes no
// virtual network has no network line, picker or button.
function hubRow(hub) {
  const jobs = hub.jobs || {};
  const software = hub.software ? ' · ' + t('ui.hub_software', { software: hub.software }) : '';
  const extras = [];
  if (hub.is_exit) extras.push(noteLine(t('ui.hub_is_exit')));
  const overlay = hub.overlay || {};
  const hasNetwork = (overlay.networks || []).length > 0;
  if (hasNetwork) {
    extras.push(overlayLine(hub));
    const stage = overlayStage(overlay);
    if (stage) {
      const line = reasonLine(stage);
      if (overlay.state === 'connecting' && overlay.stage === 'hub' && !overlay.is_waiting) {
        line.classList.add('stage_clock');
        line.dataset.address = overlay.address || '';
        line.dataset.since = String(overlay.stage_since || 0);
      }
      extras.push(line);
    }
    if (overlay.state === 'off' && overlay.error) {
      extras.push(errorLine(wordError(overlay.error)));
    }
  }
  if (hub.last_error) extras.push(errorLine(wordError(hub.last_error)));
  if (isJoinRefused(hub)) {
    return rowElement({
      tone: hubTone(hub),
      title: hubName(hub),
      word: hubWord(hub),
      mono: hub.gateway_url,
      extras: extras,
      actions: [leaveButton(hub)],
    });
  }
  const actions = [];
  const networkPicker = hasNetwork ? overlayPicker(hub) : null;
  if (networkPicker) actions.push(networkPicker);
  const network = hasNetwork ? overlayButton(hub) : null;
  if (network) actions.push(network);
  if (hub.is_panel_allowed) actions.push(panelButton(hub));
  if (hub.connection === 'replaced') {
    const reconnect = document.createElement('button');
    reconnect.type = 'button';
    reconnect.textContent = t('ui.reconnect');
    reconnect.onclick = () => send('/api/session/start', { hub_id: hubKey(hub) });
    actions.push(reconnect);
  }
  actions.push(leaveButton(hub));
  return rowElement({
    tone: hubTone(hub),
    title: hubName(hub),
    word: hubWord(hub),
    mono: hub.gateway_url + software,
    extras: extras,
    reason: (!network || network.disabled) && !jobs.is_leaving ? overlayReason(hub) : '',
    actions: actions,
  });
}

// Panel: opens the hub's panel in the browser through its forward, and is
// the row's indicator while it does; it acts on a connected hub only.
function panelButton(hub) {
  const jobs = hub.jobs || {};
  const button = jobButton(t('ui.hub_panel'), jobs.is_opening_panel ? 'opening' : '');
  if (!jobs.is_opening_panel) {
    button.disabled = hub.connection !== 'connected' || !!jobs.is_leaving
      || !!jobs.is_refreshing;
    button.onclick = () => send('/api/panel/open', { hub_id: hubKey(hub) });
  }
  return button;
}

// A join whose ticket the hub refused: the row is down with the code, and
// Leave is all it offers.
function isJoinRefused(hub) {
  return hub.is_pending === true && hub.connection === 'down';
}

// Leave: arms on the first press, leaves on the second, and is the row's
// indicator while the hub is being left.
function leaveButton(hub) {
  if ((hub.jobs || {}).is_leaving) return jobButton('', 'leaving', 'danger');
  const key = 'leave:' + hubKey(hub);
  return armedButton(key, t('ui.leave'), t('ui.leave_armed'),
    () => send('/api/leave', { hub_id: hubKey(hub) }));
}

// The line for the hub's virtual network: the engine or the word for it,
// the state word, the address while on.
function overlayLine(hub) {
  const overlay = hub.overlay || {};
  const networks = overlay.networks || [];
  const state = OVERLAY_STATES.indexOf(overlay.state) >= 0 ? overlay.state : 'off';
  const line = document.createElement('div');
  line.className = 'overlay_line';
  const tone = overlay.state === 'on' && !(hub.jobs || {}).overlay_job ? 'ok'
    : overlay.state === 'connecting' || (hub.jobs || {}).overlay_job ? 'pulse' : 'off';
  line.innerHTML = marker(tone);
  const name = networks.length === 1
    ? (OVERLAY_TITLES[networks[0].provider] || networks[0].provider)
    : t('ui.overlay');
  line.appendChild(document.createTextNode(
    name + ' · ' + t('ui.overlay.' + state, { address: overlay.address || '' })));
  return line;
}

// The stage a connect is in, as the line's reason: the engine logging in,
// the console not yet assigning a network, or the hub not yet answering.
function overlayStage(overlay) {
  if (overlay.state !== 'connecting') return '';
  if (overlay.is_waiting) return t('ui.reason.console_waiting');
  if (overlay.stage === 'login') {
    return t('ui.stage.login', { engine: OVERLAY_TITLES[overlay.network] || overlay.network });
  }
  if (overlay.stage === 'hub') return hubStageWords(overlay.address || '', overlay.stage_since);
  return '';
}

// The hub stage's reason: the address and the seconds waited since the
// stage began, by this machine's clock.
function hubStageWords(address, since) {
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - (Number(since) || 0)));
  return t('ui.stage.hub', { address: address, seconds: since ? seconds : 0 });
}

// The seconds on every hub stage's reason move once a second, with no
// state pushed.
setInterval(() => {
  for (const line of document.querySelectorAll('.stage_clock')) {
    line.textContent = hubStageWords(line.dataset.address, line.dataset.since);
  }
}, 1000);

// The engine picker, while the hub publishes two networks or more; it
// picks only while the network is off, and names the engine otherwise.
function overlayPicker(hub) {
  const overlay = hub.overlay || {};
  const networks = overlay.networks || [];
  if (networks.length < 2) return null;
  const options = networks.map((network) => ({
    value: network.provider,
    label: OVERLAY_TITLES[network.provider] || network.provider,
  }));
  const key = hubKey(hub);
  const isLocked = overlay.state !== 'off' || !!(hub.jobs || {}).overlay_job
    || hub.connection === 'disabled' || !!(hub.jobs || {}).is_leaving;
  const wrap = picker('overlay_' + key, options, overlay.network, (provider) => {
    send('/api/overlay/pick', { hub_id: key, provider: provider });
  }, isLocked);
  wrap.classList.add('overlay_pick');
  wrap.title = t('ui.overlay_pick');
  return wrap;
}

// The one network button: Connect while off, Cancel while connecting,
// Disconnect while on; the step that stops the engine shows on it.
function overlayButton(hub) {
  const overlay = hub.overlay || {};
  const jobs = hub.jobs || {};
  const key = hubKey(hub);
  if (jobs.overlay_job === 'disconnecting') return jobButton('', 'disconnecting');
  const button = document.createElement('button');
  button.type = 'button';
  if (overlay.state === 'connecting') {
    button.innerHTML = '<span class="spin"></span>';
    button.appendChild(document.createTextNode(t('ui.network_cancel')));
    button.onclick = () => send('/api/overlay/cancel', { hub_id: key });
    return button;
  }
  if (overlay.state === 'on') {
    button.textContent = t('ui.network_disconnect');
    button.onclick = () => send('/api/overlay/disconnect', { hub_id: key });
  } else {
    button.textContent = t('ui.network_connect');
    button.onclick = () => send('/api/overlay/connect', { hub_id: key });
  }
  button.disabled = hub.connection === 'disabled' || !!jobs.is_leaving;
  return button;
}

// Why the network button cannot act, and why a hub with no network is idle.
function overlayReason(hub) {
  if (hub.connection === 'disabled') return t('ui.reason.disabled');
  return '';
}

// The row that is always there: paste a link, join one more hub.
function joinRow() {
  const body = document.createElement('div');
  const line = document.createElement('div');
  line.className = 'row';
  const input = document.createElement('input');
  input.placeholder = 'neutrino://enroll/...';
  input.onkeydown = (e) => { if (e.key === 'Enter') join(); };
  input.onblur = settle;
  const button = jobButton(t('ui.join'), isJoining ? 'joining' : '');
  button.onclick = join;
  function join() {
    if (isJoining) return;
    isJoining = true;
    joinError = null;
    redraw();
    api('/api/join', { link: input.value }).then((reply) => {
      isJoining = false;
      joinError = reply && reply.error ? reply.error : null;
      if (reply && !reply.code) { lastSerialized = JSON.stringify(reply); draw(reply); }
    });
  }
  line.appendChild(input);
  line.appendChild(button);
  body.appendChild(line);
  return rowElement({
    tone: 'off',
    title: t('ui.add_hub'),
    word: t('ui.paste_hint'),
    extras: [body],
    error: joinError ? wordCode(joinError.code, joinError.params) : '',
  });
}

function noteLine(text) {
  const note = document.createElement('div');
  note.className = 'note muted';
  note.textContent = text;
  return note;
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

// --- the entries of the service pages ---

// Which hub, which of its machines and which module an entry comes from; a
// hub that names no machine leaves the address the entry points at, and an
// entry the hub's own machine serves names the hub once.
function providerLine(hub, entry) {
  const name = hubName(hub);
  const device = entry.device_name || entryHost(entry);
  if (device === name) {
    return t('ui.machine_provided_by', { hub: name, device: entryModule(entry) });
  }
  return t('ui.provided_by', { hub: name, device: device, module: entryModule(entry) });
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

// The work on an entry: its own job, else its hub's refresh.
function entryWork(hub, entry) {
  if (entry.job) return entry.job;
  return isRefreshing(hub) ? 'refreshing' : '';
}

// Whether an entry is unhealthy: only a health of false is. An entry with
// empty health, a record no probe has reached, is not.
function isUnhealthy(entry) {
  return entry.is_healthy === false;
}

// An entry's dot: amber pulsing while work runs on it, amber unhealthy,
// green otherwise.
function entryTone(hub, entry) {
  if (entryWork(hub, entry)) return 'pulse';
  return isUnhealthy(entry) ? 'wait' : 'ok';
}

// An entry's state word: the work running on it, else unhealthy, else what
// the caller says it stands at.
function entryWord(hub, entry, standing) {
  const work = entryWork(hub, entry);
  if (work) return t('ui.job.' + work);
  if (isUnhealthy(entry)) return t('ui.unhealthy');
  return standing || '';
}

// Why an entry's action cannot run, empty when it can.
function entryReason(hub, entry, isHealthNeeded) {
  if (hub.connection === 'disabled') return t('ui.reason.disabled');
  if (isHealthNeeded && isUnhealthy(entry)) return t('ui.reason.unhealthy');
  return '';
}

// Whether an entry's actions may run: nothing at work on it, its hub not
// refreshing and not switched off.
function isEntryFree(hub, entry) {
  return !entryWork(hub, entry) && hub.connection !== 'disabled';
}

function entryRow(hub, entry, mono, standing, actions, reason, extras) {
  return rowElement({
    tone: entryTone(hub, entry),
    title: entry.title,
    word: entryWord(hub, entry, standing),
    mono: mono,
    provider: providerLine(hub, entry),
    error: wordError(entry.last_error),
    reason: reason,
    actions: actions,
    extras: extras,
  });
}

function serviceAction(type, body) {
  return send('/api/services/' + type, body);
}

// A web entry: Configure, Open and, while forwarded, Disconnect, with the
// loopback port on the mono line. Open runs as the opening job while the
// resident makes the forward and, for an entry with is_token_required,
// reads its token.
function drawWebEntry(card, state, hub, entry) {
  const payload = entry.payload || {};
  const isOn = !!entry.forward;
  const opening = entry.job === 'opening' ? entry.job : '';
  const open = jobButton(t('ui.open'), opening);
  if (!opening) {
    open.disabled = isUnhealthy(entry) || !isEntryFree(hub, entry);
    open.onclick = () => serviceAction('web', { hub_id: entry.hub_id, id: entry.id });
  }
  let reason = open.disabled && !entryWork(hub, entry) ? entryReason(hub, entry, true) : '';
  const configure = configureButton(hub, entry, isOn);
  const actions = [configure, open];
  if (isOn || entry.job === 'disconnecting') {
    actions.push(disconnectButton('web', entry));
  }
  if (!reason && configure.disabled && isOn) reason = t('ui.reason.disconnect_first');
  card.appendChild(entryRow(hub, entry, (payload.url || '') + forwardedTo(entry), '',
    actions, reason));
}

function drawPortEntry(card, state, hub, entry) {
  const payload = entry.payload || {};
  const isOn = !!entry.forward;
  const button = jobButton(isOn ? t('ui.port_disconnect') : t('ui.port_connect'),
    entry.job, isOn ? 'danger' : '');
  if (!entry.job) {
    button.disabled = !isEntryFree(hub, entry) || (isUnhealthy(entry) && !isOn);
    button.onclick = () => serviceAction('port',
      { hub_id: entry.hub_id, id: entry.id, is_enabled: !isOn });
  }
  const configure = configureButton(hub, entry, isOn);
  let reason = button.disabled && !entryWork(hub, entry)
    ? entryReason(hub, entry, !isOn) : '';
  if (!reason && configure.disabled && isOn) reason = t('ui.reason.disconnect_first');
  const suffix = protocolSuffix(entry);
  card.appendChild(entryRow(hub, entry,
    (payload.host || '') + ':' + (payload.port || '') + suffix + forwardedTo(entry),
    '', [configure, button], reason));
}

// What a port entry's addresses carry after them: `/udp` for a UDP entry,
// nothing for a TCP one.
function protocolSuffix(entry) {
  return (entry.payload || {}).protocol === 'udp' ? '/udp' : '';
}

// The mono line's tail of a forwarded entry: where its forward listens.
function forwardedTo(entry) {
  if (!entry.forward) return '';
  return ' → ' + t('ui.forwarding_to', { port: entry.forward }) + protocolSuffix(entry);
}

// The Disconnect of a forwarded page: ends its forward.
function disconnectButton(type, entry) {
  const button = jobButton(t('ui.port_disconnect'),
    entry.job === 'disconnecting' ? entry.job : '', 'danger');
  if (entry.job !== 'disconnecting') {
    button.disabled = !!entry.job;
    button.onclick = () => serviceAction(type,
      { hub_id: entry.hub_id, id: entry.id, is_enabled: false });
  }
  return button;
}

// Configure on a forwardable entry: the local port dialog, closed to an
// entry that is forwarded.
function configureButton(hub, entry, isForwarded) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = t('ui.configure');
  button.disabled = isForwarded || !isEntryFree(hub, entry);
  button.onclick = () => openPortDialog(entry);
  return button;
}

// The local port dialog: Auto, or Fixed with a number from 1024 to 65535.
function openPortDialog(entry) {
  const saved = entry.local_port === undefined ? 'auto' : entry.local_port;
  let isFixed = saved !== 'auto';
  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  const modal = document.createElement('div');
  modal.className = 'card modal';
  const heading = document.createElement('div');
  heading.className = 'panel_title';
  heading.textContent = entry.title;
  modal.appendChild(heading);
  const label = document.createElement('label');
  label.textContent = t('ui.local_port');
  modal.appendChild(label);
  const line = document.createElement('div');
  line.className = 'row';
  const number = document.createElement('input');
  number.type = 'number';
  number.min = '1024';
  number.max = '65535';
  number.value = isFixed ? String(saved) : '';
  const choice = picker('local_port_' + serviceKey(entry), [
    { value: 'auto', label: t('ui.local_port_auto') },
    { value: 'fixed', label: t('ui.local_port_fixed') },
  ], isFixed ? 'fixed' : 'auto', (value) => { isFixed = value === 'fixed'; check(); },
  false);
  choice.style.flex = 'none';
  choice.style.minWidth = '120px';
  line.appendChild(choice);
  line.appendChild(number);
  modal.appendChild(line);
  const why = reasonLine('');
  modal.appendChild(why);
  const actions = document.createElement('div');
  actions.className = 'form_actions';
  const save = document.createElement('button');
  save.textContent = t('ui.save');
  const cancel = document.createElement('button');
  cancel.className = 'ghost';
  cancel.textContent = t('ui.cancel');
  actions.appendChild(save);
  actions.appendChild(cancel);
  modal.appendChild(actions);

  function chosen() {
    return isFixed ? Number(number.value) : 'auto';
  }
  function check() {
    number.disabled = !isFixed;
    const value = chosen();
    const isValid = !isFixed || (Number.isInteger(value) && value >= 1024 && value <= 65535);
    why.textContent = isValid ? '' : t('ui.reason.port_range');
    save.disabled = !isValid;
    modal.classList.toggle('dirty', value !== saved);
  }
  number.oninput = check;
  save.onclick = async () => {
    save.disabled = true;
    const reply = await api('/api/forward/configure',
      { hub_id: entry.hub_id, id: entry.id, local_port: chosen() });
    if (reply && reply.code) {
      why.textContent = reply.code === 'port_taken'
        ? t('ui.reason.port_taken', { port: chosen() }) : wordError(reply);
      save.disabled = false;
      return;
    }
    closeDialog(overlay);
    if (reply) { lastSerialized = JSON.stringify(reply); draw(reply); }
  };
  cancel.onclick = () => { closeDialog(overlay); redraw(); };
  overlay.appendChild(modal);
  overlay.onclick = (event) => {
    if (event.target === overlay) { closeDialog(overlay); redraw(); }
  };
  check();
  openDialog(overlay);
}

// --- the remote desktops panel: connect there ---

function drawDesktopEntry(card, state, hub, entry) {
  const payload = entry.payload || {};
  const viewer = (state.viewers || {})[serviceKey(entry)] || {};
  const isOpen = !!viewer.is_running;
  const connect = jobButton(t('ui.rdp_connect'), entry.job);
  if (!entry.job) {
    connect.disabled = isUnhealthy(entry) || !isEntryFree(hub, entry) || isOpen;
    connect.onclick = () => serviceAction('rdp',
      { action: 'connect', hub_id: entry.hub_id, id: entry.id });
  }
  const reason = connect.disabled && !entryWork(hub, entry) && !isOpen
    ? entryReason(hub, entry, true) : '';
  const extras = payload.platform_os === 'darwin' ? [noteLine(t('ui.rdp_mac_hint'))] : [];
  card.appendChild(entryRow(hub, entry,
    (payload.host || '') + ':' + (payload.port || ''),
    isOpen ? t('ui.rdp_open') : t('ui.healthy'), [connect], reason, extras));
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

// Whether a switch of the tools runs anywhere.
function isAiSwitching(state) {
  if (((state.ai || {}).work || {}).state === 'working') return true;
  return (state.services || []).some((entry) => entry.type === 'ai' && entry.job);
}

// A gateway is in use while its hub is the exit and the tools are pointed;
// switching one on points the tools at it and leaves every other off.
function drawAiEntry(card, state, hub, entry) {
  const staged = ensureAiStaged(state);
  const ai = state.ai || {};
  const isExit = !!hub.is_exit;
  const isInUse = isExit && !!ai.is_enabled;
  const payload = entry.payload || {};
  // With the agent installed, its tools are set from the hub's panel.
  const isManaged = !!ai.is_managed;
  const isFree = !isManaged && !isUnhealthy(entry) && isEntryFree(hub, entry)
    && !isAiSwitching(state);
  const config = document.createElement('button');
  config.type = 'button';
  config.className = 'ghost';
  config.textContent = t('ui.configure');
  config.disabled = !isFree;
  config.onclick = () => openConfigDialog(staged, payload.models || [],
    () => { if (isInUse) askAiUse(hub, entry, true); });
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = isInUse ? 'chip on' : 'chip';
  toggle.disabled = !isFree;
  if (entry.job) {
    toggle.innerHTML = '<span class="spin"></span>';
    toggle.appendChild(document.createTextNode(t('ui.job.switching')));
  } else {
    toggle.innerHTML = marker(isInUse && ai.is_active ? 'ok' : 'off');
    toggle.appendChild(document.createTextNode(t('ui.ai_use')));
  }
  toggle.onclick = () => askAiUse(hub, entry, !isInUse);
  const extras = [noteLine(t('ui.ai_needs_client'))];
  if (isExit && ai.code) extras.push(errorLine(wordCode(ai.code, ai.params)));
  let reason = '';
  if (isManaged) reason = t('ui.reason.ai_managed');
  else if (!isFree && !entryWork(hub, entry) && !isAiSwitching(state)) {
    reason = entryReason(hub, entry, true);
  }
  card.appendChild(entryRow(hub, entry, (payload.endpoint || '') + forwardedTo(entry),
    isInUse && ai.is_active ? t('ui.ai_on') : '', [config, toggle], reason, extras));
}

// Switching a gateway on makes its hub the exit first, then points the
// tools; switching the one in use off puts the tools back.
async function askAiUse(hub, entry, isOn) {
  const isEnabled = !!(lastState && (lastState.ai || {}).is_enabled);
  if (isOn && !hub.is_exit) {
    const reply = await send('/api/exit/set', { hub_id: hubKey(hub) });
    if (!reply || reply.code || isEnabled) return;
  }
  const reply = await serviceAction('ai', {
    hub_id: entry.hub_id,
    is_enabled: isOn,
    tool_configs: ensureAiStaged(lastState).tool_configs,
  });
  if (reply && !reply.code) { aiStaged = null; redraw(); }
}

// --- the terminals page: the machine chips, the tab strip, the terminal ---

// Every tab, in the order it appeared: {key, hub_id, device_id, name,
// session_id, terminal_id, term, fit, pane, state, note, isRefused, typed,
// isSending, isListed, isDropped, droppedAt, flags}. ``state`` is 'idle' for
// a listed session no window of this page attached to yet, or one whose hub's
// channel dropped (``isDropped``, at the state count ``droppedAt``),
// 'connecting', 'open', 'ended' once the hub stopped
// listing the session, or 'closed' once the shell ended. The panes live in
// one surface that outlives every redraw, so a redraw moves them rather than
// rebuilding them and the shells keep running.
const shellTabs = [];
let activeShell = '';
let shellCounter = 0;
// The machine the chips have picked, by hub and device.
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
// The client carries MesloLGS NF, so a powerlevel10k prompt draws its icons.
const TERMINAL_FONT_FAMILY = 'MesloLGS NF';
const TERMINAL_FONT = '"' + TERMINAL_FONT_FAMILY + '", ui-monospace, "Cascadia Mono", ' +
  'Consolas, Menlo, monospace';
// Its two faces, by the name the resident serves each under and the weight.
const TERMINAL_FONT_FACES = [['regular', '400'], ['bold', '700']];
// The faces' load, begun by the first shell; every shell redraws once done.
let terminalFontLoad = null;
// The font size every shell draws in until the state names the kept one.
const TERMINAL_FONT_SIZE = 13;
// The context menu open over a terminal, or null.
let openMenu = null;
// The sessions whose tab this page closed, by hub and session id, until the
// hub stops listing them.
const closedSessions = new Set();

function terminalFontSize() {
  return (lastState && lastState.terminal_font_size) || TERMINAL_FONT_SIZE;
}

function isMac() {
  return !!lastState && (lastState.platform || {}).os === 'darwin';
}

function isLinux() {
  return !!lastState && (lastState.platform || {}).os === 'linux';
}

// The sessions the hubs list, merged into the strip by session id: a listed
// session no tab shows gets a tab, a tab whose hub's channel dropped attaches
// again while its session is listed, and a tab whose listed session is gone
// is ended. Only a hub whose socket is up says anything about its sessions.
function mergeSessions(state) {
  const sessions = ((state.terminals || {}).sessions) || [];
  const reachable = (state.hubs || []).filter(isReachable).map((hub) => hub.hub_id);
  const listed = new Set(sessions.map((row) => row.hub_id + '/' + row.session_id));
  for (const tab of shellTabs) {
    if (!tab.session_id || reachable.indexOf(tab.hub_id) < 0) continue;
    const isListedNow = listed.has(tab.hub_id + '/' + tab.session_id);
    if (isListedNow) tab.isListed = true;
    if (tab.isDropped) {
      if (stateSerial <= tab.droppedAt) continue;
      tab.isDropped = false;
      if (isListedNow) {
        reattachShell(tab);
      } else {
        endTab(tab, t('ui.terminal_ended'));
      }
      continue;
    }
    if (tab.isListed && !isListedNow && ['idle', 'connecting', 'open'].indexOf(tab.state) >= 0) {
      endTab(tab, t('ui.terminal_ended'));
    }
  }
  for (const key of Array.from(closedSessions)) {
    if (!listed.has(key)) closedSessions.delete(key);
  }
  const shown = new Set(shellTabs.map((tab) => tab.hub_id + '/' + tab.session_id));
  const isFirst = shellTabs.length === 0;
  for (const row of sessions) {
    const key = row.hub_id + '/' + row.session_id;
    if (shown.has(key) || closedSessions.has(key)) continue;
    const machine = machineOf(state, row.hub_id, row.device_id);
    if (!machine) continue;
    const tab = newTab(row.hub_id, machine, row.session_id);
    tab.state = 'idle';
    tab.isListed = true;
  }
  if (isFirst && shellTabs.length && !activeShell) {
    activeShell = shellTabs[0].key;
  }
}

function machineOf(state, hubId, deviceId) {
  return (((state.terminals || {}).machines) || []).filter((machine) =>
    machine.hub_id === hubId && machine.device_id === deviceId)[0] || null;
}

// The session row the hub last listed for a tab, or null.
function sessionRow(tab) {
  const sessions = ((lastState && lastState.terminals) || {}).sessions || [];
  return sessions.filter((row) =>
    row.hub_id === tab.hub_id && row.session_id === tab.session_id)[0] || null;
}

// A tab's two flags and its owner: the hub's last word, else what this
// window set on a session the hub has not listed yet, which this client
// opened.
function tabFlags(tab) {
  const row = sessionRow(tab);
  if (row) return row;
  return Object.assign(
    { is_owned: true, owner: '', owner_name: '', attached_count: 1 }, tab.flags);
}

function drawTerminals(state) {
  const hubs = state.hubs || [];
  if (hubs.length === 0) return waitCard();
  const themeKey = document.documentElement.dataset.theme;
  if (themeKey !== shellThemeKey) {
    shellThemeKey = themeKey;
    for (const tab of shellTabs) tab.term.options.theme = terminalTheme();
  }
  for (const tab of shellTabs) {
    if (tab.term.options.fontSize !== terminalFontSize()) {
      tab.term.options.fontSize = terminalFontSize();
    }
  }
  const page = document.createElement('div');
  page.className = 'term_page';
  page.appendChild(machineStrip(state));
  page.appendChild(shellPanel(state));
  window.requestAnimationFrame(fitActiveShell);
  const active = activeTab();
  if (active && active.state === 'idle') {
    window.requestAnimationFrame(() => attachShell(active));
  }
  return page;
}

// Every machine a connected hub offers a terminal on, one chip each with its
// presence dot, and the button that opens a new terminal on the picked one.
function machineStrip(state) {
  const card = document.createElement('div');
  card.className = 'card term_pick';
  const chips = document.createElement('div');
  chips.className = 'term_chips';
  const picked = pickedMachine(state);
  let count = 0;
  for (const hub of state.hubs || []) {
    if (!isReachable(hub)) continue;
    const machines = (((state.terminals || {}).machines) || []).filter(
      (machine) => machine.hub_id === hub.hub_id);
    for (const machine of machines) {
      count += 1;
      const isPicked = !!picked && picked.machine === machine;
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = isPicked ? 'chip on' : 'chip';
      chip.title = t('ui.machine_provided_by', { hub: hubName(hub), device: machine.name });
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
  const open = newShellButton(picked);
  line.appendChild(open);
  card.appendChild(line);
  if (picked) {
    card.appendChild(noteLine(t('ui.machine_provided_by',
      { hub: hubName(picked.hub), device: picked.machine.name })));
  }
  if (open.disabled) card.appendChild(reasonLine(newShellReason(picked)));
  return card;
}

// The machine the chips have picked, while a connected hub still offers it.
function pickedMachine(state) {
  if (!shellPick) return null;
  for (const hub of state.hubs || []) {
    if (!isReachable(hub) || hub.hub_id !== shellPick.hub_id) continue;
    const machine = machineOf(state, hub.hub_id, shellPick.device_id);
    if (machine) return { hub: hub, machine: machine };
  }
  return null;
}

function canOpenShell(picked) {
  return !!picked && picked.machine.is_online && picked.hub.connection === 'connected';
}

function newShellReason(picked) {
  if (!picked) return t('ui.reason.no_machine');
  if (picked.hub.connection === 'disabled') return t('ui.reason.disabled');
  return t('ui.reason.offline');
}

// The button that opens a new terminal on the picked machine.
function newShellButton(picked) {
  const open = document.createElement('button');
  open.type = 'button';
  open.textContent = t('ui.terminal_new');
  open.disabled = !canOpenShell(picked);
  open.onclick = () => openShell(picked.hub, picked.machine);
  return open;
}

// The tab strip, the active terminal, and the status line with the hint and
// the two switches. With no tab, a dashed frame offers a new terminal.
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
  // A double click on the strip's empty space opens a new terminal.
  head.ondblclick = (event) => {
    if (event.target !== head) return;
    const picked = pickedMachine(state);
    if (canOpenShell(picked)) openShell(picked.hub, picked.machine);
  };
  panel.appendChild(head);
  panel.appendChild(shellSurfaceElement());
  panel.appendChild(statusLine(activeTab()));
  return panel;
}

// The line under the terminal: where the keys go, or why the shell ended,
// then the two switches.
function statusLine(tab) {
  const status = document.createElement('div');
  status.className = 'term_status';
  const hint = document.createElement('span');
  hint.className = 'term_hint';
  hint.textContent = !tab ? ''
    : tab.state === 'closed' || tab.state === 'ended' ? (tab.note || t('ui.terminal_ended'))
    : tab.isDropped ? tab.note
    : tab.hint || '';
  if (hint.textContent) status.appendChild(hint);
  if (!tab) return status;
  const flags = tabFlags(tab);
  const isOpen = tab.state === 'open';
  const isEnabled = isOpen && flags.is_owned;
  const switches = document.createElement('div');
  switches.className = 'term_switches';
  if (!flags.is_owned) {
    switches.appendChild(reasonLine(t('ui.reason.not_owned', { owner: flags.owner_name || flags.owner })));
  }
  switches.appendChild(flagSwitch(t('ui.terminal_persistent'), !!flags.is_persistent,
    isEnabled, () => askPersist(tab, !flags.is_persistent, !!flags.is_shared)));
  switches.appendChild(flagSwitch(t('ui.terminal_shared'), !!flags.is_shared,
    isEnabled, () => askPersist(tab, !!flags.is_persistent, !flags.is_shared)));
  status.appendChild(switches);
  return status;
}

function flagSwitch(label, isOn, isEnabled, onFlip) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = isOn ? 'switch on' : 'switch';
  button.setAttribute('role', 'switch');
  button.setAttribute('aria-checked', String(isOn));
  button.disabled = !isEnabled;
  button.innerHTML = '<span class="switch_track"><span class="switch_thumb"></span></span>';
  button.appendChild(document.createTextNode(label));
  button.onclick = onFlip;
  return button;
}

// Both flags go in one persist; the resident shows them at once and the
// hub's next state confirms them.
function askPersist(tab, isPersistent, isShared) {
  api('/api/terminal/persist', {
    terminal_id: tab.terminal_id, is_persistent: isPersistent, is_shared: isShared,
  }).then((reply) => {
    if (!reply) return;
    tab.hint = reply.code ? wordCode(reply.code, reply.params) : '';
    if (!reply.code) tab.flags = { is_persistent: isPersistent, is_shared: isShared };
    redraw();
  });
}

// One tab: its dot, its label, its badges and its ×; a middle click closes
// it as × does.
function shellTabButton(tab) {
  const wrap = document.createElement('div');
  wrap.className = tab.key === activeShell ? 'term_tab on' : 'term_tab';
  const label = document.createElement('button');
  label.type = 'button';
  label.className = 'term_tab_label';
  label.innerHTML = marker(shellTone(tab));
  label.title = tab.name;
  label.appendChild(document.createTextNode(
    tab.state === 'ended' ? t('ui.terminal_ended') : tab.name));
  const flags = tabFlags(tab);
  if (flags.is_persistent) label.appendChild(badge(t('ui.badge.kept')));
  if (flags.is_shared) label.appendChild(badge(t('ui.badge.shared')));
  if ((flags.attached_count || 0) > 1) label.appendChild(badge(String(flags.attached_count)));
  label.onclick = () => selectTab(tab);
  wrap.onmousedown = (event) => { if (event.button === 1) event.preventDefault(); };
  wrap.onauxclick = (event) => {
    if (event.button !== 1) return;
    event.preventDefault();
    pressClose(tab);
  };
  wrap.appendChild(label);
  wrap.appendChild(closeButton(tab));
  return wrap;
}

function badge(text) {
  const mark = document.createElement('span');
  mark.className = 'badge';
  mark.textContent = text;
  return mark;
}

// Whether closing a tab ends a session others can see or that outlives it.
function isGuarded(tab) {
  const flags = tabFlags(tab);
  return ['idle', 'connecting', 'open'].indexOf(tab.state) >= 0
    && (flags.is_persistent || flags.is_shared);
}

// The ×: a plain session ends with its tab; a kept or shared one arms, and
// the second press ends the session.
function closeButton(tab) {
  const key = 'end:' + tab.key;
  const close = document.createElement('button');
  close.type = 'button';
  close.dataset.arm = key;
  close.className = isArmed(key) ? 'term_tab_close armed' : 'term_tab_close';
  close.textContent = isArmed(key) ? t('ui.terminal_end_armed') : '×';
  close.title = t('ui.terminal_close', { name: tab.name });
  close.setAttribute('aria-label', close.title);
  close.onclick = () => pressClose(tab);
  return close;
}

function pressClose(tab) {
  const key = 'end:' + tab.key;
  if (!isGuarded(tab)) { closeShell(tab); return; }
  if (!isArmed(key)) { arm(key); return; }
  disarm();
  api('/api/terminal/stop', { hub_id: tab.hub_id, session_id: tab.session_id })
    .then((reply) => {
      if (reply && reply.code) {
        tab.hint = wordCode(reply.code, reply.params);
        redraw();
        return;
      }
      closeShell(tab);
    });
}

// Selecting a tab shows it, and attaches a listed session on first sight.
function selectTab(tab) {
  activeShell = tab.key;
  shouldFocusShell = true;
  redraw();
  if (tab.state === 'idle') attachShell(tab);
}

// A shell's dot: amber pulsing while it opens or waits to attach, amber
// while its hub is away, green while open, red for a refusal, grey once it
// ended.
function shellTone(tab) {
  if (tab.isDropped) return 'wait';
  if (tab.state === 'connecting') return 'pulse';
  if (tab.state === 'idle') return 'off';
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

// A tab and its pane, its terminal made and wired, attached to nothing yet.
function newTab(hubId, machine, sessionId) {
  shellCounter += 1;
  const pane = document.createElement('div');
  pane.className = 'term_pane hidden';
  shellSurfaceElement().appendChild(pane);
  const term = new Terminal({
    fontFamily: TERMINAL_FONT,
    fontSize: terminalFontSize(),
    lineHeight: 1.2,
    cursorBlink: true,
    theme: terminalTheme(),
    scrollback: TERMINAL_SCROLLBACK_LINES,
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  const tab = {
    key: 'shell' + shellCounter, terminal_id: '', hub_id: hubId,
    device_id: machine.device_id, name: machine.name, term: term, fit: fit,
    pane: pane, state: 'connecting', note: '', isRefused: false, typed: '',
    isSending: false, hint: '', session_id: sessionId || '', isListed: false,
    isDropped: false, droppedAt: 0, flags: {}, isClearAsked: false, isClearing: false,
    clearMark: document.createElement('div'),
  };
  tab.clearMark.className = 'term_clearing hidden';
  tab.clearMark.textContent = t('ui.job.clearing');
  pane.appendChild(tab.clearMark);
  shellTabs.push(tab);
  term.open(pane);
  loadTerminalFont();
  wireShell(tab);
  return tab;
}

// The keys, the menu, the mouse and the size of one terminal.
function wireShell(tab) {
  const term = tab.term;
  term.onData((data) => sendShellKeys(tab, data));
  tab.pane.addEventListener('contextmenu', (event) => {
    event.preventDefault();
    openTerminalMenu(tab, event.clientX, event.clientY);
  });
  tab.pane.addEventListener('mouseup', (event) => {
    if (event.button !== 1 || !isLinux()) return;
    event.preventDefault();
    const selection = term.getSelection();
    if (selection && tab.state === 'open') term.paste(selection);
  });
  term.attachCustomKeyEventHandler((event) => {
    if (event.type !== 'keydown') return true;
    const chord = terminalChord(event);
    if (!chord) return true;
    event.preventDefault();
    runTerminalChord(tab, chord);
    return false;
  });
  term.onResize((size) => {
    if (tab.state !== 'open') return;
    api('/api/terminal/resize',
      { terminal_id: tab.terminal_id, cols: size.cols, rows: size.rows });
  });
}

// What a key press asks of the terminal itself: copy, paste, page, or the
// font size; empty for a key the shell takes.
function terminalChord(event) {
  const key = (event.key || '').toLowerCase();
  if (event.altKey) return '';
  const isCommand = isMac() && event.metaKey && !event.ctrlKey;
  if ((event.ctrlKey && event.shiftKey && key === 'c') || (isCommand && key === 'c')) {
    return 'copy';
  }
  if ((event.ctrlKey && event.shiftKey && key === 'v') || (isCommand && key === 'v')) {
    return 'paste';
  }
  if (event.shiftKey && !event.ctrlKey && key === 'pageup') return 'page_up';
  if (event.shiftKey && !event.ctrlKey && key === 'pagedown') return 'page_down';
  if (event.ctrlKey && !event.shiftKey && (key === '=' || key === '+')) return 'larger';
  if (event.ctrlKey && event.shiftKey && key === '+') return 'larger';
  if (event.ctrlKey && key === '-') return 'smaller';
  return '';
}

function runTerminalChord(tab, chord) {
  if (chord === 'copy') copySelection(tab);
  else if (chord === 'paste') pasteClipboard(tab);
  else if (chord === 'page_up') tab.term.scrollPages(-1);
  else if (chord === 'page_down') tab.term.scrollPages(1);
  else if (chord === 'larger') send('/api/terminal/font', { size: terminalFontSize() + 1 });
  else if (chord === 'smaller') send('/api/terminal/font', { size: terminalFontSize() - 1 });
}

// The selection goes to the system clipboard through the resident.
function copySelection(tab) {
  const text = tab.term.getSelection();
  if (!text) return;
  api('/api/clipboard', { text: text }).then((reply) => {
    const note = reply && reply.code ? wordCode(reply.code, reply.params) : '';
    if (note !== tab.hint) { tab.hint = note; redraw(); }
  });
}

// Pastes the clipboard as the resident reads it; a refusal shows in the line
// under the terminal until the next paste.
function pasteClipboard(tab) {
  if (tab.state !== 'open') return;
  api('/api/clipboard').then((reply) => {
    if (!reply) return;
    const note = reply.code ? wordCode(reply.code, reply.params) : '';
    if (note !== tab.hint) { tab.hint = note; redraw(); }
    if (!reply.code && reply.text) tab.term.paste(reply.text);
    tab.term.focus();
  });
}

// The menu a right click opens at the pointer: Copy with a selection,
// Paste, Select all, Clear. Escape or a press elsewhere closes it.
function openTerminalMenu(tab, x, y) {
  closeTerminalMenu();
  const menu = document.createElement('div');
  menu.className = 'menu';
  const items = [
    [t('ui.menu.copy'), !tab.term.hasSelection(), () => copySelection(tab)],
    [t('ui.menu.paste'), tab.state !== 'open', () => pasteClipboard(tab)],
    [t('ui.menu.select_all'), false, () => tab.term.selectAll()],
    [t('ui.menu.clear'), false, () => clearTerminal(tab)],
  ];
  for (const [label, isDisabled, onPick] of items) {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'menu_row';
    item.textContent = label;
    item.disabled = isDisabled;
    item.onmousedown = (event) => event.stopPropagation();
    item.onclick = () => { closeTerminalMenu(); onPick(); tab.term.focus(); };
    menu.appendChild(item);
  }
  document.body.appendChild(menu);
  const width = menu.offsetWidth;
  const height = menu.offsetHeight;
  menu.style.left = Math.min(x, window.innerWidth - width - 4) + 'px';
  menu.style.top = Math.min(y, window.innerHeight - height - 4) + 'px';
  openMenu = menu;
}

// Clear: the screen is cleared at once, and the resident sends Ctrl+C after
// what was typed before it and drops the output until the stream is quiet,
// telling the page when the dropping starts and ends.
function clearTerminal(tab) {
  if (tab.state !== 'open') return;
  showClearing(tab, true);
  tab.isClearAsked = true;
  if (!tab.isSending) flushShellKeys(tab);
}

// Erases the screen and the scrollback and puts the cursor home, the
// terminal's modes kept.
const TERMINAL_ERASE = '\x1b[2J\x1b[3J\x1b[H';

// The Clearing word over a terminal's box: shown while the output is
// dropped. Output that reaches the page meanwhile was read before the drop
// began and is not drawn; the box is erased when the drop begins, after
// what the terminal still had to draw, and again when it ends.
function showClearing(tab, isClearing) {
  tab.isClearing = isClearing;
  tab.clearMark.textContent = t('ui.job.clearing');
  tab.clearMark.className = isClearing ? 'term_clearing' : 'term_clearing hidden';
  tab.term.write(TERMINAL_ERASE);
}

function closeTerminalMenu() {
  if (!openMenu) return;
  openMenu.remove();
  openMenu = null;
  settle();
}
document.addEventListener('mousedown', closeTerminalMenu);
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeTerminalMenu();
});

// A new terminal on one machine: its tab at once, the shell once the
// resident has opened it at the pane's size.
function openShell(hub, machine) {
  const tab = newTab(hub.hub_id, machine, '');
  activeShell = tab.key;
  shouldFocusShell = true;
  redraw();
  startShell(tab);
}

// A listed session's tab attaches when first shown, its kept output first.
// A tab whose hub is away waits for the hub to list its session again.
function attachShell(tab) {
  if (tab.state !== 'idle' || tab.isDropped) return;
  tab.state = 'connecting';
  redraw();
  startShell(tab);
}

// A tab whose hub came back attaches again by itself; the terminal starts
// empty, since the attach replays the session's kept output.
function reattachShell(tab) {
  tab.note = '';
  tab.isRefused = false;
  tab.term.reset();
  window.setTimeout(() => attachShell(tab), 0);
}

function startShell(tab) {
  fitShell(tab);
  api('/api/terminal/open', {
    hub_id: tab.hub_id, device_id: tab.device_id,
    cols: tab.term.cols, rows: tab.term.rows, session_id: tab.session_id,
  }).then((reply) => {
    if (reply && reply.code === 'hub_unreachable' && tab.session_id) {
      loseShell(tab, wordCode(reply.code, reply.params));
      return;
    }
    if (!reply || reply.code || !reply.terminal_id) {
      endShell(tab, reply && reply.code ? wordCode(reply.code, reply.params) : '', true);
      return;
    }
    tab.terminal_id = reply.terminal_id;
    tab.session_id = reply.session_id || tab.session_id;
    tab.state = 'open';
    const early = earlyOutput[reply.terminal_id] || [];
    delete earlyOutput[reply.terminal_id];
    for (const piece of early) takeShellPiece(piece);
    redraw();
  });
}

// Loads both faces once, through the resident in pieces, then has every shell
// measure its cells again in the loaded face.
function loadTerminalFont() {
  if (terminalFontLoad) return terminalFontLoad;
  terminalFontLoad = Promise.all(TERMINAL_FONT_FACES.map((entry) =>
    fontBytes(entry[0]).then((bytes) => {
      const face = new FontFace(TERMINAL_FONT_FAMILY, bytes, { weight: entry[1] });
      document.fonts.add(face);
      return face.load();
    }))).then(() => {
    for (const tab of shellTabs) {
      tab.term.options.fontFamily = 'monospace';
      tab.term.options.fontFamily = TERMINAL_FONT;
      fitShell(tab);
    }
  }).catch(() => {});
  return terminalFontLoad;
}

// One face's file, asked for piece by piece until its size is reached.
async function fontBytes(name) {
  const pieces = [];
  let offset = 0;
  let size = 1;
  while (offset < size) {
    const reply = await api('/api/font?name=' + name + '&offset=' + offset);
    if (!reply || reply.code) throw new Error('font ' + name);
    const piece = base64Bytes(reply.data);
    if (piece.length === 0) break;
    pieces.push(piece);
    offset += piece.length;
    size = reply.size;
  }
  const bytes = new Uint8Array(offset);
  let at = 0;
  for (const piece of pieces) { bytes.set(piece, at); at += piece.length; }
  return bytes.buffer;
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
    if (!tab.isClearing) tab.term.write(base64Bytes(piece.data));
    return;
  }
  if (piece.clearing !== undefined) {
    if (piece.clearing === true || tab.isClearing) {
      showClearing(tab, piece.clearing === true);
    }
    return;
  }
  if (tab.isClearing) showClearing(tab, false);
  const end = piece.end || {};
  if (!end.code && !tab.isListed && !isGuarded(tab)) { dropShell(tab); return; }
  if (end.code === 'hub_unreachable' && tab.session_id) {
    loseShell(tab, wordCode(end.code, end.params));
    return;
  }
  if (end.code === 'session_unknown') {
    endTab(tab, t('ui.terminal_ended'));
    redraw();
    return;
  }
  endShell(tab, end.code ? wordCode(end.code, end.params) : t('ui.terminal_ended'),
    !!end.code);
}

// A shell that ended or was refused keeps its tab and its output, saying why.
function endShell(tab, note, isRefused) {
  tab.state = 'closed';
  tab.note = note;
  tab.isRefused = isRefused;
  if (note) tab.term.write('\r\n' + note + '\r\n');
  redraw();
}

// A shell whose hub's channel dropped: its tab keeps its session id and its
// output, and waits for a later state in which the hub is back.
function loseShell(tab, note) {
  tab.state = 'idle';
  tab.isDropped = true;
  tab.droppedAt = stateSerial;
  tab.terminal_id = '';
  tab.note = note;
  tab.isRefused = false;
  tab.term.write('\r\n' + note + '\r\n');
  redraw();
}

// A session the hub stopped listing: its tab stays with its last output.
function endTab(tab, note) {
  tab.state = 'ended';
  tab.note = note;
  tab.isRefused = false;
}

// Keys go in the order typed: one request at a time, whatever was typed
// meanwhile riding the next.
function sendShellKeys(tab, data) {
  if (tab.state !== 'open') return;
  tab.typed += data;
  if (!tab.isSending) flushShellKeys(tab);
}

function flushShellKeys(tab) {
  if (tab.state !== 'open') { tab.isSending = false; return; }
  if (!tab.typed && tab.isClearAsked) {
    tab.isClearAsked = false;
    tab.isSending = true;
    api('/api/terminal/clear', { terminal_id: tab.terminal_id })
      .then((reply) => {
        if (!reply || reply.code) showClearing(tab, false);
        flushShellKeys(tab);
      });
    return;
  }
  if (!tab.typed) { tab.isSending = false; return; }
  const text = tab.typed;
  tab.typed = '';
  tab.isSending = true;
  api('/api/terminal/input', { terminal_id: tab.terminal_id, data: textBase64(text) })
    .then(() => flushShellKeys(tab));
}

// Closing a tab ends its window's stream, and with it a plain session.
function closeShell(tab) {
  if (tab.state === 'open') api('/api/terminal/close', { terminal_id: tab.terminal_id });
  if (tab.session_id) closedSessions.add(tab.hub_id + '/' + tab.session_id);
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

// --- the Files panel: Configure, then Mount / Unmount ---

function mountDefaultPath(payload, state) {
  // A drive letter where that is the shape, the platform's own free one.
  if ((state.mount_location_shape || 'path') === 'drive_letter') {
    return state.mount_location_suggestion || 'N:';
  }
  // A volume's mount point is the system's to pick.
  if (!asksMountPlace(state)) return '';
  return (state.home || '') + '/nas/' + (payload.share || '');
}

// Whether the form asks where to mount: not for a volume the system places.
function asksMountPlace(state) {
  return (state.mount_location_shape || 'path') !== 'volume';
}

// Whether a staged form holds everything a mount needs.
function isMountFormFilled(staged, state) {
  return !!staged.username && (!!staged.path || !asksMountPlace(state));
}

// A form staged for an entry no hub carries any more is gone.
function dropStaleFileStages(state) {
  const present = new Set((state.services || []).map(serviceKey));
  for (const key of Object.keys(fileStaged)) {
    if (!present.has(key)) delete fileStaged[key];
  }
}

// The codes a record can only leave with a new login: mounting it again as
// it stands would be refused again, so Mount opens the form instead.
const LOGIN_CODES = ['share_login_rejected', 'credentials_missing'];
// The server a forwarded share is mounted from, as the Finder lists it.
const LOOPBACK_SERVER = '127.0.0.1';

// The panel is marked dirty while any entry's form is open. A stage stays
// through a failed mount and goes once the share is mounted.
function drawFileEntry(card, state, hub, entry) {
  const key = serviceKey(entry);
  const payload = entry.payload || {};
  const records = (state.mounts || []).filter(
    (record) => record.hub_id === entry.hub_id && record.entry_id === entry.id);
  const record = records[0];
  if (record && record.is_attached && !entry.job && fileStaged[key]
    && fileStaged[key].is_sent && !fileStaged[key].is_open) {
    delete fileStaged[key];
  }
  const staged = fileStaged[key];
  if (staged && staged.is_open) card.classList.add('dirty');
  const config = document.createElement('button');
  config.type = 'button';
  config.className = 'ghost';
  config.textContent = t('ui.configure');
  config.disabled = !isEntryFree(hub, entry);
  config.onclick = () => {
    if (staged && staged.is_open) {
      cancelFileForm(key);
    } else {
      openFileForm(key, state, payload, record);
    }
    redraw();
  };
  const mount = mountButton(state, hub, entry, record, staged);
  const extras = [];
  for (const each of records) {
    extras.push(drawMountRecord(each));
    // A volume is listed in the Finder under the server it came from.
    if (!asksMountPlace(state) && each.is_attached && each.path) {
      extras.push(noteLine(t('ui.mount_finder', { server: each.server || each.host || '' })));
    }
  }
  let row = null;
  if (staged && staged.is_open) {
    const isLoginRefused = !!record && LOGIN_CODES.indexOf(record.code) >= 0;
    // After a refused login, Save mounts with the new login at once.
    const onSave = isLoginRefused && !entry.job
      ? () => sendFileMount(entry, staged) : null;
    extras.push(drawFileForm(staged, state, LOOPBACK_SERVER, key, onSave, () => {
      if (!entry.job) {
        mount.disabled = !isEntryFree(hub, entry) || isUnhealthy(entry)
          || !isMountFormFilled(staged, state);
      }
      if (row) setReasonLine(row, mountReason(state, hub, entry, record, mount));
    }));
  }
  row = entryRow(hub, entry,
    '//' + (payload.host || '') + '/' + (payload.share || ''),
    '', [config, mount], mountReason(state, hub, entry, record, mount), extras);
  card.appendChild(row);
}

// Why Mount cannot run, empty while it can. Each system's sentence names
// what its own form asks for: a path, a drive letter, or a user name alone.
function mountReason(state, hub, entry, record, mount) {
  if (!mount.disabled || entryWork(hub, entry)) return '';
  return entryReason(hub, entry, !(record && record.is_attached))
    || t(MOUNT_FORM_REASONS[state.mount_location_shape || 'path']
      || 'ui.reason.mount_form');
}

// The empty form's reason, by the system's mount location shape.
const MOUNT_FORM_REASONS = {
  path: 'ui.reason.mount_form',
  drive_letter: 'ui.reason.mount_form_drive',
  volume: 'ui.reason.mount_form_volume',
};

// A row's faint reason line set to a text, or removed with none.
function setReasonLine(row, text) {
  const body = row.querySelector('.body');
  const line = body.querySelector('.reason');
  if (!text) {
    if (line) line.remove();
  } else if (line) {
    line.textContent = text;
  } else {
    body.appendChild(reasonLine(text));
  }
}

// Open an entry's form on its saved stage, else on the record's login,
// else on the defaults; what it held before is what Cancel puts back.
function openFileForm(key, state, payload, record) {
  const staged = fileStaged[key];
  if (staged) {
    staged.before = Object.assign({}, staged);
    staged.is_open = true;
    return;
  }
  fileStaged[key] = {
    is_open: true, username: record ? (record.username || '') : '',
    password: '',
    path: record && asksMountPlace(state) ? record.path
      : mountDefaultPath(payload, state),
    before: null,
  };
}

// Close an entry's form on what its stage held before the form opened.
function cancelFileForm(key) {
  const staged = fileStaged[key];
  if (staged && staged.before) {
    fileStaged[key] = Object.assign({}, staged.before, { is_open: false });
  } else {
    delete fileStaged[key];
  }
}

// The one button beside Configure: Mount, its job while it mounts, Unmount
// once mounted, its job while it unmounts. A stage wins: what it holds is
// sent as a fresh mount, and it is kept until the share is mounted; after a
// refused login the press opens the form on it instead.
function mountButton(state, hub, entry, record, staged) {
  if (entry.job) {
    return jobButton('', entry.job, entry.job === 'unmounting' ? 'danger' : '');
  }
  const button = document.createElement('button');
  button.type = 'button';
  const isFree = isEntryFree(hub, entry);
  const isLoginRefused = !!record && LOGIN_CODES.indexOf(record.code) >= 0;
  if (staged && !staged.is_open && isLoginRefused) {
    button.textContent = t('ui.mount');
    button.disabled = !isFree;
    button.onclick = () => {
      staged.before = Object.assign({}, staged);
      staged.is_open = true;
      redraw();
    };
    return button;
  }
  if (staged) {
    button.textContent = t('ui.mount');
    button.disabled = !isFree || isUnhealthy(entry) || !isMountFormFilled(staged, state);
    button.onclick = () => sendFileMount(entry, staged);
    return button;
  }
  if (record === undefined) {
    button.textContent = t('ui.mount');
    button.disabled = true;
    return button;
  }
  if (isLoginRefused) {
    // Nothing to retry with: the press opens the form, the login prefilled.
    button.textContent = t('ui.mount');
    button.disabled = !isFree;
    button.onclick = () => {
      fileStaged[serviceKey(entry)] = {
        is_open: true, username: record.username || '', password: '',
        path: asksMountPlace(state) ? record.path : '', before: null,
      };
      redraw();
    };
    return button;
  }
  if (!record.is_attached) {
    button.textContent = t('ui.mount');
    button.disabled = !isFree || isUnhealthy(entry);
    button.onclick = () => serviceAction('file',
      { action: 'mount', hub_id: entry.hub_id, record_id: record.record_id });
    return button;
  }
  button.className = 'danger';
  button.textContent = t('ui.unmount');
  button.disabled = !isFree;
  button.onclick = () => serviceAction('file',
    { action: 'unmount', hub_id: entry.hub_id, record_id: record.record_id });
  return button;
}

// A stage sent as a fresh mount: the form closes, and the stage is kept
// until the share is mounted.
function sendFileMount(entry, staged) {
  staged.is_open = false;
  staged.is_sent = true;
  staged.before = null;
  serviceAction('file', {
    action: 'mount', hub_id: entry.hub_id, id: entry.id,
    username: staged.username, password: staged.password, path: staged.path,
  });
}

// A record's own line carries only where it stands: the words, never a
// button.
function drawMountRecord(record) {
  const line = document.createElement('div');
  line.className = 'rec';
  const isBusy = MOUNT_BUSY_STATES.indexOf(record.state) >= 0;
  const status = isBusy ? t('ui.job.mounting')
    : record.code ? wordCode(record.code, record.params)
    : record.is_attached ? '' : t('ui.not_attached');
  const tone = isBusy ? 'pulse' : record.is_attached ? 'ok' : record.code ? 'bad' : 'off';
  line.innerHTML = marker(tone);
  const path = document.createElement('span');
  path.className = 'path';
  // A volume has no path until the system has mounted it.
  path.textContent = record.path
    ? record.path + (status ? ' — ' + status : '') : status;
  line.appendChild(path);
  return line;
}

// The form's fields write the stage as typed, and onChange keeps the Mount
// button and the reason line in step with them. Save keeps the stage for the
// next Mount; Cancel puts back what the stage held before the form opened.
function drawFileForm(staged, state, server, key, onSave, onChange) {
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
    input.oninput = () => { staged[name] = input.value; changed(); };
    // Leaving the field lets a state that arrived while typing draw.
    input.onblur = settle;
    line.appendChild(input);
    form.appendChild(line);
  }
  if ((state.mount_location_shape || 'path') === 'drive_letter') {
    form.appendChild(driveLetterLine(staged, state));
  } else if (!asksMountPlace(state)) {
    form.appendChild(volumeCaptionLine(server));
  } else {
    form.appendChild(mountPathLine(staged, changed));
  }
  const actions = document.createElement('div');
  actions.className = 'form_actions';
  const save = document.createElement('button');
  save.type = 'button';
  save.textContent = t('ui.save');
  save.onclick = () => {
    if (onSave && isMountFormFilled(staged, state)) { onSave(); return; }
    staged.is_open = false;
    staged.before = null;
    redraw();
  };
  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'ghost';
  cancel.textContent = t('ui.cancel');
  cancel.onclick = () => { cancelFileForm(key); redraw(); };
  actions.appendChild(save);
  actions.appendChild(cancel);
  form.appendChild(actions);
  function changed() {
    save.disabled = !isMountFormFilled(staged, state);
    onChange();
  }
  save.disabled = !isMountFormFilled(staged, state);
  return form;
}

// A directory under the home, with a Browse button that lists it as this
// person.
function mountPathLine(staged, onChange) {
  const pathLine = document.createElement('div');
  pathLine.className = 'row';
  const path = document.createElement('input');
  path.placeholder = t('ui.path_hint');
  path.value = staged.path;
  path.oninput = () => { staged.path = path.value; onChange(); };
  path.onblur = settle;
  const browse = document.createElement('button');
  browse.type = 'button';
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
    (value) => { staged.path = value; redraw(); }, false);
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

// The caption naming where the system lists a volume: in the Finder,
// under its server.
function volumeCaptionLine(server) {
  const caption = document.createElement('div');
  caption.className = 'feat';
  const note = document.createElement('div');
  note.className = 'note';
  note.textContent = t('ui.mount_volume_caption', { server: server });
  caption.appendChild(note);
  return caption;
}

// --- the Settings page: About, then the window's own choices ---

// What the settings page holds before Save: {language, theme}, or null while
// it holds what the window already uses.
let settingsDraft = null;

// The About card, then the settings card: the language and the palette,
// nothing sent until Save, the frame lit while the page holds a change.
function drawSettings(state) {
  const page = document.createElement('div');
  page.className = 'settings_page';
  page.appendChild(aboutSection(state));
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
  actions.className = 'form_actions';
  const save = document.createElement('button');
  save.type = 'button';
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
  cancel.type = 'button';
  cancel.className = 'ghost';
  cancel.textContent = t('ui.cancel');
  cancel.disabled = !isDirty;
  cancel.onclick = () => { settingsDraft = null; redraw(); };
  actions.appendChild(save);
  actions.appendChild(cancel);
  card.appendChild(actions);
  page.appendChild(card);
  return page;
}

// About, as the panel's About card: a header with the title, then two
// groups under their section labels, this machine and what the package
// carries; one row per fact, the label at the left and the value in mono at
// the right, a carried program's row ending in its Source link.
function aboutSection(state) {
  const card = document.createElement('div');
  card.className = 'card';
  const header = document.createElement('div');
  header.className = 'card_header';
  const title = document.createElement('h2');
  title.textContent = t('ui.about');
  header.appendChild(title);
  card.appendChild(header);
  const about = document.createElement('div');
  about.className = 'about';
  const platform = state.platform || {};
  const versions = state.carried_versions || {};
  aboutGroup(about, t('ui.about_this_machine'), [
    [t('ui.about_machine'), state.hostname, []],
    [t('ui.about_platform'), platform.os + '/' + platform.arch, []],
  ]);
  const source = t('ui.about_source_link');
  aboutGroup(about, t('ui.about_carried'), [
    ['Neutrino client ' + state.version, CLIENT_LICENCE,
      [[source, CLIENT_SOURCES[state.edition] || CLIENT_SOURCES.intl]]],
  ].concat(CARRIED.filter((core) => !core.os || core.os === platform.os)
    .map((core) => {
    const version = versions[core.key];
    return [version ? core.name + ' ' + version : core.name, core.licence,
      [[source, carriedSource(core, version, state.edition)]]];
  })));
  card.appendChild(about);
  return card;
}

// One group of About: its section label, then a row per [label, value,
// links], each link a short word after the value that opens the browser,
// as the panel's credits rows draw them.
function aboutGroup(about, title, rows) {
  const heading = document.createElement('div');
  heading.className = 'section_label';
  heading.textContent = title;
  about.appendChild(heading);
  for (const [name, value, links] of rows) {
    const row = document.createElement('div');
    row.className = 'about_row';
    const label = document.createElement('span');
    label.className = 'about_key';
    label.textContent = name;
    const text = document.createElement('span');
    text.className = 'about_value';
    text.textContent = (value || '') + (links.length ? ' — ' : '');
    links.forEach(([word, url], index) => {
      if (index) text.appendChild(document.createTextNode(' · '));
      text.appendChild(aboutLink(word, url));
    });
    row.appendChild(label);
    row.appendChild(text);
    about.appendChild(row);
  }
}

// One short link word of About, opened in the browser by the resident.
function aboutLink(word, url) {
  const link = document.createElement('a');
  link.className = 'about_link';
  link.href = url;
  link.textContent = word;
  link.onclick = (event) => {
    event.preventDefault();
    api('/api/open_link', { url: url });
  };
  return link;
}

// A carried program's source: at the tag of the version the package
// carries, its repository when no version is stamped.
function carriedSource(core, version, edition) {
  const repository = (edition === 'cn' && core.mainland) || core.repository;
  if (!version) return repository;
  return repository + '/tree/' + fill(core.tag, { version: version });
}

// --- the one picker, and the dialogs ---

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
  actions.className = 'form_actions';
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
  actions.className = 'form_actions';
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
