"""The panel's certificate authority and the certificate it signs.

What these pin: the authority carries the extensions a browser enforces, its
key lands sealed, the panel certificate chains to it under ``cryptography``'s
own verifier, a certificate for a public name signed by the same authority
fails that verifier, only private names reach a certificate, and the served
certificate is issued again when its names change or it nears expiry, into a
live TLS context that hands the new one to the next connection.
"""

import ipaddress
import json
import socket
import ssl
import stat
import threading
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509 import DNSName, IPAddress
from cryptography.x509.oid import NameOID
from cryptography.x509.verification import (
    PolicyBuilder,
    Store,
    VerificationError,
)

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.web import panel_tls
from neutrino_hub.web.panel_tls import (
    authority_file_name,
    authority_fingerprint,
    certificate_names,
    ensure_authority,
    is_leaf_due,
    issue_leaf,
    leaf_names,
    renew_served_leaf,
    reset_authority,
    watch_served_context,
    write_served_leaf,
)
from tests.conftest import unlock_vault

NOW = datetime.now(timezone.utc)


@pytest.fixture
def paths(tmp_path, monkeypatch):
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(panel_tls, "_served_contexts", [])
    monkeypatch.setattr(panel_tls, "_last_renewed_at", None)
    monkeypatch.setattr(panel_tls, "_loaded_certificate", b"")
    return {
        "certificate_path": tmp_path / "authority.pem",
        "sealed_key_path": tmp_path / "authority_key.sealed",
    }


@pytest.fixture
def served(tmp_path, paths):
    return {
        **paths,
        "served_certificate_path": tmp_path / "served" / "certificate.pem",
        "served_key_path": tmp_path / "served" / "key.pem",
    }


def authority(paths) -> x509.Certificate:
    return x509.load_pem_x509_certificate(paths["certificate_path"].read_bytes())


def verify(paths, leaf_pem: bytes, name) -> None:
    verifier = (
        PolicyBuilder()
        .store(Store([authority(paths)]))
        .time(datetime.now(timezone.utc))
        .build_server_verifier(name)
    )
    verifier.verify(x509.load_pem_x509_certificate(leaf_pem), [])


# --- the authority ---


def test_the_authority_is_a_p256_ca_limited_to_private_names(paths):
    assert ensure_authority(**paths, host_name="argon")

    certificate = authority(paths)
    extensions = certificate.extensions
    constraints = extensions.get_extension_for_class(x509.BasicConstraints)
    names = extensions.get_extension_for_class(x509.NameConstraints)
    usage = extensions.get_extension_for_class(x509.KeyUsage)
    assert isinstance(certificate.public_key().curve, ec.SECP256R1)
    assert constraints.critical and constraints.value.ca
    assert constraints.value.path_length == 0
    assert usage.critical and usage.value.key_cert_sign
    assert names.critical
    assert names.value.excluded_subtrees is None
    assert names.value.permitted_subtrees == [
        IPAddress(ipaddress.ip_network("10.0.0.0/8")),
        IPAddress(ipaddress.ip_network("172.16.0.0/12")),
        IPAddress(ipaddress.ip_network("192.168.0.0/16")),
        IPAddress(ipaddress.ip_network("100.64.0.0/10")),
        IPAddress(ipaddress.ip_network("127.0.0.0/8")),
        DNSName("localhost"),
        DNSName("argon"),
        DNSName("neutrino.internal"),
        DNSName("netbird.cloud"),
    ]
    lifetime = certificate.not_valid_after_utc - certificate.not_valid_before_utc
    assert lifetime == timedelta(days=3650)


def test_the_authority_key_lands_sealed_and_never_plain(paths):
    ensure_authority(**paths, host_name="argon")

    sealed = paths["sealed_key_path"]
    assert stat.S_IMODE(sealed.stat().st_mode) == 0o600
    assert "PRIVATE KEY" not in sealed.read_text()
    assert set(json.loads(sealed.read_text())) == {"nonce", "data"}


