"""Fetching vendor packages on the device's own network.

The gateway never ships these binaries: the repo stays light, and a fleet
install means every device downloads in parallel from wherever is closest to
it. Some vendors (ToDesk among them) refuse plain fetchers, so downloads can
run with browser impersonation — through ``curl_cffi`` when it is available,
and with a full set of browser headers otherwise, which is enough for the
filters that only look at headers.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import shutil
import urllib.request

DOWNLOAD_TIMEOUT_S = 600
GITHUB_API = "https://api.github.com/repos/{repo}/releases/latest"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
}


# What a package of each kind starts with. Checked after every download
# because a CDN that refuses a fetcher does not answer with an error: ToDesk's
# serves a two-kilobyte HTML challenge page under HTTP 200, and installing
# that as a package fails in a way that reads like a broken package rather
# than a blocked download.
MAGIC_BY_KIND = {
    "deb": b"!<ar",
    "rpm": (b"\xed\xab\xee\xdb", b"!<ar"),
    "msi": b"\xd0\xcf\x11\xe0",
    "exe": b"MZ",
    "dmg": None,
    "pkg": b"xar!",
    "zip": b"PK",
    "tar.gz": b"\x1f\x8b",
}

MINIMUM_PACKAGE_BYTES = 100 * 1024


class DownloadError(RuntimeError):
    """Raised when a package cannot be fetched."""


def verify_package(path: str, kind: str) -> None:
    """Check a downloaded file really is the kind of package expected.

    Args:
        path: The downloaded file.
        kind: Package kind from the manifest.

    Raises:
        DownloadError: If the file is too small or does not start the way its
            kind does — which is what a challenge page or an error page looks
            like once it has been saved under HTTP 200.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as stream:
            head = stream.read(8)
    except OSError as error:
        raise DownloadError(f"could not read the download: {error}")

    if size < MINIMUM_PACKAGE_BYTES:
        raise DownloadError(
            f"the download is only {size} bytes — the server most likely "
            f"answered with a challenge or error page instead of the package"
        )
    expected = MAGIC_BY_KIND.get(kind)
    if expected is None:
        return
    candidates = expected if isinstance(expected, tuple) else (expected,)
    if not any(head.startswith(magic) for magic in candidates):
        raise DownloadError(
            f"the download does not look like a {kind} package "
            f"(starts with {head[:4]!r}); the server may have blocked it"
        )


def resolve_github_asset(repo: str, asset_pattern: str) -> str:
    """Find the newest release asset whose name ends with a pattern.

    Args:
        repo: ``owner/name`` on GitHub.
        asset_pattern: Suffix the wanted asset's file name ends with.

    Returns:
        The asset's download URL.

    Raises:
        DownloadError: If the release cannot be read or nothing matches.
    """
    request = urllib.request.Request(
        GITHUB_API.format(repo=repo), headers=BROWSER_HEADERS
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.load(response)
    except OSError as error:
        raise DownloadError(f"could not read {repo} releases: {error}")
    for asset in release.get("assets", []):
        if asset.get("name", "").endswith(asset_pattern):
            return asset.get("browser_download_url", "")
    raise DownloadError(f"no {asset_pattern!r} asset in {repo}'s latest release")


def download(url: str, destination: str, *, is_impersonated: bool = False) -> None:
    """Fetch one file to disk, always presenting as a browser.

    Browser headers are not an opt-in: they cost nothing and are what several
    vendor CDNs check before serving anything but a challenge page.
    ``is_impersonated`` goes further, matching a browser's TLS fingerprint too
    — which needs ``curl_cffi``, and falls back to headers alone without it.

    Args:
        url: Where from.
        destination: Where to.
        is_impersonated: Also impersonate a browser's TLS fingerprint.

    Raises:
        DownloadError: If the fetch fails.
    """
    if is_impersonated and _curl_cffi_download(url, destination):
        return
    request = urllib.request.Request(url, headers=BROWSER_HEADERS)
    try:
        with (
            urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response,
            open(destination, "wb") as stream,
        ):
            shutil.copyfileobj(response, stream)
    except OSError as error:
        raise DownloadError(f"download failed: {error}")


def _curl_cffi_download(url: str, destination: str) -> bool:
    """Best-effort fetch with TLS impersonation; False means fall back."""
    try:
        from curl_cffi import requests
    except ImportError:
        return False
    try:
        response = requests.get(url, impersonate="chrome", timeout=DOWNLOAD_TIMEOUT_S)
        response.raise_for_status()
    except Exception as error:  # noqa: BLE001 - any failure falls back
        raise DownloadError(f"impersonated download failed: {error}")
    with open(destination, "wb") as stream:
        stream.write(response.content)
    return True
