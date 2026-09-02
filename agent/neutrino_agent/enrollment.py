"""Joining a gateway, and leaving one.

A machine with no SSH — a Windows laptop, a tablet — cannot be reached by the
gateway, so it introduces itself instead: the owner pastes one enrollment link
into the agent's own page, and the agent posts to the gateway, which hands
back the token its heartbeats will carry. Nothing else has to be configured.

The link is ``neutrino://enroll/<payload>`` where the payload is base64url
over ``{"urls": [...], "token": ...}``. That alphabet holds no character a
shell splits or a URL escapes, so the link pastes into a terminal, a page or
a chat unquoted; and being one JSON object, later fields — a certificate
fingerprint — cost nothing.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64
import binascii
import json
import os
import socket
import uuid

from neutrino_agent.constants import AGENT_CONFIG_PATH
from neutrino_agent.http_channel import (
    GatewayHttpChannel,
    GatewayRefused,
    GatewayUnreachable,
)
from neutrino_agent.platform_info import platform_tuple

ENROLL_PATH = "/api/agent/enroll"


class EnrollmentError(RuntimeError):
    """Raised when a machine cannot join a gateway."""


LINK_PREFIX = "neutrino://enroll/"


def parse_link(link: str) -> "tuple[list, str]":
    """Pull the gateway addresses and enrollment token out of a link.

    A hub serves more than one network, and the address that reaches it
    depends on which one this machine is on, so the link carries every
    address the hub answers on rather than one somebody had to pick. The
    bare payload without its scheme is accepted too, because it is the part
    a partial copy loses last.

    Args:
        link: What the owner pasted.

    Returns:
        The gateway base URLs, in the order the hub offered them, and the
        enrollment token.

    Raises:
        EnrollmentError: If the link carries neither.
    """
    text = link.strip()
    if not text:
        raise EnrollmentError("paste the link from the gateway's Devices page")
    if text.startswith(LINK_PREFIX):
        text = text[len(LINK_PREFIX) :]
    try:
        padded = text + "=" * (-len(text) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        urls = [
            str(url).rstrip("/") for url in payload.get("urls", []) if str(url).strip()
        ]
        token = str(payload.get("token", ""))
    except (binascii.Error, ValueError, UnicodeDecodeError, AttributeError) as error:
        raise EnrollmentError(
            "that is not an enrollment link; copy the whole line from the "
            "gateway's Devices page"
        ) from error
    if not urls or not token:
        raise EnrollmentError("that link carries no gateway address and token")
    return urls, token


def load_config() -> dict:
    """Read the agent's configuration.

    Returns:
        The stored configuration, or an empty object when unconfigured.
    """
    try:
        with open(AGENT_CONFIG_PATH, "r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return {}


def save_config(config: dict) -> None:
    """Write the agent's configuration, readable only by root.

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


def is_configured() -> bool:
    """Whether the agent already belongs to a gateway."""
    config = load_config()
    return bool(config.get("gateway_url") and config.get("token"))


def config_stamp() -> int:
    """A marker that moves whenever the configuration file does.

    The running service compares it between beats, so a binding written by
    another process — ``nagent connect``, ``nagent disconnect`` — is adopted
    without a restart.

    Returns:
        The file's mtime in nanoseconds, or 0 when it does not exist.
    """
    try:
        return os.stat(AGENT_CONFIG_PATH).st_mtime_ns
    except OSError:
        return 0


def machine_id() -> str:
    """A stable identifier for this machine.

    Returns:
        The system's machine id where there is one, else a generated id kept
        in the agent's own configuration — a Windows laptop on the overlay has
        no LAN MAC the gateway could key it by.
    """
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, "r", encoding="utf-8") as stream:
                value = stream.read().strip()
            if value:
                return value
        except OSError:
            continue
    config = load_config()
    stored = config.get("device_id")
    if stored:
        return stored
    generated = uuid.uuid4().hex
    config["device_id"] = generated
    save_config(config)
    return generated


def enroll(link: str) -> dict:
    """Join the gateway the link points at.

    Every address in the link is tried in turn, because only one of them is
    on this machine's network and the link cannot know which.

    Args:
        link: The enrollment link from the gateway's Devices page.

    Returns:
        The stored configuration after joining.

    Raises:
        EnrollmentError: If the link is unusable or no address accepted it.
    """
    gateway_urls, enrollment_token = parse_link(link)
    payload = {
        "enrollment_token": enrollment_token,
        "device_id": machine_id(),
        "hostname": socket.gethostname(),
        "platform": platform_tuple(),
    }
    reply = None
    refusal = ""
    for gateway_url in gateway_urls:
        channel = GatewayHttpChannel(gateway_url=gateway_url, token="")
        try:
            reply = channel.post(ENROLL_PATH, payload)
            break
        except GatewayRefused as error:
            # The gateway answered and said no: the ticket is spent or has
            # expired. The other addresses reach the same gateway.
            raise EnrollmentError(
                "the gateway refused this link — it may have expired; mint a "
                "fresh one on the Devices page"
            ) from error
        except GatewayUnreachable as error:
            refusal = str(error)
    if reply is None:
        tried = ", ".join(gateway_urls)
        raise EnrollmentError(f"no gateway answered at {tried}: {refusal}")

    token = reply.get("token", "")
    if not token:
        raise EnrollmentError("the gateway sent no device token back")
    config = load_config()
    config.update(
        {
            "gateway_url": gateway_url,
            "token": token,
            "device_id": payload["device_id"],
        }
    )
    save_config(config)
    return config


def disconnect() -> None:
    """Forget the gateway, keeping the machine's own identity.

    The device id survives so re-joining the same gateway lands on the same
    device rather than creating a second one.
    """
    config = load_config()
    config.pop("gateway_url", None)
    config.pop("token", None)
    save_config(config)
