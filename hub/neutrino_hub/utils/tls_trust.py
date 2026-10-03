"""The certificates the hub verifies public HTTPS downloads against.

OpenSSL on Linux finds the system's certificates. The compiled hub on macOS
and Windows carries its own OpenSSL, whose default store on macOS holds
nothing, so when the default context trusts no authority the bundle
``certifi`` ships is loaded into it. ``certifi`` is imported only then: the
build scripts import this package from its checkout, where it is not
installed.

Pure: builds a context and reaches no network.
"""

import ssl


def public_ssl_context() -> ssl.SSLContext:
    """A verifying context for a public host.

    Returns:
        The default context, with certifi's bundle loaded when the default
        store holds no certificate authority and certifi is installed.
    """
    context = ssl.create_default_context()
    if context.cert_store_stats().get("x509_ca", 0) == 0:
        try:
            import certifi
        except ImportError:
            return context
        context.load_verify_locations(cafile=certifi.where())
    return context
