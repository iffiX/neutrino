"""Joining a hub as one person, leaving it, and the bindings kept in between.

The link is ``neutrino://enroll/<payload>`` where the payload is ``{"urls":
[...], "token": ..., "fp": ..., "role": "client", "overlays": [...]}`` as
JSON, compressed with zlib and written in base64url without padding. That
alphabet holds no character a shell splits or a URL escapes. A QR code
carries the same link. ``fp`` pins the hub: it is the SHA-256 fingerprint of
the agent port's TLS certificate, checked on every connection before
anything is sent. A link whose ``role`` is not ``client`` was made for a
device agent and is refused.

The bindings live in ``client.json`` in the person's own configuration
directory, mode 0600, one per hub joined: ``{"bindings": [{id, name, hub_id,
hub_name, gateway_url, gateway_urls, fingerprint, token, ticket, is_pending,
overlays, is_overlay_on, overlay_pick}], "exit_hub_id"}``, ``ticket`` and
``is_pending`` only on a pending join. A file without ``bindings`` reads as
none. A join stores its binding at once, ``is_pending`` with the link's
``ticket``, no token and an id of this machine's own; the session spends the
ticket at the first address that answers, and the binding then holds the
hub's id and token and no ticket. ``gateway_urls`` is every address the hub
answers on, from the link and then from each ``state`` frame;
``gateway_url`` is the one that last answered. A binding written by 0.3.0
has no list and reads as one with none. ``overlays`` is how this machine
joins each of the hub's virtual networks, the hub's preferred first, from
the link and then from each ``state``: one provider's own fields each, the
secret among them, which is why the file is 0600. ``is_overlay_on`` is
whether the hub's virtual network was last ``on``, which a start connects
once, and ``overlay_pick`` the provider the person chose, empty for the
first.

A connection round is the addresses in ``candidate_urls`` order: the address
``hub.neutrino.internal`` resolves to on the network this machine stands on,
then the hub's list in its own order, at a reconnect as at the first connect.
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
import time
import urllib.parse
import uuid
import zlib

from neutrino_client import CLIENT_VERSION, edition
from neutrino_client.constants import (
    CLIENT_CONFIG_FILE_NAME,
    CLIENT_HUB_NAME,
    CLIENT_JOIN_PATH,
    CLIENT_LEAVE_PATH,
    CLIENT_LEAVE_TELL_TIMEOUT_S,
    CLIENT_ROLE,
    CLIENT_SOFTWARE_PREFIX,
    CLIENT_STATE_FILE_NAME,
    PROTOCOL,
)
from neutrino_client.core import files
from neutrino_client.core.channel import GatewayHttpChannel
from neutrino_client.exceptions import (
    EnrollmentError,
    GatewayProtocolRefused,
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
)
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
# The string fields each overlay object carries, by provider and, for
# EasyTier, by mode. An EasyTier object that names no mode is a manual one,
# as a hub before the console mode sends it. The edition table adds the
# objects of the engines it carries.
OVERLAY_FIELDS = {
    ("easytier", "manual"): ("network_name", "network_secret", "peer", "hub_address"),
    ("easytier", "console"): ("config_server", "hub_address"),
}
OVERLAY_DEFAULT_MODES = {"easytier": "manual"}
# The fields that may be empty: a hub that does not know its own virtual
# address names none.
OVERLAY_OPTIONAL_FIELDS = ("hub_address",)


def parse_link(link: str) -> "tuple[list, str, str, list]":
    """Pull the addresses, ticket, fingerprint and overlays out of a link.

    Args:
        link: What the person pasted; the bare payload without its scheme
            is accepted too.

    Returns:
        The hub base URLs in the order the hub offered them, the enrollment
        ticket, the certificate fingerprint the hub pins, empty when the
        link carries none, and the overlay objects this client can read,
        the hub's preferred first, empty when the link carries none.

    Raises:
        EnrollmentError: ``link_missing`` for an empty paste,
            ``link_unreadable`` for something that is not a link,
            ``link_incomplete`` for a link without an address or ticket,
            ``link_not_for_client`` for a link whose role is not ``client``.
    """
    text = link.strip()
    if not text:
        raise EnrollmentError("link_missing")
    if text.startswith(LINK_PREFIX):
        text = text[len(LINK_PREFIX) :]
    return read_link_object(_decoded(text))


def read_link_object(payload: dict) -> "tuple[list, str, str, list]":
    """Pull the addresses, ticket, fingerprint and overlays out of a link's object.

    Args:
        payload: The object a link carries.

    Returns:
        The same four as :func:`parse_link`.

    Raises:
        EnrollmentError: ``link_unreadable``, ``link_incomplete`` or
            ``link_not_for_client``, as for :func:`parse_link`.
    """
    try:
        urls = [
            str(url).rstrip("/") for url in payload.get("urls", []) if str(url).strip()
        ]
        token = str(payload.get("token", ""))
        fingerprint = str(payload.get("fp", "")).strip().lower()
        role = str(payload.get("role", ""))
        overlays = clean_overlays(payload.get("overlays"))
    except (binascii.Error, ValueError, UnicodeDecodeError, AttributeError) as error:
        raise EnrollmentError("link_unreadable") from error
    if not urls or not token:
        raise EnrollmentError("link_incomplete")
    if role != CLIENT_ROLE:
        raise EnrollmentError("link_not_for_client", {"role": role})
    return urls, token, fingerprint, overlays


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
    every_fields, default_modes, optional_fields = _overlay_objects()
    provider = str(value.get("provider", "") or "")
    if provider not in default_modes:
        return None
    mode = str(value.get("mode", "") or "") or default_modes[provider]
    fields = every_fields.get((provider, mode))
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
        if not text and field not in optional_fields:
            return None
        cleaned[field] = text
    return cleaned


def _overlay_objects() -> tuple:
    """The overlay objects a binding keeps: EasyTier's and the table's.

    Returns:
        ``(fields, default_modes, optional_fields)``, shaped as
        :data:`OVERLAY_FIELDS`, :data:`OVERLAY_DEFAULT_MODES` and
        :data:`OVERLAY_OPTIONAL_FIELDS`.
    """
    fields = dict(OVERLAY_FIELDS)
    default_modes = dict(OVERLAY_DEFAULT_MODES)
    optional_fields = OVERLAY_OPTIONAL_FIELDS
    for added in edition.hooks("overlay_objects"):
        fields.update(added["fields"])
        default_modes.update(added["default_modes"])
        optional_fields += tuple(added["optional_fields"])
    return fields, default_modes, optional_fields


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


def candidate_urls(binding: dict, name_url: str = "") -> list:
    """The addresses one connection round connects to, in order.

    Args:
        binding: The binding.
        name_url: What :func:`hub_name_url` returned, or empty.

    Returns:
        The name's address, then the stored list in the hub's order, each
        once; the address that last answered keeps its place in the list,
        or comes last when the list does not hold it.
    """
    return clean_urls([name_url, *stored_urls(binding)])


def resolve_hub_address() -> str:
    """The IPv4 address the hub's name resolves to on this network.

    Returns:
        The address, or empty when the name does not resolve.
    """
    try:
        found = socket.getaddrinfo(
            CLIENT_HUB_NAME, None, socket.AF_INET, socket.SOCK_STREAM
        )
    except OSError:
        return ""
    return str(found[0][4][0]) if found else ""


def hub_name_url(gateway_url: str) -> str:
    """The hub's address by its name, on the scheme and port of a stored one.

    Args:
        gateway_url: A stored address, for its scheme and port.

    Returns:
        ``<scheme>://<address>:<port>``, or empty when the name does not
        resolve.
    """
    address = resolve_hub_address()
    if not address:
        return ""
    parts = urllib.parse.urlsplit(gateway_url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return f"{parts.scheme}://{address}:{port}"


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
        The binding stored: pending, with the link's ticket, its first
        address, every address and its overlays, and an id of its own.

    Raises:
        EnrollmentError: If the link is unusable.
        OSError: When the binding file cannot be written.
    """
    gateway_urls, ticket, fingerprint, overlays = parse_link(link)
    binding = _binding(
        {
            "id": BINDING_PENDING_ID_PREFIX + uuid.uuid4().hex,
            "name": socket.gethostname(),
            "gateway_url": gateway_urls[0],
            "gateway_urls": gateway_urls,
            "fingerprint": fingerprint,
            "ticket": ticket,
            BINDING_PENDING_KEY: True,
            "overlays": overlays,
        }
    )
    add_binding(binding)
    return binding


