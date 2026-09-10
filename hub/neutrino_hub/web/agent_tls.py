"""The agent channel's certificate and the fingerprint agents pin.

The channel is verified by fingerprint alone — no chain, no hostname — so one
self-signed certificate generated at setup is the whole identity. The
certificate is public and lives plainly under ``config/web/agent_tls/``; the
private key sits beside it sealed under the vault's data key, so a config
backup carries it protected. Serving needs the key as a file, so apply and
the web process unseal it into ``/var/lib/neutrino/agent_tls_key.pem`` — and
a locked vault means the channel cannot start.
"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from neutrino_hub.modules.credentials.vault import seal_bytes, unseal_bytes
from neutrino_hub.web.constants import (
    WEB_AGENT_TLS_CERT_PATH,
    WEB_AGENT_TLS_KEY_AAD,
    WEB_AGENT_TLS_SEALED_KEY_PATH,
    WEB_AGENT_TLS_SERVED_KEY_PATH,
    WEB_AGENT_TLS_SUBJECT,
    WEB_AGENT_TLS_VALIDITY_DAYS,
)


def ensure_certificate(
    *,
    certificate_path: Path = WEB_AGENT_TLS_CERT_PATH,
    sealed_key_path: Path = WEB_AGENT_TLS_SEALED_KEY_PATH,
) -> bool:
    """Generate the self-signed pair once; an existing pair is left alone.

    Regenerating would change the fingerprint every enrolled agent pins, so
    the pair is written only when it is not there. The private key lands
    sealed under the vault's data key and never plainly in ``config/``.

    Args:
        certificate_path: Where the public certificate lives.
        sealed_key_path: Where the sealed private key lives.

    Returns:
        True when a pair was generated.

    Raises:
        VaultLockedError: If a pair is needed and there is no data key to
            seal it under.
    """
    if certificate_path.is_file() and sealed_key_path.is_file():
        return False
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, WEB_AGENT_TLS_SUBJECT)]
    )
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=WEB_AGENT_TLS_VALIDITY_DAYS))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    sealed = seal_bytes(key_pem, WEB_AGENT_TLS_KEY_AAD)
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    _write_private(sealed_key_path, json.dumps(sealed, indent=2).encode())
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return True


def write_served_key(
    *,
    sealed_key_path: Path = WEB_AGENT_TLS_SEALED_KEY_PATH,
    served_key_path: Path = WEB_AGENT_TLS_SERVED_KEY_PATH,
) -> Path:
    """Unseal the private key into the state file uvicorn serves with.

    Args:
        sealed_key_path: The sealed key in ``config/``.
        served_key_path: The PEM state file to write, mode 0600.

    Returns:
        The state file's path.

    Raises:
        VaultLockedError: If there is no data key on this box.
        ValueError: If the sealed key is missing, malformed, or does not
            decrypt.
        OSError: If the state file cannot be written.
    """
    sealed = json.loads(sealed_key_path.read_text(encoding="utf-8"))
    key_pem = unseal_bytes(sealed, WEB_AGENT_TLS_KEY_AAD)
    served_key_path.parent.mkdir(parents=True, exist_ok=True)
    _write_private(served_key_path, key_pem)
    return served_key_path


def certificate_fingerprint(*, certificate_path: Path = WEB_AGENT_TLS_CERT_PATH) -> str:
    """The pinned identity: SHA-256 hex of the DER-encoded certificate.

    Args:
        certificate_path: The certificate to fingerprint.

    Returns:
        64 lowercase hex characters.

    Raises:
        OSError: If the certificate is not there.
        ValueError: If the file is not a certificate.
    """
    certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    der = certificate.public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(der).hexdigest()


def _write_private(path: Path, data: bytes) -> None:
    """Write the file readable by root alone, from its first byte on disk."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    os.chmod(path, 0o600)
