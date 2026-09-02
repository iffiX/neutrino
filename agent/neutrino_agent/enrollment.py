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


def parse_link(link: str) -> "tuple[list, str]":
    """Pull the gateway addresses and enrollment token out of a link.

    A hub serves more than one network, and the address that reaches it
    depends on which one this machine is on, so the link carries every
    address the hub answers on rather than one somebody had to pick.

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
    parsed = urllib.parse.urlparse(text)
    query = urllib.parse.parse_qs(parsed.query)
    urls = [url.rstrip("/") for url in query.get("url", []) if url.strip()]
    token = (query.get("token") or [""])[0] or parsed.fragment
    if not urls and parsed.scheme in ("http", "https"):
        urls = [f"{parsed.scheme}://{parsed.netloc}"]
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
