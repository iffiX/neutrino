"""Joining a hub as one person, leaving it, and the bindings kept in between.

The link is ``neutrino://enroll/<payload>`` where the payload is ``{"urls":
[...], "token": ..., "key": ..., "role": "client", "overlays": [...]}`` as
JSON, compressed with zlib and written in base64url without padding. That
alphabet holds no character a shell splits or a URL escapes. A QR code
carries the same link. ``key`` is the hub's static public key, 64 hex
characters, which every handshake pins. A link whose ``role`` is not
``client`` was made for a device agent and is refused. Every address is
``tcp://<host>:<port>``; an address of another scheme is skipped.

The bindings live in ``client.json`` in the person's own configuration
directory, mode 0600, one per hub joined: ``{"bindings": [{id, name, hub_id,
hub_name, gateway_url, gateway_urls, hub_key, private_key, token, ticket,
is_pending, overlays, is_overlay_on, overlay_pick}], "exit_hub_id"}``,
``ticket`` and ``is_pending`` only on a pending join. ``private_key`` is this
client's own static key for the hub, made when the link is read. A join
stores its binding at once, ``is_pending`` with the link's ``ticket``, no
token and an id of this machine's own; the session spends the ticket
through the transport at the first address that answers, and the binding
then holds the hub's id and token and no ticket. ``gateway_urls`` is every
address the hub answers on, from the link and then from each ``state``
frame; ``gateway_url`` is the one that last answered. ``overlays`` is how
this machine joins each of the hub's virtual networks, the hub's preferred
first, from the link and then from each ``state``: one provider's own fields
each, the secret among them, which is why the file is 0600.
``is_overlay_on`` is whether the hub's virtual network was last ``on``,
which a start connects once, and ``overlay_pick`` the provider the person
chose, empty for the first. A binding a 0.5 client kept holds the hub's
certificate ``fingerprint`` and no ``hub_key`` until it is moved.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import base64
import binascii
import functools
import hashlib
import ipaddress
import json
import os
import socket
import threading
import urllib.parse
import uuid
import zlib

from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import (
    CLIENT_ADDRESS_SCHEME,
    CLIENT_CONFIG_FILE_NAME,
    CLIENT_HUB_NAME,
    CLIENT_LEGACY_SCHEME,
    CLIENT_ROLE,
    CLIENT_SOFTWARE_PREFIX,
    CLIENT_STATE_FILE_NAME,
    PROTOCOL,
)
from neutrino_client.core import files
from neutrino_client.exceptions import EnrollmentError
from neutrino_client.platforms.detect import detect_platform, platform_tuple
from neutrino_client.services.store import ClientServiceStore

LINK_PREFIX = "neutrino://enroll/"
# What one binding keeps: every field a string but the list of every address
# the hub answers on, the list of overlay objects and the two flags.
BINDING_KEYS = (
    "id",
    "name",
    "hub_id",
    "hub_name",
    "gateway_url",
    "gateway_urls",
    "hub_key",
    "private_key",
    "fingerprint",
    "token",
    "ticket",
    "is_pending",
    "overlays",
    "is_overlay_on",
    "overlay_pick",
)
BINDING_URLS_KEY = "gateway_urls"
BINDING_OVERLAYS_KEY = "overlays"
BINDING_OVERLAY_ON_KEY = "is_overlay_on"
BINDING_PENDING_KEY = "is_pending"
BINDING_TICKET_KEY = "ticket"
# What a pending binding's own id starts with, before the hub names one.
BINDING_PENDING_ID_PREFIX = "pending_"
# A key, a psk and a digest are 64 lowercase hex characters wherever they
# are written; a static key is 32 bytes.
KEY_HEX_LENGTH = 64
KEY_BYTES = 32
# The string fields each overlay object carries, by provider and, for
# EasyTier, by mode. An EasyTier object that names no mode is a manual one,
# as a hub before the console mode sends it.
OVERLAY_FIELDS = {
    ("netbird", ""): ("setup_key", "management_url", "fqdn", "hub_address"),
    ("easytier", "manual"): ("network_name", "network_secret", "peer", "hub_address"),
    ("easytier", "console"): ("config_server", "hub_address"),
}
OVERLAY_DEFAULT_MODES = {"netbird": "", "easytier": "manual"}
# The fields that may be empty: a NetBird management URL left empty is
# NetBird's own cloud, a hub whose daemon reports no name has no fqdn, and a
# hub that does not know its own virtual address names none.
OVERLAY_OPTIONAL_FIELDS = ("management_url", "fqdn", "hub_address")


def parse_link(link: str) -> "tuple[list, str, str, list]":
    """Pull the addresses, ticket, hub key and overlays out of a link.

    Args:
        link: What the person pasted; the bare payload without its scheme
            is accepted too.

    Returns:
        The hub's ``tcp://`` addresses in the order the hub offered them,
        the enrollment ticket, the hub's static public key in lowercase
        hex, and the overlay objects this client can read, the hub's
        preferred first, empty when the link carries none.

    Raises:
        EnrollmentError: ``link_missing`` for an empty paste,
            ``link_unreadable`` for something that is not a link,
            ``link_incomplete`` for a link without an address this client
            dials, a ticket or a key, ``link_not_for_client`` for a link
            whose role is not ``client``.
    """
    text = link.strip()
    if not text:
        raise EnrollmentError("link_missing")
    if text.startswith(LINK_PREFIX):
        text = text[len(LINK_PREFIX) :]
    return read_link_object(_decoded(text))


def read_link_object(payload: dict) -> "tuple[list, str, str, list]":
    """Pull the addresses, ticket, hub key and overlays out of a link's object.

    Args:
        payload: The object a link carries.

    Returns:
        The same four as :func:`parse_link`.

    Raises:
        EnrollmentError: ``link_unreadable``, ``link_incomplete`` or
            ``link_not_for_client``, as for :func:`parse_link`.
    """
    try:
        urls = dialable_urls(clean_urls(payload.get("urls")))
        token = str(payload.get("token", ""))
        hub_key = str(payload.get("key", "") or "").strip().lower()
        role = str(payload.get("role", ""))
        overlays = clean_overlays(payload.get("overlays"))
    except (binascii.Error, ValueError, UnicodeDecodeError, AttributeError) as error:
        raise EnrollmentError("link_unreadable") from error
    if role != CLIENT_ROLE:
        raise EnrollmentError("link_not_for_client", {"role": role})
    if not urls or not token or not is_key(hub_key):
        raise EnrollmentError("link_incomplete")
    return urls, token, hub_key, overlays


def is_key(value: str) -> bool:
    """Whether a value is a key as a link and a binding write one.

    Args:
        value: The value.

    Returns:
        True for 64 lowercase hex characters.
    """
    return len(value) == KEY_HEX_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


def make_private_key() -> str:
    """This client's static private key for one hub, made when a link is read.

    Returns:
        32 random bytes as 64 lowercase hex characters.
    """
    return os.urandom(KEY_BYTES).hex()


def psk_of(binding: dict) -> str:
    """The pre-shared key a bound handshake mixes in: the token's SHA-256.

    Args:
        binding: A completed binding.

    Returns:
        The digest of the token's UTF-8 bytes, 64 lowercase hex characters.
    """
    return hashlib.sha256(str(binding.get("token", "")).encode("utf-8")).hexdigest()


def is_legacy(binding: dict) -> bool:
    """Whether a binding is one a 0.5 client kept, pinned by a certificate.

    Args:
        binding: The binding.

    Returns:
        True when it holds a fingerprint and no hub key.
    """
    return bool(binding.get("fingerprint")) and not binding.get("hub_key")


def config_path() -> str:
    """Where this person's bindings live.

    Returns:
        The absolute path of ``client.json`` under the platform's
        configuration directory.
    """
    return os.path.join(detect_platform().config_dir(), CLIENT_CONFIG_FILE_NAME)


def load_config() -> dict:
    """Read the bindings and the exit hub.

    Returns:
        ``{"bindings": [...], "exit_hub_id": str}``; a file that is absent,
        unreadable or of another shape reads as no bindings.
    """
    data = files.read_json(config_path())
    raw = data.get("bindings")
    bindings = [
        _binding(record)
        for record in (raw if isinstance(raw, list) else [])
        if isinstance(record, dict)
    ]
    return {
        "bindings": [binding for binding in bindings if _is_complete(binding)],
        "exit_hub_id": str(data.get("exit_hub_id", "") or ""),
    }


def save_config(config: dict) -> None:
    """Write the bindings atomically, readable only by this person.

    Args:
        config: ``{"bindings": [...], "exit_hub_id": str}``.

    Raises:
        OSError: When the file cannot be written.
    """
    path = config_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    files.write_text(path, json.dumps(config, indent=2) + "\n", mode=0o600)


def is_configured() -> bool:
    """Whether this person belongs to at least one hub."""
    return bool(bindings())


def config_stamp() -> int:
    """A marker that moves whenever the binding file's content does.

    The resident compares it between polls, so a binding written by
    ``nclient join`` or ``nclient leave`` is adopted without a restart.
    A digest of the bytes rather than the mtime: the kernel stamps every
    write inside one tick of its clock alike, and the file is small.

    Returns:
        A digest of the file's bytes, or 0 when it does not exist.
    """
    try:
        with open(config_path(), "rb") as stream:
            data = stream.read()
    except OSError:
        return 0
    return int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), "big")


def bindings() -> list:
    """Every hub this person has joined, in the order joined.

    Returns:
        The binding records.
    """
    return load_config()["bindings"]


def binding_for(hub_id: str) -> "dict | None":
    """The binding to one hub.

    Args:
        hub_id: The hub's id, as its welcome named it.

    Returns:
        The binding, or None when this person has not joined that hub.
    """
    for binding in bindings():
        if hub_id and binding["hub_id"] == hub_id:
            return binding
    return None


def find_binding(needle: str) -> "dict | None":
    """The binding a person named by the binding id, the hub id or its name.

    Args:
        needle: What the person typed.

    Returns:
        The first binding matching on any of the three, or None.
    """
    if not needle:
        return None
    for binding in bindings():
        if needle in (binding["id"], binding["hub_id"], binding["hub_name"]):
            return binding
    return None


# Held while one writer of this process reads, changes and writes the binding
# file, so no two of its threads write over each other.
BINDING_WRITE_LOCK = threading.RLock()


def _one_writer(change):
    """``change`` run while no other thread of this process writes the file."""

    @functools.wraps(change)
    def run(*args, **kwargs):
        with BINDING_WRITE_LOCK:
            return change(*args, **kwargs)

    return run


@_one_writer
def add_binding(binding: dict) -> None:
    """Keep one binding; one with the same ``id`` is replaced in place.

    Args:
        binding: The record; fields outside ``BINDING_KEYS`` are dropped.

    Raises:
        ValueError: When the record names no ``id``, ``gateway_url`` or
            ``token``, or ``ticket`` while pending.
        OSError: When the file cannot be written.
    """
    kept = _binding(binding)
    if not _is_complete(kept):
        raise ValueError("a binding needs an id, a gateway_url and a token")
    config = load_config()
    held = config["bindings"]
    for index, existing in enumerate(held):
        if existing["id"] == kept["id"]:
            held[index] = kept
            break
    else:
        held.append(kept)
    save_config(config)


@_one_writer
def remove_binding(binding_id: str) -> None:
    """Drop one binding; an id nobody holds changes nothing.

    Args:
        binding_id: The binding's id.

    Raises:
        OSError: When the file cannot be written.
    """
    config = load_config()
    config["bindings"] = [
        binding for binding in config["bindings"] if binding["id"] != binding_id
    ]
    save_config(config)


@_one_writer
def drop_repeated_hubs() -> list:
    """Keep one binding per hub id, the one joined last.

    Returns:
        The bindings dropped, in the order joined; empty when no hub id
        is held twice, and the file is then not written.

    Raises:
        OSError: When the file cannot be written.
    """
    config = load_config()
    held = config["bindings"]
    last = {binding["hub_id"]: index for index, binding in enumerate(held)}
    dropped = [
        binding
        for index, binding in enumerate(held)
        if binding["hub_id"] and last[binding["hub_id"]] != index
    ]
    if dropped:
        config["bindings"] = [
            binding
            for index, binding in enumerate(held)
            if not binding["hub_id"] or last[binding["hub_id"]] == index
        ]
        save_config(config)
    return dropped


def note_hub(binding_id: str, hub_id: str, hub_name: str) -> None:
    """Record what the hub's welcome said it is, on one binding.

    Args:
        binding_id: The binding the welcome arrived on.
        hub_id: The hub's id.
        hub_name: The hub's name.

    Raises:
        OSError: When the file cannot be written.
    """
    _note(binding_id, hub_id=str(hub_id), hub_name=str(hub_name))


def note_url(binding_id: str, gateway_url: str) -> None:
    """Record the address that last answered, on one binding.

    Args:
        binding_id: The binding the socket was opened for.
        gateway_url: The address it connected through.

    Raises:
        OSError: When the file cannot be written.
    """
    _note(binding_id, gateway_url=str(gateway_url))


def note_urls(binding_id: str, gateway_urls: list) -> None:
    """Record every address the hub's state names, on one binding.

    Args:
        binding_id: The binding the state arrived on.
        gateway_urls: The addresses, in the hub's order.

    Raises:
        OSError: When the file cannot be written.
    """
    _note(binding_id, gateway_urls=clean_urls(gateway_urls))


def note_overlays(binding_id: str, overlays: list) -> None:
    """Record the overlay objects the hub's state names, on one binding.

    Args:
        binding_id: The binding the state arrived on.
        overlays: The objects, in the hub's order.

    Raises:
        OSError: When the file cannot be written.
    """
    _note(binding_id, overlays=clean_overlays(overlays))


def note_overlay_choice(binding_id: str, is_on: bool, pick: str) -> None:
    """Record where a hub's virtual network stands, and the engine chosen.

    Args:
        binding_id: The binding to the hub.
        is_on: Whether the hub's virtual network is ``on``.
        pick: The provider chosen, empty for the hub's first.

    Raises:
        OSError: When the file cannot be written.
    """
    _note(binding_id, is_overlay_on=bool(is_on), overlay_pick=str(pick))


def clean_overlays(value) -> list:
    """The overlay objects as a binding keeps them.

    Args:
        value: What a link, a state or the file carried.

    Returns:
        Each object :func:`clean_overlay` reads, in order, the first of each
        provider only; empty when ``value`` is not a list.
    """
    kept: list = []
    for item in value if isinstance(value, list) else []:
        cleaned = clean_overlay(item)
        if cleaned is not None and all(
            other["provider"] != cleaned["provider"] for other in kept
        ):
            kept.append(cleaned)
    return kept


def clean_overlay(value) -> "dict | None":
    """One overlay object as a binding keeps it.

    Args:
        value: One object a link, a state or the file carried.

    Returns:
        ``{"provider", ...}`` with exactly the provider's own fields, each a
        stripped string, the EasyTier peer without its trailing slash; an
        EasyTier object also carries its ``mode``, and a console one its
        ``is_secure_mode``. None for anything else, an unknown provider or
        mode, or a missing required field among them.
    """
    if not isinstance(value, dict):
        return None
    provider = str(value.get("provider", "") or "")
    if provider not in OVERLAY_DEFAULT_MODES:
        return None
    mode = str(value.get("mode", "") or "") or OVERLAY_DEFAULT_MODES[provider]
    fields = OVERLAY_FIELDS.get((provider, mode))
    if fields is None:
        return None
    cleaned = {"provider": provider}
    if mode:
        cleaned["mode"] = mode
    if mode == "console":
        cleaned["is_secure_mode"] = value.get("is_secure_mode") is True
    for field in fields:
        text = str(value.get(field, "") or "").strip()
        if field == "peer":
            text = text.rstrip("/")
        if not text and field not in OVERLAY_OPTIONAL_FIELDS:
            return None
        cleaned[field] = text
    return cleaned


def clean_urls(value) -> list:
    """A list of addresses as a binding keeps them.

    Args:
        value: What a link, a state or the file carried.

    Returns:
        Each non-blank entry as a string without its trailing slash, in
        order, each once; empty when ``value`` is not a list.
    """
    kept: list = []
    for url in value if isinstance(value, list) else []:
        text = str(url).strip().rstrip("/")
        if text and text not in kept:
            kept.append(text)
    return kept


def stored_urls(binding: dict) -> list:
    """Every address a binding holds, in the hub's order.

    Args:
        binding: The binding.

    Returns:
        ``gateway_urls``, with ``gateway_url`` appended when it is not among
        them.
    """
    urls = list(binding.get(BINDING_URLS_KEY) or [])
    last = str(binding.get("gateway_url", "") or "")
    if last and last not in urls:
        urls.append(last)
    return urls


def dialable_urls(urls: list) -> list:
    """The addresses of a list whose scheme this client dials.

    Args:
        urls: Addresses as a binding keeps them.

    Returns:
        Each ``tcp://`` address, in order; every other scheme is skipped.
    """
    return [
        url
        for url in urls
        if urllib.parse.urlsplit(url).scheme == CLIENT_ADDRESS_SCHEME
        and urllib.parse.urlsplit(url).hostname
    ]


def hub_name_address(gateway_url: str) -> str:
    """The hub's address by its name, at the port of a stored one.

    Args:
        gateway_url: A stored address, for its port.

    Returns:
        ``tcp://hub.neutrino.internal:<port>``, which the transport resolves
        at each round; empty when the address names no port.
    """
    try:
        port = urllib.parse.urlsplit(gateway_url).port
    except ValueError:
        return ""
    if not port:
        return ""
    return f"{CLIENT_ADDRESS_SCHEME}://{CLIENT_HUB_NAME}:{port}"


def default_source_address(urls: list) -> str:
    """This machine's own address on the route to the hub.

    Read off a UDP socket connected to the first address naming an IPv4
    literal; no packet is sent.

    Args:
        urls: The hub's addresses, in the order to look for a literal.

    Returns:
        The address, or empty when no address names a literal or no route
        reaches it.
    """
    for url in urls:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            continue
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect((host, parts.port or 443))
            return str(probe.getsockname()[0])
        except OSError:
            return ""
        finally:
            probe.close()
    return ""


def exit_hub_id() -> str:
    """The hub whose AI gateway this person's tools point at.

    Returns:
        The hub's id, empty when none is chosen.
    """
    return load_config()["exit_hub_id"]


@_one_writer
def set_exit_hub_id(hub_id: str) -> None:
    """Choose the hub whose AI gateway this person's tools point at.

    Args:
        hub_id: The hub's id; empty chooses none.

    Raises:
        OSError: When the file cannot be written.
    """
    config = load_config()
    config["exit_hub_id"] = str(hub_id)
    save_config(config)


def join_payload(ticket: str) -> dict:
    """What this person sends to join.

    Args:
        ticket: The enrollment ticket from the link.

    Returns:
        ``{ticket, role, protocol, machine_id, name, software, platform}``.
    """
    return {
        "ticket": ticket,
        "role": CLIENT_ROLE,
        "protocol": PROTOCOL,
        "machine_id": _machine_id(),
        "name": socket.gethostname(),
        "software": f"{CLIENT_SOFTWARE_PREFIX}{CLIENT_VERSION}",
        "platform": platform_tuple(),
    }


def enroll(link: str) -> dict:
    """Store the binding of the hub the link points at, before any hub is asked.

    Args:
        link: The enrollment link from the hub.

    Returns:
        The binding stored: pending, with the link's ticket and key, its
        first address, every address and its overlays, a static key of its
        own, and an id of its own.

    Raises:
        EnrollmentError: If the link is unusable.
        OSError: When the binding file cannot be written.
    """
    gateway_urls, ticket, hub_key, overlays = parse_link(link)
    binding = _binding(
        {
            "id": BINDING_PENDING_ID_PREFIX + uuid.uuid4().hex,
            "name": socket.gethostname(),
            "gateway_url": gateway_urls[0],
            "gateway_urls": gateway_urls,
            "hub_key": hub_key,
            "private_key": make_private_key(),
            "ticket": ticket,
            BINDING_PENDING_KEY: True,
            "overlays": overlays,
        }
    )
    add_binding(binding)
    return binding


def joined_binding(binding: dict, binding_id: str, token: str) -> dict:
    """A pending binding as the hub completed it.

    Args:
        binding: The pending binding.
        binding_id: The binding's id the hub returned.
        token: The token the hub returned.

    Returns:
        The binding with the hub's id and token, no ticket and no longer
        pending.

    Raises:
        EnrollmentError: ``enroll_no_token`` when the id or the token is
            empty.
    """
    completed = _binding(
        dict(binding, id=binding_id, token=token, ticket="", is_pending=False)
    )
    if not completed["id"] or not completed["token"]:
        raise EnrollmentError("enroll_no_token")
    return completed


def moved_binding(binding: dict, hub_key: str, private_key: str) -> dict:
    """A 0.5 binding as it stands once moved to the transport.

    Args:
        binding: The binding, pinned by a certificate fingerprint.
        hub_key: The hub's static public key the move returned.
        private_key: This client's static private key the move recorded.

    Returns:
        The binding with the hub's key and its own, no fingerprint, and
        every ``https://`` address written as ``tcp://`` at the same host
        and port.
    """
    return _binding(
        dict(
            binding,
            hub_key=hub_key,
            private_key=private_key,
            fingerprint="",
            gateway_url=_moved_url(str(binding.get("gateway_url", ""))),
            gateway_urls=[
                _moved_url(url) for url in binding.get(BINDING_URLS_KEY) or []
            ],
        )
    )


def _moved_url(url: str) -> str:
    """An ``https://`` address as ``tcp://`` at the same host and port; any other as it is."""
    prefix = CLIENT_LEGACY_SCHEME + "://"
    if url.startswith(prefix):
        return CLIENT_ADDRESS_SCHEME + "://" + url[len(prefix) :]
    return url


