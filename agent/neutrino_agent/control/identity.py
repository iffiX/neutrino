"""Who is asking on the local control channel.

An identity comes from the control connection's kernel peer credentials,
read through the platform contract; nothing a request carries can name a
different caller.
"""


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