def test_an_existing_authority_is_kept_and_a_reset_replaces_it(paths):
    ensure_authority(**paths, host_name="argon")
    first = authority_fingerprint(certificate_path=paths["certificate_path"])

    assert not ensure_authority(**paths, host_name="argon")
    assert authority_fingerprint(certificate_path=paths["certificate_path"]) == first

    reset_authority(**paths, host_name="argon")
    assert authority_fingerprint(certificate_path=paths["certificate_path"]) != first


def test_a_locked_vault_makes_no_authority(tmp_path, monkeypatch):
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATE_ROOT", tmp_path)

    with pytest.raises(VaultLockedError):
        ensure_authority(
            certificate_path=tmp_path / "authority.pem",
            sealed_key_path=tmp_path / "authority_key.sealed",
            host_name="argon",
        )

    assert not (tmp_path / "authority.pem").exists()


def test_the_download_is_named_after_the_hub():
    assert authority_file_name("Neutrino") == "neutrino-neutrino-ca.crt"
    assert authority_file_name("Home Hub 2") == "neutrino-home-hub-2-ca.crt"
    assert authority_file_name("微子") == "neutrino-hub-ca.crt"


# --- the panel certificate ---


def test_the_panel_certificate_chains_to_the_authority(paths):
    ensure_authority(**paths, host_name="argon")
    names = ["hub.neutrino.internal", "localhost", "argon", "127.0.0.1"]
    names += ["192.168.100.1", "100.92.10.4", "argon.netbird.cloud"]

    leaf_pem, _ = issue_leaf(names, **paths)

    verify(paths, leaf_pem, IPAddress(ipaddress.ip_address("192.168.100.1")))
    verify(paths, leaf_pem, IPAddress(ipaddress.ip_address("100.92.10.4")))
    verify(paths, leaf_pem, DNSName("hub.neutrino.internal"))
    verify(paths, leaf_pem, DNSName("argon.netbird.cloud"))
    verify(paths, leaf_pem, DNSName("argon"))
    leaf = x509.load_pem_x509_certificate(leaf_pem)
    usage = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
    assert list(usage.value) == [x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]
    assert leaf.not_valid_after_utc - leaf.not_valid_before_utc == timedelta(days=397)


@pytest.mark.parametrize(
    "name",
    [
        DNSName("example.com"),
        DNSName("neutrino.example.com"),
        IPAddress(ipaddress.ip_address("8.8.8.8")),
    ],
)
def test_a_certificate_for_a_public_name_fails_the_verifier(paths, name):
    ensure_authority(**paths, host_name="argon")
    value = str(name.value)

    leaf_pem, _ = issue_leaf([value], **paths)

    with pytest.raises(VerificationError):
        verify(paths, leaf_pem, name)


def test_only_private_addresses_and_permitted_names_reach_a_certificate(paths):
    ensure_authority(**paths, host_name="argon")
    hosts = [
        "192.168.100.1",
        "203.0.113.7",
        "10.144.0.1",
        "100.92.10.4",
        "argon.netbird.cloud",
        "vpn.example.com",
        "192.168.100.1",
    ]

    names = leaf_names(
        hosts, host_name="Argon", certificate_path=paths["certificate_path"]
    )

    assert names == [
        "hub.neutrino.internal",
        "localhost",
        "argon",
        "127.0.0.1",
        "192.168.100.1",
        "10.144.0.1",
        "100.92.10.4",
        "argon.netbird.cloud",
    ]


def test_a_host_name_the_authority_does_not_permit_is_left_out(paths):
    ensure_authority(**paths, host_name="argon")

    names = leaf_names(
        [], host_name="xenon", certificate_path=paths["certificate_path"]
    )

    assert "xenon" not in names
    assert names == ["hub.neutrino.internal", "localhost", "127.0.0.1"]


def test_the_served_pair_is_written_root_only(served):
    ensure_authority(**served_authority(served), host_name="argon")

    write_served_leaf(["127.0.0.1"], **served)

    for key in ("served_certificate_path", "served_key_path"):
        assert stat.S_IMODE(served[key].stat().st_mode) == 0o600
    assert "PRIVATE KEY" in served["served_key_path"].read_text()


