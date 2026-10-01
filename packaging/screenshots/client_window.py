"""The desktop client's window page, served over HTTP from a state file.

The window page reaches its resident through a bridge the shell injects. Here
a small HTTP server stands in for both: it serves the page the client builds,
with a bridge that posts each request to this server, and it answers the
page's requests from a state file instead of a running resident. Only what the
page draws from is answered; any other request returns the state unchanged.
"""

import json
import pathlib
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPOSITORY = pathlib.Path(__file__).resolve().parents[2]
CLIENT_SOURCE = REPOSITORY / "client" / "desktop"

# The bridge the shell would inject: each request is posted to /bridge and
# its answer is handed back the way pywebview hands it.
BRIDGE_SCRIPT = """<script>
window.pywebview = {
  api: {
    request: (request) =>
      fetch('/bridge', { method: 'POST', body: JSON.stringify(request) })
        .then((response) => response.json())
        .then((body) => ({ body: body })),
  },
};
</script>"""


class ClientWindowServer:
    """Serves the window page and answers its requests from one state."""

    def __init__(self, *, state_path: pathlib.Path, language: str):
        """
        Args:
            state_path: The state file, shaped as the resident's
                ``/api/state`` answer.
            language: The window's language, ``en`` or ``zh-CN``.
        """
        self.state = json.loads(state_path.read_text())
        self.state["language"] = language
        self._server = None
        self._thread = None

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
        if route == "/api/language":
            self.state["language"] = str(body.get("language", self.state["language"]))
        if route == "/api/theme":
            self.state["theme"] = str(body.get("theme", self.state["theme"]))
        return self.state
