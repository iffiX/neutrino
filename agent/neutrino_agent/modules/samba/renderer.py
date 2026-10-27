"""Rendering the module's own configuration file, the shares it serves.

The module writes its shares to a file of its own, which ``smb.conf``
includes; ``smb.conf`` itself stays the person's or the distribution's, so
the file renders no ``[global]``.

Pure: text in, text out. Writing, validating and reloading is
:mod:`neutrino_agent.modules.samba.applier`.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from neutrino_agent.modules.samba.config import SambaConfig, SambaShare
from neutrino_agent.modules.samba.constants import (
    SAMBA_CONF_MARKER,
    SAMBA_SHARE_HOSTS_ALLOW,
    SAMBA_USERS_FILE_SUFFIX,
    SAMBA_USERS_INCLUDE,
)


class SambaConfigRenderer:
    """Builds the module's own file from the parsed configuration."""

    def __init__(self, *, config: SambaConfig):
        """
        Args:
            config: The parsed share configuration.
        """
        self._config = config

    def render(self) -> str:
        """Render the module's file: the marker, then every share with a user.

        Returns:
            Text ready to write as the module's own file, which ``smb.conf``
            includes. A share that admits no user is left out
            (:meth:`left_out`), never rendered open.
        """
        lines = [SAMBA_CONF_MARKER, ""]
        for share in self._config.served_shares():
            lines += self._render_share(share)
        return "\n".join(lines)

    def left_out(self) -> list:
        """The names of the shares the file leaves out, admitting no user."""
        served = self._config.served_shares()
        return [share.name for share in self._config.shares if share not in served]

    def render_user_files(self) -> dict:
        """Render the file each SMB user's connection includes on a named share.

        Returns:
            File name to text: ``<user>.conf`` for every user an account's
            share admits, holding ``force user`` of that account, so a share
            the file names itself writes the user's files as the account.
        """
        files = {}
        for share in self._config.shares:
            if not share.force_user:
                continue
            for user in share.valid_users:
                files[f"{user}{SAMBA_USERS_FILE_SUFFIX}"] = "\n".join(
                    [SAMBA_CONF_MARKER, f"   force user = {share.force_user}", ""]
                )
        return files

    def _render_share(self, share: SambaShare) -> list:
        # A share admits the users its list names and no other. An account's
        # share writes every file as the account, its primary group with it;
        # a share the file names itself includes the connected user's file,
        # which forces that user's account the same way.
        valid = " ".join(self._config.users_of(share))
        lines = [
            f"[{share.name}]",
            f"   path = {share.path}",
            f"   valid users = {valid}",
            f"   read only = {'yes' if share.is_read_only else 'no'}",
            f"   hosts allow = {SAMBA_SHARE_HOSTS_ALLOW}",
        ]
        if share.force_user:
            lines.append(f"   force user = {share.force_user}")
        else:
            lines.append(f"   include = {SAMBA_USERS_INCLUDE}")
        if share.comment:
            lines.append(f"   comment = {share.comment}")
        lines.append("")
        return lines
