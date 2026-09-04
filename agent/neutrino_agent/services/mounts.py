"""The mounts service: attaching published shares where a person asks.

The form asks for the share's own username, password and a path; the
password becomes a root-only credentials file on this machine and never
travels to the hub. A path under the asking account's home is
ownership-mapped to that account; anywhere else follows the share's own
permissions. Refusals are typed: ``mountpoint_not_empty``, ``cifs_missing``,
``credentials_missing``. The contract below is what the services flow fills
in; nothing calls it yet.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations


class MountsService:
    """Attaches, detaches and lists this machine's share mounts."""

    def __init__(self, *, platform):
        """
        Args:
            platform: The machine's platform, behind the contract.
        """
        self._platform = platform

    def attach(
        self,
        *,
        account: str,
        share_url: str,
        username: str,
        password: str,
        location: str,
    ) -> dict:
        """Attach one published share at a location.

        Args:
            account: The asking account.
            share_url: The share to attach.
            username: The share's own username.
            password: The share's own password; it stays on this machine.
            location: Where the share appears.

        Returns:
            ``{"state", "code", "params"}``.
        """
        raise NotImplementedError

    def detach(self, *, location: str) -> dict:
        """Detach the share attached at a location.

        Args:
            location: Where the share is attached.

        Returns:
            ``{"state", "code", "params"}``.
        """
        raise NotImplementedError

    def attached(self) -> list:
        """The locations this machine has shares attached at.

        Returns:
            One row per attachment.
        """
        raise NotImplementedError
