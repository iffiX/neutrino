"""Joining a hub as one person, leaving it, and the bindings kept in between.

The link is ``neutrino://enroll/<payload>`` where the payload is base64url
over ``{"urls": [...], "token": ..., "fp": ..., "role": "client"}``. That
alphabet holds no character a shell splits or a URL escapes. ``fp`` pins the
hub: it is the SHA-256 fingerprint of the agent port's TLS certificate,
checked on every connection before anything is sent. A link whose ``role``
is not ``client`` was made for a device agent and is refused.

The bindings live in ``client.json`` in the person's own configuration
directory, mode 0600, one per hub joined:
``{"bindings": [{id, name, hub_id, hub_name, gateway_url, fingerprint,
token}], "exit_hub_id"}``. A file without ``bindings`` reads as none.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import socket

from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import (
    CLIENT_CONFIG_FILE_NAME,
    CLIENT_JOIN_PATH,
    CLIENT_LEAVE_PATH,
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
    GatewayUnreachable,
    GatewayUntrusted,
)
from neutrino_client.platforms.detect import detect_platform, platform_tuple
from neutrino_client.services.store import ClientServiceStore

LINK_PREFIX = "neutrino://enroll/"
# What one binding keeps, every field a string.
BINDING_KEYS = (
    "id",
    "name",
    "hub_id",
    "hub_name",
    "gateway_url",
    "fingerprint",
    "token",
)


def parse_link(link: str) -> "tuple[list, str, str]":
    """Pull the addresses, enrollment ticket and fingerprint out of a link.

    Args:
        link: What the person pasted; the bare payload without its scheme
            is accepted too.

    Returns:
        The hub base URLs in the order the hub offered them, the enrollment
        ticket, and the certificate fingerprint the hub pins, empty when the
        link carries none.

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
    try:
        padded = text + "=" * (-len(text) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        urls = [
            str(url).rstrip("/") for url in payload.get("urls", []) if str(url).strip()
        ]
        token = str(payload.get("token", ""))
        fingerprint = str(payload.get("fp", "")).strip().lower()
        role = str(payload.get("role", ""))
    except (binascii.Error, ValueError, UnicodeDecodeError, AttributeError) as error:
        raise EnrollmentError("link_unreadable") from error
    if not urls or not token:
        raise EnrollmentError("link_incomplete")
    if role != CLIENT_ROLE:
        raise EnrollmentError("link_not_for_client", {"role": role})
    return urls, token, fingerprint


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


def add_binding(binding: dict) -> None:
    """Keep one binding; one with the same ``id`` is replaced in place.

    Args:
        binding: The record; fields outside ``BINDING_KEYS`` are dropped.

    Raises:
        ValueError: When the record names no ``id``, ``gateway_url`` or
            ``token``.
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
    config = load_config()
    for binding in config["bindings"]:
        if binding["id"] == binding_id:
            binding["hub_id"] = str(hub_id)
            binding["hub_name"] = str(hub_name)
            save_config(config)
            return


def exit_hub_id() -> str:
    """The hub whose AI gateway this person's tools point at.

    Returns:
        The hub's id, empty when none is chosen.
    """
    return load_config()["exit_hub_id"]


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
    """Join the hub the link points at.

    Every address in the link is tried in turn, because only one of them is
    on this machine's network and the link cannot know which.

    Args:
        link: The enrollment link from the hub.

    Returns:
        The binding stored.

    Raises:
        EnrollmentError: If the link is unusable, the fingerprint does not
            match what answers, the hub does not speak this client's
            protocol, the hub refused the ticket, the reply names no id or
            token, or no address answered.
    """
    gateway_urls, ticket, fingerprint = parse_link(link)
    payload = join_payload(ticket)
    reply = None
    refusal = ""
    for gateway_url in gateway_urls:
        channel = GatewayHttpChannel(gateway_url=gateway_url, fingerprint=fingerprint)
        try:
            reply = channel.post(CLIENT_JOIN_PATH, payload)
            break
        except GatewayProtocolRefused as error:
            raise EnrollmentError(
                error.code,
                {"peer": error.peer, "hub": error.hub, "min": error.minimum},
            ) from error
        except GatewayRefused as error:
            raise EnrollmentError("enroll_refused") from error
        except GatewayUntrusted as error:
            raise EnrollmentError("hub_untrusted", {"url": gateway_url}) from error
        except GatewayUnreachable as error:
            refusal = str(error)
    if reply is None:
        raise EnrollmentError(
            "hub_unreachable", {"detail": refusal, "urls": ", ".join(gateway_urls)}
        )

    binding = _binding(
        {
            "id": reply.get("id", ""),
            "name": payload["name"],
            "gateway_url": gateway_url,
            "fingerprint": fingerprint,
            "token": reply.get("token", ""),
        }
    )
    if not _is_complete(binding):
        raise EnrollmentError("enroll_no_token")
    add_binding(binding)
    return binding


def leave(binding: dict) -> None:
    """Tell one hub this person is leaving it.

    The binding itself stays until the caller removes it.

    Args:
        binding: The binding to the hub.

    Raises:
        GatewayUntrusted: When what answers is not the pinned hub.
        GatewayRefused: When the hub rejected the token.
        GatewayUnreachable: When the hub cannot be reached.
    """
    channel = GatewayHttpChannel(
        gateway_url=binding["gateway_url"], fingerprint=binding["fingerprint"]
    )
    channel.post(CLIENT_LEAVE_PATH, {"id": binding["id"], "token": binding["token"]})


def _binding(raw: dict) -> dict:
    """One binding with every kept field, each a string."""
    return {key: str(raw.get(key, "") or "") for key in BINDING_KEYS}


def _is_complete(binding: dict) -> bool:
    """Whether a binding names a hub, a token and an id."""
    return bool(binding["id"] and binding["gateway_url"] and binding["token"])


def _machine_id() -> str:
    """This installation's id, from the state store."""
    store = ClientServiceStore(
        path=os.path.join(detect_platform().config_dir(), CLIENT_STATE_FILE_NAME)
    )
    return store.machine_id()
