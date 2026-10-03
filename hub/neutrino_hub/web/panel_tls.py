"""The panel's own certificate authority and the certificate the panel serves.

The authority is limited by name constraints to private addresses and a few
names, so a browser that trusts it trusts nothing public. Its certificate
lives plainly under ``config/web/panel_tls/`` and its key beside it sealed
under the vault's data key, as the agent channel's does. The panel's
certificate is state: issued for the names the panel answers on, written with
its key under ``/var/lib/neutrino/hub``, and issued again when those names change
or it nears expiry, into the live TLS context as well.
"""

import hashlib
import ipaddress
import json
import logging
import os
import re
import socket
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from neutrino_hub.modules.credentials.vault import seal_bytes, unseal_bytes
from neutrino_hub.modules.router.constants import ROUTER_HUB_NAME
from neutrino_hub.modules.router.controller import rendered_overlay_devices
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.utils.json_file import read_config
from neutrino_hub.web.constants import (
    WEB_PANEL_TLS_AUTHORITY_KEY_AAD,
    WEB_PANEL_TLS_AUTHORITY_KEY_PATH,
    WEB_PANEL_TLS_AUTHORITY_ORGANIZATION,
    WEB_PANEL_TLS_AUTHORITY_PATH,
    WEB_PANEL_TLS_AUTHORITY_VALIDITY_DAYS,
    WEB_PANEL_TLS_BACKDATE_S,
    WEB_PANEL_TLS_FILE_NAME,
    WEB_PANEL_TLS_LEAF_VALIDITY_DAYS,
    WEB_PANEL_TLS_LOOPBACK_NAMES,
    WEB_PANEL_TLS_PERMITTED_DOMAINS,
    WEB_PANEL_TLS_PERMITTED_NETWORKS,
    WEB_PANEL_TLS_RENEW_BEFORE_DAYS,
    WEB_PANEL_TLS_SERVED_CERT_PATH,
    WEB_PANEL_TLS_SERVED_KEY_PATH,
    WEB_SETTING_HTTPS,
)
from neutrino_hub.web.channel_addresses import channel_hosts

LOGGER = logging.getLogger(__name__)
PANEL_TLS_SETTINGS_FILE = "web/settings.json"
# One DNS label: what a host name may be made of to stand in a certificate.
PANEL_TLS_LABEL_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

# The TLS contexts serving the panel in this process, which a renewal loads
# the new pair into, and when the last renewal happened.
_served_contexts: list = []
_state_lock = threading.Lock()
_last_renewed_at: "datetime | None" = None
# The served certificate those contexts hold, so a pair another process
# wrote is loaded as well.
_loaded_certificate = b""


def is_https_enabled() -> bool:
    """Whether ``web/settings.json`` says the panel speaks HTTPS.

    Returns:
        The stored flag, False when the file or the key is missing.
    """
    try:
        return bool(read_config(PANEL_TLS_SETTINGS_FILE).get(WEB_SETTING_HTTPS))
    except (FileNotFoundError, ValueError):
        return False


def ensure_served() -> bool:
    """Make a missing authority, and a served certificate for the names now.

    What ``nhub apply``, the panel's start and turning HTTPS on share.

    Returns:
        True when a certificate was issued.

    Raises:
        VaultLockedError: If something is missing and there is no data key
            to seal or unseal the authority's key with.
        OSError: If a file cannot be written.
        ValueError: If the authority's files are malformed.
    """
    ensure_authority()
    return renew_served_leaf(served_names())


def ensure_authority(
    *,
    certificate_path: Path = WEB_PANEL_TLS_AUTHORITY_PATH,
    sealed_key_path: Path = WEB_PANEL_TLS_AUTHORITY_KEY_PATH,
    host_name: str | None = None,
) -> bool:
    """Generate the certificate authority once; an existing one is left alone.

    Args:
        certificate_path: Where the authority's certificate lives.
        sealed_key_path: Where its sealed private key lives.
        host_name: The host name the authority may sign for; ``None`` reads
            this machine's.

    Returns:
        True when an authority was generated.

    Raises:
        VaultLockedError: If one is needed and there is no data key to seal
            its key under.
        OSError: If the files cannot be written.
    """
    if certificate_path.is_file() and sealed_key_path.is_file():
        return False
    reset_authority(
        certificate_path=certificate_path,
        sealed_key_path=sealed_key_path,
        host_name=host_name,
    )
    return True


