"""The agent's own page, for the machine it runs on.

Three things, and deliberately no more: join a gateway by pasting its link,
see and switch the features this machine can run, and leave the gateway. Every
richer view of the fleet belongs in the gateway's own panel — this exists so a
machine the gateway cannot reach (no SSH, or behind someone else's NAT) can
still be set up by its owner sitting in front of it.

Bound to the loopback address: the page has no password, so the only
credential it accepts is being on the machine.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from neutrino_agent import AGENT_VERSION
from neutrino_agent import enrollment
from neutrino_agent.metrics import hostname
from neutrino_agent.platform_info import platform_keys

MINI_UI_HOST = "127.0.0.1"
MINI_UI_PORT = 8765


class MiniUiServer:
    """Serves the agent's local page in a background thread."""

    def __init__(self, *, agent, log=print):
        """
        Args:
            agent: The running :class:`~neutrino_agent.agent.Agent`, which
                owns the connection state and the feature manager.
            log: Callable used for progress messages.
        """
        self._agent = agent
        self._log = log
        self._server = None

    def start(self) -> None:
        """Start serving, or log why it could not.

        A machine that cannot bind the port is still a working agent, so this
        never takes the process down with it.
        """
        try:
            self._server = HTTPServer(
                (MINI_UI_HOST, MINI_UI_PORT), _build_handler(self._agent)
            )
        except OSError as error:
            self._log(f"local page not available: {error}")
            return
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        self._log(f"local page on http://{MINI_UI_HOST}:{MINI_UI_PORT}")


def _build_handler(agent):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith("/api/state"):
                self._send_json(_state(agent))
                return
            self._send_html(PAGE_HTML)

        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                body = {}
            if self.path.startswith("/api/connect"):
                self._send_json(_connect(agent, body.get("link", "")))
            elif self.path.startswith("/api/disconnect"):
                agent.disconnect()
                self._send_json(_state(agent))
            elif self.path.startswith("/api/feature"):
                agent.request_feature(
                    body.get("name", ""),
                    is_enabled=body.get("is_enabled"),
                    is_activated=body.get("is_activated"),
                )
                self._send_json(_state(agent))
            else:
                self._send_json({"error": "unknown request"}, status=404)

        def _send_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            # The journal already has the agent's own lines; access logs for a
            # single-user local page would only bury them.
            return

    return Handler


def _connect(agent, link: str) -> dict:
    try:
        agent.connect(link)
    except enrollment.EnrollmentError as error:
        state = _state(agent)
        state["error"] = str(error)
        return state
    return _state(agent)


def _state(agent) -> dict:
    """Everything the page draws, in one payload."""
    config = enrollment.load_config()
    features = []
    catalog = agent.catalog()
    keys = platform_keys(agent.platform())
    reported = agent.feature_states()
    desired = agent.desired_features()
    for name, manifest in sorted(catalog.items()):
        is_supported = any(key in manifest.get("platforms", {}) for key in keys)
        status = reported.get(name, {})
        features.append(
            {
                "name": name,
                "title": manifest.get("title", name),
                "description": manifest.get("description", ""),
                "is_supported": is_supported,
                "is_enabled": bool(desired.get(name, {}).get("is_enabled")),
                "is_activated": bool(desired.get(name, {}).get("is_activated")),
                "is_active": bool(status.get("is_active")),
                "has_activation": manifest.get("has_activation", False),
                "is_removable": manifest.get("is_removable", True),
                "state": status.get("state", "unknown"),
                "message": status.get("message", ""),
            }
        )
    return {
        "version": AGENT_VERSION,
        "hostname": hostname(),
        "platform": agent.platform(),
        "is_connected": bool(config.get("gateway_url") and config.get("token")),
        "gateway_url": config.get("gateway_url", ""),
        "last_error": agent.last_error(),
        "features": features,
    }


