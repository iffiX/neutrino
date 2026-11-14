"""A stand-in for Ollama's API on loopback, for the tests that call it."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOllama:
    """Ollama's API over real HTTP: tags, ps, delete, generate and a streamed pull.

    Attributes:
        models: The pulled models, as ``/api/tags`` lists them.
        loaded: The models in memory, as ``/api/ps`` lists them.
        requests: Each request taken, ``(method, path, body)``.
        pull_lines: The lines a pull streams, by name; a name missing here
            streams an error line.
        gate: Set to let a pull stream past its first line.
    """

    def __init__(self):
        self.models = []
        self.loaded = []
        self.requests = []
        self.pull_lines = {}
        self.gate = threading.Event()
        self.gate.set()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _body(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                return json.loads(raw) if raw else {}

            def _answer(self, status, document):
                data = json.dumps(document).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                fake.requests.append(("GET", self.path, {}))
                if self.path == "/api/tags":
                    self._answer(200, {"models": fake.models})
                elif self.path == "/api/ps":
                    self._answer(200, {"models": fake.loaded})
                else:
                    self._answer(404, {"error": "not found"})

            def do_DELETE(self):
                body = self._body()
                fake.requests.append(("DELETE", self.path, body))
                names = [model["name"] for model in fake.models]
                if body.get("model") not in names:
                    self._answer(
                        404, {"error": f"model '{body.get('model')}' not found"}
                    )
                    return
                fake.models = [
                    model for model in fake.models if model["name"] != body["model"]
                ]
                self._answer(200, {})

            def do_POST(self):
                body = self._body()
                fake.requests.append(("POST", self.path, body))
                if self.path == "/api/generate":
                    fake.loaded = [
                        model for model in fake.loaded if model["name"] != body["model"]
                    ]
                    self._answer(200, {"done": True, "done_reason": "unload"})
                    return
                if self.path != "/api/pull":
                    self._answer(404, {"error": "not found"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                lines = fake.pull_lines.get(body.get("model"))
                if lines is None:
                    lines = [{"error": "pull model manifest: file does not exist"}]
                for index, line in enumerate(lines):
                    if index == 1:
                        fake.gate.wait(10)
                    try:
                        self.wfile.write(json.dumps(line).encode("utf-8") + b"\n")
                        self.wfile.flush()
                    except OSError:
                        return
                if lines and lines[-1].get("status") == "success":
                    fake.models.append(
                        {
                            "name": body["model"],
                            "size": 397821319,
                            "modified_at": "2026-11-14T08:00:00Z",
                            "details": {
                                "parameter_size": "494.03M",
                                "quantization_level": "Q4_K_M",
                            },
                        }
                    )

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.address = f"127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self):
        """Serve until :meth:`stop`."""
        self._thread.start()
        return self

    def stop(self):
        """Stop serving."""
        self.gate.set()
        self._server.shutdown()
        self._server.server_close()
