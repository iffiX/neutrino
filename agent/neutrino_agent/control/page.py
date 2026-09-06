"""The agent's local page, served on the loopback.

The page carries no state of its own beyond what a person has staged: it
reads the token ``nagent ui`` put in the URL fragment, sends it as a bearer
on every request, and renders three sections — Status, Modules, Services —
in the scope the reply says the token owns. A control the caller's scope
does not own is disabled, never hidden. Opened without a token it only says
how to get one.

The page redraws only when the state payload actually changed, and never
while the person holds a text selection, a focused form field, or an open
dialog. Its own polling is the token's pulse: the agent expires a token
whose pulse stops, which is how a closed window ends the ``nagent ui``
session that opened it.

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
  .wrap { max-width: 680px; margin: 0 auto; display: flex;
          flex-direction: column; gap: 24px; }
  h1 { margin: 0; font-size: 18px; letter-spacing: .02em; }
  .sect { display: flex; flex-direction: column; gap: 12px; }
  .sect_title { margin: 0; font-size: 16px; font-weight: 600; }
  .sub { color: #8b96a5; font-size: 12px; font-family: ui-monospace, monospace; }
  .card { border: 1px solid #1f2937; border-radius: 12px; background: #111721;
          padding: 18px; transition: border-color .15s, box-shadow .15s; }
  .card.dirty { border-color: #fbbf24; box-shadow: 0 0 26px -16px #fbbf24; }
  .row { display: flex; gap: 12px; align-items: center; }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .spin { width: 10px; height: 10px; flex: none; border-radius: 50%;
          border: 2px solid #1f2937; border-top-color: #22d3ee;
          animation: spin 0.9s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .ok { background: #34d399; box-shadow: 0 0 10px -1px #34d399; }
  .off { background: #8b96a5; }
  .bad { background: #fb7185; box-shadow: 0 0 10px -1px #fb7185; }
  input, select { padding: 9px 12px; border: 1px solid #1f2937;
          border-radius: 8px; background: #0a0e14; color: #e6edf3;
          font-family: ui-monospace, monospace; font-size: 13px; }
  input { flex: 1; min-width: 0; }
  input:disabled, select:disabled { opacity: .4; }
  button { padding: 9px 16px; border: 1px solid #22d3ee; border-radius: 8px;
           background: rgba(34,211,238,.1); color: #22d3ee; font-size: 13px;
           cursor: pointer; }
  button.ghost { border-color: #1f2937; background: none; color: #8b96a5; }
  button.danger { border-color: rgba(251,113,133,.5); background: none;
                  color: #fb7185; }
  button.install { border-color: rgba(52,211,153,.6);
                   background: rgba(52,211,153,.1); color: #34d399; }
  button:disabled { opacity: .4; cursor: not-allowed; border-color: #1f2937; }
  .feat { display: flex; gap: 12px; align-items: center; padding: 12px 0;
          border-bottom: 1px solid #1f2937; }
  .feat:last-child { border-bottom: none; }
  .feat.greyed .body { opacity: .5; }
  .feat .body { flex: 1; min-width: 0; }
  .feat .title { font-weight: 600; }
  .feat .note { color: #8b96a5; font-size: 12px; }
  .panel_title { color: #8b96a5; font-size: 11px; text-transform: uppercase;
           letter-spacing: .08em; border-bottom: 1px solid #1f2937;
           padding-bottom: 6px; margin-bottom: 4px; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; padding: 6px 0 10px; }
  .subhead { color: #7d8590; font-size: 11px; letter-spacing: .06em;
             text-transform: uppercase; margin-top: 10px; }
  .chip { display: inline-flex; gap: 8px; align-items: center;
          border: 1px solid #1f2937; border-radius: 999px; padding: 6px 14px;
          background: none; color: #e6edf3; font-size: 13px; cursor: pointer; }
  .chip.on { border-color: rgba(52,211,153,.6); color: #34d399; }
  a.link { color: #22d3ee; text-decoration: none; }
  a.link:hover { text-decoration: underline; }
  .err { color: #fb7185; font-size: 12px; }
  .muted { color: #8b96a5; }
  .form { display: flex; flex-direction: column; gap: 8px;
          padding: 10px 0 4px 20px; }
  .form .row input { flex: 1; }
  .rec { display: flex; gap: 8px; align-items: center; padding: 4px 0 4px 20px;
         font-size: 12px; color: #8b96a5; font-family: ui-monospace, monospace; }
  .rec .path { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .rec button { padding: 4px 10px; font-size: 12px; }
  .oplog { margin: 10px 0 0; padding: 10px; border: 1px solid #1f2937;
           border-radius: 8px; background: #0a0e14; color: #8b96a5;
           font: 12px/1.5 ui-monospace, monospace; white-space: pre-wrap;
           overflow-wrap: anywhere; max-height: 260px; overflow-y: auto; }
  .overlay { position: fixed; inset: 0; background: rgba(4,6,10,.7);
             display: flex; align-items: center; justify-content: center;
             z-index: 10; }
  .modal { width: min(500px, calc(100vw - 40px)); max-height: 76vh;
           overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
  .modal label { color: #8b96a5; font-size: 12px; }
  .modal select { width: 100%; }
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
    section_status: "Status",
    section_modules: "Modules",
    section_services: "Services",
    connected: "Connected",
    not_connected: "Not connected",
    paste_hint: "Paste the link from the gateway's Devices page",
    connect: "Connect",
    disconnect: "Disconnect",
    privileged_only: "Sign in as an administrator to change this.",
    install: "Install",
    uninstall: "Uninstall",
    built_in: "built in",
    uninstall_ssh_title: "Uninstall the SSH server?",
    uninstall_ssh_body:
      "SSH stops answering on this machine; the agent channel keeps managing it.",
    apply: "Apply",
    config: "Config",
    mount: "Mount",
    unmount: "Unmount",
    port_connect: "Connect",
    port_disconnect: "Disconnect",
    open: "Open",
    browse: "Browse…",
    new_folder: "New folder",
    new_folder_name: "Name of the new folder:",
    choose: "Choose this folder",
    cancel: "Cancel",
    save: "Save",
    up: ".. up",
    username_hint: "Share username",
    password_hint: "Share password",  // scan: allow
    path_hint: "Mount path",
    not_attached: "not mounted",
    browse_drive_letter: "This machine mounts at a drive letter, typed as Z:",
    unmounting: "unmounting…",
    enabled_users: "Enabled users",
    mount_queued: "waiting for the agent…",
    mount_mounting: "mounting…",
    mount_pending: "waiting to mount…",
    forwarding_to: "127.0.0.1:{port}",
    unhealthy: "not reachable now",
    modules_wait_join: "Modules appear once this machine joins a gateway.",
    modules_wait_list: "Waiting for the gateway to send its module list…",
    services_empty: "Nothing is published for this machine yet.",
    operation_title: "Operation output",
    operation_agent: "agent",
    service_needs_modules: "Install these modules to enable this service: {modules}",
    panel_web: "Web",
    panel_ports: "Ports",
    panel_ai: "AI",
    panel_files: "Files",
    gateway_default: "gateway default",
    tool_claude: "Claude Code",
    tool_codex: "Codex",
    tool_gemini: "Gemini",
    slot_default: "Default model",
    slot_opus: "Opus slot",
    slot_sonnet: "Sonnet slot",
    slot_haiku: "Haiku slot",
    codex_model: "Model",
    codex_effort: "Reasoning effort",
    gemini_model: "Model",
    config_title: "AI tool configuration",
    not_for_platform: "This machine cannot run this.",
  },
  states: {
    installed: "installed",
    absent: "not installed",
    installing: "installing…",
    uninstalling: "uninstalling…",
    activating: "switching…",
    deactivating: "switching back…",
    unsupported: "not available on this machine",
    failed: "failed",
    unknown: "waiting for the agent",
  },
  codes: {
    no_platform_build: "no version of this exists for this machine",
    install_unconfirmed: "the install finished, but the software cannot be found",
    vendor_served_a_page: "the vendor served a challenge page, not the package — install it by hand and this row follows",
    module_fetch_failed: "the hub could not fetch this from the vendor",
    module_fetch_unavailable: "the hub cannot fetch downloads gated on a browser",
    module_fetch_too_large: "the vendor's download is larger than the hub will fetch",
    module_release_unreadable: "the hub could not read that project's releases",
    module_cache_unwritable: "the hub could not save the download",
    module_artifact_missing: "the hub no longer holds that download; ask again",
    module_digest_mismatch: "what arrived did not match the hub's checksum",
    agent_never_reported: "this machine never said how the install went",
    uninstall_unconfirmed: "the uninstall finished, but the software is still there",
    no_download_named: "the catalog names no download for this machine",
    unsupported_platform: "this machine cannot do this",
    unknown_kind: "the agent does not know this kind of module",
    unknown_action: "the hub asked for something this agent does not know",
    order_failed: "the install did not finish",
    verify_failed: "this machine could not tell whether the software is there",
    install_failed: "the install failed",
    no_target_user: "that account does not exist on this machine",
    no_endpoint: "the hub has not granted this account a key yet",
    module_missing: "install the {module} module first",
    mountpoint_not_empty: "that folder is not empty",
    mountpoint_invalid: "that is not a mount location this machine can use",
    cifs_missing: "the mount tooling is missing on this machine",
    credentials_missing: "the saved login is gone — enter it again with Config",
    fs_refused: "this account may not use that folder",
    control_scope_refused: "this account is not allowed to do that",
    control_token_invalid: "this page's key was refused",
    control_page_not_served: "the agent serves no page right now",
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
    agent_update_fetch_failed: "self-update failed: the package could not be fetched from the hub",
    agent_package_missing: "self-update to {target} failed: the hub has no agent package for this platform",
    agent_wire_stale: "this agent's build does not match the hub; it reinstalls itself from the hub's package",
    hub_reply_unreadable: "the hub sent a reply this agent could not read",
  },
  causes: {
    hub_untrusted: "the hub's identity changed (it was reset or reinstalled)",
    agent_newer_than_hub: "this agent is newer than the hub",
    hub_refused: "the hub no longer knows this machine",
  },
  operation: {
    queued: "waiting its turn",
    fetching: "downloading…",
    running: "running…",
    done: "done",
    failed: "failed",
  },
};

const TOKEN = location.hash.slice(1);
const POLL_INTERVAL_MS = 1500;

// Claude Code's four role slots and Codex's reasoning scale, as the agent
// stores them.
const CLAUDE_SLOTS = ['default', 'opus', 'sonnet', 'haiku'];
const REASONING_EFFORTS = ['minimal', 'low', 'medium', 'high'];

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
const BUSY = ['installing', 'uninstalling', 'activating', 'deactivating'];

let lastState = null;
let lastSerialized = '';
let pendingState = null;
let serviceNotes = {};
// The staged AI apply: which chips are on and what each tool points with.
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

// --- redraw discipline ---

function canRedraw() {
  if (openDialogs > 0) return false;
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

function redraw() {
  if (lastState !== null && canRedraw()) draw(lastState);
}

async function poll() {
  if (pendingState !== null && canRedraw()) {
    present(pendingState);
    return;
  }
  const state = await api('/api/state');
  if (state) present(state);
}

async function send(path, body) {
  const reply = await api(path, body || {});
  if (reply && !reply.code) { lastSerialized = JSON.stringify(reply); draw(reply); }
  return reply;
}

function askFor(name, step, body) {
  asked[name] = step;
  redraw();
  send('/api/module', body);
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

// --- the three sections ---

function draw(state) {
  lastState = state;
  document.getElementById('ident').textContent =
    state.hostname + ' · ' + state.platform.os + '/' + state.platform.arch +
    ' · agent ' + state.version + ' · ' + state.caller.account;

  const content = document.getElementById('content');
  content.innerHTML = '';
  content.style.display = 'flex';
  content.style.flexDirection = 'column';
  content.style.gap = '24px';
  const modulePanels = [drawModules(state)];
  if (state.operation) modulePanels.push(drawOperation(state.operation));
  content.appendChild(section(WORDS.ui.section_status, [drawConnection(state)]));
  content.appendChild(section(WORDS.ui.section_modules, modulePanels));
  content.appendChild(section(WORDS.ui.section_services, drawServices(state)));
}

// Whether the hub is running an operation on this machine right now —
// whichever surface started it. Every button that would start another one
// greys while it does.
const OPERATION_RUNNING_STATES = ['queued', 'fetching', 'installing',
  'running'];

function isOperationRunning(state) {
  return !!state.operation &&
    OPERATION_RUNNING_STATES.indexOf(state.operation.state) >= 0;
}

// A running order is worded by what it was asked to do; every other state
// has its own word.
function operationWord(op) {
  if (op.state === 'installing') {
    const transient = { install: 'installing',
      uninstall: 'uninstalling' }[op.action];
    return WORDS.states[transient] || WORDS.operation.running;
  }
  return WORDS.operation[op.state] || op.state;
}

function drawOperation(op) {
  const card = document.createElement('div');
  card.className = 'card';
  const heading = document.createElement('div');
  heading.className = 'panel_title';
  heading.textContent = WORDS.ui.operation_title;
  card.appendChild(heading);
  const isRunning = OPERATION_RUNNING_STATES.indexOf(op.state) >= 0;
  const tone = op.state === 'failed' ? 'bad' : op.state === 'done' ? 'ok'
    : 'off';
  const title = op.kind === 'bootstrap' ? WORDS.ui.operation_agent
    : (op.title || '');
  const row = document.createElement('div');
  row.className = 'row';
  row.innerHTML = (isRunning ? '<span class="spin"></span>'
    : '<span class="dot ' + tone + '"></span>') +
    '<div class="body">' + title + ' — ' + operationWord(op) + '</div>';
  card.appendChild(row);
  if (op.output) {
    const log = document.createElement('pre');
    log.className = 'oplog';
    log.textContent = op.output;
    card.appendChild(log);
  }
  return card;
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
  const isPrivileged = state.caller.is_privileged;
  const lastError = wordError(state.last_error);
  if (state.is_connected) {
    const row = document.createElement('div');
    row.className = 'row';
    row.innerHTML = '<span class="dot ok"></span><div style="flex:1"><div>' +
      WORDS.ui.connected + '</div><div class="sub">' + state.gateway_url +
      '</div></div>';
    const leave = document.createElement('button');
    leave.className = 'danger';
    leave.textContent = WORDS.ui.disconnect;
    leave.disabled = !isPrivileged;
    leave.title = isPrivileged ? '' : WORDS.ui.privileged_only;
    leave.onclick = () => send('/api/disconnect');
    row.appendChild(leave);
    conn.appendChild(row);
    if (lastError) conn.appendChild(errorLine(lastError));
  } else {
    conn.innerHTML = '<div class="row" style="margin-bottom:12px">' +
      '<span class="dot off"></span><div><div>' + WORDS.ui.not_connected +
      '</div><div class="sub">' + WORDS.ui.paste_hint + '</div></div></div>';
    const row = document.createElement('div');
    row.className = 'row';
    const input = document.createElement('input');
    input.placeholder = 'neutrino://enroll/...';
    input.disabled = !isPrivileged;
    input.onkeydown = (e) => { if (e.key === 'Enter') join(); };
    const button = document.createElement('button');
    button.textContent = WORDS.ui.connect;
    button.disabled = !isPrivileged;
    button.title = isPrivileged ? '' : WORDS.ui.privileged_only;
    button.onclick = join;
    function join() { send('/api/connect', { link: input.value }); }
    row.appendChild(input);
    row.appendChild(button);
    conn.appendChild(row);
    if (state.error || lastError) conn.appendChild(errorLine(state.error || lastError));
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

// What a module row stands at, mid-step included. A step shows the world it
// is leaving, not the one it is heading for.
function standing(m) {
  if (m.state === 'installing') return false;
  if (m.state === 'uninstalling') return true;
  return m.state === 'installed';
}

function withAsked(m) {
  const step = asked[m.name];
  if (step === undefined) return m;
  if (hasArrived(m, step)) {
    delete asked[m.name];
    return m;
  }
  return Object.assign({}, m, { state: step });
}

function hasArrived(m, step) {
  if (m.state === 'failed' || BUSY.indexOf(m.state) >= 0) return true;
  if (step === 'installing') return m.state === 'installed';
  return m.state === 'absent';
}

function drawModules(state) {
  const panel = document.createElement('div');
  panel.className = 'card';
  if (!state.is_connected) {
    panel.innerHTML = '<span class="muted">' + WORDS.ui.modules_wait_join +
      '</span>';
    return panel;
  }
  if (state.modules.length === 0) {
    panel.innerHTML = '<span class="muted">' + WORDS.ui.modules_wait_list +
      '</span>';
    return panel;
  }
  const isPrivileged = state.caller.is_privileged;
  const isHeld = isOperationRunning(state);
  for (const raw of state.modules) {
    const m = withAsked(raw);
    const isOn = standing(m);
    const working = BUSY.indexOf(m.state) >= 0;
    const tone = isOn ? 'ok' : m.state === 'failed' ? 'bad' : 'off';
    const worded = wordCode(m.code, m.params);
    const note = !m.is_supported ? WORDS.ui.not_for_platform
      : m.is_native ? WORDS.ui.built_in
      : (WORDS.states[m.state] || WORDS.states.unknown) +
        (worded ? ' — ' + worded : '');
    const row = document.createElement('div');
    row.className = 'feat';
    row.innerHTML = (working ? '<span class="spin"></span>'
      : '<span class="dot ' + tone + '"></span>') +
      '<div class="body"><div class="title">' + m.title + '</div>' +
      '<div class="note">' + m.description + '</div>' +
      '<div class="note">' + note + '</div></div>';
    // A module the platform carries natively offers nothing to press.
    if (m.is_native) {
      panel.appendChild(row);
      continue;
    }
    const button = document.createElement('button');
    button.className = isOn ? 'danger' : 'install';
    button.textContent = isOn ? WORDS.ui.uninstall : WORDS.ui.install;
    button.disabled = !isPrivileged || !m.is_supported || working || isHeld;
    button.title = isPrivileged ? '' : WORDS.ui.privileged_only;
    const act = () => askFor(m.name, isOn ? 'uninstalling' : 'installing',
      { name: m.name, is_enabled: !isOn });
    // Losing SSH can lock a person out, so its uninstall asks first.
    button.onclick = (m.kind === 'openssh' && isOn)
      ? () => confirmDialog(WORDS.ui.uninstall_ssh_title,
          WORDS.ui.uninstall_ssh_body, WORDS.ui.uninstall, act)
      : act;
    row.appendChild(button);
    panel.appendChild(row);
  }
  return panel;
}

function confirmDialog(title, body, confirmLabel, onConfirm) {
  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  const modal = document.createElement('div');
  modal.className = 'card modal';
  const heading = document.createElement('div');
  heading.className = 'title';
  heading.textContent = title;
  const text = document.createElement('div');
  text.className = 'muted';
  text.textContent = body;
  const actions = document.createElement('div');
  actions.className = 'row';
  const confirm = document.createElement('button');
  confirm.className = 'danger';
  confirm.textContent = confirmLabel;
  confirm.onclick = () => { closeDialog(overlay); onConfirm(); };
  const cancel = document.createElement('button');
  cancel.className = 'ghost';
  cancel.textContent = WORDS.ui.cancel;
  cancel.onclick = () => closeDialog(overlay);
  actions.appendChild(confirm);
  actions.appendChild(cancel);
  modal.appendChild(heading);
  modal.appendChild(text);
  modal.appendChild(actions);
  overlay.appendChild(modal);
  overlay.onclick = (event) => {
    if (event.target === overlay) closeDialog(overlay);
  };
  openDialog(overlay);
}

function entriesOf(state, type) {
  return (state.services || []).filter((entry) => entry.type === type);
}

function drawServices(state) {
  const panels = [];
  const kinds = [
    ['web', WORDS.ui.panel_web, drawWebPanel],
    ['port', WORDS.ui.panel_ports, drawPortsPanel],
    ['ai', WORDS.ui.panel_ai, drawAiPanel],
    ['file', WORDS.ui.panel_files, drawFilesPanel],
  ];
  for (const [type, title, build] of kinds) {
    const entries = entriesOf(state, type);
    if (entries.length === 0) continue;
    panels.push(build(state, entries, title));
  }
  if (panels.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'card';
    empty.innerHTML = '<span class="muted">' + WORDS.ui.services_empty +
      '</span>';
    panels.push(empty);
  }
  return panels;
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

// The modules a panel's entries depend on that this machine does not have.
// The panel stays present with its controls disabled until they are all on.
function missingModules(state, entries) {
  const needed = [];
  for (const entry of entries) {
    for (const name of (entry.modules || [])) {
      if (needed.indexOf(name) < 0) needed.push(name);
    }
  }
  const byName = {};
  for (const m of state.modules) byName[m.name] = m;
  return needed
    .filter((name) => {
      const row = byName[name];
      return !row || row.state !== 'installed';
    })
    .map((name) => byName[name] || { name: name, title: name });
}

// The notice a gated panel stands behind. A privileged caller gets the one
// action that queues every missing module through the one install queue;
// an ordinary caller gets the words alone.
function missingModulesNotice(state, missing) {
  const box = document.createElement('div');
  const note = document.createElement('div');
  note.className = 'err';
  note.style.margin = '6px 0';
  note.textContent = fill(WORDS.ui.service_needs_modules,
    { modules: missing.map((m) => m.title).join(', ') });
  box.appendChild(note);
  if (state.caller.is_privileged) {
    const button = document.createElement('button');
    button.className = 'install';
    button.textContent = WORDS.ui.install;
    button.disabled = isOperationRunning(state);
    button.onclick = () => installMissing(missing.map((m) => m.name));
    box.appendChild(button);
  }
  return box;
}

async function installMissing(names) {
  for (const name of names) asked[name] = 'installing';
  redraw();
  for (const name of names) {
    await send('/api/module', { name: name, is_enabled: true });
  }
}

function entryRow(entry, payloadText, extraNote) {
  const row = document.createElement('div');
  row.className = entry.is_healthy ? 'feat' : 'feat greyed';
  const note = (entry.is_healthy ? '' : WORDS.ui.unhealthy) +
    (extraNote ? (entry.is_healthy ? '' : ' — ') + extraNote : '');
  row.innerHTML = '<span class="dot ' + (entry.is_healthy ? 'ok' : 'off') +
    '"></span>' +
    '<div class="body"><div class="title">' + entry.title + '</div>' +
    '<div class="note">' + payloadText + (note ? ' — ' + note : '') + '</div>' +
    (entry.description
      ? '<div class="note muted">' + entry.description + '</div>' : '') +
    '</div>';
  return row;
}

function drawWebPanel(state, entries, title) {
  const card = panelCard(title, false);
  for (const entry of entries) {
    const payload = entry.payload || {};
    const row = entryRow(entry, payload.url || '', '');
    const open = document.createElement('button');
    open.textContent = WORDS.ui.open;
    open.disabled = !entry.is_healthy;
    open.onclick = () => window.open(payload.url || '#', '_blank', 'noopener');
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
      ? ' → ' + fill(WORDS.ui.forwarding_to, { port: forward.local_port }) : '';
    const note = serviceNotes[noteKey] || '';
    const row = entryRow(
      entry, (payload.host || '') + ':' + (payload.port || '') + local, note);
    const button = document.createElement('button');
    button.className = isOn ? 'danger' : '';
    button.textContent = isOn ? WORDS.ui.port_disconnect : WORDS.ui.port_connect;
    button.disabled = !entry.is_healthy && !isOn;
    button.onclick = () => serviceAction('port',
      { id: entry.id, is_enabled: !isOn }, noteKey);
    row.appendChild(button);
    card.appendChild(row);
  }
  return card;
}

// --- the AI panel: chips + Config + Apply, staged ---

function ensureAiStaged(state) {
  if (aiStaged !== null) return;
  const targets = {};
  for (const account of state.accounts) {
    targets[account] = !!(state.ai_targets || {})[account];
  }
  aiStaged = {
    targets: targets,
    tool_configs: JSON.parse(JSON.stringify(state.ai_tool_configs || {})),
  };
}

function isAiDirty(state) {
  for (const account of state.accounts) {
    if (aiStaged.targets[account] !== !!(state.ai_targets || {})[account])
      return true;
  }
  return JSON.stringify(aiStaged.tool_configs) !==
    JSON.stringify(state.ai_tool_configs || {});
}

function drawAiPanel(state, entries, title) {
  ensureAiStaged(state);
  const entry = entries[0];
  const missing = missingModules(state, entries);
  const isGated = missing.length > 0;
  const isDirty = !isGated && isAiDirty(state);
  const card = panelCard(title, isDirty);
  if (isGated) card.appendChild(missingModulesNotice(state, missing));
  const payload = entry.payload || {};
  const head = entryRow(entry, payload.endpoint || '', '');
  if (isGated) head.classList.add('greyed');
  const config = document.createElement('button');
  config.className = 'ghost';
  config.textContent = WORDS.ui.config;
  config.disabled = isGated || !entry.is_healthy;
  config.onclick = () => openConfigDialog(payload.models || []);
  const apply = document.createElement('button');
  apply.textContent = WORDS.ui.apply;
  apply.disabled = isGated || !isDirty || !entry.is_healthy;
  apply.onclick = () => {
    serviceAction('ai', {
      targets: aiStaged.targets,
      tool_configs: aiStaged.tool_configs,
    }, 'ai').then((ok) => { if (ok) { aiStaged = null; redraw(); } });
  };
  head.appendChild(config);
  head.appendChild(apply);
  card.appendChild(head);

  const chipsHead = document.createElement('div');
  chipsHead.className = 'subhead';
  chipsHead.textContent = WORDS.ui.enabled_users;
  card.appendChild(chipsHead);
  const chips = document.createElement('div');
  chips.className = 'chips';
  if (isGated) chips.style.opacity = '.5';
  const notes = [];
  for (const account of state.accounts) {
    const row = (state.ai_states || {})[account] || {};
    const isBusy = BUSY.indexOf(row.state) >= 0;
    const isOn = !!aiStaged.targets[account];
    const chip = document.createElement('button');
    chip.className = isOn ? 'chip on' : 'chip';
    chip.disabled = isGated || isBusy || !entry.is_healthy;
    chip.innerHTML = (isBusy ? '<span class="spin"></span>'
      : '<span class="dot ' + (row.is_active ? 'ok' : 'off') + '"></span>') +
      account + (isBusy ? '…' : '');
    chip.onclick = () => {
      aiStaged.targets[account] = !isOn;
      redraw();
    };
    chips.appendChild(chip);
    if (row.code) notes.push(account + ': ' + wordCode(row.code, row.params));
    else if (isBusy)
      notes.push(account + ': ' + (WORDS.states[row.state] || row.state));
  }
  card.appendChild(chips);
  if (serviceNotes.ai) notes.push(serviceNotes.ai);
  for (const text of notes) {
    const note = document.createElement('div');
    note.className = 'feat note muted';
    note.style.border = 'none';
    note.style.padding = '2px 0';
    note.textContent = text;
    card.appendChild(note);
  }

  return card;
}

function modelSelect(models, chosen, onPick) {
  const select = document.createElement('select');
  const blank = document.createElement('option');
  blank.value = '';
  blank.textContent = '(' + WORDS.ui.gateway_default + ')';
  select.appendChild(blank);
  for (const model of models) {
    const option = document.createElement('option');
    option.value = model;
    option.textContent = model;
    select.appendChild(option);
  }
  select.value = models.indexOf(chosen) >= 0 ? chosen : '';
  select.onchange = () => onPick(select.value);
  return select;
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
  heading.textContent = WORDS.ui.config_title;
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

  toolTitle(WORDS.ui.tool_claude);
  const slotLabels = {
    default: WORDS.ui.slot_default, opus: WORDS.ui.slot_opus,
    sonnet: WORDS.ui.slot_sonnet, haiku: WORDS.ui.slot_haiku,
  };
  for (const slot of CLAUDE_SLOTS) {
    field(slotLabels[slot], modelSelect(models, draft.claude[slot] || '',
      (value) => { draft.claude[slot] = value; }));
  }

  toolTitle(WORDS.ui.tool_codex);
  field(WORDS.ui.codex_model, modelSelect(models, draft.codex.model || '',
    (value) => { draft.codex.model = value; }));
  const effort = document.createElement('select');
  const none = document.createElement('option');
  none.value = '';
  none.textContent = '(' + WORDS.ui.gateway_default + ')';
  effort.appendChild(none);
  for (const level of REASONING_EFFORTS) {
    const option = document.createElement('option');
    option.value = level;
    option.textContent = level;
    effort.appendChild(option);
  }
  effort.value = REASONING_EFFORTS.indexOf(
    draft.codex.model_reasoning_effort) >= 0
    ? draft.codex.model_reasoning_effort : '';
  effort.onchange = () => { draft.codex.model_reasoning_effort = effort.value; };
  field(WORDS.ui.codex_effort, effort);

  toolTitle(WORDS.ui.tool_gemini);
  field(WORDS.ui.gemini_model, modelSelect(models, draft.gemini.model || '',
    (value) => { draft.gemini.model = value; }));

  const actions = document.createElement('div');
  actions.className = 'row';
  actions.style.marginTop = '8px';
  const save = document.createElement('button');
  save.textContent = WORDS.ui.save;
  save.onclick = () => {
    aiStaged.tool_configs = draft;
    closeDialog(overlay);
    redraw();
  };
  const cancel = document.createElement('button');
  cancel.className = 'ghost';
  cancel.textContent = WORDS.ui.cancel;
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

function closeDialog(overlay) {
  openDialogs -= 1;
  overlay.remove();
}

// --- the Files panel: Config, then Mount / Unmount ---

function mountDefaultPath(payload, state) {
  const home = state.caller.home || ('/home/' + state.caller.account);
  return home + '/nas/' + (payload.share || '');
}

function drawFilesPanel(state, entries, title) {
  const missing = missingModules(state, entries);
  const isGated = missing.length > 0;
  const isDirty = !isGated && Object.keys(fileStaged).some(
    (id) => fileStaged[id] && fileStaged[id].is_open);
  const card = panelCard(title, isDirty);
  if (isGated) card.appendChild(missingModulesNotice(state, missing));
  for (const entry of entries) {
    const payload = entry.payload || {};
    const records = (state.mounts || []).filter(
      (record) => record.entry_id === entry.id);
    const noteKey = 'file_' + entry.id;
    const note = serviceNotes[noteKey] || '';
    const row = entryRow(
      entry, '//' + (payload.host || '') + '/' + (payload.share || ''), note);
    if (isGated) row.classList.add('greyed');

    const staged = fileStaged[entry.id];
    const config = document.createElement('button');
    config.className = 'ghost';
    config.textContent = WORDS.ui.config;
    config.disabled = isGated;
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
    if (isGated) mount.disabled = true;
    row.appendChild(mount);
    card.appendChild(row);

    for (const record of records)
      card.appendChild(drawMountRecord(record, state, noteKey));
    if (staged && staged.is_open)
      card.appendChild(drawFileForm(entry.id, staged, state));
  }
  return card;
}

const MOUNT_BUSY_WORDS = () => ({
  queued: WORDS.ui.mount_queued,
  mounting: WORDS.ui.mount_mounting,
  pending: WORDS.ui.mount_pending,
});

// The one button position beside Config: Mount morphs through the
// transients and into Unmount, never a second button anywhere.
function mountButton(entry, record, staged, state, noteKey) {
  const button = document.createElement('button');
  if (record === undefined) {
    button.textContent = WORDS.ui.mount;
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
  const busyWord = askedStep ? WORDS.ui.unmounting
    : MOUNT_BUSY_WORDS()[record.state];
  if (busyWord) {
    button.textContent = busyWord;
    button.disabled = true;
    return button;
  }
  const mayAct = state.caller.is_privileged ||
    record.account === state.caller.account;
  if (record.state === 'detached') {
    button.textContent = WORDS.ui.mount;
    button.disabled = !mayAct;
    button.title = mayAct ? '' : WORDS.ui.privileged_only;
    button.onclick = () => serviceAction('file',
      { action: 'mount', record_id: record.record_id }, noteKey);
    return button;
  }
  button.className = 'danger';
  button.textContent = WORDS.ui.unmount;
  button.disabled = !mayAct;
  button.title = mayAct ? '' : WORDS.ui.privileged_only;
  button.onclick = () => {
    fileAsked[record.record_id] = 'unmounting';
    redraw();
    serviceAction('file',
      { action: 'unmount', record_id: record.record_id }, noteKey
    ).then(() => { delete fileAsked[record.record_id]; redraw(); });
  };
  return button;
}

// A record's own line carries only where it stands — the words, never a
// button.
function drawMountRecord(record, state, noteKey) {
  const line = document.createElement('div');
  line.className = 'rec';
  const askedStep = fileAsked[record.record_id];
  const busyWord = askedStep ? WORDS.ui.unmounting
    : MOUNT_BUSY_WORDS()[record.state];
  const status = busyWord ? busyWord
    : record.code ? wordCode(record.code, record.params)
    : record.is_attached ? '' : WORDS.ui.not_attached;
  const marker = busyWord ? '<span class="spin"></span>'
    : '<span class="dot ' +
      (record.is_attached ? 'ok' : record.code ? 'bad' : 'off') + '"></span>';
  line.innerHTML = marker +
    '<span class="path">' + record.path + ' · ' + record.account +
    (status ? ' — ' + status : '') + '</span>';
  return line;
}

function drawFileForm(entryId, staged, state) {
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
    input.value = staged[name];
    input.oninput = () => { staged[name] = input.value; };
    line.appendChild(input);
    form.appendChild(line);
  }
  const pathLine = document.createElement('div');
  pathLine.className = 'row';
  const path = document.createElement('input');
  path.placeholder = WORDS.ui.path_hint;
  path.value = staged.path;
  path.oninput = () => { staged.path = path.value; };
  const browse = document.createElement('button');
  browse.className = 'ghost';
  browse.textContent = WORDS.ui.browse;
  // Where a mount location is a drive letter there is no directory to pick.
  const canBrowse = (state.mount_location_shape || 'path') === 'path';
  browse.disabled = !canBrowse;
  browse.title = canBrowse ? '' : WORDS.ui.browse_drive_letter;
  browse.onclick = () => openBrowser(staged.path, (chosen) => {
    staged.path = chosen;
    redraw();
  });
  pathLine.appendChild(path);
  pathLine.appendChild(browse);
  form.appendChild(pathLine);
  return form;
}

// --- the browse dialog, fed by the agent as the caller's identity ---

function parentPath(path) {
  const trimmed = path.replace(/\\/+$/, '');
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
      up.textContent = WORDS.ui.up;
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
  create.textContent = WORDS.ui.new_folder;
  create.onclick = async () => {
    const name = prompt(WORDS.ui.new_folder_name);
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
  choose.textContent = WORDS.ui.choose;
  choose.onclick = () => { closeDialog(overlay); onChoose(current); };
  const cancel = document.createElement('button');
  cancel.className = 'ghost';
  cancel.textContent = WORDS.ui.cancel;
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

if (!TOKEN) {
  renderHint(WORDS.ui.open_hint);
} else {
  poll();
  setInterval(poll, POLL_INTERVAL_MS);
}
</script>
</body>
</html>
"""