@_one_writer
def replace_binding(binding_id: str, binding: dict) -> None:
    """Put a completed binding where a pending one was.

    A binding already held under the completed id gives way to it.

    Args:
        binding_id: The pending binding's id.
        binding: The completed binding.

    Raises:
        ValueError: When the completed binding names no id, address or token.
        OSError: When the file cannot be written.
    """
    kept = _binding(binding)
    if not _is_complete(kept):
        raise ValueError("a binding needs an id, a gateway_url and a token")
    config = load_config()
    held = config["bindings"]
    for index, existing in enumerate(held):
        if existing["id"] == binding_id:
            held[index] = kept
            break
    else:
        held.append(kept)
    config["bindings"] = [
        existing
        for existing in held
        if existing is kept or existing["id"] != kept["id"]
    ]
    save_config(config)


def _binding(raw: dict) -> dict:
    """One binding with every kept field, each a string but the lists and the
    flags; the ticket and the pending flag only while the join is pending."""
    flags = (BINDING_OVERLAY_ON_KEY, BINDING_PENDING_KEY)
    binding = {
        key: str(raw.get(key, "") or "")
        for key in BINDING_KEYS
        if key not in (BINDING_URLS_KEY, BINDING_OVERLAYS_KEY) + flags
    }
    binding[BINDING_URLS_KEY] = clean_urls(raw.get(BINDING_URLS_KEY))
    binding[BINDING_OVERLAYS_KEY] = clean_overlays(raw.get(BINDING_OVERLAYS_KEY))
    for key in flags:
        binding[key] = raw.get(key) is True
    if not binding[BINDING_PENDING_KEY]:
        binding.pop(BINDING_PENDING_KEY)
        binding.pop(BINDING_TICKET_KEY)
    return binding


