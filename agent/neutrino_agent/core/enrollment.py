"""Joining a hub, leaving one, and the binding file in between.

A machine introduces itself: the owner pastes one enrollment link into
``nagent join``, the agent spends the link's ticket at the hub, and the hub
hands back the binding its hello will carry. Nothing else is configured.

The link is ``neutrino://enroll/<payload>`` where the payload is base64url
over ``{"urls": [...], "token": ..., "fp": ..., "role": "agent"}``. That
alphabet holds no character a shell splits or a URL escapes. ``fp`` pins the
hub: the SHA-256 fingerprint of the agent port's TLS certificate, checked on
every connection before anything is sent. A link whose role is not ``agent``
was made for a client and is refused.

The binding file is ``{gateway_url, id, token, fingerprint, machine_id}``,
root-owned, mode 0600. A file missing any field is an unbound agent.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64
import binascii
import json
import os
import socket

from neutrino_agent import AGENT_VERSION
from neutrino_agent.constants import (
    AGENT_CONFIG_PATH,
    AGENT_ROLE,
    AGENT_SOFTWARE_PREFIX,
    PROTOCOL,
)
from neutrino_agent.core.channel import BindingHttpClient
from neutrino_agent.exceptions import (
    EnrollmentError,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
    PlatformUnsupportedError,
)
from neutrino_agent.platforms.detect import detect_platform, platform_tuple

LINK_PREFIX = "neutrino://enroll/"
# What the binding file holds, every field a string.
BINDING_KEYS = ("gateway_url", "id", "token", "fingerprint", "machine_id")


def parse_link(link: str) -> "tuple[list, str, str, str]":
    """Pull the addresses, ticket, fingerprint and role out of a link.

    The bare payload without its scheme is accepted too, because it is the
    part a partial copy loses last.

    Args:
        link: What the owner pasted.

    Returns:
        The hub base URLs in the order the hub offered them, the ticket,
        the certificate fingerprint the hub pins, empty when the link carries
        none, and the role the link was made for.

    Raises:
        EnrollmentError: If the link is unreadable or carries no address or
            ticket, with the words for this side; ``link_not_for_agent``,
            whose ``params`` name the link's ``role``, when it was made for
            another role.
    """
    text = link.strip()
    if not text:
        raise EnrollmentError("paste the link from the hub's Devices page")
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
        raise EnrollmentError(
            "that is not an enrollment link; copy the whole line from the "
            "hub's Devices page"
        ) from error
    if not urls or not token:
        raise EnrollmentError("that link carries no hub address and ticket")
    if role != AGENT_ROLE:
        raise EnrollmentError(
            "link_not_for_agent", code="link_not_for_agent", params={"role": role}
        )
    return urls, token, fingerprint, role


def load_config() -> dict:
    """Read the binding file as it is.

    Returns:
        The stored object, or an empty one when the file is absent or
        unreadable.
    """
    try:
        with open(AGENT_CONFIG_PATH, "r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return {}


def load_binding() -> dict:
    """The binding, complete or nothing.

    Returns:
        ``{gateway_url, id, token, fingerprint, machine_id}``, or an empty
        object when the file is absent, misses any field, or names no hub,
        id or token. The fingerprint and the machine id may be empty.
    """
    config = load_config()
    if not isinstance(config, dict) or any(key not in config for key in BINDING_KEYS):
        return {}
    binding = {key: str(config.get(key, "") or "") for key in BINDING_KEYS}
    if not (binding["gateway_url"] and binding["id"] and binding["token"]):
        return {}
    return binding


def save_config(config: dict) -> None:
    """Write the binding file, readable only by root.

    Args:
        config: What to store.
    """
    directory = os.path.dirname(AGENT_CONFIG_PATH)
    os.makedirs(directory, exist_ok=True)
    with open(AGENT_CONFIG_PATH, "w", encoding="utf-8") as stream:
        json.dump(config, stream, indent=2)
        stream.write("\n")
    try:
        os.chmod(AGENT_CONFIG_PATH, 0o600)
    except OSError:
        pass


def remove_binding() -> None:
    """Delete the binding file; a file already gone is no error."""
    try:
        os.unlink(AGENT_CONFIG_PATH)
    except FileNotFoundError:
        pass


def is_bound() -> bool:
    """Whether this machine holds a complete binding."""
    return bool(load_binding())


def config_stamp() -> int:
    """A marker that moves whenever the binding file does.

    The running service compares it between beats, so a binding written or
    removed by another process is adopted without a restart.

    Returns:
        The file's mtime in nanoseconds, or 0 when it does not exist.
    """
    try:
        return os.stat(AGENT_CONFIG_PATH).st_mtime_ns
    except OSError:
        return 0


def join_payload(ticket: str, *, platform=None) -> dict:
    """What this machine sends to join.

    Args:
        ticket: The ticket from the link.
        platform: The machine's platform, asked for the machine id; None
            detects it.

    Returns:
        ``{ticket, role, protocol, machine_id, name, software, platform}``,
        the machine id empty where the platform keeps none.
    """
    platform = platform if platform is not None else detect_platform()
    try:
        machine_id = platform.read_machine_id()
    except PlatformUnsupportedError:
        machine_id = ""
    return {
        "ticket": ticket,
        "role": AGENT_ROLE,
        "protocol": PROTOCOL,
        "machine_id": machine_id,
        "name": socket.gethostname(),
        "software": f"{AGENT_SOFTWARE_PREFIX}{AGENT_VERSION}",
        "platform": platform_tuple(),
    }


def enroll(link: str, *, platform=None) -> dict:
    """Join the hub the link points at.

    Every address in the link is tried in turn, because only one of them is
    on this machine's network and the link cannot know which.

    Args:
        link: The enrollment link from the hub's Devices page.
        platform: The machine's platform; None detects it.

    Returns:
        The binding stored.

    Raises:
        EnrollmentError: If the link is unusable, the fingerprint does not
            match what answers, the hub refused with a code, the reply
            names no binding, or no address answered. A hub's refusal
            carries its ``code`` and ``params``.
    """
    gateway_urls, ticket, fingerprint, _ = parse_link(link)
    payload = join_payload(ticket, platform=platform)
    reply = None
    failure = ""
    for gateway_url in gateway_urls:
        client = BindingHttpClient(gateway_url=gateway_url, fingerprint=fingerprint)
        try:
            reply = client.join(payload)
            break
        except GatewayRefusedDetail as error:
            raise EnrollmentError(
                error.code, code=error.code, params=error.params
            ) from error
        except GatewayUntrusted as error:
            raise EnrollmentError(
                f"{gateway_url} presented a certificate this link does not "
                f"pin; generate a fresh link on the hub's Devices page"
            ) from error
        except GatewayUnreachable as error:
            failure = str(error)
    if reply is None:
        tried = ", ".join(gateway_urls)
        raise EnrollmentError(f"no hub answered at {tried}: {failure}")

    binding = {
        "gateway_url": gateway_url,
        "id": str(reply.get("id", "") or ""),
        "token": str(reply.get("token", "") or ""),
        "fingerprint": fingerprint,
        "machine_id": payload["machine_id"],
    }
    if not binding["id"] or not binding["token"]:
        raise EnrollmentError("the hub sent no binding back")
    save_config(binding)
    return binding


def unbind() -> dict:
    """Give the binding back to the hub and delete the file.

    The file goes whether or not the hub could be told, so a hub that is
    gone does not hold the machine.

    Returns:
        Empty when the hub took the leave, ``{"code", "params"}`` when it
        could not be told, and empty with nothing posted when the machine
        held no binding.
    """
    binding = load_binding()
    outcome: dict = {}
    if binding:
        client = BindingHttpClient(
            gateway_url=binding["gateway_url"], fingerprint=binding["fingerprint"]
        )
        try:
            client.leave(binding["id"], binding["token"])
        except GatewayRefusedDetail as error:
            outcome = {"code": error.code, "params": dict(error.params)}
        except GatewayUntrusted:
            outcome = {"code": "hub_untrusted", "params": {}}
        except GatewayUnreachable as error:
            outcome = {"code": "hub_unreachable", "params": {"detail": str(error)}}
    remove_binding()
    return outcome
