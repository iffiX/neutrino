"""A stand-in for Ayakaleaf's app on loopback: sessions, CSRF tokens, the launchpad, the login, a password change, guests and invitations.

It keeps what the routes the hooks use change: the accounts, the sessions,
the invitations waiting for each account, and every request it was sent.
"""

import json
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ADMIN_EMAIL = "admin@ayakaleaf.neutrino"


class FakeApp(ThreadingHTTPServer):
    """The app's routes the hooks reach, on a port of its own."""

    daemon_threads = True

    def __init__(self, *, cookie_name: str):
        super().__init__(("127.0.0.1", 0), FakeAppHandler)
        self.cookie_name = cookie_name
        self.port = self.server_address[1]
        self.status_code = 200
        self.is_admin_made = False
        # Each account by e-mail: password, user_id, first_name, is_admin.
        self.accounts: dict = {}
        # Each session by id: the signed-in e-mail, empty for none, and its
        # CSRF token.
        self.sessions: dict = {}
        # Each new account's activation token, to its user_id.
        self.activations: dict = {}
        # Each account's waiting invitations, ``(project_id, token)``.
        self.invitations: dict = {}
        self.accepted: list = []
        self.requests: list = []
        self.refused_paths: set = set()
        self.lock = threading.Lock()
        self._thread = threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self.shutdown()
        self.server_close()

    def add_account(self, email: str, password: str, *, is_admin=False) -> str:
        user_id = secrets.token_hex(12)
        self.accounts[email] = {
            "password": password,
            "user_id": user_id,
            "first_name": "",
            "is_admin": is_admin,
        }
        if is_admin:
            self.is_admin_made = True
        return user_id

    def paths(self, method: str = "") -> list:
        return [
            path for verb, path, _, _ in self.requests if not method or verb == method
        ]