def complete_join(binding: dict, gateway_url: str) -> dict:
    """Spend a pending binding's ticket at one address that answered.

    Args:
        binding: The pending binding.
        gateway_url: The address whose certificate matched the pin.

    Returns:
        The binding as the hub completed it: the hub's id and token, that
        address, no ticket and no longer pending.

    Raises:
        EnrollmentError: When the hub refused the join: ``ticket_spent``
            or another code it named, ``enroll_refused`` for one it did
            not, the protocol refusals with their numbers, or
            ``enroll_no_token`` for a reply without an id or a token.
        GatewayUntrusted: When what answers is not the pinned hub.
        GatewayUnreachable: When the address stops answering.
    """
    channel = GatewayHttpChannel(
        gateway_url=gateway_url, fingerprint=binding["fingerprint"]
    )
    try:
        reply = channel.post(CLIENT_JOIN_PATH, join_payload(binding["ticket"]))
    except GatewayProtocolRefused as error:
        raise EnrollmentError(
            error.code,
            {"peer": error.peer, "hub": error.hub, "min": error.minimum},
        ) from error
    except GatewayRefused as error:
        raise EnrollmentError(error.code or "enroll_refused", error.params) from error
    except GatewayRefusedDetail as error:
        raise EnrollmentError(error.code, error.params) from error
    completed = _binding(
        dict(
            binding,
            id=reply.get("id", ""),
            token=reply.get("token", ""),
            gateway_url=gateway_url,
            ticket="",
            is_pending=False,
        )
    )
    if not completed["id"] or not completed["token"]:
        raise EnrollmentError("enroll_no_token")
    return completed


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


