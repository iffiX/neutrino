"""The agent channel's certificate: generated once, key sealed, pin stable.

The fingerprint is the channel's whole identity — no chain, no hostname — so
what these pin is that a pair appears exactly once, that the private key
never lands plainly in ``config/``, that serving means unsealing into a
root-only state file, and that the fingerprint is the SHA-256 of the DER
bytes every agent will hash for itself.
"""

import hashlib
import json
import stat

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from neutrino_hub.modules.credentials.vault import VaultLockedError
from neutrino_hub.web.agent_tls import (
    certificate_fingerprint,
    ensure_certificate,
    write_served_key,
)
from tests.conftest import unlock_vault


@pytest.fixture
def unlocked(tmp_path, monkeypatch):
    unlock_vault(monkeypatch, tmp_path)
    return tmp_path


def pair(tmp_path):
    return tmp_path / "certificate.pem", tmp_path / "key.sealed"


def test_a_missing_pair_is_generated(unlocked):
    certificate_path, sealed_key_path = pair(unlocked)

    is_generated = ensure_certificate(
        certificate_path=certificate_path, sealed_key_path=sealed_key_path
    )

    assert is_generated
    assert certificate_path.is_file()
    assert sealed_key_path.is_file()


def test_the_key_lands_sealed_and_never_plain(unlocked):
    certificate_path, sealed_key_path = pair(unlocked)

    ensure_certificate(
        certificate_path=certificate_path, sealed_key_path=sealed_key_path
    )

    assert stat.S_IMODE(sealed_key_path.stat().st_mode) == 0o600
    text = sealed_key_path.read_text()
    assert "PRIVATE KEY" not in text
    assert set(json.loads(text)) == {"nonce", "data"}


def test_a_locked_vault_generates_nothing(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATE_ROOT", state)
    certificate_path, sealed_key_path = pair(tmp_path)

    with pytest.raises(VaultLockedError):
        ensure_certificate(
            certificate_path=certificate_path, sealed_key_path=sealed_key_path
        )

    assert not certificate_path.exists()
    assert not sealed_key_path.exists()


def test_an_existing_pair_is_never_regenerated(unlocked):
    """Regenerating would change the fingerprint every enrolled agent pins."""
    certificate_path, sealed_key_path = pair(unlocked)
    ensure_certificate(
        certificate_path=certificate_path, sealed_key_path=sealed_key_path
    )
    certificate_bytes = certificate_path.read_bytes()
    key_bytes = sealed_key_path.read_bytes()

    is_generated = ensure_certificate(
        certificate_path=certificate_path, sealed_key_path=sealed_key_path
    )

    assert not is_generated
    assert certificate_path.read_bytes() == certificate_bytes
    assert sealed_key_path.read_bytes() == key_bytes


def test_the_served_key_unseals_to_the_matching_pem(unlocked):
    certificate_path, sealed_key_path = pair(unlocked)
    ensure_certificate(
        certificate_path=certificate_path, sealed_key_path=sealed_key_path
    )
    served_path = unlocked / "state" / "agent_tls_key.pem"

    written = write_served_key(
        sealed_key_path=sealed_key_path, served_key_path=served_path
    )

    assert written == served_path
    assert stat.S_IMODE(served_path.stat().st_mode) == 0o600
    key = serialization.load_pem_private_key(served_path.read_bytes(), password=None)
    certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    assert key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ) == certificate.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def test_a_locked_vault_serves_no_key(unlocked, monkeypatch):
    certificate_path, sealed_key_path = pair(unlocked)
    ensure_certificate(
        certificate_path=certificate_path, sealed_key_path=sealed_key_path
    )
    (unlocked / "state" / "vault.key").unlink()

    with pytest.raises(VaultLockedError):
        write_served_key(
            sealed_key_path=sealed_key_path,
            served_key_path=unlocked / "state" / "agent_tls_key.pem",
        )

    assert not (unlocked / "state" / "agent_tls_key.pem").exists()


def test_the_fingerprint_is_sha256_of_the_der(unlocked):
    """The same digest an agent computes from the socket's peer certificate."""
    certificate_path, sealed_key_path = pair(unlocked)
    ensure_certificate(
        certificate_path=certificate_path, sealed_key_path=sealed_key_path
    )

    fingerprint = certificate_fingerprint(certificate_path=certificate_path)

    certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    der = certificate.public_bytes(serialization.Encoding.DER)
    assert fingerprint == hashlib.sha256(der).hexdigest()
    assert len(fingerprint) == 64
    assert fingerprint == certificate_fingerprint(certificate_path=certificate_path)


def test_the_certificate_outlives_the_box(unlocked):
    certificate_path, sealed_key_path = pair(unlocked)
    ensure_certificate(
        certificate_path=certificate_path, sealed_key_path=sealed_key_path
    )

    certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    lifetime = certificate.not_valid_after_utc - certificate.not_valid_before_utc

    assert lifetime.days >= 3650
