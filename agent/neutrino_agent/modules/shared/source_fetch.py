"""Probing and ranking the sources of what the agent hands to a tool.

The agent downloads no file itself: it chooses the npm registry an install
runs against, the host an npm setting names, the registry Podman pulls an
image from, and the source of a source set a container's tools read. Every
source is probed at once, and a probe waits at most
``AGENT_SOURCE_PROBE_TIMEOUT_S`` for an answer. A probe reads a real file:
its first ``AGENT_SOURCE_PROBE_BYTES``, for as long again as it waited, and
an npm registry's probe reads the package's whole document. The sources that
answered are ranked by the probe's speed, measured from its first byte to
its last, and two speeds within a tenth of each other go to the earlier
first byte. A source that did not answer in time is not ranked: an image's,
a set's and a host's are tried after the ranked ones, and an npm registry's
is not, since its probe checks the package's integrity. Nothing is
remembered: each ranking probes again.

Not pure: opens connections.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import functools
import http.client
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from neutrino_agent.constants import (
    AGENT_SOURCE_DOCKER_HUB,
    AGENT_SOURCE_DOCKER_LIBRARY,
    AGENT_SOURCE_DOCKER_REGISTRY,
    AGENT_SOURCE_DOCUMENT_LIMIT_BYTES,
    AGENT_SOURCE_HEADERS,
    AGENT_SOURCE_MANIFEST_ACCEPT,
    AGENT_SOURCE_NEAR_TIE,
    AGENT_SOURCE_PROBE_BYTES,
    AGENT_SOURCE_PROBE_TIMEOUT_S,
)

# The reasons a source fails, as ``download_failed`` names them.
REASON_UNREACHABLE = "unreachable"
REASON_TIMEOUT = "timeout"
REASON_DIGEST_MISMATCH = "digest_mismatch"
REASON_HTTP_PREFIX = "http_"
REASON_PULL_FAILED = "pull_failed"
# Where macOS keeps the certificate authorities when the interpreter's own
# store holds none.
SYSTEM_CA_FILE = "/etc/ssl/cert.pem"
DETAIL_CHARS = 200
# A registry that wants a token answers 401 with this challenge.
BEARER_CHALLENGE_PATTERN = re.compile(r'(\w+)="([^"]*)"')
HTTP_UNAUTHORIZED = 401
# The system of an image a manifest list names; an attestation names "unknown".
IMAGE_SYSTEM = "linux"


@dataclass
class SourceProbe:
    """What one probe of one source found.

    Attributes:
        source: The source, as the recipe names it.
        is_answered: Whether it answered in time; an HTTP error counts only
            where the probe takes one.
        first_byte_s: Seconds from the request to the first byte.
        speed: Bytes per second from the first byte to the last.
        status: The HTTP status; 0 when none came.
        body: What it answered, up to the probe's limit.
        reason: Why it failed, empty when it answered.
        detail: The error's own words, empty when it answered.
        challenge: The ``WWW-Authenticate`` a 401 answer carried; empty for
            any other answer.
    """

    source: str
    is_answered: bool = False
    first_byte_s: float = 0.0
    speed: float = 0.0
    status: int = 0
    body: bytes = b""
    reason: str = ""
    detail: str = ""
    challenge: str = ""

    def failure(self) -> dict:
        """The source as ``download_failed`` lists it.

        Returns:
            ``{source, reason, detail}``.
        """
        return {"source": self.source, "reason": self.reason, "detail": self.detail}


def public_context() -> ssl.SSLContext:
    """The TLS context a probe of a public source verifies with.

    Returns:
        The system's certificate authorities, or macOS's file of them when
        the interpreter's own store holds none.
    """
    context = ssl.create_default_context()
    if not context.cert_store_stats().get("x509_ca") and os.path.isfile(SYSTEM_CA_FILE):
        context.load_verify_locations(cafile=SYSTEM_CA_FILE)
    return context


def probe(
    url: str,
    *,
    source: str = "",
    timeout_s: float = AGENT_SOURCE_PROBE_TIMEOUT_S,
    is_document: bool = False,
    clock=time.monotonic,
    context: "ssl.SSLContext | None" = None,
    headers: "dict | None" = None,
) -> SourceProbe:
    """GET one address and time its answer.

    A file is asked for its first ``AGENT_SOURCE_PROBE_BYTES`` with a Range
    request, and the read stops ``timeout_s`` after the first byte; the speed
    is taken over what arrived. A document is read whole, up to
    ``AGENT_SOURCE_DOCUMENT_LIMIT_BYTES``. An ``Authorization`` header goes
    to the address asked and to no address it redirects to.

    Args:
        url: What to ask.
        source: The source the address belongs to; the address itself when
            empty.
        timeout_s: How long the probe waits for an answer, and then for each
            read and for a file's bytes.
        is_document: Whether the answer is read whole, as one whose content
            is used.
        clock: Monotonic seconds.
        context: The TLS context; None verifies with :func:`public_context`.
        headers: Headers sent beside the agent's own; None sends none.

    Returns:
        The probe.
    """
    found = SourceProbe(source=source or url)
    sent = {**AGENT_SOURCE_HEADERS, **(headers or {})}
    authorization = sent.pop("Authorization", "")
    limit = AGENT_SOURCE_DOCUMENT_LIMIT_BYTES
    if not is_document:
        limit = AGENT_SOURCE_PROBE_BYTES
        sent["Range"] = f"bytes=0-{limit - 1}"
    request = urllib.request.Request(url, headers=sent)
    if authorization:
        request.add_unredirected_header("Authorization", authorization)
    started = clock()
    try:
        response = urllib.request.urlopen(
            request,
            timeout=timeout_s,
            context=context if context is not None else public_context(),
        )
    except urllib.error.HTTPError as error:
        if error.code == HTTP_UNAUTHORIZED and error.headers is not None:
            found.challenge = str(error.headers.get("WWW-Authenticate", "") or "")
        error.close()
        found.status = error.code
        found.reason = f"{REASON_HTTP_PREFIX}{error.code}"
        found.detail = str(error.reason or "")[:DETAIL_CHARS]
        return found
    except (socket.timeout, TimeoutError) as error:
        found.reason = REASON_TIMEOUT
        found.detail = str(error)[:DETAIL_CHARS]
        return found
    except (OSError, ValueError, http.client.HTTPException) as error:
        cause = getattr(error, "reason", error)
        is_timeout = isinstance(cause, (socket.timeout, TimeoutError))
        found.reason = REASON_TIMEOUT if is_timeout else REASON_UNREACHABLE
        found.detail = str(cause)[:DETAIL_CHARS]
        return found
    with response:
        found.status = int(response.getcode() or 200)
        try:
            body = response.read(1)
            first_at = last_at = clock()
            while len(body) < limit:
                chunk = response.read1(limit - len(body))
                if not chunk:
                    break
                body += chunk
                last_at = clock()
                if not is_document and last_at - first_at > timeout_s:
                    break
        except (OSError, ValueError, http.client.HTTPException) as error:
            is_timeout = isinstance(error, (socket.timeout, TimeoutError))
            found.reason = REASON_TIMEOUT if is_timeout else REASON_UNREACHABLE
            found.detail = str(error)[:DETAIL_CHARS]
            return found
    found.body = body
    found.is_answered = True
    found.first_byte_s = first_at - started
    found.speed = len(found.body) / max(last_at - first_at, 1e-6)
    return found


def probe_all(urls: list, *, probe_one=probe) -> list:
    """Probe every address at once.

    Args:
        urls: ``(source, url)`` pairs.
        probe_one: Called with ``url, source=``; returns a
            :class:`SourceProbe`.

    Returns:
        One probe per pair, in the pairs' order.
    """
    found: list = [None] * len(urls)

    def ask(index: int, source: str, url: str) -> None:
        found[index] = probe_one(url, source=source)

    threads = [
        threading.Thread(target=ask, args=(index, source, url), daemon=True)
        for index, (source, url) in enumerate(urls)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return found


def ranked(probes: list) -> list:
    """The probes that answered, fastest first.

    Args:
        probes: The probes.

    Returns:
        The answered probes by speed, two speeds within a tenth of each
        other ordered by the earlier first byte.
    """
    return sorted(
        (found for found in probes if found.is_answered),
        key=functools.cmp_to_key(_compare),
    )


def registry_document(registry: str, package: str) -> str:
    """The address of a package's document on an npm registry. Pure.

    Args:
        registry: The registry, such as ``https://registry.npmjs.org``.
        package: The package, such as ``@cloudcli-ai/cloudcli``.

    Returns:
        ``<registry>/<package, its slash escaped>``.
    """
    name = urllib.parse.quote(package, safe="@")
    return f"{registry.rstrip('/')}/{name}"


def rank_registries(
    registries: list, *, package: str, version: str, integrity: str, probe_one=probe
) -> tuple:
    """Rank npm registries by speed, keeping those whose integrity is the pinned one.

    Args:
        registries: The artifact's registries, in its order.
        package: The npm package.
        version: The version installed.
        integrity: The artifact's digest, npm's ``integrity``.
        probe_one: Called with ``url, source=, is_document=``; returns a
            :class:`SourceProbe`.

    Returns:
        ``(chosen, failures)``: the registries that answered with the
        pinned integrity, fastest first, and each other one as
        ``{source, reason, detail}``.
    """
    probes = probe_all(
        [(registry, registry_document(registry, package)) for registry in registries],
        probe_one=functools.partial(probe_one, is_document=True),
    )
    for found in probes:
        if not found.is_answered:
            continue
        named = _integrity_of(found.body, version)
        if named != integrity:
            found.is_answered = False
            found.reason = REASON_DIGEST_MISMATCH
            found.detail = f"the registry names {named or 'no integrity'}"[
                :DETAIL_CHARS
            ]
    chosen = [found.source for found in ranked(probes)]
    return chosen, [found.failure() for found in probes if not found.is_answered]


def set_document(source: str, probe_path: str) -> str:
    """The address one source of a source set is probed at. Pure.

    Args:
        source: The source, such as ``https://pypi.org/simple``.
        probe_path: The set's ``probe``, such as ``/pip/``.

    Returns:
        The source with the path after it, one slash between them.
    """
    return source.rstrip("/") + "/" + probe_path.lstrip("/")


def rank_set(sources: list, *, probe_path: str, probe_one=probe) -> list:
    """Rank the sources of one source set, or the hosts of one npm setting, by speed.

    Args:
        sources: The sources, the publisher's first.
        probe_path: The path probed under each source.
        probe_one: Called with ``url, source=``; returns a
            :class:`SourceProbe`.

    Returns:
        The sources that answered, fastest first, then those that did not,
        in their order; the first is the one a tool reads.
    """
    probes = probe_all(
        [(source, set_document(source, probe_path)) for source in sources],
        probe_one=probe_one,
    )
    order = [found.source for found in ranked(probes)]
    return order + [source for source in sources if source not in order]


def manifest_document(source: str, digest: str) -> str:
    """The registry's address of one image's manifest by its digest. Pure.

    Args:
        source: An image reference with no tag, such as
            ``ghcr.io/owner/image`` or ``docker.io/library/mongo``.
        digest: The image's digest.

    Returns:
        ``https://<registry>/v2/<repository>/manifests/<digest>``, docker.io
        asked at its registry's own host and a one-name repository there in
        its ``library`` namespace.
    """
    return f"{_repository_address(source)}/manifests/{digest}"


def layer_document(source: str, digest: str) -> str:
    """The registry's address of one image layer by its digest. Pure.

    Args:
        source: An image reference with no tag.
        digest: The layer's digest.

    Returns:
        ``https://<registry>/v2/<repository>/blobs/<digest>``, asked as
        :func:`manifest_document` asks.
    """
    return f"{_repository_address(source)}/blobs/{digest}"


def probe_image(source: str, digest: str, *, probe_one=probe) -> SourceProbe:
    """Read the first bytes of an image's largest layer from one registry.

    The manifest by the image's digest comes first. A registry that answers
    401 with a bearer challenge is asked its token service for an anonymous
    token, and the manifest is asked again with it. A manifest list names the
    manifest of its first Linux image, and that manifest names the layers.

    Args:
        source: The image reference with no tag.
        digest: The image's digest.
        probe_one: Called with ``url, source=, headers=``, and ``is_document=``
            for a manifest; returns a :class:`SourceProbe`.

    Returns:
        The probe of the layer; of the last manifest request when none named
        a layer to read.
    """
    url = manifest_document(source, digest)
    asked = {"Accept": AGENT_SOURCE_MANIFEST_ACCEPT}
    found = probe_one(url, source=source, headers=asked, is_document=True)
    token = {}
    if found.status == HTTP_UNAUTHORIZED and found.challenge:
        bearer = _bearer_token(found.challenge, source=source, probe_one=probe_one)
        if not bearer:
            return found
        token = {"Authorization": f"Bearer {bearer}"}
        asked = {**asked, **token}
        found = probe_one(url, source=source, headers=asked, is_document=True)
    if not found.is_answered:
        return found
    image = _first_linux_image(found.body)
    if image:
        found = probe_one(
            manifest_document(source, image),
            source=source,
            headers=asked,
            is_document=True,
        )
        if not found.is_answered:
            return found
    layer = _largest_layer(found.body)
    if not layer:
        found.is_answered = False
        found.reason = REASON_UNREACHABLE
        found.detail = "the manifest names no layer"
        return found
    return probe_one(layer_document(source, layer), source=source, headers=token)


def rank_images(sources: list, digest: str, *, probe_one=probe) -> list:
    """Rank the registries that serve one image by the speed of its largest layer.

    Podman checks the digest of every pull, so a source whose probe got
    no answer is still tried. A list of one is not probed.

    Args:
        sources: The image's references with no tag, the publisher's first.
        digest: The image's digest.
        probe_one: Called as :func:`probe_image` calls it; returns a
            :class:`SourceProbe`.

    Returns:
        The sources to pull from in order: those that answered, fastest
        first, then those that did not, in their order.
    """
    if len(sources) < 2:
        return list(sources)
    probes: list = [None] * len(sources)

    def ask(index: int, source: str) -> None:
        probes[index] = probe_image(source, digest, probe_one=probe_one)

    threads = [
        threading.Thread(target=ask, args=(index, source), daemon=True)
        for index, source in enumerate(sources)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    order = [found.source for found in ranked(probes)]
    return order + [source for source in sources if source not in order]


def _bearer_token(challenge: str, *, source: str, probe_one) -> str:
    """An anonymous token from the service a bearer challenge names, empty for none."""
    if not challenge.lower().startswith("bearer "):
        return ""
    fields = dict(BEARER_CHALLENGE_PATTERN.findall(challenge))
    realm = fields.pop("realm", "")
    if not realm:
        return ""
    query = urllib.parse.urlencode(fields)
    found = probe_one(
        f"{realm}?{query}" if query else realm, source=source, is_document=True
    )
    if not found.is_answered:
        return ""
    document = _json_object(found.body)
    token = document.get("token") or document.get("access_token")
    return token if isinstance(token, str) else ""


def _repository_address(source: str) -> str:
    """The registry's address of an image reference's repository."""
    host, _, repository = source.partition("/")
    if host == AGENT_SOURCE_DOCKER_HUB:
        host = AGENT_SOURCE_DOCKER_REGISTRY
        if "/" not in repository:
            repository = f"{AGENT_SOURCE_DOCKER_LIBRARY}/{repository}"
    return f"https://{host}/v2/{repository}"


def _first_linux_image(body: bytes) -> str:
    """The digest of the first Linux image a manifest list names, empty for none."""
    listed = _json_object(body).get("manifests")
    for entry in listed if isinstance(listed, list) else ():
        named = entry.get("platform") if isinstance(entry, dict) else None
        if (
            isinstance(named, dict)
            and named.get("os") == IMAGE_SYSTEM
            and isinstance(entry.get("digest"), str)
        ):
            return entry["digest"]
    return ""


def _largest_layer(body: bytes) -> str:
    """The digest of the largest layer an image's manifest names, empty for none."""
    listed = _json_object(body).get("layers")
    layers = [
        layer
        for layer in (listed if isinstance(listed, list) else ())
        if isinstance(layer, dict) and isinstance(layer.get("digest"), str)
    ]
    if not layers:
        return ""
    return max(layers, key=_layer_size)["digest"]


def _layer_size(layer: dict) -> int:
    """The size a manifest names for a layer, 0 when it names none."""
    size = layer.get("size")
    return size if isinstance(size, int) else 0


def _json_object(body: bytes) -> dict:
    """The JSON object a body holds, empty for any other body."""
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def _integrity_of(body: bytes, version: str) -> str:
    """The ``dist.integrity`` a package's document names for a version, empty for none."""
    versions = _json_object(body).get("versions")
    entry = versions.get(version) if isinstance(versions, dict) else None
    dist = entry.get("dist") if isinstance(entry, dict) else None
    integrity = dist.get("integrity") if isinstance(dist, dict) else None
    return integrity if isinstance(integrity, str) else ""


def _compare(first: SourceProbe, second: SourceProbe) -> int:
    """The ranking's order of two answered probes."""
    fastest = max(first.speed, second.speed)
    if (
        fastest <= 0
        or abs(first.speed - second.speed) <= AGENT_SOURCE_NEAR_TIE * fastest
    ):
        return (first.first_byte_s > second.first_byte_s) - (
            first.first_byte_s < second.first_byte_s
        )
    return -1 if first.speed > second.speed else 1
