"""A stand-in for AstrBot on loopback: its page, its login, its providers, one provider read and written back, its sources, a source's providers and its deletion, and its default profile.

It keeps what the routes the hooks use change: the providers, the sources,
the default profile, and every request it was sent. Deleting a source
deletes every provider on it, as AstrBot 4.29.4 does.
"""

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USERNAME = "astrbot"


class FakeAstrbot(ThreadingHTTPServer):
    """AstrBot's routes the hooks and the forwarder reach, on a port of its own."""

    daemon_threads = True

    def __init__(self, *, password: str):
        super().__init__(("127.0.0.1", 0), FakeAstrbotHandler)
        self.port = self.server_address[1]
        self.password = password
        self.page_status = 200
        self.tokens = 0
        self.providers: list = []
        self.sources: list = []
        self.profile: dict = {"agent_runner": {"runner_type": "local"}}
        # ``(method, path)`` pairs answered with an error.
        self.failing: set = set()
        self.requests: list = []
        self.lock = threading.Lock()
        threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()

    def stop(self) -> None:
        self.shutdown()
        self.server_close()

    def paths(self, method: str = "") -> list:
        return [
            path for verb, path, _, _ in self.requests if not method or verb == method
        ]

    def provider_ids(self) -> list:
        return [provider["id"] for provider in self.providers]

    def source_ids(self) -> list:
        return [source["id"] for source in self.sources]

    def default_provider(self) -> str:
        runner = self.profile.get("agent_runner") or {}
        return ((runner.get("config") or {}).get("model") or {}).get("provider_id", "")


class FakeAstrbotHandler(BaseHTTPRequestHandler):
    server: FakeAstrbot

    def log_message(self, *args):
        return

    def do_GET(self):
        self._serve("GET")

    def do_POST(self):
        self._serve("POST")

    def do_PUT(self):
        self._serve("PUT")

    def do_DELETE(self):
        self._serve("DELETE")

    def _serve(self, method):
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else b""
        path = urllib.parse.urlsplit(self.path).path
        headers = {name.lower(): value for name, value in self.headers.items()}
        with self.server.lock:
            self.server.requests.append((method, path, headers, body))
        if (method, path) in self.server.failing:
            self._answer(200, {"status": "error", "message": "refused here"})
            return
        if path == "/" and method == "GET":
            self._answer(self.server.page_status, {})
            return
        if path == "/api/auth/login" and method == "POST":
            self._login(headers, body)
            return
        if path.startswith("/api/v1/") and not self._is_signed_in(headers):
            self._answer(401, {"status": "error"})
            return
        self._route(method, path, body)

    def _login(self, headers: dict, body: bytes) -> None:
        sent = json.loads(body or b"{}")
        is_good = "origin" not in headers and sent == {
            "username": USERNAME,
            "password": self.server.password,
        }
        if not is_good:
            self._answer(200, {"status": "error", "message": "bad login"})
            return
        with self.server.lock:
            self.server.tokens += 1
            token = f"jwt-{self.server.tokens}"
        self._answer(
            200, {"status": "ok", "data": {"token": token, "username": USERNAME}}
        )

    def _is_signed_in(self, headers: dict) -> bool:
        return headers.get("authorization", "").startswith("Bearer jwt-")

    def _route(self, method: str, path: str, body: bytes) -> None:
        server = self.server
        sent = json.loads(body) if body else {}
        if path == "/api/v1/providers" and method == "GET":
            self._ok({"providers": list(server.providers)})
        elif path == "/api/v1/provider-sources" and method == "GET":
            self._ok({"provider_sources": list(server.sources)})
        elif path == "/api/v1/provider-sources" and method == "POST":
            source = sent["config"]
            server.sources = [
                held for held in server.sources if held["id"] != source["id"]
            ] + [source]
            self._ok({})
        elif path == "/api/v1/provider-sources/neutrino_gateway/providers":
            if method == "GET":
                on_source = [
                    provider
                    for provider in server.providers
                    if provider.get("provider_source_id") == "neutrino_gateway"
                ]
                self._ok({"providers": on_source, "model_metadata": {}})
                return
            server.providers.append(dict(sent["config"]))
            self._ok({})
        elif path.startswith("/api/v1/provider-sources/") and method == "DELETE":
            gone = urllib.parse.unquote(path[len("/api/v1/provider-sources/") :])
            if gone not in self.server.source_ids():
                self._answer(200, {"status": "error", "message": "not found"})
                return
            server.sources = [held for held in server.sources if held["id"] != gone]
            server.providers = [
                held
                for held in server.providers
                if held.get("provider_source_id") != gone
            ]
            self._ok({})
        elif path == "/api/v1/config-profiles/default" and method == "GET":
            self._ok({"config": server.profile, "metadata": {}})
        elif path == "/api/v1/config-profiles/default" and method == "PUT":
            server.profile = sent
            self._ok({})
        elif path.startswith("/api/v1/providers/") and method == "DELETE":
            gone = urllib.parse.unquote(path[len("/api/v1/providers/") :])
            server.providers = [held for held in server.providers if held["id"] != gone]
            self._ok({})
        elif path.startswith("/api/v1/providers/") and method == "GET":
            asked = urllib.parse.unquote(path[len("/api/v1/providers/") :])
            held = [
                provider for provider in server.providers if provider["id"] == asked
            ]
            if not held:
                self._answer(200, {"status": "error", "message": "no such provider"})
                return
            self._ok({"provider": dict(held[0]), "model_metadata": {}})
        elif path.startswith("/api/v1/providers/") and method == "PUT":
            asked = urllib.parse.unquote(path[len("/api/v1/providers/") :])
            server.providers = [
                dict(sent["config"]) if provider["id"] == asked else provider
                for provider in server.providers
            ]
            self._ok({})
        else:
            self._answer(200, {"status": "ok", "data": {"path": path}})

    def _ok(self, data) -> None:
        self._answer(200, {"status": "ok", "data": data})

    def _answer(self, status: int, document: dict) -> None:
        payload = json.dumps(document).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
