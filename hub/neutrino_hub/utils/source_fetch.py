"""Fetching a file or a document from every address that serves the same bytes.

Every download the hub makes names a list of sources and the digest of what
they serve, so every source is equal and the fastest one serves. A file's
download probes every source at once with a Range request for its first
bytes, ranks the ones that answered by speed, starts on the fastest, measures
the others again at the current offset while enough of the download is left,
moves to one that is clearly faster, resumes on the next source when one
stalls or fails, and checks the digest when the last byte arrives. A
document, a version list or a ``latest.json``, is read from every source at
once and the first valid answer wins. Nothing remembers a past result.

When every source fails, :class:`DownloadFailedError` names each source and
why it failed.

Not pure: opens network connections and writes files.
"""

import collections
import contextlib
import functools
import hashlib
import http.client
import os
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from neutrino_hub.exceptions import DownloadFailedError, DownloadTooLargeError
from neutrino_hub.utils.constants import (
    UTILS_FETCH_CHUNK_BYTES,
    UTILS_FETCH_DOCUMENT_LIMIT_BYTES,
    UTILS_FETCH_HEAD_BYTES,
    UTILS_FETCH_HEADERS,
    UTILS_FETCH_MEASURE_INTERVAL_S,
    UTILS_FETCH_MOVE_FACTOR,
    UTILS_FETCH_NEAR_TIE,
    UTILS_FETCH_PROBE_BYTES,
    UTILS_FETCH_PROBE_TIMEOUT_S,
    UTILS_FETCH_PROGRESS_INTERVAL_S,
    UTILS_FETCH_PROGRESS_PERCENT_STEP,
    UTILS_FETCH_SPEED_WINDOW_S,
    UTILS_FETCH_STALL_S,
)
from neutrino_hub.utils.tls_trust import public_ssl_context

DIGEST_PREFIX = "sha256:"
PARTIAL_PREFIX = ".partial_"
# The reasons a source fails, as ``download_failed`` names them.
REASON_UNREACHABLE = "unreachable"
REASON_TIMEOUT = "timeout"
REASON_STALLED = "stalled"
REASON_DIGEST_MISMATCH = "digest_mismatch"
REASON_HTTP = "http_{status}"
DETAIL_LIMIT = 200
# The shortest span a speed is measured over, so bytes that arrived in one
# read give a finite speed.
SPEED_SPAN_MIN_S = 0.001


class DownloadedFile:
    """One finished download in a temporary file, not yet in its place.

    Attributes:
        path: The temporary file.
        size: How many bytes it holds.
        sha256: Their digest, in hex.
        head: Its first bytes, for a check of what kind of file it is.
        source: The source that served its last byte.
    """

    def __init__(
        self, *, path: Path, size: int, sha256: str, head: bytes, source: str = ""
    ):
        """
        Args:
            path: The temporary file.
            size: How many bytes it holds.
            sha256: Their digest, in hex.
            head: Its first bytes.
            source: The source that served its last byte.
        """
        self.path = path
        self.size = size
        self.sha256 = sha256
        self.head = head
        self.source = source

    def place(self, target: Path) -> None:
        """Move the file to where it is kept, in one rename.

        Args:
            target: Its place, in the same directory.

        Raises:
            OSError: When it cannot be moved; the temporary file is gone.
        """
        try:
            os.replace(self.path, target)
        except OSError:
            self.discard()
            raise

    def discard(self) -> None:
        """Delete the temporary file."""
        with contextlib.suppress(OSError):
            os.unlink(self.path)


@dataclass
class SourceProbe:
    """What one source answered to a probe or a measure.

    Attributes:
        source: The address asked.
        is_answered: Whether it answered in time with the bytes asked for.
        is_resumable: Whether it answered the Range request with part of
            the file, so a download can resume on it at an offset.
        first_byte_s: Seconds from the request to the first byte.
        speed: Bytes per second, from the first byte to the last.
        size: The whole file's size as the answer named it; 0 when unnamed.
        body: The bytes the answer carried.
        is_complete: Whether the body reached the end of the file.
        reason: Why it failed, empty when it did not; ``timeout`` for a
            source that did not answer in time, which has not failed.
        detail: The error's own words.
    """

    source: str
    is_answered: bool = False
    is_resumable: bool = False
    first_byte_s: float = 0.0
    speed: float = 0.0
    size: int = 0
    body: bytes = b""
    is_complete: bool = False
    reason: str = ""
    detail: str = ""

    @property
    def is_failed(self) -> bool:
        """Whether the answer failed the source: an error, not a late answer."""
        return bool(self.reason) and self.reason != REASON_TIMEOUT


