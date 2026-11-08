"""The downloads a build makes, each asked again while its server or the
network fails.

A 5xx, a 429, a timeout or a dropped connection is tried again after each
wait of ``PACKAGING_DOWNLOAD_RETRY_WAITS_S``; any other answer fails at once.

Not pure: reaches the network, writes files.
"""

import http
import http.client
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

from shared.constants import PACKAGING_DOWNLOAD_RETRY_WAITS_S


def read_url(url: str, *, timeout: float, what: str) -> bytes:
    """The body at an address, asked again while the answer fails for a while.

    Args:
        url: The address.
        timeout: Seconds each connection may stay silent.
        what: The file, for the line each retry prints.

    Returns:
        The body.

    Raises:
        urllib.error.HTTPError: At once on a status other than a 5xx or a
            429, and on the last try's 5xx or 429.
        OSError: When the last try times out or loses its connection.
        http.client.HTTPException: When the last try's answer is cut short.
    """
    return _retried(url, timeout, what, lambda response: response.read())


def save_url(url: str, target: Path, *, timeout: float, what: str) -> None:
    """Stream the body at an address into a file, asked again as
    :func:`read_url` asks, each try writing the file from its start.

    Args:
        url: The address.
        target: The file written.
        timeout: Seconds each connection may stay silent.
        what: The file, for the line each retry prints.

    Raises:
        urllib.error.HTTPError: At once on a status other than a 5xx or a
            429, and on the last try's 5xx or 429.
        OSError: When the last try times out or loses its connection.
        http.client.HTTPException: When the last try's answer is cut short.
    """

    def write(response) -> None:
        with target.open("wb") as out:
            shutil.copyfileobj(response, out)

    _retried(url, timeout, what, write)


def _retried(url: str, timeout: float, what: str, consume):
    """What ``consume`` makes of the answer at ``url``, after the retries."""
    for wait in (*PACKAGING_DOWNLOAD_RETRY_WAITS_S, None):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return consume(response)
        except urllib.error.HTTPError as error:
            if wait is None or not _is_retried(error.code):
                raise
            reason = f"HTTP {error.code}"
        except (OSError, http.client.HTTPException) as error:
            if wait is None:
                raise
            reason = str(getattr(error, "reason", error)) or type(error).__name__
        print(f"  {what}: {reason}, trying again in {wait} s", flush=True)
        time.sleep(wait)


def _is_retried(status: int) -> bool:
    """Whether an HTTP status is one a later try may not get."""
    return (
        status == http.HTTPStatus.TOO_MANY_REQUESTS
        or status >= http.HTTPStatus.INTERNAL_SERVER_ERROR
    )
