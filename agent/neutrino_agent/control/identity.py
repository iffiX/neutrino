"""Who is asking on the local control channel.

An identity comes from one of two places: the control socket's kernel peer
credentials, read through the platform contract, or a bearer token minted
over that socket and bound to the identity that asked. Tokens live in
memory only and die with the process.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import secrets
import threading

CONTROL_TOKEN_BYTES = 24


class ControlIdentity:
    """One local caller: an account, its uid, and whether it is privileged."""

    def __init__(self, *, account: str, uid: int, is_privileged: bool):
        """
        Args:
            account: The account name.
            uid: The kernel-reported uid, -1 where the platform reports none.
            is_privileged: Whether the caller holds the platform's
                administrative identity.
        """
        self.account = account
        self.uid = uid
        self.is_privileged = is_privileged

    def to_dict(self) -> dict:
        """This identity as the wire carries it.

        Returns:
            ``{"account", "uid", "is_privileged"}``.
        """
        return {
            "account": self.account,
            "uid": self.uid,
            "is_privileged": self.is_privileged,
        }


class ControlTokenStore:
    """The tokens minted over the socket, each bound to an identity."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tokens: dict = {}

    def mint(self, identity: ControlIdentity) -> str:
        """Mint a token bound to one identity.

        Args:
            identity: The identity the token answers as.

        Returns:
            The token.
        """
        token = secrets.token_urlsafe(CONTROL_TOKEN_BYTES)
        with self._lock:
            self._tokens[token] = identity
        return token

    def identity_of(self, presented: str) -> "ControlIdentity | None":
        """The identity a presented token is bound to.

        Args:
            presented: The token a request carried.

        Returns:
            The bound identity, or None for a token never minted here.
        """
        if not presented:
            return None
        with self._lock:
            entries = list(self._tokens.items())
        for token, identity in entries:
            if secrets.compare_digest(token, presented):
                return identity
        return None


def peer_identity(platform, connection) -> ControlIdentity:
    """The identity of a control socket peer.

    Args:
        platform: The machine's platform, behind the contract.
        connection: The accepted socket.

    Returns:
        The caller's identity.

    Raises:
        PlatformUnsupportedError: When the platform cannot read peers.
        KeyError: When the peer's uid names no account.
    """
    raw = platform.read_peer_identity(connection)
    return ControlIdentity(
        account=str(raw.get("account", "")),
        uid=int(raw.get("uid", -1)),
        is_privileged=bool(raw.get("is_privileged")),
    )
