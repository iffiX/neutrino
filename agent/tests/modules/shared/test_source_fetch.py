"""The agent's source chooser, against fake registries and hosts on loopback.

What these pin: a probe reads a source's answer and times it from its first
byte to its last, names an HTTP error ``http_<status>``, a refused
connection ``unreachable`` and a source that does not answer in time
``timeout``, and takes any HTTP answer from a host; the ranking puts the
fastest first and gives two speeds within a tenth of each other to the
earlier first byte; a registry is ranked only while it names the pinned
integrity, the others listed with their reason; the hosts of an npm setting
are ranked fastest first with those that did not answer after them; and
nothing is remembered between two rankings.
"""

import http.server
import json
import socket
import threading
import time

import pytest

from neutrino_agent.modules.shared import source_fetch
from neutrino_agent.modules.shared.source_fetch import (
    SourceProbe,
    probe,
    rank_hosts,
    rank_registries,
    ranked,
    registry_document,
)

PACKAGE = "@cloudcli-ai/cloudcli"
VERSION = "1.37.3"
INTEGRITY = "sha512-pinned"


class Source:
    """One loopback HTTP server answering every GET as it is told."""

    def __init__(self, *, status=200, body=b"{}", chunks=1, pause_s=0.0, wait_s=0.0):
        self.asked: list = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                owner.asked.append(self.path)
                time.sleep(wait_s)
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                size = max(1, len(body) // chunks)
                for start in range(0, len(body), size):
                    self.wfile.write(body[start : start + size])
                    self.wfile.flush()
                    time.sleep(pause_s)

            def log_message(self, *args):
                """Quiet."""

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.server.daemon_threads = True
        self.server.block_on_close = False
        threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.02},
            daemon=True,
        ).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def sources():
    made: list = []

    def make(**kwargs):
        source = Source(**kwargs)
        made.append(source)
        return source

    yield make
    for source in made:
        source.close()


def document(integrity=INTEGRITY, size=200_000) -> bytes:
    return json.dumps({"dist": {"integrity": integrity}, "pad": "x" * size}).encode()


def closed_port() -> str:
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{held.getsockname()[1]}"


# --- one probe ---


def test_a_probe_reads_the_answer_and_times_it(sources):
    source = sources(body=b"hello world")

    found = probe(source.url + "/doc", source="registry")

    assert (found.source, found.is_answered, found.status) == ("registry", True, 200)
    assert found.body == b"hello world"
    assert found.first_byte_s >= 0 and found.speed > 0
    assert source.asked == ["/doc"]


def test_an_http_error_is_its_status_unless_any_answer_counts(sources):
    source = sources(status=404, body=b"gone")

    refused = probe(source.url)
    answered = probe(source.url, is_error_answer=True)

    assert (refused.is_answered, refused.reason) == (False, "http_404")
    assert refused.failure() == {
        "source": source.url,
        "reason": "http_404",
        "detail": refused.detail,
    }
    assert (answered.is_answered, answered.status) == (True, 404)


def test_a_refused_connection_is_unreachable():
    found = probe(closed_port())

    assert (found.is_answered, found.reason) == (False, "unreachable")


def test_a_source_that_does_not_answer_in_time_is_a_timeout(sources):
    source = sources(wait_s=1.0)

    started = time.monotonic()
    found = probe(source.url, timeout_s=0.2)

    assert (found.is_answered, found.reason) == (False, "timeout")
    assert time.monotonic() - started < 0.9


# --- the ranking ---


def test_the_fastest_comes_first_and_a_near_tie_goes_to_the_earlier_first_byte():
    probes = [
        SourceProbe(source="slow", is_answered=True, speed=10.0, first_byte_s=0.01),
        SourceProbe(source="tie_late", is_answered=True, speed=95.0, first_byte_s=0.3),
        SourceProbe(source="fast", is_answered=True, speed=100.0, first_byte_s=0.5),
        SourceProbe(source="tie_early", is_answered=True, speed=91.0, first_byte_s=0.1),
        SourceProbe(source="silent", reason="timeout"),
    ]

    assert [found.source for found in ranked(probes)] == [
        "tie_early",
        "tie_late",
        "fast",
        "slow",
    ]


def test_a_registry_document_names_the_package_with_its_slash_escaped():
    assert registry_document("https://registry.npmjs.org/", PACKAGE, VERSION) == (
        "https://registry.npmjs.org/@cloudcli-ai%2Fcloudcli/1.37.3"
    )


def test_registries_are_ranked_by_speed_while_they_name_the_pinned_integrity(sources):
    slow = sources(body=document(), chunks=10, pause_s=0.03)
    fast = sources(body=document())
    wrong = sources(body=document("sha512-other"))
    missing = sources(status=404)
    silent = closed_port()

    chosen, failures = rank_registries(
        [slow.url, wrong.url, fast.url, missing.url, silent],
        package=PACKAGE,
        version=VERSION,
        integrity=INTEGRITY,
    )

    assert chosen == [fast.url, slow.url]
    assert [(entry["source"], entry["reason"]) for entry in failures] == [
        (wrong.url, "digest_mismatch"),
        (missing.url, "http_404"),
        (silent, "unreachable"),
    ]
    assert failures[0]["detail"] == "the registry names sha512-other"
    assert fast.asked == ["/@cloudcli-ai%2Fcloudcli/1.37.3"]


def test_every_ranking_probes_again(sources):
    source = sources(body=document())

    for _ in range(2):
        rank_registries(
            [source.url], package=PACKAGE, version=VERSION, integrity=INTEGRITY
        )

    assert len(source.asked) == 2


def test_hosts_are_ranked_fastest_first_whatever_they_answer(sources):
    slow = sources(status=404, body=b"x" * 100_000, chunks=10, pause_s=0.03)
    fast = sources(status=404, body=b"x" * 100_000)
    silent = closed_port()

    assert rank_hosts([silent, slow.url, fast.url]) == [fast.url, slow.url, silent]


def test_the_probes_run_at_once():
    started: list = []

    def slow_probe(url, *, source=""):
        started.append(time.monotonic())
        time.sleep(0.2)
        return SourceProbe(source=source, is_answered=True, speed=1.0)

    began = time.monotonic()
    source_fetch.probe_all([("a", "a"), ("b", "b"), ("c", "c")], probe_one=slow_probe)

    assert time.monotonic() - began < 0.5
    assert max(started) - min(started) < 0.15
