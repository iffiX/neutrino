"""The build scripts on the import path, the way they put each other there,
and stand-in release sites for the install scripts.

``hub/packaging`` is scripts rather than a package — importing it as one would
shadow the ``packaging`` distribution the tooling itself uses — so the
directory goes on the path and its modules are imported by their own names.
The repository's own ``packaging`` and its ``build`` directory go there too,
the shared modules imported as ``shared.<module>`` and the target scripts by
their own names.
"""

import re
import select
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PACKAGING_DIR = Path(__file__).resolve().parent.parent.parent / "packaging"
SHARED_PACKAGING_DIR = PACKAGING_DIR.parent.parent / "packaging"
BUILD_SCRIPTS_DIR = SHARED_PACKAGING_DIR / "build"

for directory in (SHARED_PACKAGING_DIR, BUILD_SCRIPTS_DIR, PACKAGING_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

# What a stand-in site writes at a time, and how long at most it holds a
# request it hangs or a download it stalls; the hold ends when the client
# hangs up. curl reads a stall from its speed over the last five seconds, so
# the hold outlasts that.
SITE_CHUNK_BYTES = 64 * 1024
SITE_HOLD_S = 15
SITE_FILE_PATH = re.compile(r"^/download/([^/]+)/([^/]+)$")
SITE_RANGE = re.compile(r"^bytes=(\d+)-(\d*)$")


class ReleaseSite:
    """One stand-in release site on 127.0.0.1: a tag's files under
    ``/download/<tag>/``, read from one directory whatever the tag, and
    ``latest.json`` at ``/latest.json``, read from the same directory.

    Every request is recorded as ``(path, range)``. What the site does
    otherwise is set on it: ``is_missing`` answers 404 for every file,
    ``is_wrong`` serves other bytes of the same length for every file but
    ``SHA256SUMS``, ``is_hanging`` answers nothing,
    ``is_rangeless`` ignores a Range request, ``chunk_delay_s`` sleeps after
    each chunk, ``latest_text`` is served as ``latest.json`` after
    ``latest_delay_s``, and ``stall_at`` holds a download from the start
    once that many bytes are out.
    """

    def __init__(self, served: Path):
        self.served = served
        self.requests = []
        self.is_missing = False
        self.is_wrong = False
        self.is_hanging = False
        self.is_rangeless = False
        self.chunk_delay_s = 0.0
        self.latest_text = None
        self.latest_delay_s = 0.0
        self.stall_at = None
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _ReleaseSiteHandler)
        self._server.daemon_threads = True
        self._server.site = self
        threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        ).start()

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self._server.server_address[1]}"

    @property
    def files(self) -> str:
        return f"http://{self.host}/download/{{tag}}/"

    @property
    def latest(self) -> str:
        return f"http://{self.host}/latest.json"

    def downloads(self, name: str) -> list:
        """The ranges this site was asked for one file with, probes aside."""
        return [
            asked
            for path, asked in self.requests
            if path.endswith("/" + name) and not asked.startswith("bytes=0-1048575")
        ]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


class _ReleaseSiteHandler(BaseHTTPRequestHandler):
    def log_message(self, *_arguments):
        pass

    def do_GET(self):
        site = self.server.site
        asked = self.headers.get("Range", "")
        site.requests.append((self.path, asked))
        try:
            self._answer(site, asked)
        except (ConnectionError, OSError):
            pass

    def _hold(self):
        """Send nothing until the client hangs up or ``SITE_HOLD_S`` ends."""
        select.select([self.connection], [], [], SITE_HOLD_S)

    def _answer(self, site, asked):
        if site.is_hanging:
            self._hold()
            return
        if self.path == "/latest.json":
            time.sleep(site.latest_delay_s)
            if site.latest_text is not None:
                self._send_bytes(site.latest_text.encode())
            elif (site.served / "latest.json").is_file():
                self._send_bytes((site.served / "latest.json").read_bytes())
            else:
                self.send_error(404)
            return
        found = SITE_FILE_PATH.match(self.path)
        path = site.served / found.group(2) if found else None
        if site.is_missing or path is None or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        if site.is_wrong and path.name != "SHA256SUMS":
            data = bytes(byte ^ 0xFF for byte in data)
        start, end = 0, len(data) - 1
        ranged = SITE_RANGE.match(asked) if asked and not site.is_rangeless else None
        if ranged:
            start = int(ranged.group(1))
            if ranged.group(2):
                end = min(end, int(ranged.group(2)))
            if start > end:
                self.send_error(416)
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        sent = start
        while sent <= end:
            chunk = data[sent : min(sent + SITE_CHUNK_BYTES, end + 1)]
            self.wfile.write(chunk)
            self.wfile.flush()
            sent += len(chunk)
            if site.stall_at is not None and not asked and sent >= site.stall_at:
                self._hold()
                return
            time.sleep(site.chunk_delay_s)

    def _send_bytes(self, data: bytes):
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def release_sites(tmp_path):
    """A factory of stand-in release sites serving one directory, and the
    address of a site nothing listens on."""
    served = tmp_path / "release"
    served.mkdir(exist_ok=True)
    opened = []

    def open_site() -> ReleaseSite:
        site = ReleaseSite(served)
        opened.append(site)
        return site

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
    open_site.served = served
    open_site.dead = (
        f"http://127.0.0.1:{dead_port}/download/{{tag}}/",
        f"http://127.0.0.1:{dead_port}/latest.json",
    )
    open_site.dead_host = f"127.0.0.1:{dead_port}"
    yield open_site
    for site in opened:
        site.close()
