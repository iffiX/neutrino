"""The hub's fetcher against sources served on loopback.

Each source is a small HTTP server in the test's own thread pool, told how to
behave: how fast it sends, whether it honours a Range request, whether it
stalls, what bytes it serves and what status it answers. The fetcher runs with
its waits scaled down so a stall or a measure takes a fraction of a second.
"""

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from neutrino_hub.exceptions import DownloadFailedError, DownloadTooLargeError
from neutrino_hub.utils.source_fetch import (
    SourceFetcher,
    SourceProbe,
    hex_of,
    rank_probes,
)

BODY = bytes(range(256)) * 2048  # 512 KiB
DIGEST = "sha256:" + hashlib.sha256(BODY).hexdigest()
CHUNK = 16 * 1024


@dataclass
class Behaviour:
    """How one source answers."""

    body: bytes = BODY
    is_range_honoured: bool = True
    chunk_delay_s: float = 0.0
    slow_requests: int = 0
    slow_delay_s: float = 0.0
    stall_after: int = -1
    answer_delay_s: float = 0.0
    status: int = 0
    ranges: list = field(default_factory=list)


class Source:
    """One HTTP server on loopback serving one behaviour."""

    def __init__(self, behaviour: Behaviour):
        self.behaviour = behaviour
        handler = type("Handler", (_Handler,), {"behaviour": behaviour})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/file.bin"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class _Handler(BaseHTTPRequestHandler):
    behaviour: Behaviour

    def log_message(self, *args):
        pass

    def do_GET(self):
        behaviour = self.behaviour
        asked = self.headers.get("Range", "")
        behaviour.ranges.append(asked)
        if behaviour.answer_delay_s:
            time.sleep(behaviour.answer_delay_s)
        if behaviour.status:
            self.send_response(behaviour.status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = behaviour.body
        start, end = 0, len(body) - 1
        if asked and behaviour.is_range_honoured:
            first, _, last = asked.removeprefix("bytes=").partition("-")
            start = int(first)
            end = min(int(last), len(body) - 1) if last else len(body) - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        is_slow = len(behaviour.ranges) <= behaviour.slow_requests
        delay = behaviour.slow_delay_s if is_slow else behaviour.chunk_delay_s
        sent = 0
        position = start
        try:
            while position <= end:
                if behaviour.stall_after >= 0 and sent >= behaviour.stall_after:
                    time.sleep(5)
                    return
                piece = body[position : min(position + CHUNK, end + 1)]
                self.wfile.write(piece)
                self.wfile.flush()
                position += len(piece)
                sent += len(piece)
                if delay:
                    time.sleep(delay)
        except (BrokenPipeError, ConnectionResetError):
            return


@pytest.fixture
def serve():
    started = []

    def start(**behaviour) -> Source:
        source = Source(Behaviour(**behaviour))
        started.append(source)
        return source

    yield start
    for source in started:
        source.close()


def fetcher(**overrides) -> SourceFetcher:
    settings = {
        "probe_bytes": 32 * 1024,
        "probe_timeout_s": 0.5,
        "measure_interval_s": 0.3,
        "speed_window_s": 0.3,
        "stall_s": 0.6,
    }
    settings.update(overrides)
    return SourceFetcher(**settings)


def fetch(tmp_path, sources, **overrides):
    lines = []
    download = fetcher(**overrides).fetch_file(
        file="file.bin",
        sources=sources,
        digest=DIGEST,
        directory=tmp_path,
        limit=10 * 1024 * 1024,
        on_line=lines.append,
    )
    return download, lines


def test_rank_puts_the_faster_source_first_and_breaks_a_near_tie_by_first_byte():
    slow = SourceProbe(source="slow", is_answered=True, speed=100.0, first_byte_s=0.1)
    fast = SourceProbe(source="fast", is_answered=True, speed=300.0, first_byte_s=0.5)
    early = SourceProbe(source="early", is_answered=True, speed=295.0, first_byte_s=0.2)
    late = SourceProbe(source="late", is_answered=False, reason="timeout")
    ranked = rank_probes([slow, fast, late, early])
    assert [probe.source for probe in ranked] == ["early", "fast", "slow"]


def test_the_download_starts_on_the_fastest_source(tmp_path, serve):
    slow = serve(chunk_delay_s=0.05)
    fast = serve()
    download, lines = fetch(tmp_path, [slow.url, fast.url])
    assert download.source == fast.url
    assert download.path.read_bytes() == BODY
    assert download.sha256 == hashlib.sha256(BODY).hexdigest()
    assert lines[0] == "hub: fetching file.bin from 127.0.0.1"
    # The fastest probe's bytes start the file; the rest comes by a Range.
    assert fast.behaviour.ranges[-1] == f"bytes={32 * 1024}-"


def test_a_source_that_does_not_answer_the_probe_in_time_has_not_failed(
    tmp_path, serve
):
    late = serve(answer_delay_s=0.55)
    download, _ = fetch(tmp_path, [late.url])
    assert download.source == late.url
    assert download.path.read_bytes() == BODY


def test_a_stall_moves_the_download_to_the_next_source_by_a_range(tmp_path, serve):
    stalling = serve(stall_after=96 * 1024)
    steady = serve(chunk_delay_s=0.02)
    download, lines = fetch(tmp_path, [stalling.url, steady.url])
    assert download.source == steady.url
    assert download.path.read_bytes() == BODY
    resumed = steady.behaviour.ranges[-1]
    assert resumed.startswith("bytes=") and resumed != "bytes=0-"
    assert int(resumed.removeprefix("bytes=").rstrip("-")) > 32 * 1024


def test_a_source_answering_a_range_with_the_whole_file_serves_from_its_start(
    tmp_path, serve
):
    whole = serve(is_range_honoured=False)
    download, _ = fetch(tmp_path, [whole.url])
    assert download.path.read_bytes() == BODY


def test_after_a_stall_a_whole_file_source_starts_the_file_again(tmp_path, serve):
    stalling = serve(stall_after=96 * 1024)
    whole = serve(is_range_honoured=False, chunk_delay_s=0.02)
    download, _ = fetch(tmp_path, [stalling.url, whole.url])
    assert download.source == whole.url
    assert download.path.read_bytes() == BODY


def test_a_digest_mismatch_drops_its_source_and_fetches_again(tmp_path, serve):
    wrong = serve(body=b"x" * len(BODY))
    right = serve(chunk_delay_s=0.01)
    download, _ = fetch(tmp_path, [wrong.url, right.url])
    assert download.source == right.url
    assert download.path.read_bytes() == BODY


def test_every_source_failing_names_each_source_and_its_reason(tmp_path, serve):
    missing = serve(status=404)
    wrong = serve(body=b"y" * len(BODY))
    closed = serve()
    closed_url = closed.url
    closed.close()
    with pytest.raises(DownloadFailedError) as raised:
        fetch(tmp_path, [missing.url, wrong.url, closed_url])
    assert raised.value.code == "download_failed"
    reasons = {
        item["source"]: item["reason"] for item in raised.value.params["sources"]
    }
    assert raised.value.params["file"] == "file.bin"
    assert reasons == {
        missing.url: "http_404",
        wrong.url: "digest_mismatch",
        closed_url: "unreachable",
    }
    assert list(tmp_path.iterdir()) == []


def test_a_measure_moves_to_a_source_one_and_a_half_times_as_fast(tmp_path, serve):
    # Ahead in the probe, then steady at about 160 KiB/s.
    first = serve(chunk_delay_s=0.1)
    # Slow for its probe, then several times faster.
    second = serve(slow_requests=1, slow_delay_s=0.3, chunk_delay_s=0.005)
    download, lines = fetch(tmp_path, [first.url, second.url])
    assert download.source == second.url
    assert download.path.read_bytes() == BODY
    starts = [
        int(asked.removeprefix("bytes=").partition("-")[0])
        for asked in second.behaviour.ranges
    ]
    # The probe at 0, a measure and the move at the current offset.
    assert starts[0] == 0 and max(starts) > 32 * 1024
    assert len([line for line in lines if line.endswith("127.0.0.1")]) >= 2


def test_a_size_past_the_limit_is_refused(tmp_path, serve):
    source = serve()
    with pytest.raises(DownloadTooLargeError):
        fetcher().fetch_file(
            file="file.bin",
            sources=[source.url],
            digest=DIGEST,
            directory=tmp_path,
            limit=1024,
        )


def test_a_digest_of_another_form_is_refused(tmp_path):
    with pytest.raises(ValueError):
        hex_of("md5:abc")
    with pytest.raises(ValueError):
        fetcher().fetch_file(
            file="file.bin",
            sources=["http://127.0.0.1:9/"],
            digest="abc",
            directory=tmp_path,
            limit=1024,
        )


def test_a_document_is_the_first_valid_answer(serve):
    invalid = serve(body=b"not json")
    valid = serve(body=json.dumps({"tag": "v1.2.3"}).encode(), chunk_delay_s=0.05)
    document, source = fetcher().fetch_document(
        file="latest.json",
        sources=[invalid.url, valid.url],
        parse=lambda body: json.loads(body)["tag"],
    )
    assert (document, source) == ("v1.2.3", valid.url)


def test_a_document_no_source_serves_names_each_source(serve):
    invalid = serve(body=b"not json")
    missing = serve(status=503)
    with pytest.raises(DownloadFailedError) as raised:
        fetcher().fetch_document(
            file="latest.json",
            sources=[invalid.url, missing.url],
            parse=json.loads,
        )
    assert [item["reason"] for item in raised.value.params["sources"]] == [
        "digest_mismatch",
        "http_503",
    ]


class _Answer:
    """A response the fake opener hands back."""

    def __init__(self, body: bytes):
        self._body = body
        self.status = 200
        self.headers = {}

    def read(self, limit=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_a_document_is_asked_with_the_headers_given():
    asked: list = []

    def opener(request, timeout):
        asked.append(dict(request.header_items()))
        return _Answer(b'{"tags": []}')

    document, _ = SourceFetcher(opener=opener).fetch_document(
        file="tags",
        sources=["https://registry.example/v2/a/b/tags/list"],
        parse=json.loads,
        headers={"Authorization": "Bearer t", "Accept": "application/json"},
    )

    assert document == {"tags": []}
    (headers,) = asked
    assert headers["Authorization"] == "Bearer t"
    assert headers["Accept"] == "application/json"


def test_a_bearer_challenge_is_read_from_a_401_alone():
    import email.message
    import urllib.error

    def challenged(request, timeout):
        said = email.message.Message()
        said["WWW-Authenticate"] = 'Bearer realm="https://r.example/token"'
        raise urllib.error.HTTPError(request.full_url, 401, "no", said, None)

    def open_door(request, timeout):
        return _Answer(b"{}")

    def refusing(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "no", None, None)

    url = "https://r.example/v2/"
    assert SourceFetcher(opener=challenged).bearer_challenge(url) == (
        'Bearer realm="https://r.example/token"'
    )
    assert SourceFetcher(opener=open_door).bearer_challenge(url) == ""
    assert SourceFetcher(opener=refusing).bearer_challenge(url) == ""
