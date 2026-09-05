"""Fetching a vendor's package for a device that cannot fetch it itself.

Several vendors serve their downloads only to what looks like a browser,
gating on the TLS fingerprint rather than on a header — a plain fetcher gets
a challenge page with a 200 beside it. Presenting a browser's fingerprint
takes a library, and the agent carries no dependencies at all, so the hub
does this fetch and hands the bytes down the channel the agent already
trusts.

What comes back is checked here: a challenge page is bytes like any other,
and the honest answer to one is naming it, not installing it.

Not pure: fetches over the network.
"""

from dataclasses import dataclass

from neutrino_hub.modules.devices.constants import (
    DEVICE_VENDOR_FETCH_IMPERSONATE,
    DEVICE_VENDOR_FETCH_LIMIT_BYTES,
    DEVICE_VENDOR_FETCH_TIMEOUT_S,
)

# What each package kind starts with, so a page served in a package's place
# is caught before anything hands it to an installer.
PACKAGE_MAGIC = {
    "deb": (b"!<arch>",),
    "rpm": (b"\xed\xab\xee\xdb",),
    "msi": (b"\xd0\xcf\x11\xe0",),
    "exe": (b"MZ",),
    "dmg": (b"koly", b"\x78\x01\x73", b"\x42\x5a\x68"),
    "tar_binary": (b"\x1f\x8b", b"BZh", b"\xfd7zXZ"),
    "zip_binary": (b"PK\x03\x04",),
}


class VendorFetchError(RuntimeError):
    """Raised when a vendor's package cannot be fetched or is not one.

    Attributes:
        code: The typed reason, for the panel and the agent to word.
        params: What the wording needs.
    """

    def __init__(self, code: str, **params):
        """
        Args:
            code: The typed reason.
            **params: Values the wording names.
        """
        super().__init__(code)
        self.code = code
        self.params = params


@dataclass
class VendorPackage:
    """A fetched package.

    Attributes:
        content: The bytes.
        content_type: What the server called them.
    """

    content: bytes
    content_type: str


def looks_like_package(content: bytes, package_kind: str) -> bool:
    """Whether these bytes open like the package kind they claim to be.

    Args:
        content: What arrived.
        package_kind: The kind the manifest names.

    Returns:
        True when the magic matches, or when the kind is one this does not
        know — an unknown kind is not evidence of a page.
    """
    magic = PACKAGE_MAGIC.get(package_kind)
    if magic is None:
        return True
    return any(content.startswith(prefix) for prefix in magic)


def fetch_vendor_package(url: str, *, package_kind: str) -> VendorPackage:
    """Fetch one vendor package as a browser would.

    Args:
        url: Where the manifest says the package lives.
        package_kind: The kind it should be, so a challenge page is caught.

    Returns:
        The fetched package.

    Raises:
        VendorFetchError: ``vendor_fetch_unavailable`` when this hub has no
            impersonating fetcher, ``vendor_fetch_failed`` when the request
            itself failed, ``vendor_fetch_too_large`` past the size ceiling,
            and ``vendor_served_a_page`` when what came back is not the
            package — which is what a bot check looks like from here.
    """
    try:
        from curl_cffi import requests
    except ImportError as error:
        raise VendorFetchError("vendor_fetch_unavailable") from error

    try:
        response = requests.get(
            url,
            impersonate=DEVICE_VENDOR_FETCH_IMPERSONATE,
            timeout=DEVICE_VENDOR_FETCH_TIMEOUT_S,
        )
        response.raise_for_status()
    except Exception as error:  # noqa: BLE001 - any failure is one answer
        raise VendorFetchError(
            "vendor_fetch_failed", detail=str(error)[:200]
        ) from error

    content = response.content
    if len(content) > DEVICE_VENDOR_FETCH_LIMIT_BYTES:
        raise VendorFetchError(
            "vendor_fetch_too_large",
            limit_mb=DEVICE_VENDOR_FETCH_LIMIT_BYTES // (1024 * 1024),
        )
    if not looks_like_package(content, package_kind):
        raise VendorFetchError(
            "vendor_served_a_page",
            content_type=str(response.headers.get("content-type", ""))[:80],
        )
    return VendorPackage(
        content=content,
        content_type=str(response.headers.get("content-type", "")),
    )
