"""The desktop client's window page, served over HTTP from a state file.

The window page reaches its resident through a bridge the shell injects. Here
a small HTTP server stands in for both: it serves the page the client builds,
with a bridge that posts each request to this server, and it answers the
page's requests from a state file instead of a running resident. Only what the
page draws from is answered; any other request returns the state unchanged. A
terminal open is answered with an id and the prompt of a root shell on that
machine, which the bridge pushes to the page as the shell's output, and a
persist sets the session's two flags as the hub would confirm them and is
pushed as the next state. Each load of the page starts again from the file,
with the variant a shot names laid over it.
"""

import base64
import json
import pathlib
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPOSITORY = pathlib.Path(__file__).resolve().parents[2]
CLIENT_SOURCE = REPOSITORY / "client" / "desktop"

# The bridge the shell would inject: each request is posted to /bridge and
# its answer is handed back the way pywebview hands it. An answer carrying
# ``terminal_output`` is followed by that output, pushed the way the resident
# pushes a shell's; a persist's answer, the state with the flags set, is
# pushed the way the resident pushes a state.
BRIDGE_SCRIPT = """<script>
window.pywebview = {
  api: {
    request: (request) =>
      fetch('/bridge', { method: 'POST', body: JSON.stringify(request) })
        .then((response) => response.json())
        .then((body) => {
          if (body.terminal_output) {
            setTimeout(() => window.neutrinoState(
              { terminal: { id: body.terminal_id, data: body.terminal_output } }), 0);
          } else if (request.path === '/api/terminal/persist' && !body.code) {
            setTimeout(() => window.neutrinoState(body), 0);
          }
          return { body: body };
        }),
  },
};
</script>"""
# What a terminal opened on a machine shows first: the prompt of a root shell.
TERMINAL_PROMPT = "root@{name}:~# "
# The state file's key holding the variants, each a map of dotted paths to the
# values a shot sets over the file's state; the key is not served.
VARIANTS_KEY = "_variants"


class ClientWindowServer:
    """Serves the window page and answers its requests from one state."""

    def __init__(self, *, state_path: pathlib.Path, language: str):
        """
        Args:
            state_path: The state file, shaped as the resident's
                ``/api/state`` answer.
            language: The window's language, ``en`` or ``zh-CN``.
        """
        self._state_path = state_path
        self._language = language
        # The variant laid over the file's state at the next load, or empty.
        self.variant = ""
        self.state = {}
        # The session each open terminal attached, by terminal id.
        self._sessions = {}
        self.reset()
        self._server = None
        self._thread = None

    def reset(self) -> None:
        """Put the state back to the file's and its variant, for a fresh page.

        Raises:
            OSError: When the state file cannot be read.
            json.JSONDecodeError: When it is not JSON.
            KeyError: When the variant or a path in it is not in the file.
        """
        self.state = json.loads(self._state_path.read_text())
        variants = self.state.pop(VARIANTS_KEY, {})
        for path, value in (variants[self.variant] if self.variant else {}).items():
            *parents, last = path.split(".")
            target = self.state
            for part in parents:
                target = target[int(part)] if isinstance(target, list) else target[part]
            if isinstance(target, list):
                target[int(last)] = value
            else:
                target[last] = value
        self.state["language"] = self._language
        self._sessions = {}

    @property
    def url(self) -> str:
        """Where the page is served, without a trailing slash."""
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        """Serve on a free loopback port in a background thread.

        Raises:
            ImportError: When the client package cannot be imported.
        """
        if str(CLIENT_SOURCE) not in sys.path:
            sys.path.insert(0, str(CLIENT_SOURCE))
        from neutrino_client.control import page

        document = page.control_page_html().replace(
            "<head>", "<head>\n" + BRIDGE_SCRIPT, 1
        )
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path.partition("?")[0] == "/":
                    owner.reset()
                self._send(200, "text/html; charset=utf-8", document.encode())

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length) or b"{}")
                body = owner.answer(request, page)
                self._send(200, "application/json", json.dumps(body).encode())

            def log_message(self, *args) -> None:
                return

            def _send(self, status: int, kind: str, data: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop serving."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def answer(self, request: dict, page) -> dict:
        """The body one bridged request gets.

        Args:
            request: ``{id, method, path, body}`` as the page posts it.
            page: The client's page module, for the terminal's font.

        Returns:
            The answer's body.
        """
        route, _, query = str(request.get("path", "")).partition("?")
        body = request.get("body") or {}
        if route == "/api/font":
            values = urllib.parse.parse_qs(query)
            try:
                return page.terminal_font_piece(
                    (values.get("name") or [""])[0],
                    int((values.get("offset") or ["0"])[0]),
                )
            except (KeyError, ValueError, OSError):
                return {"code": "unknown_request", "params": {}}
        if route == "/api/terminal/open":
            return self._terminal_open(body)
        if route == "/api/terminal/persist":
            self._persist_terminal(body)
        if route == "/api/language":
            self.state["language"] = str(body.get("language", self.state["language"]))
        if route == "/api/theme":
            self.state["theme"] = str(body.get("theme", self.state["theme"]))
        return self.state

    def _terminal_open(self, body: dict) -> dict:
        """The answer a terminal open gets.

        Args:
            body: ``{hub_id, device_id, session_id, cols, rows}`` as the page
                posts it.

        Returns:
            ``{terminal_id, session_id, terminal_output}``: the output is the
            prompt of a root shell on the machine, as base64.
        """
        device_id = str(body.get("device_id", "") or "")
        machines = (self.state.get("terminals") or {}).get("machines") or []
        name = next(
            (
                str(machine.get("name", ""))
                for machine in machines
                if machine.get("device_id") == device_id
            ),
            device_id,
        )
        prompt = TERMINAL_PROMPT.format(name=name)
        terminal_id = "t_" + device_id
        session_id = str(body.get("session_id", "") or "") or "s_" + device_id
        self._sessions[terminal_id] = session_id
        return {
            "terminal_id": terminal_id,
            "session_id": session_id,
            "terminal_output": base64.b64encode(prompt.encode("utf-8")).decode("ascii"),
        }

    def _persist_terminal(self, body: dict) -> None:
        """Set the two flags of an open terminal's session.

        Args:
            body: ``{terminal_id, is_persistent, is_shared}`` as the page
                posts it.
        """
        session_id = self._sessions.get(str(body.get("terminal_id", "") or ""))
        for session in (self.state.get("terminals") or {}).get("sessions") or []:
            if session.get("session_id") == session_id:
                session["is_persistent"] = body.get("is_persistent") is True
                session["is_shared"] = body.get("is_shared") is True
