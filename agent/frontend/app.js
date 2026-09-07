// Every word this surface says; the wire carries only codes.
const WORDS = {
  ui: {
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
    user_tier: "Install it on the machine yourself; the hub only manages it",
    source_label: "source: ",
    license_label: ", License: ",
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
    share_user: "Share user",
    mount_user: "Mount for",
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
    panel_rdp: "Remote desktop",
    rdp_local_share: "Local share",
    rdp_remote_shares: "Remote shares",
    rdp_no_peers: "No other machine is sharing.",
    rdp_share: "Share",
    rdp_unshare: "Stop sharing",
    rdp_connect: "Connect",
    rdp_password_hint: "Access password",  // scan: allow
    rdp_password_label: "Access password",  // scan: allow
    reveal: "Reveal",
    hide: "Hide",
    copy: "Copy",
    copied: "Copied",
    rdp_this_machine: "This machine",
    rdp_reach: "reached at {host}:{port}",
    rdp_not_shared: "This machine's desktop is not shared.",
    rdp_approval_hint:
      "Allow RustDesk to record the screen in System Settings on this " +
      "machine; the share is published once it answers.",
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
    not_shared: "not shared",
    sharing: "shared",
    starting: "starting…",
    waiting_for_approval: "waiting for permission on this machine",
  },
  codes: {
    no_platform_build: "no version of this exists for this machine",
    install_unconfirmed: "the install finished, but the software cannot be found",
    module_fetch_failed: "the hub could not fetch this from the vendor",
    module_fetch_too_large: "the vendor's download is larger than the hub will fetch",
    module_release_unreadable: "the hub could not read that project's releases",
    module_cache_unwritable: "the hub could not save the download",
    module_artifact_missing: "the hub no longer holds that download; ask again",
    module_digest_mismatch: "what arrived did not match the hub's checksum",
    module_sha256_mismatch:
      "the download did not match the checksum this hub pins for it",
    rdp_password_missing: "set an access password to share this desktop",  // scan: allow
    rdp_no_desktop: "this machine has no desktop session to share",
    rdp_wrong_seat: "{account} is not signed in at this machine's screen",
    rdp_configure_failed: "RustDesk could not be configured: {detail}",
    rdp_launch_failed: "the RustDesk client could not be started: {detail}",
    rdp_no_address: "that machine published no address to connect to",
    rdp_nobody_seated: "nobody is signed in at that machine's screen",
    rdp_screen_not_allowed:
      "allow screen sharing once at that machine's screen",
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
    credentials_missing: "the saved login is gone; enter it again with Config",
    no_logged_on_session: "sign in as the mount's account on this machine, then try again",
    fs_refused: "this account may not use that folder",
    control_scope_refused: "this account is not allowed to do that",
    control_identity_unknown: "the agent cannot tell who is asking",
    control_channel_closed:
      "the agent stopped answering; close this window and run nagent gui again",
    unknown_request: "the agent does not know this request",
    agent_internal: "the agent hit an unexpected error ({error}); check its log",
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

const POLL_INTERVAL_MS = 1500;

// Claude Code's four role slots and Codex's reasoning scale, as the agent
// stores them.
const CLAUDE_SLOTS = ['default', 'opus', 'sonnet', 'haiku'];
const REASONING_EFFORTS = ['minimal', 'low', 'medium', 'high'];

function fill(template, params) {
  return template.replace(/\{(\w+)\}/g, (whole, key) =>
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
// The access password typed into the share form, cleared the moment it is
// sent — it lives here and in that one request and nowhere else.
const rdpStaged = { password: '', account: '' };
// Dialogs are built outside draw() and counted here, so a poll never
// redraws under one.
let openDialogs = 0;

function renderHint(text) {
  document.getElementById('content').innerHTML =
    '<div class="card"><span class="muted">' + text + '</span></div>';
}

// --- the bridge: the shell carries every request over the control channel ---

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
  if (!state) return;
  if (state.code) { renderHint(wordCode(state.code, state.params)); return; }
  present(state);
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
    requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
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

// Where a module's software comes from, on the row that installs it: a
// repository, a vendor, or the machine's own packages. Every row carries
// one, so the one that must name a license is not the odd row out.
function sourceLine(m) {
  const named = m.corresponding_source
    ? '<a href="' + m.corresponding_source + '" target="_blank" ' +
      'rel="noreferrer noopener">' + (m.source || '') + '</a>'
    : (m.source || '');
  const licensed = m.license ? WORDS.ui.license_label + m.license : '';
  return '<div class="note">' + WORDS.ui.source_label + named + licensed +
    '</div>';
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
      : m.installer === 'user' && m.state === 'absent'
        ? WORDS.states.absent + ' — ' + WORDS.ui.user_tier
      : (WORDS.states[m.state] || WORDS.states.unknown) +
        (worded ? ' — ' + worded : '');
    const row = document.createElement('div');
    row.className = 'feat';
    // Three lines, the same three the panel draws: what it is, where it
    // comes from, where it stands. The description is the row's tooltip.
    row.innerHTML = (working ? '<span class="spin"></span>'
      : '<span class="dot ' + tone + '"></span>') +
      '<div class="body" title="' + m.description + '">' +
      '<div class="title">' + m.title + '</div>' +
      sourceLine(m) +
      '<div class="note">' + note + '</div></div>';
    // A module the platform carries natively, or one the person installs
    // themselves, offers nothing to press.
    if (m.is_native || m.installer === 'user') {
      panel.appendChild(row);
      continue;
    }
    const button = document.createElement('button');
    button.className = isOn ? 'danger' : 'install';
    button.textContent = isOn ? WORDS.ui.uninstall : WORDS.ui.install;
    button.disabled = !isPrivileged || !m.is_supported ||
      m.state === 'unsupported' || working || isHeld;
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

// Every rdp entry the fleet publishes except this machine's own: a share
// is offered to other machines, and connecting to yourself is not an
// offer.
function peerRdpEntries(state) {
  const own = 'rdp_' + ((state.rdp || {}).share_id || '');
  return entriesOf(state, 'rdp').filter((entry) => entry.id !== own);
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
  // Sharing this desktop is decided here and nowhere else, so the panel
  // stands whether or not the hub publishes anything at all.
  panels.push(drawRdpPanel(state, peerRdpEntries(state)));
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
  return missingNamed(state, needed);
}

// The same judgment for a panel that names its modules itself rather than
// reading them off entries: sharing this desktop is a local decision, so
// its panel stands whether or not the fleet publishes anything.
function missingNamed(state, needed) {
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

// One account, picked from the machine's people. Single-select: a mount
// belongs to one home, and a screen seats one person.
function accountChipRow(label, accounts, chosen, isDisabled, onPick) {
  const wrap = document.createElement('div');
  const head = document.createElement('div');
  head.className = 'subhead';
  head.textContent = label;
  wrap.appendChild(head);
  const chips = document.createElement('div');
  chips.className = 'chips';
  for (const account of accounts) {
    const isOn = account === chosen;
    const chip = document.createElement('button');
    chip.className = isOn ? 'chip on' : 'chip';
    chip.disabled = isDisabled;
    chip.innerHTML = '<span class="dot ' + (isOn ? 'ok' : 'off') + '"></span>' +
      account;
    chip.onclick = () => { onPick(account); redraw(); };
    chips.appendChild(chip);
  }
  wrap.appendChild(chips);
  return wrap;
}

// --- the remote desktop panels: share here, connect there ---

function drawRdpPanel(state, peers) {
  const card = drawRdpSharePanel(state, WORDS.ui.panel_rdp);
  const rule = document.createElement('div');
  rule.className = 'panel_rule';
  card.appendChild(rule);
  const head = document.createElement('div');
  head.className = 'subhead';
  head.textContent = WORDS.ui.rdp_remote_shares;
  card.appendChild(head);
  if (peers.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'note muted';
    empty.textContent = WORDS.ui.rdp_no_peers;
    card.appendChild(empty);
    return card;
  }
  const missing = missingNamed(state, ['rustdesk']);
  const isGated = missing.length > 0;
  for (const entry of peers) {
    const payload = entry.payload || {};
    const noteKey = 'rdp_' + entry.id;
    // What that machine says a peer would wait on: shown here rather than
    // discovered by dialing and sitting in "connecting".
    const attention = payload.attention || '';
    const row = entryRow(
      entry, (payload.host || '') + ':' + (payload.port || ''),
      serviceNotes[noteKey] || (attention ? wordCode(attention, {}) : ''));
    if (isGated || attention) row.classList.add('greyed');
    const connect = document.createElement('button');
    connect.textContent = WORDS.ui.rdp_connect;
    connect.disabled = isGated || !!attention || !entry.is_healthy;
    connect.onclick = () => serviceAction('rdp',
      { action: 'connect', id: entry.id }, noteKey);
    row.appendChild(connect);
    card.appendChild(row);
  }
  return card;
}

function drawRdpSharePanel(state, title) {
  const share = state.rdp || {};
  const missing = missingNamed(state, ['rustdesk']);
  const isGated = missing.length > 0;
  const isPrivileged = state.caller.is_privileged;
  const card = panelCard(title, false);
  if (isGated) card.appendChild(missingModulesNotice(state, missing));
  const localHead = document.createElement('div');
  localHead.className = 'subhead';
  localHead.textContent = WORDS.ui.rdp_local_share;
  card.appendChild(localHead);

  const isShared = !!share.is_shared;
  const standing = WORDS.states[share.state] || WORDS.states.unknown;
  const row = document.createElement('div');
  row.className = isShared ? 'feat' : 'feat greyed';
  const reach = isShared
    ? fill(WORDS.ui.rdp_reach,
        { host: state.hostname, port: share.port }) + ' — ' + standing +
      (share.account ? ' · ' + share.account : '')
    : WORDS.ui.rdp_not_shared;
  row.innerHTML = '<span class="dot ' + (share.state === 'sharing' ? 'ok' : 'off') +
    '"></span>' +
    '<div class="body"><div class="title">' + WORDS.ui.rdp_this_machine +
    '</div><div class="note">' + reach + '</div>' +
'</div>';

  const isOwn = isPrivileged || share.account === state.caller.account;
  const button = document.createElement('button');
  button.className = isShared ? 'danger' : '';
  button.textContent = isShared ? WORDS.ui.rdp_unshare : WORDS.ui.rdp_share;
  button.disabled = isGated || (isShared && !isOwn);
  button.title = !isShared || isOwn ? '' : WORDS.ui.privileged_only;
  button.onclick = () => {
    if (isShared) {
      serviceAction('rdp', { action: 'unshare' }, 'rdp');
      return;
    }
    const sent = {
      action: 'share', password: rdpStaged.password,
      account: shareUser(state),
    };
    rdpStaged.password = '';
    serviceAction('rdp', sent, 'rdp').then(() => redraw());
  };
  row.appendChild(button);
  card.appendChild(row);

  if (share.state === 'waiting_for_approval') {
    const hint = document.createElement('div');
    hint.className = 'err';
    hint.textContent = WORDS.ui.rdp_approval_hint;
    card.appendChild(hint);
  }
  const note = serviceNotes.rdp || '';
  if (note) card.appendChild(errorLine(note));

  if (!isShared) {
    card.appendChild(accountChipRow(
      WORDS.ui.share_user, state.accounts, shareUser(state),
      isGated,
      (account) => { rdpStaged.account = account; }));
    card.appendChild(rdpPasswordForm(state, isGated, button));
  } else if (share.password) {
    card.appendChild(revealedSecret(WORDS.ui.rdp_password_label, share.password));
  }
  return card;
}

function shareUser(state) {
  const seated = ((state.rdp || {}).desktop_accounts || [])[0] || '';
  return rdpStaged.account || seated || state.caller.account;
}

// The window is served over no origin the clipboard API trusts, so a copy
// falls back to selecting the text for the person to take.
function copyText(value) {
  try {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(value);
      return;
    }
  } catch (error) {
    // Fall through to the selection.
  }
  const holder = document.createElement('textarea');
  holder.value = value;
  document.body.appendChild(holder);
  holder.select();
  try { document.execCommand('copy'); } catch (error) { /* selected */ }
  document.body.removeChild(holder);
}

// A secret this machine generated for its owner: masked until asked for,
// never standing in plain text on a screen somebody else can be shown.
function revealedSecret(label, value) {
  const row = document.createElement('div');
  row.className = 'rec';
  const name = document.createElement('span');
  name.textContent = label;
  const shown = document.createElement('span');
  shown.className = 'path';
  let isRevealed = false;
  const draw = () => {
    shown.textContent = isRevealed ? value : '•'.repeat(value.length);
  };
  draw();
  const reveal = document.createElement('button');
  reveal.className = 'ghost';
  reveal.textContent = WORDS.ui.reveal;
  reveal.onclick = () => {
    isRevealed = !isRevealed;
    reveal.textContent = isRevealed ? WORDS.ui.hide : WORDS.ui.reveal;
    draw();
  };
  const copy = document.createElement('button');
  copy.className = 'ghost';
  copy.textContent = WORDS.ui.copy;
  copy.onclick = () => {
    copyText(value);
    copy.textContent = WORDS.ui.copied;
    setTimeout(() => { copy.textContent = WORDS.ui.copy; }, 1500);
  };
  row.appendChild(name);
  row.appendChild(shown);
  row.appendChild(reveal);
  row.appendChild(copy);
  return row;
}

// The password the person sets lives here and in the one request that
// sends it, exactly the way a share's password does.
function rdpPasswordForm(state, isDisabled, button) {
  const form = document.createElement('div');
  form.className = 'form';
  const input = document.createElement('input');
  input.type = 'password';
  input.placeholder = WORDS.ui.rdp_password_hint;
  input.value = rdpStaged.password;
  input.disabled = isDisabled;
  input.oninput = () => {
    rdpStaged.password = input.value;
    button.disabled = isDisabled || !input.value;
  };
  button.disabled = isDisabled || !rdpStaged.password;
  form.appendChild(input);
  return form;
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
          account: kept ? (kept.account || '') : '',
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
        account: staged.account || state.caller.account,
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
  form.appendChild(accountChipRow(
    WORDS.ui.mount_user, state.accounts,
    staged.account || state.caller.account, false,
    (account) => { staged.account = account; }));
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

bridgeReady().then(() => {
  poll();
  setInterval(poll, POLL_INTERVAL_MS);
});
