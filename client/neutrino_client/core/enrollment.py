"""Joining a hub as one person, and leaving it.

The link is ``neutrino://enroll/<payload>`` where the payload is base64url
over ``{"urls": [...], "token": ..., "fp": ..., "kind": "client"}``. That
alphabet holds no character a shell splits or a URL escapes. ``fp`` pins the
hub: it is the SHA-256 fingerprint of the agent port's TLS certificate,
checked on every connection before anything is sent. A link whose ``kind``
is not ``client`` was made for a device agent and is refused.

The binding lives in the person's own configuration directory, mode 0600,
and names no machine: the hub knows a client by the token it issued.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import base64
import binascii
import json
import os
import socket

from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import CLIENT_CONFIG_FILE_NAME, CLIENT_ENROLL_PATH
from neutrino_client.core.channel import GatewayHttpChannel
from neutrino_client.exceptions import (
    EnrollmentError,
    GatewayRefused,
    GatewayUnreachable,
    GatewayUntrusted,
    GatewayVersionRefused,
)
from neutrino_client.platforms.detect import detect_platform, platform_tuple

LINK_PREFIX = "neutrino://enroll/"
LINK_KIND = "client"


def parse_link(link: str) -> "tuple[list, str, str]":
    """Pull the addresses, enrollment token and fingerprint out of a link.

    Args:
        link: What the person pasted; the bare payload without its scheme
            is accepted too.

    Returns:
        The hub base URLs in the order the hub offered them, the enrollment
        token, and the certificate fingerprint the hub pins, empty when the
        link carries none.

    Raises:
        EnrollmentError: ``link_missing`` for an empty paste,
            ``link_unreadable`` for something that is not a link,
            ``link_incomplete`` for a link without an address or token,
            ``link_not_for_client`` for a device agent's link.
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
        kind = str(payload.get("kind", ""))
    except (binascii.Error, ValueError, UnicodeDecodeError, AttributeError) as error:
        raise EnrollmentError("link_unreadable") from error
    if not urls or not token:
        raise EnrollmentError("link_incomplete")
    if kind != LINK_KIND:
        raise EnrollmentError("link_not_for_client", {"kind": kind})
    return urls, token, fingerprint


def config_path() -> str:
    """Where this person's binding lives.

    Returns:
        The absolute path of ``client.json`` under the platform's
        configuration directory.
    """
    return os.path.join(detect_platform().config_dir(), CLIENT_CONFIG_FILE_NAME)


def load_config() -> dict:
    """Read the binding.

    Returns:
        The stored configuration, or an empty object when unconfigured.
    """
    try:
        with open(config_path(), "r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(config: dict) -> None:
    """Write the binding, readable only by this person.

    Args:
        config: What to store.
    """
    path = config_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(config, stream, indent=2)
        stream.write("\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def is_configured() -> bool:
    """Whether this person already belongs to a hub."""
    config = load_config()
    return bool(config.get("gateway_url") and config.get("token"))


def config_stamp() -> int:
    """A marker that moves whenever the binding file does.

    The resident compares it between polls, so a binding written by
    ``nclient connect`` or ``nclient disconnect`` is adopted without a
    restart.

    Returns:
        The file's mtime in nanoseconds, or 0 when it does not exist.
    """
    try:
        return os.stat(config_path()).st_mtime_ns
    except OSError:
        return 0


def enroll_payload() -> dict:
    """What this person sends to join.

    Returns:
        ``{"hostname", "client_version", "platform"}``; the enrollment token
        is added by :func:`enroll`.
    """
    return {
        "hostname": socket.gethostname(),
        "client_version": CLIENT_VERSION,
        "platform": platform_tuple(),
    }


def enroll(link: str) -> dict:
    """Join the hub the link points at.

    Every address in the link is tried in turn, because only one of them is
    on this machine's network and the link cannot know which.

    Args:
        link: The enrollment link from the hub.

    Returns:
        The stored configuration after joining.

    Raises:
        EnrollmentError: If the link is unusable, the fingerprint does not
            match what answers, this client is newer than the hub, the hub
            refused the ticket, or no address answered.
    """
    gateway_urls, enrollment_token, fingerprint = parse_link(link)
    payload = {"enrollment_token": enrollment_token, **enroll_payload()}
    reply = None
    refusal = ""
    for gateway_url in gateway_urls:
        channel = GatewayHttpChannel(
            gateway_url=gateway_url, token="", fingerprint=fingerprint
        )
        try:
            reply = channel.post(CLIENT_ENROLL_PATH, payload)
            break
        except GatewayVersionRefused as error:
            raise EnrollmentError(
                "client_newer_than_hub",
                {
                    "hub_version": error.hub_version,
                    "client_version": error.client_version,
                },
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

    token = str(reply.get("token", ""))
    if not token:
        raise EnrollmentError("enroll_no_token")
    config = load_config()
    config.update(
        {
            "gateway_url": gateway_url,
            "token": token,
            "fingerprint": fingerprint,
            "client_id": str(reply.get("client_id", "")),
        }
    )
    save_config(config)
    return config


def disconnect() -> None:
    """Forget the hub."""
    config = load_config()
    for key in ("gateway_url", "token", "fingerprint", "client_id"):
        config.pop(key, None)
    save_config(config)