def leave(binding: dict) -> None:
    """Tell one hub this person is leaving it, once, within
    ``CLIENT_LEAVE_TELL_TIMEOUT_S``.

    The address that last answered is tried first, then the rest the
    binding holds, until one answers; each address gets an equal share of
    the time, so one that hangs cannot spend it all. The binding itself is
    not touched.

    Args:
        binding: The binding to the hub.

    Raises:
        GatewayUntrusted: When what answers is not the pinned hub.
        GatewayRefused: When the hub rejected the token.
        GatewayRefusedDetail: When the hub refused with another code.
        GatewayUnreachable: When no address answered in time.
    """
    urls = clean_urls([binding.get("gateway_url", ""), *stored_urls(binding)])
    share_s = CLIENT_LEAVE_TELL_TIMEOUT_S / max(len(urls), 1)
    deadline = time.monotonic() + CLIENT_LEAVE_TELL_TIMEOUT_S
    unreachable = GatewayUnreachable("the binding holds no address")
    for url in urls:
        left_s = deadline - time.monotonic()
        if left_s <= 0:
            break
        channel = GatewayHttpChannel(
            gateway_url=url,
            fingerprint=binding["fingerprint"],
            timeout=min(share_s, left_s),
        )
        try:
            channel.post(
                CLIENT_LEAVE_PATH, {"id": binding["id"], "token": binding["token"]}
            )
            return
        except GatewayRefusedDetail:
            raise
        except GatewayUnreachable as error:
            unreachable = error
    raise unreachable


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
    """Whether a binding names a hub, an id and a token, or a ticket while pending."""
    if binding.get(BINDING_PENDING_KEY):
        secret = binding[BINDING_TICKET_KEY]
    else:
        secret = binding["token"]
    return bool(binding["id"] and binding["gateway_url"] and secret)


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