class FakeAppHandler(BaseHTTPRequestHandler):
    server: FakeApp

    def log_message(self, *args):
        return

    def do_GET(self):
        self._serve("GET")

    def do_POST(self):
        self._serve("POST")

    def _serve(self, method):
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else b""
        app = self.server
        path, _, query = self.path.partition("?")
        with app.lock:
            app.requests.append((method, path, dict(self.headers), body))
            if path in app.refused_paths:
                return self._answer(500, {"message": "refused"})
            session_id, session = self._session()
            fields = json.loads(body) if body else {}
            if method == "POST" and fields.get("_csrf") != session["csrf"]:
                return self._answer(403, {"message": "invalid csrf"}, session_id)
            self._route(method, path, query, fields, session_id, session)

    def _session(self):
        app = self.server
        cookies = {}
        for pair in self.headers.get("Cookie", "").split(";"):
            key, _, value = pair.strip().partition("=")
            cookies[key] = value
        session_id = cookies.get(app.cookie_name, "")
        if session_id not in app.sessions:
            session_id = secrets.token_hex(8)
            app.sessions[session_id] = {"email": "", "csrf": secrets.token_hex(8)}
        return session_id, app.sessions[session_id]

    def _route(self, method, path, query, fields, session_id, session):
        app = self.server
        user = app.accounts.get(session["email"]) if session["email"] else None
        if (method, path) == ("GET", "/status"):
            return self._answer(app.status_code, {"ok": True}, session_id)
        if (method, path) == ("GET", "/launchpad"):
            if app.is_admin_made:
                return self._answer(302, {}, session_id, location="/login")
            return self._page(session_id, session)
        if (method, path) == ("POST", "/launchpad/register_admin"):
            app.add_account(fields["email"], fields["password"], is_admin=True)
            return self._answer(200, {"redir": "/launchpad"}, session_id)
        if (method, path) == ("GET", "/login"):
            return self._page(session_id, session)
        if (method, path) == ("POST", "/login"):
            account = app.accounts.get(fields.get("email", ""))
            if account is None or account["password"] != fields.get("password"):
                return self._answer(401, {"message": "bad login"}, session_id)
            del app.sessions[session_id]
            new_id = secrets.token_hex(8)
            app.sessions[new_id] = {
                "email": fields["email"],
                "csrf": secrets.token_hex(8),
            }
            return self._answer(200, {"redir": "/project"}, new_id)
        if (method, path) == ("GET", "/project"):
            if user is None:
                return self._answer(302, {}, session_id, location="/login")
            waiting = [
                {
                    "templateKey": "notification_project_invite",
                    "messageOpts": {"projectId": project, "token": token},
                }
                for project, token in app.invitations.get(session["email"], [])
            ]
            return self._page(session_id, session, notifications=waiting)
        if (method, path) == ("POST", "/admin/register"):
            if user is None or not user["is_admin"]:
                return self._answer(403, {"message": "not an admin"}, session_id)
            user_id = app.add_account(fields["email"], secrets.token_hex(8))
            token = secrets.token_hex(16)
            app.activations[token] = user_id
            url = f"http://localhost/user/activate?token={token}&user_id={user_id}"
            return self._answer(
                200, {"email": fields["email"], "setNewPasswordUrl": url}, session_id
            )
        if (method, path) == ("GET", "/user/activate"):
            params = urllib.parse.parse_qs(query)
            if params.get("token", [""])[0] not in app.activations:
                return self._answer(404, {"message": "no such token"}, session_id)
            return self._page(session_id, session)
        if (method, path) == ("POST", "/user/password/set"):
            user_id = app.activations.pop(fields.get("passwordResetToken", ""), "")
            for account in app.accounts.values():
                if account["user_id"] == user_id:
                    account["password"] = fields["password"]
                    return self._answer(200, {"redir": "/login"}, session_id)
            return self._answer(404, {"message": "no such token"}, session_id)
        if (method, path) == ("POST", "/user/password/update"):
            if user is None:
                return self._answer(401, {"message": "no login"}, session_id)
            if fields.get("currentPassword") != user["password"]:
                return self._answer(400, {"message": "wrong password"}, session_id)
            if fields.get("newPassword1") != fields.get("newPassword2"):
                return self._answer(400, {"message": "no match"}, session_id)
            user["password"] = fields["newPassword1"]
            return self._answer(200, {"message": {"type": "success"}}, session_id)
        if (method, path) == ("POST", "/user/settings"):
            if user is None:
                return self._answer(401, {"message": "no login"}, session_id)
            user["first_name"] = fields.get("first_name", "")
            return self._answer(204, None, session_id)
        if method == "POST" and path.startswith("/admin/user/"):
            if user is None or not user["is_admin"]:
                return self._answer(403, {"message": "not an admin"}, session_id)
            user_id = path.split("/")[3]
            for email, account in list(app.accounts.items()):
                if account["user_id"] == user_id:
                    del app.accounts[email]
                    return self._answer(200, {"deletedAt": "now"}, session_id)
            return self._answer(422, {"message": "no such account"}, session_id)
        if path.startswith("/project/") and "/invite/token/" in path:
            if user is None:
                return self._answer(401, {"message": "no login"}, session_id)
            if method == "GET":
                return self._page(session_id, session)
            project = path.split("/")[2]
            token = path.split("/")[5]
            waiting = app.invitations.get(session["email"], [])
            if (project, token) in waiting:
                waiting.remove((project, token))
                app.accepted.append((session["email"], project))
            return self._answer(302, {}, session_id, location=f"/project/{project}")
        return self._answer(404, {"message": "no such route"}, session_id)

    def _page(self, session_id, session, *, notifications=None):
        held = json.dumps(notifications or []).replace('"', "&quot;")
        text = (
            f'<html><head><meta name="ol-csrfToken" content="{session["csrf"]}">'
            f'<meta name="ol-notifications" data-type="json" content="{held}">'
            "</head></html>"
        )
        self._write(200, text.encode(), "text/html", session_id)

    def _answer(self, status, document, session_id="", *, location=""):
        body = b"" if document is None else json.dumps(document).encode()
        self._write(status, body, "application/json", session_id, location=location)

    def _write(self, status, body, content_type, session_id, *, location=""):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if session_id:
            self.send_header(
                "Set-Cookie",
                f"{self.server.cookie_name}={session_id}; Path=/; HttpOnly; SameSite=Lax",
            )
        if location:
            self.send_header("Location", location)
        self.end_headers()
        self.wfile.write(body)
