"""The agent's local page, served on the loopback.

The page carries no state of its own: it reads the token ``nagent ui`` put
in the URL fragment, sends it as a bearer on every request, and renders the
scope the reply says the token owns — the connection and functions with
controls for a privileged caller and read-only otherwise, then the services
the catalog publishes, grouped by kind. Opened without a token it only says
how to get one.

The agent reports errors and states as ``{"code", "params"}``; every word
on this surface lives in the page's own table.
"""

CONTROL_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Neutrino agent</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; padding: 32px 20px; background: #0a0e14; color: #e6edf3;
         font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, sans-serif; }
  .wrap { max-width: 620px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }
  h1 { margin: 0; font-size: 18px; letter-spacing: .02em; }
  .sub { color: #7d8590; font-size: 12px; font-family: ui-monospace, monospace; }
  .card { border: 1px solid #1f2937; border-radius: 12px; background: #111721; padding: 18px; }
  .row { display: flex; gap: 12px; align-items: center; }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .ok { background: #34d399; box-shadow: 0 0 10px -1px #34d399; }
  .off { background: #7d8590; }
  .bad { background: #ff4252; box-shadow: 0 0 10px -1px #ff4252; }
  input { flex: 1; min-width: 0; padding: 9px 12px; border: 1px solid #1f2937;
          border-radius: 8px; background: #0a0e14; color: #e6edf3;
          font-family: ui-monospace, monospace; font-size: 13px; }
  button { padding: 9px 16px; border: 1px solid #22d3ee; border-radius: 8px;
           background: rgba(34,211,238,.1); color: #22d3ee; font-size: 13px; cursor: pointer; }
  button.ghost { border-color: #1f2937; background: none; color: #7d8590; }
  button.danger { border-color: rgba(255,66,82,.5); background: none; color: #ff4252; }
  button.install { border-color: rgba(52,211,153,.6); background: rgba(52,211,153,.1); color: #34d399; }
  button:disabled { opacity: .4; cursor: not-allowed; border-color: #1f2937; }
  .feat { display: flex; gap: 12px; align-items: center; padding: 12px 0;
          border-bottom: 1px solid #1f2937; }
  .feat:last-child { border-bottom: none; }
  .feat .body { flex: 1; min-width: 0; }
  .feat .title { font-weight: 600; }
  .feat .note { color: #7d8590; font-size: 12px; }
  .group { color: #7d8590; font-size: 11px; text-transform: uppercase;
           letter-spacing: .08em; border-bottom: 1px solid #1f2937;
           padding-bottom: 6px; margin: 18px 0 4px; }
  .group:first-child { margin-top: 0; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; padding: 10px 0; }
  .chip { display: inline-flex; gap: 8px; align-items: center;
          border: 1px solid #1f2937; border-radius: 999px; padding: 6px 14px;
          background: none; color: #e6edf3; font-size: 13px; cursor: pointer; }
  .chip.on { border-color: rgba(52,211,153,.6); color: #34d399; }
  a.link { color: #22d3ee; text-decoration: none; }
  a.link:hover { text-decoration: underline; }
  .err { color: #ff4252; font-size: 12px; }
  .muted { color: #7d8590; }
  .form { display: flex; flex-direction: column; gap: 8px; padding: 10px 0 4px 20px; }
  .form .row input { flex: 1; }
  .rec { display: flex; gap: 8px; align-items: center; padding: 4px 0 4px 20px;
         font-size: 12px; color: #7d8590; font-family: ui-monospace, monospace; }
  .rec .path { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .rec button { padding: 4px 10px; font-size: 12px; }
  .overlay { position: fixed; inset: 0; background: rgba(4,6,10,.7);
             display: flex; align-items: center; justify-content: center; z-index: 10; }
  .modal { width: min(480px, calc(100vw - 40px)); max-height: 70vh;
           display: flex; flex-direction: column; gap: 10px; }
  .dirlist { overflow-y: auto; border: 1px solid #1f2937; border-radius: 8px;
             min-height: 120px; max-height: 40vh; }
  .dirlist button { display: block; width: 100%; text-align: left; border: none;
                    border-bottom: 1px solid #1f2937; border-radius: 0;
                    background: none; color: #e6edf3;
                    font-family: ui-monospace, monospace; }
  .dirlist button:last-child { border-bottom: none; }
</style>
</head>
<body>
<div class="wrap">
  <div>
    <h1>Neutrino agent</h1>
    <div class="sub" id="ident"></div>
  </div>
  <div id="content"></div>
</div>
<script>
// Every word this surface says; the wire carries only codes.
const WORDS = {
  ui: {
    open_hint: "Open this page with nagent ui.",
    stale_token: "This page's key has expired — run nagent ui again.",
    connected: "Connected",
    not_connected: "Not connected",
    paste_hint: "Paste the link from the gateway's Devices page",
    connect: "Connect",
    disconnect: "Disconnect",
    install: "Install",
    uninstall: "Uninstall",
    activate: "Activate",
    deactivate: "Deactivate",
    forward: "Forward",
    stop: "Stop",
    attach: "Attach",
    detach: "Detach",
    browse: "Browse…",
    new_folder: "New folder",
    new_folder_name: "Name of the new folder:",
    choose: "Choose this folder",
    cancel: "Cancel",
    up: ".. up",
    open: "Open",
    username_hint: "Share username",
    password_hint: "Share password",  // scan: allow
    path_hint: "Mount path",
    not_attached: "not attached",
    forwarding_to: "127.0.0.1:{port}",
    functions_wait_join: "Functions appear once this machine joins a gateway.",
    functions_wait_list: "Waiting for the gateway to send its function list…",
    services_empty: "Nothing is published for this machine yet.",
    group_ai: "AI",
    group_links: "Links",
    group_ports: "Ports",
    group_mounts: "Mounts",
    not_for_platform: "Not available for this platform",
    pointing: " · pointing at the hub",
    not_pointing: " · not pointing here",
  },
  states: {
    installed: "installed",
    absent: "not installed",
    installing: "installing…",
    uninstalling: "uninstalling…",
    removing: "uninstalling…",
    activating: "activating…",
    deactivating: "deactivating…",
    unsupported: "not available here",
    failed: "failed",
    unknown: "waiting for the agent",
  },
  codes: {
    no_platform_build: "no build for this platform",
    verify_unconfirmed: "installed; verify did not confirm",
    remove_unconfirmed: "removal did not take",
    no_download_named: "manifest names no download",
    unsupported_platform: "not supported on this platform",
    unknown_kind: "unknown kind {kind}",
    no_target_user: "no account to switch for",
    no_endpoint: "the hub sent no endpoint for this account",
    desktop_app_remains: "the desktop app remains installed",
    mountpoint_not_empty: "that folder is not empty",
    cifs_missing: "this machine has no CIFS mount tooling",
    credentials_missing: "the saved login is gone — attach again",
    fs_refused: "not allowed there for this account",
    control_scope_refused: "not allowed for this account",
    control_token_invalid: "this page's key was refused",
    unknown_request: "the agent does not know this request",
  },
  errors: {
    hub_refused: "the hub refused this machine's token",
    hub_untrusted: "what answers is not the hub this machine pinned",
    hub_unreachable: "the hub cannot be reached",
    agent_newer_than_hub: "this agent ({agent_version}) is newer than the hub ({hub_version}); update the hub first",
    self_unbound: "{cause}; rejoin by pasting a fresh link from the hub's Devices page",
    agent_package_digest_mismatch: "self-update to {target} failed: the package did not match its digest",
    agent_update_launch_failed: "self-update to {target} could not be launched",
  },
  causes: {
    hub_untrusted: "the hub's identity changed (it was reset or reinstalled)",
    agent_newer_than_hub: "this agent is newer than the hub",
    hub_refused: "the hub no longer knows this machine",
  },
};

const TOKEN = location.hash.slice(1);

function fill(template, params) {
  return template.replace(/\\{(\\w+)\\}/g, (whole, key) =>
    params && params[key] !== undefined ? params[key] : '');
}

function wordCode(code, params) {
  if (!code) return '';
  const p = params || {};
  if (code === 'install_failed' || code === 'download_failed' ||
      code === 'reconcile_failed' || code === 'mount_failed' ||
      code === 'unmount_failed' || code === 'forward_failed')
    return p.detail || WORDS.states.failed;
  const word = WORDS.codes[code];
  return word ? fill(word, p) : code;
}

function wordError(e) {
  if (!e || !e.code) return '';
  const p = e.params || {};
  if (e.code === 'hub_unreachable') return p.detail || WORDS.errors.hub_unreachable;
  if (e.code === 'self_unbound')
    return fill(WORDS.errors.self_unbound,
      { cause: WORDS.causes[p.cause] || WORDS.causes.hub_refused });
  const word = WORDS.errors[e.code];
  return word ? fill(word, p) : e.code;
}

// The step each click asked for, shown until the machine reports having got
// there. A click changes the row at once: an install can finish between two
// heartbeats, and a button that looks unpressed is worse than a stale label.
const asked = {};
const BUSY = ['installing', 'uninstalling', 'removing', 'activating',
  'deactivating'];

// What a row stands at, mid-step included. A step shows the world it is
// leaving, not the one it is heading for: uninstalling is still installed
// until it is gone, activating is still not aimed here until it arrives.
// Deciding this once is what keeps the buttons agreeing with each other.
function standing(f) {
  if (f.state === 'installing') return { on: false, aimed: false };
  if (f.state === 'uninstalling' || f.state === 'removing')
    return { on: true, aimed: f.is_active };
  if (f.state === 'activating') return { on: true, aimed: false };
  if (f.state === 'deactivating') return { on: true, aimed: true };
  return { on: f.state === 'installed', aimed: f.is_active };
}

let lastState = null;
let serviceNotes = {};
// The AI step each chip asked for, shown until the account's row reports it.
const askedAi = {};
// The attach form's own values, kept across redraws; the password lives
// only here and in the one request that sends it.
let mountFormOffer = null;
let mountForm = { username: '', password: '', path: '' };
// The browse dialog: null when closed, else its current directory.
let browser = null;

function renderHint(text) {
  document.getElementById('content').innerHTML =
    '<div class="card"><span class="muted">' + text + '</span></div>';
}

async function api(path, body) {
  const options = { headers: { 'Authorization': 'Bearer ' + TOKEN } };
  if (body !== undefined) {
    options.method = 'POST';
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const reply = await fetch(path, options);
  if (reply.status === 401) {
    renderHint(WORDS.ui.stale_token);
    return null;
  }
  return await reply.json();
}

async function load() {
  const state = await api('/api/state');
  if (state) draw(state);
}

// What the rows show: the machine's report, with any step just asked for
// standing in front of it, until the machine reports having got there.
function withAsked(state) {
  for (const f of state.functions) {
    const step = asked[f.name];
    if (step === undefined) continue;
    if (hasArrived(f, step)) {
      delete asked[f.name];
    } else {
      f.state = step;
    }
  }
  return state;
}

function hasArrived(f, step) {
  if (f.state === 'failed' || BUSY.includes(f.state)) return true;
  if (step === 'installing') return f.state === 'installed';
  if (step === 'uninstalling') return f.state === 'absent';
  if (step === 'activating') return f.is_active;
  return !f.is_active;
}

async function send(path, body) {
  const reply = await api(path, body || {});
  if (reply) draw(reply);
}

function askFor(name, step, body) {
  asked[name] = step;
  redraw();
  send('/api/function', body);
}

async function serviceAction(path, body, noteKey) {
  const reply = await api(path, body);
  if (!reply) return false;
  if (reply.code) {
    serviceNotes[noteKey] = wordCode(reply.code, reply.params);
    redraw();
    return false;
  }
  delete serviceNotes[noteKey];
  draw(reply);
  return true;
}

function redraw() {
  if (lastState !== null) draw(lastState);
}

function draw(rawState) {
  const state = withAsked(rawState);
  lastState = rawState;
  document.getElementById('ident').textContent =
    state.hostname + ' · ' + state.platform.os + '/' + state.platform.arch +
    ' · agent ' + state.version + ' · ' + state.caller.account;

  const content = document.getElementById('content');
  content.innerHTML = '';
  content.style.display = 'flex';
  content.style.flexDirection = 'column';
  content.style.gap = '20px';
  content.appendChild(drawConnection(state));
  content.appendChild(drawFunctions(state));
  content.appendChild(drawServices(state));
  if (browser !== null) content.appendChild(drawBrowser());
}

function drawConnection(state) {
  const conn = document.createElement('div');
  conn.className = 'card';
  const isPrivileged = state.caller.is_privileged;
  const lastError = wordError(state.last_error);
  if (state.is_connected) {
    const row = document.createElement('div');
    row.className = 'row';
    row.innerHTML = '<span class="dot ok"></span><div style="flex:1"><div>' +
      WORDS.ui.connected + '</div><div class="sub">' + state.gateway_url +
      '</div></div>';
    if (isPrivileged) {
      const leave = document.createElement('button');
      leave.className = 'danger';
      leave.textContent = WORDS.ui.disconnect;
      leave.onclick = () => send('/api/disconnect');
      row.appendChild(leave);
    }
    conn.appendChild(row);
    if (lastError) conn.appendChild(errorLine(lastError));
  } else if (isPrivileged) {
    conn.innerHTML = '<div class="row" style="margin-bottom:12px">' +
      '<span class="dot off"></span><div><div>' + WORDS.ui.not_connected +
      '</div><div class="sub">' + WORDS.ui.paste_hint + '</div></div></div>';
    const row = document.createElement('div');
    row.className = 'row';
    const input = document.createElement('input');
    input.placeholder = 'neutrino://enroll/...';
    input.onkeydown = (e) => { if (e.key === 'Enter') join(); };
    const button = document.createElement('button');
    button.textContent = WORDS.ui.connect;
    button.onclick = join;
    function join() { send('/api/connect', { link: input.value }); }
    row.appendChild(input);
    row.appendChild(button);
    conn.appendChild(row);
    if (state.error || lastError) conn.appendChild(errorLine(state.error || lastError));
  } else {
    conn.innerHTML = '<div class="row"><span class="dot off"></span><div>' +
      WORDS.ui.not_connected + '</div></div>';
    if (lastError) conn.appendChild(errorLine(lastError));
  }
  return conn;
}

function errorLine(text) {
  const err = document.createElement('div');
  err.className = 'err';
  err.style.marginTop = '10px';
  err.textContent = text;
  return err;
}

function drawFunctions(state) {
  const feats = document.createElement('div');
  feats.className = 'card';
  if (!state.is_connected) {
    feats.innerHTML = '<span class="muted">' + WORDS.ui.functions_wait_join +
      '</span>';
    return feats;
  }
  if (state.functions.length === 0) {
    feats.innerHTML = '<span class="muted">' + WORDS.ui.functions_wait_list +
      '</span>';
    return feats;
  }
  const isPrivileged = state.caller.is_privileged;
  for (const f of state.functions) {
    const row = document.createElement('div');
    row.className = 'feat';
    const here = standing(f);
    const working = BUSY.includes(f.state);
    const tone = working ? 'bad' : here.on ? 'ok'
      : f.state === 'failed' ? 'bad' : 'off';
    const worded = wordCode(f.code, f.params);
    const note = !f.is_supported ? WORDS.ui.not_for_platform
      : (WORDS.states[f.state] || WORDS.states.unknown) +
        (f.has_activation && here.on && !working
          ? (here.aimed ? WORDS.ui.pointing : WORDS.ui.not_pointing)
          : '') +
        (worded ? ' — ' + worded : '');
    row.innerHTML = '<span class="dot ' + tone + '"></span>' +
      '<div class="body"><div class="title">' + f.title + '</div>' +
      '<div class="note">' + f.description + '</div>' +
      '<div class="note">' + note + '</div></div>';
    if (isPrivileged) {
      if (f.has_activation && here.on) {
        const aim = document.createElement('button');
        aim.className = here.aimed ? 'danger' : 'install';
        aim.textContent = here.aimed ? WORDS.ui.deactivate : WORDS.ui.activate;
        aim.disabled = !f.is_supported || working;
        aim.onclick = () => askFor(f.name,
          here.aimed ? 'deactivating' : 'activating',
          { name: f.name, is_activated: !here.aimed });
        row.appendChild(aim);
      }
      if (f.is_removable || !here.on) {
        const button = document.createElement('button');
        button.className = here.on ? 'danger' : 'install';
        button.textContent = here.on ? WORDS.ui.uninstall : WORDS.ui.install;
        button.disabled = !f.is_supported || working;
        button.onclick = () => askFor(f.name,
          here.on ? 'uninstalling' : 'installing',
          { name: f.name, is_enabled: !here.on });
        row.appendChild(button);
      }
    }
    feats.appendChild(row);
  }
  return feats;
}

function drawServices(state) {
  const card = document.createElement('div');
  card.className = 'card';
  const offers = Object.entries(state.services || {}).map(
    ([id, offer]) => Object.assign({ id: id }, offer));
  const groups = [
    ['ai', WORDS.ui.group_ai, drawAiGroup],
    ['link', WORDS.ui.group_links, drawLinkRow],
    ['port', WORDS.ui.group_ports, drawPortRow],
    ['mount', WORDS.ui.group_mounts, drawMountRow],
  ];
  let hasAny = false;
  for (const [kind, title, drawEntry] of groups) {
    const members = offers.filter((offer) => offer.kind === kind);
    if (members.length === 0) continue;
    hasAny = true;
    const divider = document.createElement('div');
    divider.className = 'group';
    divider.textContent = title;
    card.appendChild(divider);
    if (kind === 'ai') {
      card.appendChild(drawEntry(state));
    } else {
      for (const offer of members) card.appendChild(drawEntry(offer, state));
    }
  }
  if (!hasAny) {
    card.innerHTML = '<span class="muted">' + WORDS.ui.services_empty +
      '</span>';
  }
  return card;
}

function drawAiGroup(state) {
  const box = document.createElement('div');
  const chips = document.createElement('div');
  chips.className = 'chips';
  const notes = [];
  for (const account of state.accounts) {
    const row = (state.ai_states || {})[account] || {};
    const isOn = !!row.is_active;
    let step = askedAi[account];
    if (step !== undefined && (row.code || isOn === step)) {
      delete askedAi[account];
      step = undefined;
    }
    const isBusy = step !== undefined ||
      ['installing', 'activating', 'deactivating'].includes(row.state);
    const chip = document.createElement('button');
    chip.className = isOn ? 'chip on' : 'chip';
    chip.disabled = isBusy;
    chip.innerHTML = '<span class="dot ' + (isBusy ? 'bad' : isOn ? 'ok' : 'off') +
      '"></span>' + account + (isBusy ? '…' : '');
    chip.onclick = () => {
      askedAi[account] = !isOn;
      redraw();
      serviceAction('/api/services/ai',
        { account: account, is_activated: !isOn }, 'ai');
    };
    chips.appendChild(chip);
    if (row.code) notes.push(account + ': ' + wordCode(row.code, row.params));
  }
  box.appendChild(chips);
  if (serviceNotes.ai) notes.push(serviceNotes.ai);
  for (const text of notes) {
    const note = document.createElement('div');
    note.className = 'note muted';
    note.textContent = text;
    box.appendChild(note);
  }
  return box;
}

function drawLinkRow(offer) {
  const row = document.createElement('div');
  row.className = 'feat';
  row.innerHTML = '<span class="dot ok"></span>' +
    '<div class="body"><div class="title">' + offer.title + '</div>' +
    '<div class="note">' + offer.url + '</div></div>';
  const anchor = document.createElement('a');
  anchor.className = 'link';
  anchor.href = offer.url;
  anchor.target = '_blank';
  anchor.rel = 'noopener';
  anchor.textContent = WORDS.ui.open;
  row.appendChild(anchor);
  return row;
}

function drawPortRow(offer, state) {
  const forward = (state.forwards || {})[offer.id] || {};
  const isOn = !!forward.is_active;
  const noteKey = 'port_' + offer.id;
  const row = document.createElement('div');
  row.className = 'feat';
  const local = isOn
    ? ' → ' + fill(WORDS.ui.forwarding_to, { port: forward.local_port }) : '';
  const note = serviceNotes[noteKey]
    ? ' — ' + serviceNotes[noteKey] : '';
  row.innerHTML = '<span class="dot ' + (isOn ? 'ok' : 'off') + '"></span>' +
    '<div class="body"><div class="title">' + offer.title + '</div>' +
    '<div class="note">' + offer.host + ':' + offer.port + local + note +
    '</div></div>';
  const button = document.createElement('button');
  button.className = isOn ? 'danger' : '';
  button.textContent = isOn ? WORDS.ui.stop : WORDS.ui.forward;
  button.onclick = () => serviceAction('/api/services/forward',
    { offer_id: offer.id, is_enabled: !isOn }, noteKey);
  row.appendChild(button);
  return row;
}

function mountDefaultPath(offer, state) {
  const home = state.caller.home || ('/home/' + state.caller.account);
  return home + '/nas/' + offer.share;
}

function drawMountRow(offer, state) {
  const records = (state.mounts || []).filter(
    (record) => record.offer_id === offer.id);
  const isAttached = records.some((record) => record.is_attached);
  const noteKey = 'mount_' + offer.id;
  const box = document.createElement('div');
  const row = document.createElement('div');
  row.className = 'feat';
  const note = serviceNotes[noteKey] ? ' — ' + serviceNotes[noteKey] : '';
  row.innerHTML = '<span class="dot ' + (isAttached ? 'ok' : 'off') +
    '"></span>' +
    '<div class="body"><div class="title">' + offer.title + '</div>' +
    '<div class="note">//' + offer.host + '/' + offer.share + note +
    '</div></div>';
  if (mountFormOffer !== offer.id) {
    const button = document.createElement('button');
    button.textContent = WORDS.ui.attach;
    button.onclick = () => {
      mountFormOffer = offer.id;
      mountForm = { username: '', password: '',
        path: mountDefaultPath(offer, state) };
      redraw();
    };
    row.appendChild(button);
  }
  box.appendChild(row);
  for (const record of records) box.appendChild(drawMountRecord(record, state));
  if (mountFormOffer === offer.id) box.appendChild(drawMountForm(offer));
  return box;
}

function drawMountRecord(record, state) {
  const line = document.createElement('div');
  line.className = 'rec';
  const status = record.code ? wordCode(record.code, record.params)
    : record.is_attached ? '' : WORDS.ui.not_attached;
  line.innerHTML = '<span class="dot ' +
    (record.is_attached ? 'ok' : record.code ? 'bad' : 'off') + '"></span>' +
    '<span class="path">' + record.path + ' · ' + record.account +
    (status ? ' — ' + status : '') + '</span>';
  if (state.caller.is_privileged || record.account === state.caller.account) {
    const button = document.createElement('button');
    button.className = 'danger';
    button.textContent = WORDS.ui.detach;
    button.onclick = () => serviceAction('/api/services/mount',
      { action: 'detach', record_id: record.record_id },
      'mount_' + record.offer_id);
    line.appendChild(button);
  }
  return line;
}

function drawMountForm(offer) {
  const form = document.createElement('div');
  form.className = 'form';
  const fields = [
    ['username', WORDS.ui.username_hint, 'text'],
    ['password', WORDS.ui.password_hint, 'password'],
  ];
  for (const [name, hint, type] of fields) {
    const line = document.createElement('div');
    line.className = 'row';
    const input = document.createElement('input');
    input.type = type;
    input.placeholder = hint;
    input.value = mountForm[name];
    input.oninput = () => { mountForm[name] = input.value; };
    line.appendChild(input);
    form.appendChild(line);
  }
  const pathLine = document.createElement('div');
  pathLine.className = 'row';
  const path = document.createElement('input');
  path.placeholder = WORDS.ui.path_hint;
  path.value = mountForm.path;
  path.oninput = () => { mountForm.path = path.value; };
  const browse = document.createElement('button');
  browse.className = 'ghost';
  browse.textContent = WORDS.ui.browse;
  browse.onclick = () => openBrowser(mountForm.path);
  pathLine.appendChild(path);
  pathLine.appendChild(browse);
  form.appendChild(pathLine);
  const actions = document.createElement('div');
  actions.className = 'row';
  const attach = document.createElement('button');
  attach.textContent = WORDS.ui.attach;
  attach.onclick = async () => {
    const sent = { action: 'attach', offer_id: offer.id,
      username: mountForm.username, password: mountForm.password,
      path: mountForm.path };
    mountForm.password = '';
    if (await serviceAction('/api/services/mount', sent, 'mount_' + offer.id)) {
      mountFormOffer = null;
      load();
    }
  };
  const cancel = document.createElement('button');
  cancel.className = 'ghost';
  cancel.textContent = WORDS.ui.cancel;
  cancel.onclick = () => { mountFormOffer = null; redraw(); };
  actions.appendChild(attach);
  actions.appendChild(cancel);
  form.appendChild(actions);
  return form;
}

function parentPath(path) {
  const trimmed = path.replace(/\\/+$/, '');
  const cut = trimmed.slice(0, trimmed.lastIndexOf('/'));
  return cut || '/';
}

function joinPath(path, name) {
  return (path === '/' ? '' : path) + '/' + name;
}

async function openBrowser(path) {
  browser = { path: '/', dirs: [], note: '' };
  await browseTo(parentPath(path || '/'));
}

async function browseTo(path) {
  const reply = await api('/api/fs?path=' + encodeURIComponent(path));
  if (!reply) return;
  if (reply.code) {
    browser.note = wordCode(reply.code, reply.params);
  } else {
    browser.path = reply.path;
    browser.dirs = reply.dirs;
    browser.note = '';
  }
  redraw();
}

function drawBrowser() {
  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  overlay.onclick = (event) => {
    if (event.target === overlay) { browser = null; redraw(); }
  };
  const modal = document.createElement('div');
  modal.className = 'card modal';
  const where = document.createElement('div');
  where.className = 'sub';
  where.textContent = browser.path;
  modal.appendChild(where);
  const list = document.createElement('div');
  list.className = 'dirlist';
  if (browser.path !== '/') {
    const up = document.createElement('button');
    up.textContent = WORDS.ui.up;
    up.onclick = () => browseTo(parentPath(browser.path));
    list.appendChild(up);
  }
  for (const name of browser.dirs) {
    const entry = document.createElement('button');
    entry.textContent = name + '/';
    entry.onclick = () => browseTo(joinPath(browser.path, name));
    list.appendChild(entry);
  }
  modal.appendChild(list);
  if (browser.note) {
    const note = document.createElement('div');
    note.className = 'err';
    note.textContent = browser.note;
    modal.appendChild(note);
  }
  const actions = document.createElement('div');
  actions.className = 'row';
  const create = document.createElement('button');
  create.className = 'ghost';
  create.textContent = WORDS.ui.new_folder;
  create.onclick = async () => {
    const name = prompt(WORDS.ui.new_folder_name);
    if (!name) return;
    const reply = await api('/api/fs', { path: joinPath(browser.path, name) });
    if (!reply) return;
    if (reply.code) {
      browser.note = wordCode(reply.code, reply.params);
      redraw();
      return;
    }
    browseTo(browser.path);
  };
  const choose = document.createElement('button');
  choose.textContent = WORDS.ui.choose;
  choose.onclick = () => {
    mountForm.path = browser.path;
    browser = null;
    redraw();
  };
  const cancel = document.createElement('button');
  cancel.className = 'ghost';
  cancel.textContent = WORDS.ui.cancel;
  cancel.onclick = () => { browser = null; redraw(); };
  actions.appendChild(create);
  actions.appendChild(choose);
  actions.appendChild(cancel);
  modal.appendChild(actions);
  overlay.appendChild(modal);
  return overlay;
}

if (!TOKEN) {
  renderHint(WORDS.ui.open_hint);
} else {
  load();
  // The poll pauses while the attach form or the browse dialog is open, so
  // a redraw cannot take what is being typed.
  setInterval(() => {
    if (mountFormOffer === null && browser === null) load();
  }, 1500);
}
</script>
</body>
</html>
"""