PAGE_HTML = """<!doctype html>
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
  .err { color: #ff4252; font-size: 12px; }
  .muted { color: #7d8590; }
</style>
</head>
<body>
<div class="wrap">
  <div>
    <h1>Neutrino agent</h1>
    <div class="sub" id="ident"></div>
  </div>
  <div class="card" id="conn"></div>
  <div class="card" id="feats"></div>
</div>
<script>
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

async function load() {
  draw(await (await fetch('/api/state')).json());
}

// What the rows show: the machine's report, with any step just asked for
// standing in front of it, until the machine reports having got there.
function withAsked(state) {
  for (const f of state.features) {
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
  draw(await (await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  })).json());
}

function askFor(feature, step, body) {
  asked[feature] = step;
  redraw();
  send('/api/feature', body);
}

function redraw() {
  if (lastState !== null) draw(lastState);
}

let lastState = null;

function draw(rawState) {
  const state = withAsked(rawState);
  lastState = rawState;
  document.getElementById('ident').textContent =
    state.hostname + ' · ' + state.platform.os + '/' + state.platform.arch +
    ' · agent ' + state.version;

  const conn = document.getElementById('conn');
  if (state.is_connected) {
    conn.innerHTML = '';
    const row = document.createElement('div');
    row.className = 'row';
    row.innerHTML = '<span class="dot ok"></span><div style="flex:1"><div>' +
      'Connected</div><div class="sub">' + state.gateway_url + '</div></div>';
    const leave = document.createElement('button');
    leave.className = 'danger';
    leave.textContent = 'Disconnect';
    leave.onclick = () => send('/api/disconnect');
    row.appendChild(leave);
    conn.appendChild(row);
    if (state.last_error) {
      const err = document.createElement('div');
      err.className = 'err';
      err.style.marginTop = '10px';
      err.textContent = state.last_error;
      conn.appendChild(err);
    }
  } else {
    conn.innerHTML = '<div class="row" style="margin-bottom:12px">' +
      '<span class="dot off"></span><div><div>Not connected</div>' +
      '<div class="sub">Paste the link from the gateway\\'s Devices page</div></div></div>';
    const row = document.createElement('div');
    row.className = 'row';
    const input = document.createElement('input');
    input.placeholder = 'neutrino://enroll/...';
    input.onkeydown = (e) => { if (e.key === 'Enter') join(); };
    const button = document.createElement('button');
    button.textContent = 'Connect';
    button.onclick = join;
    function join() { send('/api/connect', { link: input.value }); }
    row.appendChild(input);
    row.appendChild(button);
    conn.appendChild(row);
    if (state.error || state.last_error) {
      const err = document.createElement('div');
      err.className = 'err';
      err.style.marginTop = '10px';
      err.textContent = state.error || state.last_error;
      conn.appendChild(err);
    }
  }

  const feats = document.getElementById('feats');
  feats.innerHTML = '';
  if (!state.is_connected) {
    feats.innerHTML = '<span class="muted">Modules appear once this machine ' +
      'joins a gateway.</span>';
    return;
  }
  if (state.features.length === 0) {
    feats.innerHTML = '<span class="muted">Waiting for the gateway to send ' +
      'its module list…</span>';
    return;
  }
  for (const f of state.features) {
    const row = document.createElement('div');
    row.className = 'feat';
    const here = standing(f);
    const working = BUSY.includes(f.state);
    const tone = working ? 'bad' : here.on ? 'ok'
      : f.state === 'failed' ? 'bad' : 'off';
    const note = !f.is_supported ? 'Not available for this platform'
      : describeState(f.state) +
        (f.has_activation && here.on && !working
          ? (here.aimed ? ' · pointing at the hub' : ' · not pointing here')
          : '') +
        (f.message ? ' — ' + f.message : '');
    row.innerHTML = '<span class="dot ' + tone + '"></span>' +
      '<div class="body"><div class="title">' + f.title + '</div>' +
      '<div class="note">' + f.description + '</div>' +
      '<div class="note">' + note + '</div></div>';
    if (f.has_activation && here.on) {
      const aim = document.createElement('button');
      aim.className = here.aimed ? 'danger' : 'install';
      aim.textContent = here.aimed ? 'Deactivate' : 'Activate';
      aim.disabled = !f.is_supported || working;
      aim.onclick = () => askFor(f.name,
        here.aimed ? 'deactivating' : 'activating',
        { name: f.name, is_activated: !here.aimed });
      row.appendChild(aim);
    }
    if (f.is_removable || !here.on) {
      const button = document.createElement('button');
      button.className = here.on ? 'danger' : 'install';
      button.textContent = here.on ? 'Uninstall' : 'Install';
      button.disabled = !f.is_supported || working;
      button.onclick = () => askFor(f.name,
        here.on ? 'uninstalling' : 'installing',
        { name: f.name, is_enabled: !here.on });
      row.appendChild(button);
    }
    feats.appendChild(row);
  }
}

function describeState(state) {
  if (state === 'installed') return 'installed';
  if (state === 'absent') return 'not installed';
  if (state === 'installing') return 'installing…';
  if (state === 'removing' || state === 'uninstalling') return 'uninstalling…';
  if (state === 'activating') return 'activating…';
  if (state === 'deactivating') return 'deactivating…';
  if (state === 'unsupported') return 'not available here';
  if (state === 'failed') return 'failed';
  return 'waiting for the agent';
}

load();
setInterval(() => load(), 1500);
</script>
</body>
</html>
"""
