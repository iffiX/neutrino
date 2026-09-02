"""The agent channel's certificate and the fingerprint agents pin.

The channel is verified by fingerprint alone — no chain, no hostname — so one
self-signed certificate generated at setup is the whole identity. The pair
lives under ``config/web/agent_tls/`` and travels with a config backup.
"""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from neutrino_hub.web.constants import (
    WEB_AGENT_TLS_CERT_PATH,
    WEB_AGENT_TLS_KEY_PATH,
    WEB_AGENT_TLS_SUBJECT,
    WEB_AGENT_TLS_VALIDITY_DAYS,
)


def ensure_certificate(
    *,
    certificate_path: Path = WEB_AGENT_TLS_CERT_PATH,
    key_path: Path = WEB_AGENT_TLS_KEY_PATH,
) -> bool:
    """Generate the self-signed pair once; an existing pair is left alone.

    Regenerating would change the fingerprint every enrolled agent pins, so
    the pair is written only when it is not there.

    Args:
        certificate_path: Where the certificate lives.
        key_path: Where the private key lives; written mode 0600.

    Returns:
        True when a pair was generated.
    """
    if certificate_path.is_file() and key_path.is_file():
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
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    _write_private(
        key_path,
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return True


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
    """Write the key readable by root alone, from its first byte on disk."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    os.chmod(path, 0o600)
