"""Package bytes, down one stream the agent opens.

The agent opens ``package {module}`` for a module's package from the hub's
cache, and ``package {}`` for its own. It grants credit as it writes each
piece to a temporary file under its data directory, waits for the hub's
close, and checks the ``sha256`` the close's params carry against what
landed. Only a file that matches is handed over; a mismatch, a refusal
from the hub, or a socket that dropped mid-transfer leaves no file behind.

A file is left behind on purpose in one case: the agent's own package
outlives the process that received it, because the install restarts that
process. The agent the install put on the machine clears the directory
when it starts.

Not pure: writes the file system.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile

from neutrino_agent.constants import AGENT_WS_STREAM_CREDIT_BYTES
from neutrino_agent.exceptions import GatewayUnreachable

PACKAGE_PREFIX = ".package."
PACKAGE_SUFFIX = ".part"
# What the stream answers when the bytes do not match the close's digest,
# and when the socket went away under it.
CODE_DIGEST_MISMATCH = "package_digest_mismatch"
CODE_UNREACHABLE = "hub_unreachable"


class PackageStream:
    """One package's bytes, received into a file whose digest is checked."""

    def __init__(self, channel, *, directory: str):
        """
        Args:
            channel: The stream's channel, opened as ``package {...}``.
            directory: Where the file lands, made root-only when missing.
        """
        self._channel = channel
        self._directory = directory

    def receive(self) -> dict:
        """Take every byte, wait for the close, and check the digest.

        Returns:
            ``{"path"}`` naming the file when its digest matched; otherwise
            ``{"code", "params"}``: the hub's own code when it closed with
            one, ``package_digest_mismatch`` when the bytes do not match
            the ``sha256`` the close named, ``hub_unreachable`` when the
            stream ended without one, and ``write_failed`` when the disk
            refused. No file remains in any of those cases.
        """
        try:
            os.makedirs(self._directory, mode=0o700, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                dir=self._directory,
                prefix=PACKAGE_PREFIX,
                suffix=PACKAGE_SUFFIX,
                delete=False,
            )
        except OSError as error:
            return _refusal("write_failed", path=self._directory, detail=str(error))
        path = handle.name
        digest = hashlib.sha256()
        try:
            with handle:
                closing = self._take(handle, digest)
                handle.flush()
                os.fsync(handle.fileno())
        except GatewayUnreachable:
            _unlink(path)
            return _refusal(CODE_UNREACHABLE)
        except OSError as error:
            _unlink(path)
            return _refusal("write_failed", path=path, detail=str(error)[:200])
        code, params = closing
        if code:
            _unlink(path)
            return {"code": code, "params": dict(params)}
        expected = str(params.get("sha256", "") or "")
        if not expected:
            _unlink(path)
            return _refusal(CODE_UNREACHABLE)
        if expected != digest.hexdigest():
            _unlink(path)
            return _refusal(CODE_DIGEST_MISMATCH)
        return {"path": path}

    def _take(self, handle, digest) -> tuple:
        """Write the hub's bytes until its close, granting as each lands.

        Returns:
            The close's ``(code, params)``.

        Raises:
            OSError: When the file cannot be written.
            GatewayUnreachable: When the socket is gone.
        """
        self._channel.offer_credit(AGENT_WS_STREAM_CREDIT_BYTES)
        while True:
            item = self._channel.recv()
            if item is None:
                continue
            if item[0] == "close":
                return str(item[1] or ""), dict(item[2] or {})
            if item[0] != "data":
                continue
            handle.write(item[1])
            digest.update(item[1])
            self._channel.offer_credit(len(item[1]))


def remove_stale(directory: str) -> None:
    """Delete every file a package transfer left in the directory.

    Args:
        directory: Where packages land; one that is not there is left so.
    """
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        _unlink(os.path.join(directory, name))


def _refusal(code: str, **params) -> dict:
    return {"code": code, "params": params}


def _unlink(path: str) -> None:
    with contextlib.suppress(OSError):
        os.unlink(path)
