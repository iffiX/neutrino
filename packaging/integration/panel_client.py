"""A signed-in caller for the panel's API.

The tests beside this drive a live box the way a person drives the panel, so
what they need is a session and a way to say "this call, this status". Nothing
here knows what any page means.
"""

import json
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

# How long a call that reconfigures the machine gets before it has failed.
# Applying a mode rewrites the firewall and restarts dnsmasq; it is not fast.
PANEL_TIMEOUT_S = 90


class PanelClient:
    """One browser's worth of session against one panel."""

    def __init__(self, *, base_url: str, timeout_s: int = PANEL_TIMEOUT_S):
        """
        Args:
            base_url: Where the panel answers, without a trailing slash.
            timeout_s: Seconds one call may take.
        """
        self.base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def sign_in(self, password: str) -> None:
        """Open a session.

        Args:
            password: The panel password.

        Raises:
            RuntimeError: If the panel refused, or could not be reached.
        """
        status, answer = self.call("POST", "/auth/login", {"password": password})
        if status != 200 or not isinstance(answer, dict):
            raise RuntimeError(f"could not sign in to {self.base_url}: {answer}")
        if not answer.get("is_authenticated"):
            raise RuntimeError(f"{self.base_url} refused the password")

    def call(self, method: str, path: str, body=None) -> tuple:
        """One API call.

        Args:
            method: HTTP method.
            path: Path under ``/api``.
            body: Object to send as JSON, or None.

        Returns:
            The status code and the decoded answer, which is the error detail
            for a failure and None for an empty body. A socket that never
            answered is status 0 and the reason as text: a dead panel is a
            result these tests report rather than an error they raise.
        """
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            f"{self.base_url}/api{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self._timeout_s) as answer:
                text = answer.read().decode()
                return answer.status, (json.loads(text) if text else None)
        except urllib.error.HTTPError as error:
            text = error.read().decode()
            try:
                return error.code, json.loads(text)
            except ValueError:
                return error.code, text
        except Exception as error:  # noqa: BLE001 - a dead socket is a result
            return 0, str(error)

    def status(self, method: str, path: str, body=None) -> int:
        """The status code of one call.

        Args:
            method: HTTP method.
            path: Path under ``/api``.
            body: Object to send as JSON, or None.

        Returns:
            The status code alone.
        """
        return self.call(method, path, body)[0]

    def read(self, path: str) -> dict:
        """Read one page's payload.

        Args:
            path: Path under ``/api``.

        Returns:
            The decoded object.

        Raises:
            AssertionError: If the panel did not answer 200 with an object.
        """
        status, answer = self.call("GET", path, None)
        assert status == 200, f"GET {path} answered {status}: {answer}"
        assert isinstance(answer, dict), f"GET {path} answered {answer!r}"
        return answer

    def download(self, method: str, path: str, body=None) -> tuple:
        """One call whose answer is bytes, not JSON — a backup, a file.

        Args:
            method: HTTP method.
            path: Path under ``/api``.
            body: Object to send as JSON, or None.

        Returns:
            The status code and the raw body. A socket that never answered is
            status 0 and empty bytes.
        """
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            f"{self.base_url}/api{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self._timeout_s) as answer:
                return answer.status, answer.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
        except Exception:  # noqa: BLE001 - a dead socket is a result
            return 0, b""

    def upload(self, path: str, *, filename: str, content: bytes, fields=None) -> tuple:
        """One multipart POST carrying a file, the way the restore form does.

        Args:
            path: Path under ``/api``.
            filename: The name the file part carries.
            content: The file's bytes.
            fields: Extra plain form fields, as a dict.

        Returns:
            The status code and the decoded answer, as :meth:`call` shapes it.
        """
        boundary = "panelclientboundary7f3a"
        parts = []
        for name, value in (fields or {}).items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                f"\r\n\r\n{value}\r\n".encode()
            )
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{filename}"\r\nContent-Type: application/gzip\r\n\r\n'.encode()
            + content
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        request = urllib.request.Request(
            f"{self.base_url}/api{path}",
            data=body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with self._opener.open(request, timeout=self._timeout_s) as answer:
                text = answer.read().decode()
                return answer.status, (json.loads(text) if text else None)
        except urllib.error.HTTPError as error:
            text = error.read().decode()
            try:
                return error.code, json.loads(text)
            except ValueError:
                return error.code, text
        except Exception as error:  # noqa: BLE001 - a dead socket is a result
            return 0, str(error)
