"""Joining a hub, leaving one, and the binding file in between.

A machine introduces itself: the owner pastes one enrollment link into
``nagent join``, the agent's transport spends the link's ticket at the hub,
and the hub hands back the binding every later session runs under. Nothing
else is configured.

The link is ``neutrino://enroll/<payload>`` where the payload is
``{"urls": [...], "token": ..., "key": ..., "role": "agent"}`` as JSON,
compressed with zlib and written in base64url without padding. That
alphabet holds no character a shell splits or a URL escapes. ``key`` is the
hub's static public key: the transport knocks under it, and nothing leaves
the machine before an answer only the key's holder can make opens. A link
whose role is not ``agent`` was made for a client and is refused.

The binding file is ``{gateway_url, gateway_urls, id, token, hub_key,
private_key, machine_id}``, root-owned, mode 0600. ``private_key`` is this
agent's own static key, made when the link is first read. ``gateway_urls``
is every address the hub answers on, from the link and then from each
``state`` frame; ``gateway_url`` is the one that last answered. A file
missing any other field is an unbound agent.

A binding an agent of 0.5 left holds a certificate ``fingerprint`` and no
``hub_key``. The agent dials nothing for it and records ``hub_key_missing``
until ``nagent join`` binds the machine again.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import os
import socket
import urllib.parse
import zlib

from neutrino_agent import AGENT_VERSION
from neutrino_agent.constants import (
    AGENT_CONFIG_NAME,
    AGENT_HUB_NAME,
    AGENT_ROLE,
    AGENT_SOFTWARE_PREFIX,
    PROTOCOL,
)
from neutrino_agent.core.static_key import make_private_key
from neutrino_agent.exceptions import (
    EnrollmentError,
    GatewayUnreachable,
    PlatformUnsupportedError,
)
from neutrino_agent.platforms.detect import detect_platform, platform_tuple
from neutrino_agent.transport.constants import TRANSPORT_JOIN_TIMEOUT_S
from neutrino_agent.transport.process import one_shot_transport

# The binding file, under this platform's own data root.
AGENT_CONFIG_PATH = os.path.join(detect_platform().agent_data_dir(), AGENT_CONFIG_NAME)

LINK_PREFIX = "neutrino://enroll/"
# What the binding file holds: every field a string but the list of every
# address the hub answers on.
BINDING_KEYS = (
    "gateway_url",
    "gateway_urls",
    "id",
    "token",
    "hub_key",
    "private_key",
    "machine_id",
)
BINDING_URLS_KEY = "gateway_urls"
# What a binding of 0.5 holds in place of the hub's key.
LEGACY_FINGERPRINT_KEY = "fingerprint"
# The scheme of the transport's addresses.
ADDRESS_SCHEME = "tcp"
HEX_DIGITS = "0123456789abcdef"
KEY_HEX_LENGTH = 64


def parse_link(link: str) -> "tuple[list, str, str, str]":
    """Pull the addresses, ticket, hub key and role out of a link.

    The bare payload without its scheme is accepted too, because it is the
    part a partial copy loses last.

    Args:
        link: What the owner pasted.

    Returns:
        The hub's addresses in the order the hub offered them, the ticket,
        the hub's static public key, and the role the link was made for.

    Raises:
        EnrollmentError: If the link is unreadable or carries no address,
            ticket or key, with the words for this side;
            ``link_not_for_agent``, whose ``params`` name the link's
            ``role``, when it was made for another role.
    """
    text = link.strip()
    if not text:
        raise EnrollmentError("paste the link from the hub's Agents page")
    if text.startswith(LINK_PREFIX):
        text = text[len(LINK_PREFIX) :]
    try:
        padded = text + "=" * (-len(text) % 4)
        packed = base64.urlsafe_b64decode(padded.encode())
        payload = json.loads(zlib.decompress(packed))
        urls = clean_urls(payload.get("urls"))
        token = str(payload.get("token", ""))
        key = str(payload.get("key", "")).strip().lower()
        role = str(payload.get("role", ""))
    except (
        binascii.Error,
        zlib.error,
        ValueError,
        UnicodeDecodeError,
        AttributeError,
    ) as error:
        raise EnrollmentError(
            "that is not an enrollment link; copy the whole line from the "
            "hub's Agents page"
        ) from error
    if role != AGENT_ROLE:
        raise EnrollmentError(
            "link_not_for_agent", code="link_not_for_agent", params={"role": role}
        )
    if not urls or not token:
        raise EnrollmentError("that link carries no hub address and ticket")
    if not is_key(key):
        raise EnrollmentError(
            "that link carries no hub key; generate a fresh link on the hub's "
            "Agents page"
        )
    return urls, token, key, role


def is_key(text: str) -> bool:
    """Whether a text is a key as every file and line writes one.

    Args:
        text: The text.

    Returns:
        True for 64 lowercase hex characters.
    """
    return len(text) == KEY_HEX_LENGTH and all(c in HEX_DIGITS for c in text)


def psk_of(token: str) -> str:
    """The psk a bound peer's knock is answered under: the token's SHA-256.

    Args:
        token: The binding's token.

    Returns:
        64 lowercase hex characters.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_config() -> dict:
    """Read the binding file as it is.

    Returns:
        The stored object, or an empty one when the file is absent or
        unreadable.
    """
    try:
        with open(AGENT_CONFIG_PATH, "r", encoding="utf-8") as stream:
            config = json.load(stream)
    except (OSError, ValueError):
        return {}
    return config if isinstance(config, dict) else {}


