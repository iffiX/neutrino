"""Making the git server true on the machine.

Installing the binary the hub handed down with its user, directories and
unit; installing a rendered ``app.ini``; administering accounts through
the gitea CLI. Everything the CLI does runs as the git user through
``runuser``, because a root-owned file inside Gitea's tree is a file the
server can no longer touch.

Not pure: writes under ``/etc``, ``/usr/local/bin`` and ``/var/lib``, and
drives the unit.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import pwd
import shutil
import tempfile
from dataclasses import dataclass

from neutrino_agent.modules.gitea.constants import (
    GITEA_BINARY_PATH,
    GITEA_CONF_PATH,
    GITEA_DIR,
    GITEA_ETC_DIR,
    GITEA_SYSTEMD_DIR,
    GITEA_UNIT,
    GITEA_UNIT_SOURCE_NAME,
    GITEA_USER,
)
from neutrino_agent.modules.subprocess_run import run, unit_state

UNIT_SOURCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "systemd"
)


@dataclass
class GiteaState:
    """What the machine actually has.

    Attributes:
        is_installed: Whether the binary exists.
        version: The installed version, empty when not installed.
        admin_usernames: The administrator accounts, by name.
    """

    is_installed: bool
    version: str
    admin_usernames: list

    @property
    def has_admin(self) -> bool:
        """Whether any administrator account exists yet."""
        return len(self.admin_usernames) > 0


class GiteaInstaller:
    """Puts the binary, its user, its directories and its unit in place."""

    def install(self, binary_path: str) -> None:
        """Install what the hub handed down.

        Args:
            binary_path: The downloaded release binary.

        Raises:
            CommandError: If a step refuses.
            OSError: If a file cannot be written.
        """
        self.create_user()
        self.create_directories()
        shutil.copyfile(binary_path, GITEA_BINARY_PATH)
        os.chmod(GITEA_BINARY_PATH, 0o755)
        self.install_unit()

    def uninstall(self) -> None:
        """Remove the unit, the binary and the rendered configuration.

        The repositories under the work root stay: install after uninstall
        is a round trip.
        """
        run(["systemctl", "disable", "--now", GITEA_UNIT], is_checked=False)
        _unlink(os.path.join(GITEA_SYSTEMD_DIR, GITEA_UNIT))
        run(["systemctl", "daemon-reload"], is_checked=False)
        _unlink(GITEA_BINARY_PATH)
        _unlink(GITEA_CONF_PATH)

    def create_user(self) -> None:
        """Make the git account, if it is missing."""
        if run(["id", GITEA_USER], is_checked=False).is_success:
            return
        run(
            [
                "useradd",
                "--system",
                "--shell",
                "/bin/bash",
                "--comment",
                "Gitea",
                "--create-home",
                "--home-dir",
                GITEA_DIR,
                GITEA_USER,
            ]
        )

    def create_directories(self) -> None:
        """Make the work root and its parts, owned by the git account."""
        for directory in (
            GITEA_DIR,
            os.path.join(GITEA_DIR, "custom"),
            os.path.join(GITEA_DIR, "data"),
            os.path.join(GITEA_DIR, "log"),
            os.path.join(GITEA_DIR, ".ssh"),
            GITEA_ETC_DIR,
        ):
            os.makedirs(directory, exist_ok=True)
            shutil.chown(directory, user=GITEA_USER, group=GITEA_USER)
        os.chmod(os.path.join(GITEA_DIR, ".ssh"), 0o700)
        os.chmod(GITEA_ETC_DIR, 0o770)

    def install_unit(self) -> bool:
        """Install the packaged unit when it differs from what is live.

        Returns:
            Whether anything changed.
        """
        source = os.path.join(UNIT_SOURCE_DIR, GITEA_UNIT_SOURCE_NAME)
        with open(source, "r", encoding="utf-8") as stream:
            wanted = stream.read()
        target = os.path.join(GITEA_SYSTEMD_DIR, GITEA_UNIT)
        if os.path.isfile(target):
            with open(target, "r", encoding="utf-8") as stream:
                if stream.read() == wanted:
                    return False
        with open(target, "w", encoding="utf-8") as stream:
            stream.write(wanted)
        run(["systemctl", "daemon-reload"])
        return True


class GiteaConfigApplier:
    """Installs a rendered ``app.ini`` and puts it into effect."""

    def apply(self, rendered: str) -> str:
        """Install the rendered configuration and run the server on it.

        Args:
            rendered: The full ``app.ini`` text.

        Returns:
            A short summary of what was done.

        Raises:
            CommandError: If the server refuses to come up.
        """
        os.makedirs(GITEA_ETC_DIR, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=GITEA_ETC_DIR, prefix=".app_")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(rendered)
            # Group-readable by the git user only: the file carries the
            # session and internal-auth secrets.
            os.chmod(temporary, 0o640)
            shutil.chown(temporary, group=GITEA_USER)
            if os.path.islink(GITEA_CONF_PATH):
                os.unlink(GITEA_CONF_PATH)
            os.replace(temporary, GITEA_CONF_PATH)
        except BaseException:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise
        self._own_work_root()
        if unit_state(GITEA_UNIT) == "active":
            # Gitea re-reads app.ini only at start.
            run(["systemctl", "restart", GITEA_UNIT])
            return "restarted"
        run(["systemctl", "enable", "--now", GITEA_UNIT])
        return "started"

    def stop(self) -> None:
        """Take the server down until the next apply."""
        run(["systemctl", "disable", "--now", GITEA_UNIT], is_checked=False)

    def _own_work_root(self) -> None:
        """Give the git account the work root and its ``.ssh``.

        Gitea creates ``.ssh`` under its work root on start, so a root-owned
        root is fatal on every start. Nothing to do while the account does
        not exist.
        """
        try:
            pwd.getpwnam(GITEA_USER)
        except KeyError:
            return
        os.makedirs(GITEA_DIR, exist_ok=True)
        ssh_dir = os.path.join(GITEA_DIR, ".ssh")
        os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
        for path in (GITEA_DIR, ssh_dir):
            shutil.chown(path, user=GITEA_USER, group=GITEA_USER)


class GiteaAdminManager:
    """Administers accounts through the gitea CLI, as the git user."""

    def survey(self) -> GiteaState:
        """Read what the machine actually has.

        Returns:
            Installed-ness, version, and the administrators by name.
        """
        if not os.path.isfile(GITEA_BINARY_PATH):
            return GiteaState(is_installed=False, version="", admin_usernames=[])
        version_output = run(
            [GITEA_BINARY_PATH, "--version"], is_checked=False, timeout_s=30
        ).stdout
        version = ""
        if version_output.startswith("Gitea version"):
            version = version_output.split()[2]
        return GiteaState(
            is_installed=True, version=version, admin_usernames=self._admin_names()
        )

    def create_admin(self, *, username: str, password: str, email: str) -> None:
        """Create an administrator account.

        Args:
            username: The account name.
            password: Its password, which goes to Gitea and nowhere else.
            email: The account's address.

        Raises:
            CommandError: If Gitea refuses.
        """
        run(
            self._as_git(
                "admin",
                "user",
                "create",
                "--admin",
                "--username",
                username,
                "--password",
                password,
                "--email",
                email,
                "--must-change-password=false",
            )
        )

    def change_password(self, *, username: str, password: str) -> None:
        """Reset an administrator's password.

        Args:
            username: An existing administrator.
            password: The new password.

        Raises:
            CommandError: If Gitea refuses.
        """
        run(
            self._as_git(
                "admin",
                "user",
                "change-password",
                "--username",
                username,
                "--password",
                password,
                "--must-change-password=false",
            )
        )

    def _admin_names(self) -> list:
        if not os.path.exists(GITEA_CONF_PATH):
            return []
        result = run(
            self._as_git("admin", "user", "list", "--admin"),
            is_checked=False,
            timeout_s=30,
        )
        if not result.is_success:
            return []
        # A table: ID, Username, Email, IsActive, one header line first.
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        return [line.split()[1] for line in lines[1:] if len(line.split()) > 1]

    @staticmethod
    def _as_git(*arguments: str) -> list:
        return [
            "runuser",
            "-u",
            GITEA_USER,
            "--",
            GITEA_BINARY_PATH,
            *arguments,
            "--config",
            GITEA_CONF_PATH,
        ]


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
