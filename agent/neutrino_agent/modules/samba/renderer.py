"""Rendering the whole of ``smb.conf`` from the share configuration.

The whole file rather than an include: the stock file ships printer shares
and password-sync glue a managed machine has no business serving.

Pure: text in, text out. Writing, validating and reloading is
:mod:`neutrino_agent.modules.samba.applier`.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from neutrino_agent.modules.samba.config import SambaConfig, SambaShare
from neutrino_agent.modules.samba.constants import (
    SAMBA_CONF_MARKER,
    SAMBA_USERS_FILE_SUFFIX,
    SAMBA_USERS_INCLUDE,
)


class SambaConfigRenderer:
    """Builds ``smb.conf`` from the parsed configuration."""

    def __init__(self, *, config: SambaConfig):
        """
        Args:
            config: The parsed share configuration, whose ``allowed_subnets``
                is the second fence behind the firewall's own.
        """
        self._config = config

    def render(self) -> str:
        """Render the configuration file.

        Returns:
            Text ready to write as ``smb.conf``.
        """
        lines = self._render_global()
        for share in self._config.shares:
            lines += self._render_share(share)
        return "\n".join(lines)

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

    def _render_global(self) -> list:
        allowed = " ".join(list(self._config.allowed_subnets) + ["127.0.0.1"])
        return [
            SAMBA_CONF_MARKER,
            "",
            "[global]",
            "   server role = standalone server",
            "   server string = Neutrino share",
            "   disable netbios = yes",
            "   server min protocol = SMB2",
            "",
            "   map to guest = never",
            "",
            f"   hosts allow = {allowed}",
            "   hosts deny = 0.0.0.0/0",
            "",
            "   logging = file",
            "   log file = /var/log/samba/log.%m",
            "   max log size = 1000",
            "",
            "   load printers = no",
            "   printing = bsd",
            "   printcap name = /dev/null",
            "   disable spoolss = yes",
            "",
        ]

    def _render_share(self, share: SambaShare) -> list:
        # A share limited to named users stays limited to them; one with no
        # list is open to every configured user. An account's share writes
        # every file as the account, its primary group with it; a share the
        # file names itself includes the connected user's file, which forces
        # that user's account the same way.
        valid = " ".join(share.valid_users or self._config.users)
        lines = [
            f"[{share.name}]",
            f"   path = {share.path}",
            f"   valid users = {valid}",
            f"   read only = {'yes' if share.is_read_only else 'no'}",
        ]
        if share.force_user:
            lines.append(f"   force user = {share.force_user}")
        else:
            lines.append(f"   include = {SAMBA_USERS_INCLUDE}")
        if share.comment:
            lines.append(f"   comment = {share.comment}")
        lines.append("")
        return lines
