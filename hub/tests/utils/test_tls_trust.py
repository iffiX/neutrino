"""The context public downloads are verified with.

What these pin: the default store is used as it is when it trusts
something, and certifi's bundle is loaded when it trusts nothing.
"""

import ssl

from neutrino_hub.utils import tls_trust


def test_a_default_store_with_authorities_is_left_alone(monkeypatch):
    loaded = []
    context = ssl.create_default_context()
    monkeypatch.setattr(context, "load_verify_locations", lambda **k: loaded.append(k))
    monkeypatch.setattr(tls_trust.ssl, "create_default_context", lambda: context)

    assert tls_trust.public_ssl_context() is context
    assert loaded == [] or context.cert_store_stats()["x509_ca"] == 0


def test_an_empty_default_store_takes_certifi(monkeypatch):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    monkeypatch.setattr(tls_trust.ssl, "create_default_context", lambda: context)

    assert tls_trust.public_ssl_context().cert_store_stats()["x509_ca"] > 0