def file_sha256(path: Path) -> str:
    """A file's SHA-256, read in chunks.

    Args:
        path: The file.

    Returns:
        The digest, in hex.

    Raises:
        OSError: When it cannot be read.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(UTILS_FETCH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def hex_of(digest: str) -> str:
    """The hex of a ``sha256:<hex>`` digest.

    Args:
        digest: The digest as a manifest names it.

    Returns:
        The lowercase hex.

    Raises:
        ValueError: For a digest of another form.
    """
    value = str(digest or "")
    hexed = value[len(DIGEST_PREFIX) :].lower()
    if not value.startswith(DIGEST_PREFIX) or len(hexed) != 64:
        raise ValueError(f"{digest!r} is no sha256 digest")
    if any(letter not in "0123456789abcdef" for letter in hexed):
        raise ValueError(f"{digest!r} is no sha256 digest")
    return hexed


def is_near(one: float, other: float) -> bool:
    """Whether two speeds are within a tenth of each other.

    Args:
        one: A speed.
        other: Another.

    Returns:
        True when the gap is at most :data:`UTILS_FETCH_NEAR_TIE` of the
        larger.
    """
    return abs(one - other) <= UTILS_FETCH_NEAR_TIE * max(one, other)


def rank_probes(probes: list) -> list:
    """The sources that answered, fastest first.

    Two speeds within a tenth of each other go to the earlier first byte.

    Args:
        probes: The probes, answered or not.

    Returns:
        The answered probes in rank order.
    """
    answered = [probe for probe in probes if probe.is_answered]
    return sorted(answered, key=functools.cmp_to_key(_compare))


def failure_entry(source: str, reason: str, detail: str = "") -> dict:
    """One source of a failed download, as ``download_failed`` names it.

    Args:
        source: The address.
        reason: Why it failed.
        detail: The error's own words.

    Returns:
        ``{source, reason, detail}``.
    """
    return {"source": source, "reason": reason, "detail": detail[:DETAIL_LIMIT]}


def http_reason(status: int) -> str:
    """The reason an error status gives a source.

    Args:
        status: The HTTP status.

    Returns:
        Such as ``http_404``.
    """
    return REASON_HTTP.format(status=status)


def _compare(one: SourceProbe, other: SourceProbe) -> int:
    """Which of two answered probes ranks first."""
    if is_near(one.speed, other.speed):
        return (one.first_byte_s > other.first_byte_s) - (
            one.first_byte_s < other.first_byte_s
        )
    return -1 if one.speed > other.speed else 1


def _open_url(request: urllib.request.Request, timeout: float):
    """Open one request over the network, verifying a public host's certificate."""
    return urllib.request.urlopen(
        request, timeout=timeout, context=public_ssl_context()
    )


def _error_reason(error: BaseException) -> tuple:
    """The reason and the detail an error opening or reading a source gives.

    Args:
        error: What the open or the read raised.

    Returns:
        ``(reason, detail)``: an HTTP refusal names its status, a wait that
        ran out is ``timeout``, anything else ``unreachable``.
    """
    detail = str(error)[:DETAIL_LIMIT]
    if isinstance(error, urllib.error.HTTPError):
        return http_reason(error.code), detail
    cause = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(cause, (TimeoutError, socket.timeout)):
        return REASON_TIMEOUT, detail
    return REASON_UNREACHABLE, detail


