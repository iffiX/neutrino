"""Making the git server true on a Linux machine.

Installing the binary the hub handed down with its user, directories and
unit; installing a rendered ``app.ini``; administering accounts through
the gitea CLI. Everything the CLI does runs as the git user through
``runuser``, because a root-owned file inside Gitea's tree is a file the
server can no longer touch. Every folder and file the agent makes or
writes in the work root and in ``/etc/gitea``, the git account's, is made
as that account through the step-down; the work root and ``/etc/gitea``
themselves sit in root's place and are made and given by open descriptor,
and a handover of a tree another uid owns is made by open descriptor too,
following no link. ``app.ini`` is read through no link and waiting on no
pipe.

Not pure: writes under ``/etc``, ``/usr/local/bin`` and ``/var/lib``, and
drives the unit.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import stat
from dataclasses import dataclass

from neutrino_agent.modules.gitea.constants import (
    GITEA_BINARY_PATH,
    GITEA_CONF_PATH,
    GITEA_DIR,
    GITEA_ETC_DIR,
    GITEA_OWN_PARTS,
    GITEA_SECRET_NAMES,
    GITEA_SYSTEMD_DIR,
    GITEA_UNIT,
    GITEA_UNIT_SOURCE_NAME,
    GITEA_USER,
    GITEA_VERSION_PREFIX,
)
from neutrino_agent.modules.shared.account_files import AccountFiles
from neutrino_agent.modules.shared.account_service import read_regular
from neutrino_agent.modules.shared.handle_walk import (
    WALK_FILE_FLAGS,
    give_tree,
    make_dirs,
    open_dir,
)
from neutrino_agent.modules.shared.package import place_binary
from neutrino_agent.modules.shared.subprocess_run import run, unit_state

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None

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


def own_dir(path: str, uid: int, gid: int, mode: int = 0) -> None:
    """Make one folder in root's place and give it to an account, by open descriptor.

    Args:
        path: The folder; each level above it is root's.
        uid: The account's uid.
        gid: Its group.
        mode: The mode it is given; 0 keeps the one it has.

    Raises:
        OSError: When a level is a link or the folder cannot be made or
            given.
    """
    make_dirs(path, mode or 0o755)
    descriptor = open_dir(path)
    try:
        held = os.fstat(descriptor)
        if (held.st_uid, held.st_gid) != (uid, gid):
            os.fchown(descriptor, uid, gid)
        if mode and stat.S_IMODE(held.st_mode) != mode:
            os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def give_group(path: str, gid: int) -> None:
    """Give one file in a folder to a group, on its open descriptor, following no link.

    A file that has a second name elsewhere, or is no regular file, is
    left as it is.

    Args:
        path: The file.
        gid: The group.

    Raises:
        OSError: When the folder above it is a link, or the file cannot be
            given.
    """
    try:
        folder = open_dir(os.path.dirname(path))
    except FileNotFoundError:
        return
    try:
        try:
            descriptor = os.open(os.path.basename(path), WALK_FILE_FLAGS, dir_fd=folder)
        except OSError:
            return
        try:
            held = os.fstat(descriptor)
            if stat.S_ISREG(held.st_mode) and held.st_nlink == 1:
                os.fchown(descriptor, -1, gid)
        finally:
            os.close(descriptor)
    finally:
        os.close(folder)


def log_left(left: list, folder: str, log) -> None:
    """Log each entry a handover left outside the folder it gave.

    Args:
        left: The paths :func:`give_tree` left.
        folder: The folder given.
        log: Called with each line; None for nobody listening.
    """
    if log is None:
        return
    for path in left:
        log(f"gitea: left {path}, which is outside {folder}")


def git_files(platform) -> AccountFiles:
    """The git account's places, reached as that account through the step-down."""
    return AccountFiles(platform=platform, account=GITEA_USER)


