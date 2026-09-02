"""The agent channel's certificate: generated once, pinned by fingerprint.

The fingerprint is the channel's whole identity — no chain, no hostname — so
what these pin is that a pair appears exactly once, that the key is readable
by root alone, and that the fingerprint is the SHA-256 of the DER bytes every
agent will hash for itself.
"""

import hashlib
import stat

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from neutrino_hub.web.agent_tls import certificate_fingerprint, ensure_certificate


def pair(tmp_path):
    return tmp_path / "certificate.pem", tmp_path / "key.pem"


def test_a_missing_pair_is_generated(tmp_path):
    certificate_path, key_path = pair(tmp_path)

    is_generated = ensure_certificate(
        certificate_path=certificate_path, key_path=key_path
    )

    assert is_generated
    assert certificate_path.is_file()
    assert key_path.is_file()


def test_the_key_is_readable_by_root_alone(tmp_path):
    certificate_path, key_path = pair(tmp_path)

    ensure_certificate(certificate_path=certificate_path, key_path=key_path)

    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_an_existing_pair_is_never_regenerated(tmp_path):
    """Regenerating would change the fingerprint every enrolled agent pins."""
    certificate_path, key_path = pair(tmp_path)
    ensure_certificate(certificate_path=certificate_path, key_path=key_path)
    certificate_bytes = certificate_path.read_bytes()
    key_bytes = key_path.read_bytes()

    is_generated = ensure_certificate(
        certificate_path=certificate_path, key_path=key_path
    )

    assert not is_generated
    assert certificate_path.read_bytes() == certificate_bytes
    assert key_path.read_bytes() == key_bytes


def test_the_fingerprint_is_sha256_of_the_der(tmp_path):
    """The same digest an agent computes from the socket's peer certificate."""
    certificate_path, key_path = pair(tmp_path)
    ensure_certificate(certificate_path=certificate_path, key_path=key_path)

    fingerprint = certificate_fingerprint(certificate_path=certificate_path)

    certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    der = certificate.public_bytes(serialization.Encoding.DER)
    assert fingerprint == hashlib.sha256(der).hexdigest()
    assert len(fingerprint) == 64
    assert fingerprint == certificate_fingerprint(certificate_path=certificate_path)


def test_the_certificate_outlives_the_box(tmp_path):
    certificate_path, key_path = pair(tmp_path)
    ensure_certificate(certificate_path=certificate_path, key_path=key_path)

    certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    lifetime = certificate.not_valid_after_utc - certificate.not_valid_before_utc

    assert lifetime.days >= 3650