def _whole_size(response) -> int:
    """The whole file's size an answer names, 0 when it names none."""
    content_range = str(response.headers.get("Content-Range", "") or "")
    if "/" in content_range:
        total = content_range.rsplit("/", 1)[-1].strip()
        if total.isdigit():
            return int(total)
    if response.status == 200:
        length = str(response.headers.get("Content-Length", "") or "")
        if length.isdigit():
            return int(length)
    return 0


def _range_start(response) -> int:
    """The offset a 206 answer starts at, -1 when it names none."""
    content_range = str(response.headers.get("Content-Range", "") or "")
    unit, _, span = content_range.partition(" ")
    start = span.partition("-")[0].strip()
    if unit.strip() != "bytes" or not start.isdigit():
        return -1
    return int(start)


@dataclass
class _Download:
    """The state of one file's download while it runs."""

    order: list
    failures: dict = field(default_factory=dict)
    whole_only: set = field(default_factory=set)
    size: int = 0
    offset: int = 0


class SourceFetcher:
    """Downloads one file, or reads one document, from the fastest source."""

    def __init__(
        self,
        *,
        opener: "Callable | None" = None,
        clock: Callable[[], float] = time.monotonic,
        probe_bytes: int = UTILS_FETCH_PROBE_BYTES,
        probe_timeout_s: float = UTILS_FETCH_PROBE_TIMEOUT_S,
        measure_interval_s: float = UTILS_FETCH_MEASURE_INTERVAL_S,
        speed_window_s: float = UTILS_FETCH_SPEED_WINDOW_S,
        stall_s: float = UTILS_FETCH_STALL_S,
        move_factor: float = UTILS_FETCH_MOVE_FACTOR,
    ):
        """
        Args:
            opener: Called with ``(request, timeout)``; returns the response.
                None opens over the network.
            clock: Monotonic seconds; injected by tests.
            probe_bytes: How much of a file a probe or a measure asks for.
            probe_timeout_s: How long a probe waits for an answer, and then
                for its bytes.
            measure_interval_s: How often the other sources are measured.
            speed_window_s: The span the current source's speed is taken
                over.
            stall_s: How long a source may send no byte before it fails.
            move_factor: How many times faster a measured source must be to
                take over.
        """
        self._open = opener if opener is not None else _open_url
        self._clock = clock
        self._probe_bytes = probe_bytes
        self._probe_timeout_s = probe_timeout_s
        self._measure_interval_s = measure_interval_s
        self._speed_window_s = speed_window_s
        self._stall_s = stall_s
        self._move_factor = move_factor

    def fetch_file(
        self,
        *,
        file: str,
        sources: list,
        digest: str,
        directory: Path,
        limit: int,
        on_line: "Callable[[str], None] | None" = None,
    ) -> DownloadedFile:
        """Download one file from its sources into a temporary file.

        Args:
            file: The file's name, as ``download_failed`` names it.
            sources: Every address that serves it.
            digest: Its ``sha256:<hex>`` digest.
            directory: Where the temporary file is made, beside its place.
            limit: The largest file taken, in bytes.
            on_line: Called with ``hub: fetching <file> from <host>`` when a
                source starts serving, and with its progress; None writes no
                line.

        Returns:
            The download, its digest checked.

        Raises:
            DownloadFailedError: When every source failed.
            DownloadTooLargeError: When a source names a size past ``limit``.
            ValueError: For a digest that is not ``sha256:<hex>``.
            OSError: When the temporary file cannot be written.
        """
        wanted = hex_of(digest)
        listed = [str(source) for source in sources if source]
        if not listed:
            raise DownloadFailedError(file, [])
        directory.mkdir(parents=True, exist_ok=True)
        probes = self._probe_all(listed, offset=0)
        state = _Download(order=[])
        late = []
        for probe in probes:
            if probe.size > limit:
                raise DownloadTooLargeError(limit)
            state.size = state.size or probe.size
            if probe.is_failed:
                state.failures[probe.source] = failure_entry(
                    probe.source, probe.reason, probe.detail
                )
            elif not probe.is_answered:
                late.append(probe.source)
            elif not probe.is_resumable:
                state.whole_only.add(probe.source)
        ranked = rank_probes(probes)
        state.order = [probe.source for probe in ranked] + late
        handle, name = tempfile.mkstemp(prefix=PARTIAL_PREFIX, dir=directory)
        path = Path(name)
        try:
            with os.fdopen(handle, "r+b") as stream:
                source = self._start_from_probe(stream, ranked, state)
                while True:
                    if source is None:
                        source = self._serve(file, stream, state, limit, on_line)
                    if source is None:
                        raise DownloadFailedError(
                            file,
                            [
                                state.failures.get(item)
                                or failure_entry(item, REASON_TIMEOUT)
                                for item in listed
                            ],
                        )
                    if self._is_digest(stream, wanted, source, state):
                        break
                    source = None
                stream.seek(0)
                head = stream.read(UTILS_FETCH_HEAD_BYTES)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(path)
            raise
        return DownloadedFile(
            path=path, size=state.offset, sha256=wanted, head=head, source=source
        )

    def fetch_document(
        self,
        *,
        file: str,
        sources: list,
        parse: Callable[[bytes], object],
        limit: int = UTILS_FETCH_DOCUMENT_LIMIT_BYTES,
        headers: "dict | None" = None,
    ) -> tuple:
        """Read one document from every source at once; the first valid answer wins.

        Args:
            file: What the document is, as ``download_failed`` names it.
            sources: Every address that serves it.
            parse: Turns the bytes into the document; raises ``ValueError``
                for an answer that is not one.
            limit: The largest answer read.
            headers: More request headers, such as a registry's ``Accept``
                and its token.

        Returns:
            ``(document, source)``.

        Raises:
            DownloadFailedError: When no source gave a valid answer.
        """
        listed = [str(source) for source in sources if source]
        if not listed:
            raise DownloadFailedError(file, [])
        answers: "collections.deque" = collections.deque()
        arrived = threading.Condition()
        for source in listed:
            threading.Thread(
                target=self._read_document,
                args=(source, parse, limit, answers, arrived, dict(headers or {})),
                daemon=True,
            ).start()
        failures = {}
        with arrived:
            while len(failures) < len(listed):
                while not answers:
                    arrived.wait()
                source, document, failure = answers.popleft()
                if failure is None:
                    return document, source
                failures[source] = failure
        raise DownloadFailedError(file, [failures[source] for source in listed])

    def bearer_challenge(self, url: str) -> str:
        """The bearer challenge one address answers a request with no token with.

        Args:
            url: The address, such as a registry's ``/v2/``.

        Returns:
            The ``WWW-Authenticate`` of a 401 answer; empty for any other
            answer or none.
        """
        try:
            with self._open(
                urllib.request.Request(url, headers=dict(UTILS_FETCH_HEADERS)),
                self._probe_timeout_s,
            ):
                return ""
        except urllib.error.HTTPError as error:
            if error.code != 401:
                return ""
            return str(error.headers.get("WWW-Authenticate", "") or "")
        except (OSError, http.client.HTTPException):
            return ""

    def _read_document(
        self, source, parse, limit, answers, arrived, headers=None
    ) -> None:
        """Read one source's answer and hand it to the waiting reader."""
        try:
            with self._open(
                urllib.request.Request(
                    source, headers={**UTILS_FETCH_HEADERS, **(headers or {})}
                ),
                self._probe_timeout_s,
            ) as response:
                body = response.read(limit + 1)
        except (OSError, http.client.HTTPException) as error:
            outcome = (source, None, failure_entry(source, *_error_reason(error)))
        else:
            try:
                if len(body) > limit:
                    raise ValueError(f"the answer is larger than {limit} bytes")
                outcome = (source, parse(body), None)
            except (ValueError, KeyError, TypeError) as error:
                outcome = (
                    source,
                    None,
                    failure_entry(source, REASON_DIGEST_MISMATCH, str(error)),
                )
        with arrived:
            answers.append(outcome)
            arrived.notify_all()

    def _probe_all(self, sources: list, *, offset: int) -> list:
        """Probe every source at once at one offset.

        Args:
            sources: The addresses.
            offset: Where the probe's Range starts.

        Returns:
            One probe per source, in the order given.
        """
        probes = [SourceProbe(source=source) for source in sources]
        threads = [
            threading.Thread(
                target=self._probe_into, args=(probes, index, offset), daemon=True
            )
            for index in range(len(probes))
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return probes

    def _probe_into(self, probes: list, index: int, offset: int) -> None:
        """Probe one source and keep its answer in its slot."""
        probes[index] = self.probe(probes[index].source, offset=offset)

    def probe(self, source: str, *, offset: int = 0) -> SourceProbe:
        """Ask one source for the probe's bytes at an offset and time them.

        A probe waits :attr:`probe_timeout_s` for an answer and as long again
        for its bytes, and measures its speed from the first byte to the last
        that arrived.

        Args:
            source: The address.
            offset: Where the Range starts.

        Returns:
            The probe.
        """
        headers = dict(UTILS_FETCH_HEADERS)
        headers["Range"] = f"bytes={offset}-{offset + self._probe_bytes - 1}"
        started = self._clock()
        try:
            response = self._open(
                urllib.request.Request(source, headers=headers), self._probe_timeout_s
            )
        except (OSError, http.client.HTTPException) as error:
            reason, detail = _error_reason(error)
            return SourceProbe(source=source, reason=reason, detail=detail)
        with response:
            status = response.status
            if status not in (200, 206):
                return SourceProbe(source=source, reason=http_reason(status))
            is_resumable = status == 206 and _range_start(response) == offset
            if status == 200 and offset:
                # It cannot resume here; what it would serve is the start.
                return SourceProbe(
                    source=source, is_answered=True, size=_whole_size(response)
                )
            body = bytearray()
            first_at = last_at = 0.0
            is_ended = False
            try:
                while len(body) < self._probe_bytes:
                    chunk = response.read1(self._probe_bytes - len(body))
                    now = self._clock()
                    if not chunk:
                        is_ended = True
                        break
                    if not body:
                        first_at = now
                    body += chunk
                    last_at = now
                    if now - first_at > self._probe_timeout_s:
                        break
            except (OSError, http.client.HTTPException) as error:
                reason, detail = _error_reason(error)
                if not body:
                    return SourceProbe(source=source, reason=reason, detail=detail)
            size = _whole_size(response)
        if not body:
            return SourceProbe(source=source, reason=REASON_TIMEOUT)
        span = max(last_at - first_at, SPEED_SPAN_MIN_S)
        return SourceProbe(
            source=source,
            is_answered=True,
            is_resumable=is_resumable,
            first_byte_s=first_at - started,
            speed=len(body) / span,
            size=size,
            body=bytes(body),
            is_complete=is_ended or (size > 0 and offset + len(body) >= size),
        )

    def _start_from_probe(self, stream, ranked: list, state: _Download):
        """Keep the fastest probe's bytes as the file's start.

        Args:
            stream: The temporary file.
            ranked: The answered probes in rank order.
            state: The download.

        Returns:
            The source when its probe held the whole file, else None; the
            bytes of a resumable fastest source are kept either way.
        """
        if not ranked:
            return None
        fastest = ranked[0]
        if not (fastest.is_resumable or fastest.is_complete):
            return None
        stream.write(fastest.body)
        state.offset = len(fastest.body)
        return fastest.source if fastest.is_complete else None

    @staticmethod
    def _is_digest(stream, wanted: str, source: str, state: _Download) -> bool:
        """Whether the file holds the wanted bytes; a mismatch drops its source.

        Args:
            stream: The temporary file.
            wanted: The digest's hex.
            source: The source that served the last byte.
            state: The download, whose offset goes back to the start on a
                mismatch.

        Returns:
            True when the digest matches.
        """
        stream.flush()
        stream.seek(0)
        digest = hashlib.sha256()
        for chunk in iter(functools.partial(stream.read, UTILS_FETCH_CHUNK_BYTES), b""):
            digest.update(chunk)
        if digest.hexdigest() == wanted:
            return True
        state.failures[source] = failure_entry(
            source, REASON_DIGEST_MISMATCH, f"the file hashes to {digest.hexdigest()}"
        )
        state.offset = 0
        return False

    @staticmethod
    def _next_source(state: _Download, *, preferred: str = "") -> str:
        """The source the download goes on with, empty when none is left."""
        if preferred and preferred not in state.failures:
            return preferred
        for source in state.order:
            if source not in state.failures:
                return source
        return ""

    def _serve(self, file, stream, state: _Download, limit: int, on_line):
        """Download from the ranked sources until the last byte arrives.

        Args:
            file: The file's name.
            stream: The temporary file.
            state: The download.
            limit: The largest file taken.
            on_line: Called with each line; None writes none.

        Returns:
            The source that served the last byte, or None when every source
            failed.

        Raises:
            DownloadTooLargeError: When a source names a size past ``limit``.
            OSError: When the temporary file cannot be written.
        """
        preferred = ""
        while True:
            source = self._next_source(state, preferred=preferred)
            if not source:
                return None
            preferred = ""
            outcome = self._serve_one(file, source, stream, state, limit, on_line)
            if outcome is None:
                return source
            if outcome.startswith("move:"):
                preferred = outcome[len("move:") :]

    def _serve_one(self, file, source, stream, state, limit, on_line):
        """Take bytes from one source until the end, a failure or a move.

        Returns:
            None when the last byte arrived; ``failed`` when the source
            failed; ``move:<source>`` when a faster source takes over.
        """
        headers = dict(UTILS_FETCH_HEADERS)
        headers["Range"] = f"bytes={state.offset}-"
        try:
            response = self._open(
                urllib.request.Request(source, headers=headers), self._stall_s
            )
        except (OSError, http.client.HTTPException) as error:
            reason, detail = _error_reason(error)
            state.failures[source] = failure_entry(source, reason, detail)
            return "failed"
        with response:
            status = response.status
            if status not in (200, 206):
                state.failures[source] = failure_entry(source, http_reason(status))
                return "failed"
            size = _whole_size(response)
            if size > limit:
                raise DownloadTooLargeError(limit)
            state.size = size or state.size
            if status == 206 and _range_start(response) != state.offset:
                state.failures[source] = failure_entry(
                    source,
                    REASON_UNREACHABLE,
                    f"it answered a range at {state.offset} with another range",
                )
                return "failed"
            if status == 200:
                # It serves the file from its start alone.
                state.whole_only.add(source)
                state.offset = 0
            stream.seek(state.offset)
            stream.truncate()
            return self._take(file, source, response, stream, state, limit, on_line)

    def _take(self, file, source, response, stream, state, limit, on_line):
        """Read one source's bytes into the file, measuring the others meanwhile."""
        host = urllib.parse.urlsplit(source).hostname or source
        progress = _Progress(file=file, host=host, clock=self._clock, on_line=on_line)
        progress.start(state.offset, state.size)
        samples = collections.deque([(self._clock(), state.offset)])
        next_measure_at = self._clock() + self._measure_interval_s
        measure: "_Measure | None" = None
        while True:
            try:
                chunk = response.read1(UTILS_FETCH_CHUNK_BYTES)
            except (TimeoutError, socket.timeout) as error:
                state.failures[source] = failure_entry(
                    source, REASON_STALLED, str(error)
                )
                return "failed"
            except (OSError, http.client.HTTPException) as error:
                state.failures[source] = failure_entry(
                    source, REASON_UNREACHABLE, str(error)
                )
                return "failed"
            if not chunk:
                break
            if state.offset + len(chunk) > limit:
                state.failures[source] = failure_entry(
                    source,
                    REASON_DIGEST_MISMATCH,
                    f"it served more than {limit} bytes",
                )
                return "failed"
            stream.write(chunk)
            state.offset += len(chunk)
            now = self._clock()
            samples.append((now, state.offset))
            while len(samples) > 2 and now - samples[1][0] >= self._speed_window_s:
                samples.popleft()
            progress.note(state.offset, state.size)
            speed = _speed(samples)
            if measure is None and now >= next_measure_at:
                if self._is_long_left(state, speed):
                    measure = _Measure(
                        self, self._measured(state, source), state.offset
                    )
                else:
                    next_measure_at = now + self._measure_interval_s
            if measure is not None and measure.is_done():
                faster = self._faster(measure.results(), speed, state)
                measure = None
                next_measure_at = self._clock() + self._measure_interval_s
                if faster:
                    return f"move:{faster}"
        if state.size and state.offset < state.size:
            state.failures[source] = failure_entry(
                source,
                REASON_UNREACHABLE,
                f"the transfer broke off at {state.offset} of {state.size} bytes",
            )
            return "failed"
        progress.note(state.offset, state.size, is_done=True)
        return None

    def _is_long_left(self, state: _Download, speed: float) -> bool:
        """Whether the download has at least one measure interval left at its speed."""
        if not state.size or speed <= 0:
            return True
        return (state.size - state.offset) / speed >= self._measure_interval_s

    @staticmethod
    def _measured(state: _Download, current: str) -> list:
        """The sources a measure asks: every one not failed, resumable, not current."""
        return [
            source
            for source in state.order
            if source != current
            and source not in state.whole_only
            and source not in state.failures
        ]

    def _faster(self, probes: list, speed: float, state: _Download) -> str:
        """The measured source that takes over, empty when none is fast enough.

        A measure that answered with an error fails its source; one that
        answered the Range with the whole file is never moved to.
        """
        best = ""
        best_speed = 0.0
        for probe in probes:
            if probe.is_failed:
                state.failures[probe.source] = failure_entry(
                    probe.source, probe.reason, probe.detail
                )
                continue
            if not probe.is_answered:
                continue
            if not probe.is_resumable:
                state.whole_only.add(probe.source)
                continue
            if probe.speed > best_speed:
                best, best_speed = probe.source, probe.speed
        if best and best_speed >= self._move_factor * speed:
            return best
        return ""


class _Measure:
    """The other sources measured at one offset, on threads of their own."""

    def __init__(self, fetcher: SourceFetcher, sources: list, offset: int):
        self._probes: list = []
        self._thread = threading.Thread(
            target=self._run, args=(fetcher, sources, offset), daemon=True
        )
        self._thread.start()

    def _run(self, fetcher: SourceFetcher, sources: list, offset: int) -> None:
        self._probes = fetcher._probe_all(sources, offset=offset)

    def is_done(self) -> bool:
        """Whether every source answered or ran out of time."""
        return not self._thread.is_alive()

    def results(self) -> list:
        """The probes, once done."""
        return list(self._probes)


class _Progress:
    """Turns a running byte count into ``hub: fetching`` lines."""

    def __init__(self, *, file: str, host: str, clock, on_line):
        self._file = file
        self._host = host
        self._clock = clock
        self._on_line = on_line
        self._last_at = 0.0
        self._last_percent = 0

    def start(self, received: int, total: int) -> None:
        """Say which host the file now comes from."""
        self._last_at = self._clock()
        self._last_percent = received * 100 // total if total else 0
        if self._on_line is not None:
            self._on_line(f"hub: fetching {self._file} from {self._host}")

    def note(self, received: int, total: int, *, is_done: bool = False) -> None:
        """Write a progress line when one is due."""
        if self._on_line is None:
            return
        now = self._clock()
        percent = received * 100 // total if total else 0
        is_due = (
            is_done
            or now - self._last_at >= UTILS_FETCH_PROGRESS_INTERVAL_S
            or percent - self._last_percent >= UTILS_FETCH_PROGRESS_PERCENT_STEP
        )
        if not is_due:
            return
        self._last_at = now
        self._last_percent = percent
        amount = _megabytes(received)
        if total:
            amount = f"{amount} / {_megabytes(total)}"
        self._on_line(f"hub: fetching {self._file} from {self._host}, {amount} MB")


def _speed(samples) -> float:
    """Bytes per second over the samples kept."""
    (first_at, first_offset), (last_at, last_offset) = samples[0], samples[-1]
    return (last_offset - first_offset) / max(last_at - first_at, SPEED_SPAN_MIN_S)


def _megabytes(size: int) -> str:
    """A byte count in megabytes with one decimal."""
    return f"{size / (1024 * 1024):.1f}"