def served_authority(served) -> dict:
    return {
        "certificate_path": served["certificate_path"],
        "sealed_key_path": served["sealed_key_path"],
    }


def test_the_certificate_is_issued_again_only_when_its_names_change(served):
    ensure_authority(**served_authority(served), host_name="argon")
    names = ["127.0.0.1", "192.168.100.1"]

    assert renew_served_leaf(names, **served, now=NOW)
    assert not renew_served_leaf(list(reversed(names)), **served, now=NOW)
    assert panel_tls.last_renewed_at() is None

    assert renew_served_leaf([*names, "10.0.0.1"], **served, now=NOW)
    leaf = x509.load_pem_x509_certificate(
        served["served_certificate_path"].read_bytes()
    )
    assert set(certificate_names(leaf)) == {*names, "10.0.0.1"}
    assert panel_tls.last_renewed_at() == NOW


def test_the_certificate_is_issued_again_thirty_days_before_it_expires(served):
    ensure_authority(**served_authority(served), host_name="argon")
    names = ["127.0.0.1"]
    renew_served_leaf(names, **served, now=NOW)
    judged = {
        "certificate_path": served["certificate_path"],
        "served_certificate_path": served["served_certificate_path"],
        "served_key_path": served["served_key_path"],
    }

    assert not is_leaf_due(names, **judged, now=NOW + timedelta(days=366))
    assert is_leaf_due(names, **judged, now=NOW + timedelta(days=368))


def test_a_new_authority_makes_the_served_certificate_due(served):
    authority_paths = served_authority(served)
    ensure_authority(**authority_paths, host_name="argon")
    renew_served_leaf(["127.0.0.1"], **served, now=NOW)

    reset_authority(**authority_paths, host_name="argon")

    assert renew_served_leaf(["127.0.0.1"], **served, now=NOW)


def test_a_renewal_reaches_the_next_connection_on_a_live_context(served):
    """A real TLS server keeps serving; its context loads the new certificate."""
    ensure_authority(**served_authority(served), host_name="argon")
    renew_served_leaf(["127.0.0.1"], **served, now=NOW)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        str(served["served_certificate_path"]), str(served["served_key_path"])
    )
    watch_served_context(
        context, served_certificate_path=served["served_certificate_path"]
    )
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    stop = threading.Event()

    def serve() -> None:
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            try:
                with context.wrap_socket(connection, server_side=True) as wrapped:
                    wrapped.recv(1)
            except (ssl.SSLError, OSError):
                pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        first = served_names(served, port)
        renew_served_leaf(["127.0.0.1", "192.168.7.1"], **served, now=NOW)
        second = served_names(served, port)
        # A pair another process wrote, such as `nhub apply`, is loaded by
        # the next look even when its names are already the ones wanted.
        write_served_leaf(["127.0.0.1", "10.1.1.1"], **served)
        renew_served_leaf(["127.0.0.1", "10.1.1.1"], **served, now=NOW)
        third = served_names(served, port)
    finally:
        stop.set()
        thread.join(timeout=2)
        listener.close()

    assert first == ["127.0.0.1"]
    assert second == ["127.0.0.1", "192.168.7.1"]
    assert third == ["127.0.0.1", "10.1.1.1"]


def served_names(served, port: int) -> list:
    """Connect, trusting only the authority, and read the served names."""
    client = ssl.create_default_context(cafile=str(served["certificate_path"]))
    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        with client.wrap_socket(raw, server_hostname="127.0.0.1") as wrapped:
            der = wrapped.getpeercert(binary_form=True)
            wrapped.sendall(b"x")
    return certificate_names(x509.load_der_x509_certificate(der))


def test_a_long_host_name_is_cut_in_the_common_name_and_kept_whole_in_the_constraints(
    paths,
):
    long_name = "a" * 61 + ".example.org" + "x" * 7

    assert ensure_authority(**paths, host_name=long_name)

    certificate = authority(paths)
    common_name = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    names = certificate.extensions.get_extension_for_class(x509.NameConstraints)
    assert len(common_name[0].value) == 64
    assert DNSName("a" * 61) in names.value.permitted_subtrees