@_one_writer
def _note(binding_id: str, **fields) -> None:
    """Write fields onto one binding; an id nobody holds changes nothing."""
    config = load_config()
    for binding in config["bindings"]:
        if binding["id"] == binding_id:
            binding.update(fields)
            save_config(config)
            return


def _is_complete(binding: dict) -> bool:
    """Whether a binding names an id, an address, the hub's key or a 0.5
    fingerprint, and a token, or a ticket while pending."""
    if binding.get(BINDING_PENDING_KEY):
        secret = binding[BINDING_TICKET_KEY]
    else:
        secret = binding["token"]
    has_pin = bool(binding["hub_key"] or binding["fingerprint"])
    return bool(binding["id"] and binding["gateway_url"] and secret and has_pin)


def _decoded(text: str) -> dict:
    """The object a link's payload holds, inflated from its base64url.

    Raises:
        EnrollmentError: ``link_unreadable`` when it is not one.
    """
    try:
        padded = text + "=" * (-len(text) % 4)
        packed = base64.urlsafe_b64decode(padded.encode())
        payload = json.loads(zlib.decompress(packed))
    except (binascii.Error, zlib.error, ValueError, UnicodeDecodeError) as error:
        raise EnrollmentError("link_unreadable") from error
    if not isinstance(payload, dict):
        raise EnrollmentError("link_unreadable")
    return payload


def _machine_id() -> str:
    """This installation's id, from the state store."""
    store = ClientServiceStore(
        path=os.path.join(detect_platform().config_dir(), CLIENT_STATE_FILE_NAME)
    )
    return store.machine_id()
