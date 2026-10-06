"""Who is asking on the local control channel.

An identity comes from the control connection's kernel peer credentials,
read through the platform contract; nothing a request carries can name a
different caller. The resident answers only the person it runs as, and an
elevated caller of any account only to ask it to quit.
"""


class ControlIdentity:
    """One local caller: its account and uid, and whether it is the person, elevated."""

    def __init__(
        self, *, account: str, uid: int, is_same_user: bool, is_elevated: bool
    ):
        """
        Args:
            account: The account name.
            uid: The kernel-reported uid, -1 where the platform reports none.
            is_same_user: Whether the caller is the account the resident
                runs as.
            is_elevated: Whether the caller runs elevated, as an installer
                does; False where the platform does not tell.
        """
        self.account = account
        self.uid = uid
        self.is_same_user = is_same_user
        self.is_elevated = is_elevated

    def to_dict(self) -> dict:
        """This identity as the wire carries it.

        Returns:
            ``{"account", "uid", "is_same_user", "is_elevated"}``.
        """
        return {
            "account": self.account,
            "uid": self.uid,
            "is_same_user": self.is_same_user,
            "is_elevated": self.is_elevated,
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
    """
    raw = platform.read_peer_identity(connection)
    return ControlIdentity(
        account=str(raw.get("account", "")),
        uid=int(raw.get("uid", -1)),
        is_same_user=bool(raw.get("is_same_user")),
        is_elevated=bool(raw.get("is_elevated")),
    )
