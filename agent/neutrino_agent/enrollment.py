"""Joining a gateway, and leaving one.

A machine with no SSH — a Windows laptop, a tablet — cannot be reached by the
gateway, so it introduces itself instead: the owner pastes one enrollment link
into the agent's own page, and the agent posts to the gateway, which hands
back the token its heartbeats will carry. Nothing else has to be configured.

The link is ``neutrino://enroll?url=<gateway>&token=<enrollment token>``, and
a plain ``http://gateway/enroll#<token>`` URL is accepted too, because a link
that can be typed from a phone screen is worth more than a tidy scheme.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import socket
import urllib.parse
import uuid

from neutrino_agent.constants import AGENT_CONFIG_PATH
from neutrino_agent.http_channel import GatewayHttpChannel, GatewayUnreachable
from neutrino_agent.platform_info import platform_tuple

ENROLL_PATH = "/api/agent/enroll"


class EnrollmentError(RuntimeError):
    """Raised when a machine cannot join a gateway."""


def parse_link(link: str) -> "tuple[str, str]":
    """Pull the gateway address and enrollment token out of a link.

    Args:
        link: What the owner pasted.

    Returns:
        The gateway base URL and the enrollment token.

    Raises:
        EnrollmentError: If the link carries neither.
    """
    text = link.strip()
    if not text:
        raise EnrollmentError("paste the link from the gateway's Devices page")
    parsed = urllib.parse.urlparse(text)
    query = urllib.parse.parse_qs(parsed.query)
    url = (query.get("url") or [""])[0]
    token = (query.get("token") or [""])[0] or parsed.fragment
    if not url and parsed.scheme in ("http", "https"):
        url = f"{parsed.scheme}://{parsed.netloc}"
    if not url or not token:
        raise EnrollmentError("that link carries no gateway address and token")
    return url.rstrip("/"), token


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

    Args:
        link: The enrollment link from the gateway's Devices page.

    Returns:
        The stored configuration after joining.

    Raises:
        EnrollmentError: If the link is unusable or the gateway refuses.
    """
    gateway_url, enrollment_token = parse_link(link)
    payload = {
        "enrollment_token": enrollment_token,
        "device_id": machine_id(),
        "hostname": socket.gethostname(),
        "platform": platform_tuple(),
    }
    channel = GatewayHttpChannel(gateway_url=gateway_url, token="")
    try:
        reply = channel.post(ENROLL_PATH, payload)
    except GatewayUnreachable as error:
        raise EnrollmentError(f"the gateway did not accept this: {error}")

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