class GiteaInstaller:
    """Puts the binary, its user, its directories and its unit in place."""

    def __init__(self, *, platform=None):
        """
        Args:
            platform: The machine's platform, which steps down to the git
                account.
        """
        self._platform = platform

    def install(self, binary_path: str) -> None:
        """Install the binary the hub handed down and its unit.

        Args:
            binary_path: The downloaded release binary.

        Raises:
            subprocess.CalledProcessError: If a step refuses.
            OSError: If a file cannot be written.
        """
        place_binary(binary_path, GITEA_BINARY_PATH)
        self.install_unit()

    def ensure_account(self, *, log=None) -> bool:
        """Make the git account when it is missing, and its directories.

        A work root where another uid owns one of Gitea's own parts,
        ``custom``, ``data`` or ``log``, is given to the account with
        everything under it, and ``app.ini`` to its group. A ``git``
        account removed by hand leaves such a root.

        Args:
            log: Called with a line for each entry the handover leaves
                outside the work root; None for nobody listening.

        Returns:
            Whether the work root changed hands.

        Raises:
            subprocess.CalledProcessError: If ``useradd`` refuses.
            OSError: If a directory cannot be made or given.
        """
        self.create_user()
        account = pwd.getpwnam(GITEA_USER)
        is_given = is_handover_owed(GITEA_DIR, account.pw_uid)
        if is_given:
            left = give_tree(GITEA_DIR, account.pw_uid, account.pw_gid)
            log_left(left, GITEA_DIR, log)
            give_group(GITEA_CONF_PATH, account.pw_gid)
        self.create_directories()
        return is_given

    def uninstall(self) -> None:
        """Remove the unit, the binary and the rendered configuration.

        The repositories under the work root stay: install after uninstall
        is a round trip.
        """
        run(["systemctl", "disable", "--now", GITEA_UNIT], is_checked=False)
        _unlink(os.path.join(GITEA_SYSTEMD_DIR, GITEA_UNIT))
        run(["systemctl", "daemon-reload"], is_checked=False)
        _unlink(GITEA_BINARY_PATH)
        try:
            git_files(self._platform).remove(GITEA_CONF_PATH)
        except OSError:
            return

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
        """Make the work root and ``/etc/gitea`` the git account's, and its parts as that account.

        Raises:
            OSError: When a folder cannot be made or given.
        """
        account = pwd.getpwnam(GITEA_USER)
        own_dir(GITEA_DIR, account.pw_uid, account.pw_gid)
        files = git_files(self._platform)
        for name in ("custom", "data", "log"):
            files.make_dir(os.path.join(GITEA_DIR, name), umask=0o022)
        make_ssh_dir(files)
        own_dir(GITEA_ETC_DIR, account.pw_uid, account.pw_gid, 0o770)

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


def make_ssh_dir(files: AccountFiles) -> None:
    """Make the work root's ``.ssh`` as the git account, mode 0700.

    Raises:
        OSError: When it cannot be made or its mode set.
    """
    path = os.path.join(GITEA_DIR, ".ssh")
    files.make_dir(path)
    result = files.run(["chmod", "700", path])
    if result.returncode != 0:
        raise OSError(f"could not set the mode of {path}")


class GiteaConfigApplier:
    """Installs a rendered ``app.ini`` and puts it into effect."""

    def __init__(self, *, platform=None):
        """
        Args:
            platform: The machine's platform, which steps down to the git
                account.
        """
        self._platform = platform

    def apply(self, rendered: str, *, is_started: bool = True) -> str:
        """Install the rendered configuration and run the server on it.

        The file is written when its text differs from the one on disk, and
        a running server is restarted only then: Gitea reads ``app.ini`` at
        start alone, and a restart ends every session and transfer.

        Args:
            rendered: The full ``app.ini`` text.
            is_started: Whether the server is enabled and run on the file.
                False writes the file alone.

        Returns:
            ``unchanged``, ``written``, ``restarted`` or ``started``.

        Raises:
            subprocess.CalledProcessError: If the server refuses to come up.
        """
        is_changed = self._installed_text() != rendered
        if is_changed:
            self._write(rendered)
        self._own_work_root()
        if not is_started:
            return "written" if is_changed else "unchanged"
        if unit_state(GITEA_UNIT) == "active":
            if not is_changed:
                return "unchanged"
            run(["systemctl", "restart", GITEA_UNIT])
            return "restarted"
        run(["systemctl", "enable", "--now", GITEA_UNIT])
        return "started"

    @staticmethod
    def _installed_text() -> "str | None":
        """The ``app.ini`` on disk; None for a missing file, a link or no file."""
        held = read_regular(GITEA_CONF_PATH)
        if held is None:
            return None
        return held.decode("utf-8", "replace")

    def _write(self, rendered: str) -> None:
        """Write ``app.ini`` as the git account, mode 0640: it carries the session and internal-auth secrets.

        Raises:
            OSError: When ``/etc/gitea`` cannot be made or the file cannot
                be written.
        """
        account = pwd.getpwnam(GITEA_USER)
        own_dir(GITEA_ETC_DIR, account.pw_uid, account.pw_gid, 0o770)
        git_files(self._platform).write(
            GITEA_CONF_PATH, rendered.encode("utf-8"), 0o640
        )

    def stop(self) -> None:
        """Take the server down and disable it until the next apply starts it."""
        run(["systemctl", "disable", "--now", GITEA_UNIT], is_checked=False)

    def _own_work_root(self) -> None:
        """Give the git account the work root and its ``.ssh``.

        Gitea creates ``.ssh`` under its work root on start, so a root-owned
        root is fatal on every start. Nothing to do while the account does
        not exist.
        """
        try:
            account = pwd.getpwnam(GITEA_USER)
        except KeyError:
            return
        own_dir(GITEA_DIR, account.pw_uid, account.pw_gid)
        make_ssh_dir(git_files(self._platform))