def load_binding() -> dict:
    """The binding, complete or nothing.

    Returns:
        ``{gateway_url, gateway_urls, id, token, hub_key, private_key,
        machine_id}``, or an empty object when the file is absent, misses
        any field but ``gateway_urls``, names no hub, id or token, or holds
        a key that is not 64 hex characters. The machine id may be empty;
        ``gateway_urls`` is empty when the file has none.
    """
    config = load_config()
    if not _is_stored(config):
        return {}
    binding = {
        key: str(config.get(key, "") or "")
        for key in BINDING_KEYS
        if key != BINDING_URLS_KEY
    }
    binding[BINDING_URLS_KEY] = clean_urls(config.get(BINDING_URLS_KEY))
    if not (binding["gateway_url"] and binding["id"] and binding["token"]):
        return {}
    if not (is_key(binding["hub_key"]) and is_key(binding["private_key"])):
        return {}
    return binding


def has_legacy_binding() -> bool:
    """Whether the binding file holds a binding an agent of 0.5 left.

    Returns:
        True when the file holds a ``fingerprint`` and no ``hub_key``.
    """
    config = load_config()
    return bool(config.get(LEGACY_FINGERPRINT_KEY)) and not config.get("hub_key")


def save_config(config: dict) -> None:
    """Write the binding file, readable only by root, in one step.

    Args:
        config: What to store.

    Raises:
        OSError: When the file cannot be written.
    """
    directory = os.path.dirname(AGENT_CONFIG_PATH)
    os.makedirs(directory, exist_ok=True)
    temporary = AGENT_CONFIG_PATH + ".tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(config, stream, indent=2)
        stream.write("\n")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, AGENT_CONFIG_PATH)


def remove_binding() -> None:
    """Delete the binding file; a file already gone is no error."""
    try:
        os.unlink(AGENT_CONFIG_PATH)
    except FileNotFoundError:
        pass


def note_url(gateway_url: str) -> None:
    """Record the address that last answered, on the binding file.

    Args:
        gateway_url: The address the session runs to.

    Raises:
        OSError: When the file cannot be written.
    """
    _note(gateway_url=str(gateway_url))


def note_urls(gateway_urls: list) -> None:
    """Record every address the hub's state names, on the binding file.

    Args:
        gateway_urls: The addresses, in the hub's order.

    Raises:
        OSError: When the file cannot be written.
    """
    _note(gateway_urls=clean_urls(gateway_urls))


def clean_urls(value) -> list:
    """A list of addresses as the binding keeps them.

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
    """Every address the binding holds, in the hub's order.

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


def dial_addresses(binding: dict) -> list:
    """The addresses one round dials at once, each one the transport knows.

    The hub's name comes first, then the stored list in the hub's order.
    The address that answered last is not preferred. An address of a scheme
    the transport does not know is left out.

    Args:
        binding: The binding.

    Returns:
        ``tcp://<host>:<port>`` addresses, each once.
    """
    stored = [
        url
        for url in stored_urls(binding)
        if urllib.parse.urlsplit(url).scheme == ADDRESS_SCHEME
    ]
    name_url = hub_name_url(stored[0]) if stored else ""
    return clean_urls([name_url, *stored])


def hub_name_url(gateway_url: str) -> str:
    """The hub's address by its name, on the port of a stored one.

    Args:
        gateway_url: A stored address, for its port.

    Returns:
        ``tcp://hub.neutrino.internal:<port>``, which the transport resolves
        at each round; empty when the stored address names no port.
    """
    try:
        port = urllib.parse.urlsplit(gateway_url).port
    except ValueError:
        port = None
    if not port:
        return ""
    return f"{ADDRESS_SCHEME}://{AGENT_HUB_NAME}:{port}"


def address_url(address: str) -> str:
    """An address a ``session_open`` names, as the binding keeps it.

    Args:
        address: ``tcp://<host>:<port>``, or ``<host>:<port>``.

    Returns:
        The address with the ``tcp`` scheme.
    """
    text = str(address or "").strip().rstrip("/")
    if not text or "://" in text:
        return text
    return f"{ADDRESS_SCHEME}://{text}"


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
            port = parts.port or 1
        except ValueError:
            continue
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect((host, port))
            return str(probe.getsockname()[0])
        except OSError:
            return ""
        finally:
            probe.close()
    return ""


def is_bound() -> bool:
    """Whether this machine holds a complete binding."""
    return bool(load_binding())