def reset_authority(
    *,
    certificate_path: Path = WEB_PANEL_TLS_AUTHORITY_PATH,
    sealed_key_path: Path = WEB_PANEL_TLS_AUTHORITY_KEY_PATH,
    host_name: str | None = None,
    now: datetime | None = None,
) -> None:
    """Generate a new certificate authority over whatever was there.

    Every browser that trusted the old one has to install the new one.

    Args:
        certificate_path: Where the authority's certificate lives.
        sealed_key_path: Where its sealed private key lives.
        host_name: The host name the authority may sign for; ``None`` reads
            this machine's.
        now: The time it is issued at; ``None`` is now.

    Raises:
        VaultLockedError: If there is no data key to seal its key under.
        OSError: If the files cannot be written.
    """
    name = _dns_label(socket.gethostname() if host_name is None else host_name)
    issued = (now or datetime.now(timezone.utc)) - timedelta(
        seconds=WEB_PANEL_TLS_BACKDATE_S
    )
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name(
        [
            x509.NameAttribute(
                NameOID.ORGANIZATION_NAME, WEB_PANEL_TLS_AUTHORITY_ORGANIZATION
            ),
            x509.NameAttribute(
                NameOID.COMMON_NAME,
                f"{WEB_PANEL_TLS_AUTHORITY_ORGANIZATION} {name or 'hub'} authority",
            ),
        ]
    )
    permitted = [
        x509.IPAddress(ipaddress.ip_network(network))
        for network in WEB_PANEL_TLS_PERMITTED_NETWORKS
    ]
    domains = [WEB_PANEL_TLS_PERMITTED_DOMAINS[0]]
    if name and name not in WEB_PANEL_TLS_PERMITTED_DOMAINS:
        domains.append(name)
    domains.extend(WEB_PANEL_TLS_PERMITTED_DOMAINS[1:])
    permitted.extend(x509.DNSName(domain) for domain in domains)
    public_key = key.public_key()
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(issued)
        .not_valid_after(issued + timedelta(days=WEB_PANEL_TLS_AUTHORITY_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.NameConstraints(permitted_subtrees=permitted, excluded_subtrees=None),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    sealed = seal_bytes(key_pem, WEB_PANEL_TLS_AUTHORITY_KEY_AAD)
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    _write_private(sealed_key_path, json.dumps(sealed, indent=2).encode())
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


def authority_der(*, certificate_path: Path = WEB_PANEL_TLS_AUTHORITY_PATH) -> bytes:
    """The authority's certificate as a browser installs it.

    Args:
        certificate_path: The authority's certificate.

    Returns:
        Its DER encoding.

    Raises:
        OSError: If there is no authority.
        ValueError: If the file is not a certificate.
    """
    certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    return certificate.public_bytes(serialization.Encoding.DER)


def authority_fingerprint(
    *, certificate_path: Path = WEB_PANEL_TLS_AUTHORITY_PATH
) -> str:
    """The SHA-256 of the authority's DER encoding, as a browser shows it.

    Args:
        certificate_path: The authority's certificate.

    Returns:
        64 lowercase hex characters.

    Raises:
        OSError: If there is no authority.
        ValueError: If the file is not a certificate.
    """
    return hashlib.sha256(authority_der(certificate_path=certificate_path)).hexdigest()


def authority_file_name(hub: str) -> str:
    """What the downloaded authority is called.

    Args:
        hub: The hub's name.

    Returns:
        ``neutrino-<hub>-ca.crt``, the name folded to lowercase letters,
        digits and hyphens.
    """
    folded = re.sub(r"[^a-z0-9]+", "-", hub.lower()).strip("-") or "hub"
    return WEB_PANEL_TLS_FILE_NAME.format(hub=folded)


def issue_leaf(
    names: list,
    *,
    certificate_path: Path = WEB_PANEL_TLS_AUTHORITY_PATH,
    sealed_key_path: Path = WEB_PANEL_TLS_AUTHORITY_KEY_PATH,
    now: datetime | None = None,
) -> tuple[bytes, bytes]:
    """Sign a panel certificate for the names given.

    Args:
        names: Addresses and DNS names the certificate is for.
        certificate_path: The authority's certificate.
        sealed_key_path: The authority's sealed key.
        now: The time it is issued at; ``None`` is now.

    Returns:
        The certificate and its private key, both PEM.

    Raises:
        VaultLockedError: If there is no data key to unseal the authority's
            key with.
        OSError: If there is no authority.
        ValueError: If ``names`` is empty, or the authority's files are
            malformed or do not decrypt.
    """
    if not names:
        raise ValueError("a certificate needs at least one name")
    authority = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    sealed = json.loads(sealed_key_path.read_text(encoding="utf-8"))
    authority_key = serialization.load_pem_private_key(
        unseal_bytes(sealed, WEB_PANEL_TLS_AUTHORITY_KEY_AAD), password=None
    )
    issued = (now or datetime.now(timezone.utc)) - timedelta(
        seconds=WEB_PANEL_TLS_BACKDATE_S
    )
    key = ec.generate_private_key(ec.SECP256R1())
    alternatives = [_general_name(name) for name in names]
    certificate = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ROUTER_HUB_NAME)])
        )
        .issuer_name(authority.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(issued)
        .not_valid_after(issued + timedelta(days=WEB_PANEL_TLS_LEAF_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(x509.SubjectAlternativeName(alternatives), critical=False)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(authority.public_key()),
            critical=False,
        )
        .sign(authority_key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return certificate.public_bytes(serialization.Encoding.PEM), key_pem


def leaf_names(
    hosts: list,
    *,
    host_name: str | None = None,
    certificate_path: Path = WEB_PANEL_TLS_AUTHORITY_PATH,
) -> list:
    """The names the panel's certificate carries.

    The hub's own name, loopback and the host name first, then every host the
    panel answers on that the authority may sign for: a private or CGNAT
    address, and a NetBird name under ``netbird.cloud``. A public address or
    any other name is left out, because a browser refuses a certificate that
    breaks the authority's constraints.

    Args:
        hosts: The addresses and names the panel answers on, as the
            enrolment link lists them.
        host_name: This machine's host name; ``None`` reads it.
        certificate_path: The authority, whose constraints decide which host
            name it may sign; without one, the name is checked against the
            constraints a new authority would carry.

    Returns:
        The names, each once, in that order.
    """
    name = _dns_label(socket.gethostname() if host_name is None else host_name)
    domains = _permitted_domains(certificate_path, name)
    names = [ROUTER_HUB_NAME, WEB_PANEL_TLS_LOOPBACK_NAMES[1]]
    if name:
        names.append(name)
    names.append(WEB_PANEL_TLS_LOOPBACK_NAMES[0])
    names.extend(str(host).lower() for host in hosts)
    found = []
    for candidate in names:
        if candidate in found:
            continue
        if _is_address(candidate):
            if _is_permitted_address(candidate):
                found.append(candidate)
        elif _is_permitted_name(candidate, domains):
            found.append(candidate)
    return found


def hosts_of(urls: list) -> list:
    """The host of each URL.

    Args:
        urls: Base URLs, as :func:`channel_urls` returns them.

    Returns:
        Their hosts, in the same order.
    """
    return [urlsplit(url).hostname or "" for url in urls]


def served_names() -> list:
    """The names the panel answers on now, read from ``config/`` and the links.

    Returns:
        What :func:`leaf_names` makes of the channel's host set; the fixed
        names alone when the network configuration cannot be read.
    """
    try:
        network = RouterNetworkConfig.from_dict(
            read_config("router/network.json")
        ).with_overlay_devices(rendered_overlay_devices())
    except (FileNotFoundError, ValueError):
        return leaf_names([])
    return leaf_names(channel_hosts(network))


def write_served_leaf(
    names: list,
    *,
    certificate_path: Path = WEB_PANEL_TLS_AUTHORITY_PATH,
    sealed_key_path: Path = WEB_PANEL_TLS_AUTHORITY_KEY_PATH,
    served_certificate_path: Path = WEB_PANEL_TLS_SERVED_CERT_PATH,
    served_key_path: Path = WEB_PANEL_TLS_SERVED_KEY_PATH,
    now: datetime | None = None,
) -> Path:
    """Issue a panel certificate and write it with its key, both mode 0600.

    Args:
        names: What the certificate is for.
        certificate_path: The authority's certificate.
        sealed_key_path: The authority's sealed key.
        served_certificate_path: Where the served certificate is written.
        served_key_path: Where its key is written.
        now: The time it is issued at; ``None`` is now.

    Returns:
        The served certificate's path.

    Raises:
        VaultLockedError: If there is no data key to unseal the authority's
            key with.
        OSError: If there is no authority, or a file cannot be written.
        ValueError: If the authority's files are malformed.
    """
    certificate_pem, key_pem = issue_leaf(
        names,
        certificate_path=certificate_path,
        sealed_key_path=sealed_key_path,
        now=now,
    )
    served_key_path.parent.mkdir(parents=True, exist_ok=True)
    _write_private(served_key_path, key_pem)
    _write_private(served_certificate_path, certificate_pem)
    return served_certificate_path


def is_leaf_due(
    names: list,
    *,
    certificate_path: Path = WEB_PANEL_TLS_AUTHORITY_PATH,
    served_certificate_path: Path = WEB_PANEL_TLS_SERVED_CERT_PATH,
    served_key_path: Path = WEB_PANEL_TLS_SERVED_KEY_PATH,
    now: datetime | None = None,
) -> bool:
    """Whether the served certificate has to be issued again.

    Args:
        names: The names it should carry.
        certificate_path: The authority's certificate.
        served_certificate_path: The served certificate.
        served_key_path: Its key.
        now: The time it is judged at; ``None`` is now.

    Returns:
        True when there is no served pair, it was not signed by the current
        authority, its names are not ``names``, or it expires within
        thirty days.
    """
    if not served_key_path.is_file():
        return True
    try:
        leaf = x509.load_pem_x509_certificate(served_certificate_path.read_bytes())
        authority = x509.load_pem_x509_certificate(certificate_path.read_bytes())
        leaf.verify_directly_issued_by(authority)
    except (OSError, ValueError, TypeError, InvalidSignature):
        return True
    if set(certificate_names(leaf)) != set(names):
        return True
    moment = now or datetime.now(timezone.utc)
    remaining = leaf.not_valid_after_utc - moment
    return remaining < timedelta(days=WEB_PANEL_TLS_RENEW_BEFORE_DAYS)


def renew_served_leaf(
    names: list,
    *,
    certificate_path: Path = WEB_PANEL_TLS_AUTHORITY_PATH,
    sealed_key_path: Path = WEB_PANEL_TLS_AUTHORITY_KEY_PATH,
    served_certificate_path: Path = WEB_PANEL_TLS_SERVED_CERT_PATH,
    served_key_path: Path = WEB_PANEL_TLS_SERVED_KEY_PATH,
    now: datetime | None = None,
) -> bool:
    """Issue the served certificate again when it is due, and serve it at once.

    Every TLS context registered with :func:`watch_served_context` loads the
    new pair, so new connections get it without a restart.

    Args:
        names: The names it should carry.
        certificate_path: The authority's certificate.
        sealed_key_path: The authority's sealed key.
        served_certificate_path: Where the served certificate is written.
        served_key_path: Where its key is written.
        now: The time it is judged and issued at; ``None`` is now.

    Returns:
        True when a certificate was issued.

    Raises:
        VaultLockedError: If one is due and there is no data key to unseal
            the authority's key with.
        OSError: If there is no authority, or a file cannot be written.
        ValueError: If the authority's files are malformed.
    """
    global _last_renewed_at
    is_due = is_leaf_due(
        names,
        certificate_path=certificate_path,
        served_certificate_path=served_certificate_path,
        served_key_path=served_key_path,
        now=now,
    )
    if is_due:
        is_replacing = served_certificate_path.is_file()
        write_served_leaf(
            names,
            certificate_path=certificate_path,
            sealed_key_path=sealed_key_path,
            served_certificate_path=served_certificate_path,
            served_key_path=served_key_path,
            now=now,
        )
        if is_replacing:
            with _state_lock:
                _last_renewed_at = now or datetime.now(timezone.utc)
    _load_served_pair(served_certificate_path, served_key_path)
    return is_due


def follow_addresses(urls: list) -> None:
    """Renew the served certificate for the channel's current address set.

    Args:
        urls: The channel's base URLs, as the address sampler read them.
    """
    try:
        if renew_served_leaf(leaf_names(hosts_of(urls))):
            LOGGER.info("panel certificate issued for the current addresses")
    except (OSError, ValueError) as error:
        LOGGER.warning("panel certificate not renewed: %s", error)


def watch_served_context(
    context, *, served_certificate_path: Path = WEB_PANEL_TLS_SERVED_CERT_PATH
) -> None:
    """Register a live TLS context that a renewal loads the new pair into.

    Args:
        context: The ``ssl.SSLContext`` the panel's server hands out
            connections from, already loaded with the served pair.
        served_certificate_path: The served certificate it was loaded from.
    """
    global _loaded_certificate
    with _state_lock:
        if context not in _served_contexts:
            _served_contexts.append(context)
        try:
            _loaded_certificate = served_certificate_path.read_bytes()
        except OSError:
            _loaded_certificate = b""


def last_renewed_at() -> "datetime | None":
    """When the served certificate was last issued again in this process.

    Returns:
        The time, or None when it has not been since the panel started.
    """
    with _state_lock:
        return _last_renewed_at


def certificate_names(certificate) -> list:
    """The addresses and DNS names a certificate is for.

    Args:
        certificate: A loaded certificate.

    Returns:
        Its subject alternative names as strings; empty without any.
    """
    try:
        extension = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        )
    except x509.ExtensionNotFound:
        return []
    names = [str(value) for value in extension.value.get_values_for_type(x509.DNSName)]
    names.extend(
        str(value) for value in extension.value.get_values_for_type(x509.IPAddress)
    )
    return names


def _load_served_pair(certificate_path: Path, key_path: Path) -> None:
    """Load the served pair into every watched context when it is not the one held."""
    global _loaded_certificate
    with _state_lock:
        if not _served_contexts:
            return
        try:
            current = certificate_path.read_bytes()
        except OSError:
            return
        if current == _loaded_certificate:
            return
        for context in _served_contexts:
            context.load_cert_chain(str(certificate_path), str(key_path))
        _loaded_certificate = current


def _general_name(name: str):
    """One subject alternative name: an address or a DNS name."""
    if _is_address(name):
        return x509.IPAddress(ipaddress.ip_address(name))
    return x509.DNSName(name)


def _is_address(text: str) -> bool:
    """Whether the text is an IP address."""
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def _is_permitted_address(text: str) -> bool:
    """Whether an address lies inside the authority's permitted networks."""
    address = ipaddress.ip_address(text)
    return any(
        address in ipaddress.ip_network(network)
        for network in WEB_PANEL_TLS_PERMITTED_NETWORKS
    )


def _is_permitted_name(name: str, domains: list) -> bool:
    """Whether a DNS name is one of the permitted domains or under one."""
    labels = name.split(".")
    if not name or not all(PANEL_TLS_LABEL_PATTERN.match(label) for label in labels):
        return False
    return any(name == domain or name.endswith(f".{domain}") for domain in domains)


def _permitted_domains(certificate_path: Path, host_name: str) -> list:
    """The DNS names the authority may sign under, read from it when it exists."""
    try:
        authority = x509.load_pem_x509_certificate(certificate_path.read_bytes())
        constraints = authority.extensions.get_extension_for_class(
            x509.NameConstraints
        ).value
    except (OSError, ValueError, x509.ExtensionNotFound):
        return [*WEB_PANEL_TLS_PERMITTED_DOMAINS, host_name]
    return [
        str(subtree.value)
        for subtree in constraints.permitted_subtrees or []
        if isinstance(subtree, x509.DNSName)
    ]


def _dns_label(name: str) -> str:
    """The host name as one lowercase DNS label, or empty when it is not one."""
    label = name.strip().lower().split(".")[0]
    return label if PANEL_TLS_LABEL_PATTERN.match(label) else ""


def _write_private(path: Path, data: bytes) -> None:
    """Write the file readable by root alone, from its first byte on disk."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    os.chmod(path, 0o600)
