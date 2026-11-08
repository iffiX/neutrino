"""A build's downloads against a stand-in server: a 5xx, a 429 or a dropped
connection asked again after each wait, a 404 and a digest mismatch failing at
once, and every fetch function of the build taking the retries.
"""

import hashlib
import io
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import build_core_rustdesk
from shared import cc_switch_assets, download, hub_assets, rustdesk_assets
from shared.constants import PACKAGING_DOWNLOAD_RETRY_WAITS_S

BODY = b"the pinned bytes"
DIGEST = hashlib.sha256(BODY).hexdigest()


class _Site:
    """A server answering each request with the next of ``answers``: a status,
    or ``"drop"`` to close the connection without one."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = 0
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                site.requests += 1
                answer = site.answers.pop(0) if site.answers else 200
                if answer == "drop":
                    self.close_connection = True
                    self.connection.close()
                    return
                self.send_response(answer)
                self.send_header("Content-Length", str(len(BODY)))
                self.end_headers()
                self.wfile.write(BODY)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/files/a.tar.gz"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def site():
    opened = []

    def open_site(*answers):
        opened.append(_Site(answers))
        return opened[-1]

    yield open_site
    for each in opened:
        each.close()


@pytest.fixture
def waits(monkeypatch):
    slept = []
    monkeypatch.setattr(download.time, "sleep", slept.append)
    return slept


def test_a_504_then_an_answer_downloads_the_file(site, waits, capsys):
    served = site(504, 200)

    assert download.read_url(served.url, timeout=5, what="a.tar.gz") == BODY
    assert served.requests == 2
    assert waits == [PACKAGING_DOWNLOAD_RETRY_WAITS_S[0]]
    assert "a.tar.gz: HTTP 504, trying again in 5 s" in capsys.readouterr().out


def test_a_429_and_a_dropped_connection_are_asked_again(site, waits):
    served = site(429, "drop", 200)

    assert download.read_url(served.url, timeout=5, what="a.tar.gz") == BODY
    assert served.requests == 3
    assert waits == list(PACKAGING_DOWNLOAD_RETRY_WAITS_S[:2])


def test_a_504_every_time_fails_after_the_last_wait(site, waits):
    served = site(*[504] * (len(PACKAGING_DOWNLOAD_RETRY_WAITS_S) + 1))

    with pytest.raises(urllib.error.HTTPError) as refused:
        download.read_url(served.url, timeout=5, what="a.tar.gz")

    assert refused.value.code == 504
    assert served.requests == len(PACKAGING_DOWNLOAD_RETRY_WAITS_S) + 1
    assert waits == list(PACKAGING_DOWNLOAD_RETRY_WAITS_S)
    assert sum(waits) <= 660


def test_a_404_fails_at_once(site, waits):
    served = site(404)

    with pytest.raises(urllib.error.HTTPError) as refused:
        download.read_url(served.url, timeout=5, what="a.tar.gz")

    assert refused.value.code == 404
    assert served.requests == 1
    assert waits == []


def test_a_saved_file_is_written_from_its_start_after_a_504(site, waits, tmp_path):
    served = site(504, 200)
    target = tmp_path / "a.tar.gz"

    download.save_url(served.url, target, timeout=5, what="a.tar.gz")

    assert target.read_bytes() == BODY
    assert served.requests == 2


def _fake_urlopen(monkeypatch, answers, body=BODY):
    """``urlopen`` answering each call with the next status of ``answers``."""
    calls = []

    def urlopen(url, timeout=None):
        calls.append(url)
        status = answers.pop(0) if answers else 200
        if status != 200:
            raise urllib.error.HTTPError(url, status, "Gateway Time-out", {}, None)
        return io.BytesIO(body)

    monkeypatch.setattr(download.urllib.request, "urlopen", urlopen)
    return calls


def _rustdesk_mobile_fetch(url, digest):
    return build_core_rustdesk.fetch(url, digest, "a.tar.gz").read_bytes()


FETCHES = {
    "hub_assets.fetch": lambda url, digest: hub_assets.fetch(url, digest, "a"),
    "rustdesk_assets._fetch": rustdesk_assets._fetch,
    "cc_switch_assets._fetch": cc_switch_assets._fetch,
    "build_core_rustdesk.fetch": _rustdesk_mobile_fetch,
}


@pytest.fixture
def mobile_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(build_core_rustdesk, "RUSTDESK_MOBILE_CACHE", tmp_path)


@pytest.mark.parametrize("name", FETCHES)
def test_every_fetch_downloads_after_a_504(name, monkeypatch, waits, mobile_cache):
    calls = _fake_urlopen(monkeypatch, [504])

    assert FETCHES[name]("https://example.invalid/a.tar.gz", DIGEST) == BODY
    assert len(calls) == 2


@pytest.mark.parametrize("name", FETCHES)
def test_every_fetch_fails_at_once_on_a_404(name, monkeypatch, waits, mobile_cache):
    calls = _fake_urlopen(monkeypatch, [404])

    with pytest.raises(urllib.error.HTTPError):
        FETCHES[name]("https://example.invalid/a.tar.gz", DIGEST)
    assert len(calls) == 1


@pytest.mark.parametrize("name", FETCHES)
def test_every_fetch_fails_at_once_on_another_digest(
    name, monkeypatch, waits, mobile_cache
):
    calls = _fake_urlopen(monkeypatch, [], body=b"something else")

    with pytest.raises(SystemExit):
        FETCHES[name]("https://example.invalid/a.tar.gz", DIGEST)
    assert len(calls) == 1
    assert waits == []
