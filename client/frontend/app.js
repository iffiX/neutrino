// Every word this surface says comes from the two catalogs the loader
// inlines above; the wire carries only codes.
const CATALOGS = JSON.parse(document.getElementById('words').textContent);
const LANGUAGES = ['en', 'zh-CN'];
const DEFAULT_LANGUAGE = 'en';
// What the page words itself in, until a pushed state names another.
let language = DEFAULT_LANGUAGE;

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
  if (e.code === 'self_unbound') {
    const cause = hasWord('cause.' + p.cause) ? p.cause : 'hub_refused';
    return t('code.self_unbound', { cause: t('cause.' + cause) });
  }
  return wordCode(e.code, p);
}

let lastState = null;
let lastSerialized = '';
let pendingState = null;
let serviceNotes = {};
// The staged AI apply: the toggle and what each tool points with.
// Committed only by Apply; null rebuilds from the next server state.
let aiStaged = null;
// Records whose unmount is in flight, so the button greys at once.
const fileAsked = {};
// The staged file configs, one per entry id: {is_open, username, password,
// path}. The password lives only here and in the one request that sends it.
let fileStaged = {};
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

function present(state) {
  const serialized = JSON.stringify(state);
  if (serialized === lastSerialized) return;
  if (!canRedraw()) { pendingState = state; return; }
  lastSerialized = serialized;
  pendingState = null;
  draw(state);
}

// A redraw the person caused: it always happens, whatever is open.
function redraw() {
  if (lastState !== null) draw(lastState);
}

// The resident pushes every change of state here; nothing polls for it.
window.neutrinoState = (state) => {
  if (!state) return;
  if (state.code) { renderHint(wordCode(state.code, state.params)); return; }
  present(state);
};

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

// --- the two sections ---

function draw(state) {
  lastState = state;
  setLanguage(state.language);
  document.title = t('ui.window.title');
  document.querySelector('h1').textContent = t('ui.window.title');
  const settings = document.getElementById('settings');
  settings.textContent = t('ui.settings');
  settings.onclick = openSettingsDialog;
  document.getElementById('ident').textContent =
    state.hostname + ' · ' + state.platform.os + '/' + state.platform.arch +
    ' · client ' + state.version;

  const content = document.getElementById('content');
  content.innerHTML = '';
  content.style.display = 'flex';
  content.style.flexDirection = 'column';
  content.style.gap = '24px';
  content.appendChild(section(t('ui.section_status'), [drawConnection(state)]));
  content.appendChild(section(t('ui.section_services'), drawServices(state)));
}

function section(title, panels) {
  const box = document.createElement('div');
  box.className = 'sect';
  const heading = document.createElement('h2');
  heading.className = 'sect_title';
  heading.textContent = title;
  box.appendChild(heading);
  for (const panel of panels) box.appendChild(panel);
  return box;
}

function drawConnection(state) {
  const conn = document.createElement('div');
  conn.className = 'card';
  const lastError = wordError(state.last_error);
  if (state.is_connected) {
    const row = document.createElement('div');
    row.className = 'row';
    const tone = state.is_disabled ? 'off' : 'ok';
    const word = state.is_disabled ? t('ui.disabled') : t('ui.connected');
    const version = state.hub_version
      ? ' · ' + t('ui.hub_version', { version: state.hub_version }) : '';
    row.innerHTML = '<span class="dot ' + tone + '"></span><div style="flex:1"><div>' +
      word + '</div><div class="sub">' + state.gateway_url + version +
      '</div></div>';
    const leave = document.createElement('button');
    leave.className = 'danger';
    leave.textContent = t('ui.disconnect');
    leave.onclick = () => send('/api/disconnect');
    row.appendChild(leave);
    conn.appendChild(row);
    if (lastError) conn.appendChild(errorLine(lastError));
  } else {
    conn.innerHTML = '<div class="row" style="margin-bottom:12px">' +
      '<span class="dot off"></span><div><div>' + t('ui.not_connected') +
      '</div><div class="sub">' + t('ui.paste_hint') + '</div></div></div>';
    const row = document.createElement('div');
    row.className = 'row';
    const input = document.createElement('input');
    input.placeholder = 'neutrino://enroll/...';
    input.onkeydown = (e) => { if (e.key === 'Enter') join(); };
    const button = document.createElement('button');
    button.textContent = t('ui.connect');
    button.onclick = join;
    function join() { send('/api/connect', { link: input.value }); }
    row.appendChild(input);
    row.appendChild(button);
    conn.appendChild(row);
    const refusal = state.error ? wordCode(state.error.code, state.error.params) : '';
    if (refusal || lastError) conn.appendChild(errorLine(refusal || lastError));
  }
  return conn;
}

