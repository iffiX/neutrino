"""Who is asking on the local control channel.

An identity comes from one of two places: the control socket's kernel peer
credentials, read through the platform contract, or a bearer token minted
over that socket and bound to the identity that asked. Tokens live in
memory only and die with the process — or sooner: the page's own polling is
a token's pulse, and one whose pulse has stopped for the idle TTL is
expired, which is how a closed window ends its session.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import secrets
import threading
import time

from neutrino_agent.constants import AGENT_CONTROL_TOKEN_IDLE_TTL_S

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

    def __init__(self, *, idle_ttl_s: int = AGENT_CONTROL_TOKEN_IDLE_TTL_S, clock=None):
        """
        Args:
            idle_ttl_s: How long a token outlives its last page request.
            clock: Monotonic clock; None uses the real one.
        """
        self._idle_ttl_s = idle_ttl_s
        self._clock = clock if clock is not None else time.monotonic
        self._lock = threading.Lock()
        self._tokens: dict = {}

    def mint(self, identity: ControlIdentity) -> str:
        """Mint a token bound to one identity, its pulse started now.

        Args:
            identity: The identity the token answers as.

        Returns:
            The token.
        """
        token = secrets.token_urlsafe(CONTROL_TOKEN_BYTES)
        with self._lock:
            self._tokens[token] = [identity, self._clock()]
        return token

    def identity_of(self, presented: str) -> "ControlIdentity | None":
        """The identity a presented token is bound to, refreshing its pulse.

        Args:
            presented: The token a request carried.

        Returns:
            The bound identity, or None for a token never minted here or
            whose pulse stopped longer than the idle TTL ago.
        """
        if not presented:
            return None
        with self._lock:
            for token, entry in list(self._tokens.items()):
                if not secrets.compare_digest(token, presented):
                    continue
                if self._clock() - entry[1] > self._idle_ttl_s:
                    del self._tokens[token]
                    return None
                entry[1] = self._clock()
                return entry[0]
        return None

    def is_alive(self, presented: str) -> bool:
        """Whether a token still answers, without counting as its pulse.

        Args:
            presented: The token to ask about.

        Returns:
            True while the token exists and its pulse has not stopped.
        """
        if not presented:
            return False
        with self._lock:
            for token, entry in list(self._tokens.items()):
                if not secrets.compare_digest(token, presented):
                    continue
                if self._clock() - entry[1] > self._idle_ttl_s:
                    del self._tokens[token]
                    return False
                return True
        return False

    def revoke(self, presented: str) -> None:
        """Drop one token at once; one never minted is nothing.

        Args:
            presented: The token to revoke.
        """
        if not presented:
            return
        with self._lock:
            for token in list(self._tokens):
                if secrets.compare_digest(token, presented):
                    del self._tokens[token]
                    return


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