def config_stamp() -> int:
    """A marker that moves whenever the binding file's content does.

    The running service compares it between reports, so a binding written
    or removed by another process is adopted without a restart. A digest of
    the bytes rather than the mtime: the kernel stamps every write inside
    one tick of its clock alike, and the file is small.

    Returns:
        A digest of the file's bytes, or 0 when it does not exist.
    """
    try:
        with open(AGENT_CONFIG_PATH, "rb") as stream:
            data = stream.read()
    except OSError:
        return 0
    return int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), "big")


def join_payload(ticket: str, *, platform=None) -> dict:
    """What this machine says about itself when it joins.

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


def enroll(link: str, *, platform=None, transport=None) -> dict:
    """Join the hub the link points at, through a transport.

    The transport dials the link's addresses as a round does, knocks under
    the link's key and sends the one ``join`` on the address that answered.

    Args:
        link: The enrollment link from the hub's Agents page.
        platform: The machine's platform; None detects it.
        transport: Called with nothing for a context manager yielding a
            started :class:`TransportControlClient`; None starts a transport
            of this process's own.

    Returns:
        The binding stored.

    Raises:
        EnrollmentError: If the link is unusable, the transport cannot
            start, no address answered, what answered is not the hub the
            link names, the hub refused with a code, or the answer names no
            binding. A refusal carries its ``code`` and ``params``.
    """
    gateway_urls, ticket, hub_key, _ = parse_link(link)
    platform = platform if platform is not None else detect_platform()
    payload = join_payload(ticket, platform=platform)
    private_key = make_private_key()
    addresses = dial_addresses({BINDING_URLS_KEY: gateway_urls})
    opener = transport or (lambda: one_shot_transport(platform))
    try:
        with opener() as control:
            answer = control.command(
                "join",
                timeout_s=TRANSPORT_JOIN_TIMEOUT_S,
                hub_key=hub_key,
                private_key=private_key,
                addresses=addresses,
                **payload,
            )
    except GatewayUnreachable as error:
        raise EnrollmentError(f"the transport stopped answering: {error}") from error
    except OSError as error:
        raise EnrollmentError(f"the transport could not start: {error}") from error
    code = str(answer.get("code", "") or "")
    if code:
        params = answer.get("params")
        raise EnrollmentError(
            code, code=code, params=dict(params) if isinstance(params, dict) else {}
        )
    binding = {
        "gateway_url": gateway_urls[0],
        "gateway_urls": gateway_urls,
        "id": str(answer.get("binding_id", "") or ""),
        "token": str(answer.get("token", "") or ""),
        "hub_key": hub_key,
        "private_key": private_key,
        "machine_id": payload["machine_id"],
    }
    if not binding["id"] or not binding["token"]:
        raise EnrollmentError("the hub sent no binding back")
    save_config(binding)
    return binding


def unbind(*, platform=None, transport=None) -> dict:
    """Give the binding back to the hub and delete the file.

    The file goes whether or not the hub could be told, so a hub that is
    gone does not hold the machine.

    Args:
        platform: The machine's platform; None detects it.
        transport: As for :func:`enroll`; None starts a transport of this
            process's own.

    Returns:
        Empty when the hub took the leave, ``{"code", "params"}`` when it
        could not be told, and empty with nothing sent when the machine held
        no binding.
    """
    binding = load_binding()
    outcome: dict = {}
    if binding:
        platform = platform if platform is not None else detect_platform()
        opener = transport or (lambda: one_shot_transport(platform))
        try:
            with opener() as control:
                answer = control.command(
                    "leave", timeout_s=TRANSPORT_JOIN_TIMEOUT_S, **dial_fields(binding)
                )
            if answer.get("code"):
                params = answer.get("params")
                outcome = {
                    "code": str(answer["code"]),
                    "params": dict(params) if isinstance(params, dict) else {},
                }
        except (GatewayUnreachable, OSError) as error:
            outcome = {"code": "hub_unreachable", "params": {"detail": str(error)}}
    remove_binding()
    return outcome


def dial_fields(binding: dict) -> dict:
    """The fields a ``dial`` or a ``leave`` carries for a binding.

    Args:
        binding: The binding.

    Returns:
        ``{hub_key, private_key, psk, role, protocol, addresses}``.
    """
    return {
        "hub_key": binding["hub_key"],
        "private_key": binding["private_key"],
        "psk": psk_of(binding["token"]),
        "role": AGENT_ROLE,
        "protocol": PROTOCOL,
        "addresses": dial_addresses(binding),
    }


def _is_stored(config) -> bool:
    """Whether a file holds every field a binding needs."""
    return isinstance(config, dict) and all(
        key in config for key in BINDING_KEYS if key != BINDING_URLS_KEY
    )


def _note(**fields) -> None:
    """Write fields onto a stored binding; a file that is no binding is left."""
    config = load_config()
    if not _is_stored(config):
        return
    config.update(fields)
    save_config(config)