// The settings dialog: what this window keeps for itself, today the
// language. Nothing is sent until Save.
function openSettingsDialog() {
  const draft = { language: language };
  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  const modal = document.createElement('div');
  modal.className = 'card modal';
  const heading = document.createElement('div');
  heading.className = 'panel_title';
  heading.textContent = t('ui.settings_title');
  modal.appendChild(heading);
  const label = document.createElement('label');
  label.textContent = t('ui.language');
  modal.appendChild(label);
  const options = LANGUAGES.map(
    (code) => ({ value: code, label: t('ui.language_name.' + code) }));
  modal.appendChild(picker('language', options, draft.language,
    (value) => { draft.language = value; }, false));
  const actions = document.createElement('div');
  actions.className = 'row';
  actions.style.marginTop = '8px';
  const save = document.createElement('button');
  save.textContent = t('ui.save');
  save.onclick = () => {
    closeDialog(overlay);
    if (draft.language !== language) {
      send('/api/language', { language: draft.language });
    }
    redraw();
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

function errorLine(text) {
  const err = document.createElement('div');
  err.className = 'err';
  err.style.marginTop = '10px';
  err.textContent = text;
  return err;
}

function entriesOf(state, type) {
  return (state.services || []).filter((entry) => entry.type === type);
}

function drawServices(state) {
  const panels = [];
  if (!state.is_connected) {
    const wait = document.createElement('div');
    wait.className = 'card';
    wait.innerHTML = '<span class="muted">' + t('ui.services_wait_join') +
      '</span>';
    return [wait];
  }
  // Every kind draws, in this order, whether or not it carries entries.
  const kinds = [
    ['web', t('ui.panel_web'), drawWebPanel, t('ui.empty_web')],
    ['port', t('ui.panel_ports'), drawPortsPanel, t('ui.empty_ports')],
    ['ai', t('ui.panel_ai'), drawAiPanel, t('ui.empty_ai')],
    ['file', t('ui.panel_files'), drawFilesPanel, t('ui.empty_files')],
    ['rdp', t('ui.panel_desktops'), drawDesktopsPanel, t('ui.empty_desktops')],
  ];
  for (const [type, title, build, empty] of kinds) {
    const entries = entriesOf(state, type);
    panels.push(entries.length === 0
      ? emptyPanel(title, empty)
      : build(state, entries, title));
  }
  return panels;
}

function emptyPanel(title, line) {
  const card = panelCard(title, false);
  const row = document.createElement('div');
  row.className = 'feat';
  row.innerHTML = '<div class="body"><div class="note muted">' + line +
    '</div></div>';
  card.appendChild(row);
  return card;
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

function entryRow(entry, payloadText, extraNote) {
  const row = document.createElement('div');
  row.className = entry.is_healthy ? 'feat' : 'feat greyed';
  const note = (entry.is_healthy ? '' : t('ui.unhealthy')) +
    (extraNote ? (entry.is_healthy ? '' : ' — ') + extraNote : '');
  row.innerHTML = '<span class="dot ' + (entry.is_healthy ? 'ok' : 'off') +
    '"></span>' +
    '<div class="body"><div class="title">' + entry.title + '</div>' +
    '<div class="note">' + payloadText + (note ? ' — ' + note : '') + '</div>' +
    (describeEntry(entry)
      ? '<div class="note muted">' + describeEntry(entry) + '</div>' : '') +
    '</div>';
  return row;
}

// Where an entry comes from, in this page's own words; an older hub sends
// only the English sentence, which stands as it is.
function describeEntry(entry) {
  const code = entry.description_code;
  if (code && hasWord('ui.description.' + code)) {
    return t('ui.description.' + code, entry.description_params || {});
  }
  return entry.description || '';
}

// Every button greys while the hub has this client switched off.
function isHeld(state) {
  return !!state.is_disabled;
}

function drawWebPanel(state, entries, title) {
  const card = panelCard(title, false);
  for (const entry of entries) {
    const payload = entry.payload || {};
    const noteKey = 'web_' + entry.id;
    const row = entryRow(entry, payload.url || '', serviceNotes[noteKey] || '');
    const open = document.createElement('button');
    open.textContent = t('ui.open');
    open.disabled = !entry.is_healthy || isHeld(state);
    open.onclick = () => serviceAction('web', { id: entry.id }, noteKey);
    row.appendChild(open);
    card.appendChild(row);
  }
  return card;
}

function drawPortsPanel(state, entries, title) {
  const card = panelCard(title, false);
  for (const entry of entries) {
    const payload = entry.payload || {};
    const forward = (state.forwards || {})[entry.id] || {};
    const isOn = !!forward.is_active;
    const noteKey = 'port_' + entry.id;
    const local = isOn
      ? ' → ' + t('ui.forwarding_to', { port: forward.local_port }) : '';
    const note = serviceNotes[noteKey] || '';
    const row = entryRow(
      entry, (payload.host || '') + ':' + (payload.port || '') + local, note);
    const button = document.createElement('button');
    button.className = isOn ? 'danger' : '';
    button.textContent = isOn ? t('ui.port_disconnect') : t('ui.port_connect');
    button.disabled = (!entry.is_healthy && !isOn) || isHeld(state);
    button.onclick = () => serviceAction('port',
      { id: entry.id, is_enabled: !isOn }, noteKey);
    row.appendChild(button);
    card.appendChild(row);
  }
  return card;
}

// --- the remote desktops panel: connect there ---

function drawDesktopsPanel(state, entries, title) {
  const card = panelCard(title, false);
  const work = state.rdp_work || {};
  const isWorking = work.state === 'working';
  for (const entry of entries) {
    const payload = entry.payload || {};
    const noteKey = 'rdp_' + entry.id;
    const viewer = (state.viewers || {})[entry.id] || {};
    const open = viewer.is_running ? ' — ' + t('ui.rdp_open') : '';
    const isThisOne = work.step === 'connecting:' + entry.id;
    const row = entryRow(
      entry, (payload.host || '') + ':' + (payload.port || '') + open,
      serviceNotes[noteKey] || '');
    const connect = document.createElement('button');
    if (isWorking && isThisOne) {
      connect.innerHTML = '<span class="spin"></span>' + t('ui.rdp_connecting');
    } else {
      connect.textContent = t('ui.rdp_connect');
    }
    connect.disabled = isWorking || !entry.is_healthy || isHeld(state);
    connect.onclick = () => serviceAction('rdp',
      { action: 'connect', id: entry.id }, noteKey);
    row.appendChild(connect);
    card.appendChild(row);
  }
  if (work.code) card.appendChild(errorLine(wordCode(work.code, work.params)));
  return card;
}

// --- the AI panel: one toggle + Config + Apply, staged ---

function ensureAiStaged(state) {
  if (aiStaged !== null) return;
  aiStaged = {
    is_enabled: !!(state.ai || {}).is_enabled,
    tool_configs: JSON.parse(JSON.stringify(state.ai_tool_configs || {})),
  };
}

function isAiDirty(state) {
  if (aiStaged.is_enabled !== !!(state.ai || {}).is_enabled) return true;
  return JSON.stringify(aiStaged.tool_configs) !==
    JSON.stringify(state.ai_tool_configs || {});
}

function drawAiPanel(state, entries, title) {
  ensureAiStaged(state);
  const entry = entries[0];
  const isDirty = isAiDirty(state);
  const card = panelCard(title, isDirty);
  const payload = entry.payload || {};
  const row = (state.ai || {});
  const work = row.work || {};
  const isWorking = work.state === 'working';
  const head = entryRow(entry, payload.endpoint || '', '');
  const config = document.createElement('button');
  config.className = 'ghost';
  config.textContent = t('ui.config');
  config.disabled = !entry.is_healthy || isHeld(state) || isWorking;
  config.onclick = () => openConfigDialog(payload.models || []);
  const apply = document.createElement('button');
  if (isWorking) {
    apply.innerHTML = '<span class="spin"></span>' + t('ui.ai_switching');
  } else {
    apply.textContent = t('ui.apply');
  }
  // A failed switch leaves Apply live: pressing it asks for the same again.
  apply.disabled = isWorking || !(isDirty || work.code) || !entry.is_healthy ||
    isHeld(state);
  apply.onclick = () => {
    serviceAction('ai', {
      is_enabled: aiStaged.is_enabled,
      tool_configs: aiStaged.tool_configs,
    }, 'ai').then((ok) => { if (ok) { aiStaged = null; redraw(); } });
  };
  head.appendChild(config);
  head.appendChild(apply);
  card.appendChild(head);

  const toggle = document.createElement('button');
  const isOn = !!aiStaged.is_enabled;
  toggle.className = isOn ? 'chip on' : 'chip';
  toggle.disabled = !entry.is_healthy || isHeld(state) || isWorking;
  toggle.innerHTML = '<span class="dot ' + (row.is_active ? 'ok' : 'off') +
    '"></span>' + t('ui.ai_enabled');
  toggle.onclick = () => {
    aiStaged.is_enabled = !isOn;
    redraw();
  };
  const line = document.createElement('div');
  line.className = 'row';
  line.style.padding = '10px 0 4px';
  line.appendChild(toggle);
  const where = document.createElement('span');
  where.className = 'note muted';
  where.textContent = row.is_active ? t('ui.ai_on') : t('ui.ai_off');
  line.appendChild(where);
  card.appendChild(line);

  const notes = [];
  if (row.code) notes.push(wordCode(row.code, row.params));
  if (work.code) notes.push(wordCode(work.code, work.params));
  if (serviceNotes.ai) notes.push(serviceNotes.ai);
  for (const text of notes) card.appendChild(errorLine(text));
  return card;
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

function openConfigDialog(models) {
  const draft = JSON.parse(JSON.stringify(aiStaged.tool_configs || {}));
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
    aiStaged.tool_configs = draft;
    closeDialog(overlay);
    redraw();
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

function drawFilesPanel(state, entries, title) {
  // A form staged for an entry the catalog no longer carries is gone.
  const present = new Set(entries.map((entry) => entry.id));
  for (const id of Object.keys(fileStaged)) {
    if (!present.has(id)) delete fileStaged[id];
  }
  const isDirty = Object.keys(fileStaged).some(
    (id) => fileStaged[id] && fileStaged[id].is_open);
  const card = panelCard(title, isDirty);
  for (const entry of entries) {
    const payload = entry.payload || {};
    const records = (state.mounts || []).filter(
      (record) => record.entry_id === entry.id);
    const noteKey = 'file_' + entry.id;
    const note = serviceNotes[noteKey] || '';
    const row = entryRow(
      entry, '//' + (payload.host || '') + '/' + (payload.share || ''), note);

    const staged = fileStaged[entry.id];
    const config = document.createElement('button');
    config.className = 'ghost';
    config.textContent = t('ui.config');
    config.disabled = isHeld(state);
    config.onclick = () => {
      if (staged && staged.is_open) {
        delete fileStaged[entry.id];
      } else {
        const kept = records[0];
        fileStaged[entry.id] = {
          is_open: true, username: kept ? (kept.username || '') : '',
          password: '',
          path: kept ? kept.path : mountDefaultPath(payload, state),
        };
      }
      redraw();
    };
    row.appendChild(config);

    const mount = mountButton(entry, records[0], staged, state, noteKey);
    if (isHeld(state)) mount.disabled = true;
    row.appendChild(mount);
    card.appendChild(row);

    for (const record of records)
      card.appendChild(drawMountRecord(record, state, noteKey));
    if (staged && staged.is_open)
      card.appendChild(drawFileForm(entry.id, staged, state));
  }
  return card;
}

// A record on its way says which step it is on; anywhere else, nothing.
function mountBusyWord(state) {
  return MOUNT_BUSY_STATES.indexOf(state) >= 0 ? t('ui.mount_' + state) : '';
}

// The one button position beside Config: Mount morphs through the
// transients and into Unmount, never a second button anywhere.
function mountButton(entry, record, staged, state, noteKey) {
  const button = document.createElement('button');
  if (record === undefined) {
    button.textContent = t('ui.mount');
    button.disabled = !entry.is_healthy || !staged || !staged.is_open ||
      !staged.path;
    button.onclick = async () => {
      const sent = {
        action: 'mount', id: entry.id, username: staged.username,
        password: staged.password, path: staged.path,
      };
      staged.password = '';
      if (await serviceAction('file', sent, noteKey)) {
        delete fileStaged[entry.id];
        redraw();
      }
    };
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
  if (record.state === 'detached' || record.code) {
    button.textContent = t('ui.mount');
    button.onclick = () => serviceAction('file',
      { action: 'mount', record_id: record.record_id }, noteKey);
    return button;
  }
  button.className = 'danger';
  button.textContent = t('ui.unmount');
  button.onclick = () => {
    fileAsked[record.record_id] = 'unmounting';
    redraw();
    serviceAction('file',
      { action: 'unmount', record_id: record.record_id }, noteKey
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

function drawFileForm(entryId, staged, state) {
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