class GiteaAdminManager:
    """Administers accounts through the gitea CLI, as the git user."""

    def survey(self, *, version: str = "") -> GiteaState:
        """Read what the machine actually has.

        Args:
            version: The version the program file reads as; empty runs
                ``gitea --version``.

        Returns:
            Installed-ness, version, and the administrators by name.
        """
        if not os.path.isfile(GITEA_BINARY_PATH):
            return GiteaState(is_installed=False, version="", admin_usernames=[])
        if not version:
            version_output = run(
                [GITEA_BINARY_PATH, "--version"], is_checked=False, timeout_s=30
            ).stdout
            if version_output.lower().startswith(GITEA_VERSION_PREFIX):
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
            subprocess.CalledProcessError: If Gitea refuses.
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
            subprocess.CalledProcessError: If Gitea refuses.
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


def is_handover_owed(root: str, uid: int) -> bool:
    """Whether another uid owns one of Gitea's own parts of a data directory.

    Args:
        root: The data directory.
        uid: The account's uid.

    Returns:
        True when ``custom``, ``data`` or ``log`` is there and belongs to
        another uid.
    """
    for part in GITEA_OWN_PARTS:
        try:
            if os.lstat(os.path.join(root, part)).st_uid != uid:
                return True
        except FileNotFoundError:
            continue
    return False


def read_listen_port(path: str = "") -> int:
    """The port the installed ``app.ini`` has the server answer on.

    Args:
        path: The ``app.ini``; the Linux one when not named.

    Returns:
        ``HTTP_PORT`` from the file, or 0 when no readable one names it.
    """
    held = read_regular(path or GITEA_CONF_PATH)
    return listen_port_in((held or b"").decode("utf-8", "replace"))


def listen_port_in(text: str) -> int:
    """The port an ``app.ini``'s text has the server answer on. Pure.

    Args:
        text: The file's text.

    Returns:
        ``HTTP_PORT``, or 0 when the text names none.
    """
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "HTTP_PORT":
            try:
                return int(value.strip())
            except ValueError:
                return 0
    return 0


def read_root_url(path: str = "") -> str:
    """The root URL the installed ``app.ini`` names.

    Args:
        path: The ``app.ini``; the Linux one when not named.

    Returns:
        ``ROOT_URL`` from the file, or an empty string when no readable one
        names it.
    """
    held = read_regular(path or GITEA_CONF_PATH)
    return root_url_in((held or b"").decode("utf-8", "replace"))


def root_url_in(text: str) -> str:
    """The root URL an ``app.ini``'s text names. Pure.

    Args:
        text: The file's text.

    Returns:
        ``ROOT_URL``, or an empty string when the text names none.
    """
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "ROOT_URL":
            return value.strip()
    return ""


def read_secrets(path: str = "") -> dict:
    """The machine secrets the installed ``app.ini`` holds.

    Args:
        path: The ``app.ini``; the Linux one when not named.

    Returns:
        Each of the four secrets the file holds with a value, by name;
        empty when no readable file holds one.
    """
    held = read_regular(path or GITEA_CONF_PATH)
    return secrets_in((held or b"").decode("utf-8", "replace"))


def secrets_in(text: str) -> dict:
    """The machine secrets an ``app.ini``'s text holds with a value. Pure.

    Args:
        text: The file's text.

    Returns:
        ``SECRET_KEY``, ``INTERNAL_TOKEN``, ``JWT_SECRET`` and
        ``LFS_JWT_SECRET``, each the text gives a value, by name.
    """
    found = {}
    for line in text.splitlines():
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key in GITEA_SECRET_NAMES and value:
            found[key] = value
    return found


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
