"""Making the git server's configuration true on the box.

Three effects, kept apart from the pure renderer: generating the machine secrets
``app.ini`` needs, installing a rendered file, and administering accounts
through the gitea CLI. Everything the CLI does runs as the git user, because
a root-owned file inside Gitea's tree is a file the server can no longer
touch.
"""

import pwd
import re
import shutil
from dataclasses import dataclass

from neutrino_hub.system.constants import SYSTEM_SYSTEMD_DIR
from neutrino_hub.utils.constants import UTILS_CONFIG_DIR, UTILS_GENERATED_DIR
from neutrino_hub.utils.json_file import read_config, write_config, write_generated
from neutrino_hub.utils.subprocess_run import CommandError, run

from neutrino_hub.modules.gitea.constants import (
    GITEA_BINARY_PATH,
    GITEA_CONF_LINK_PATH,
    GITEA_DIR,
    GITEA_GENERATED_NAME,
    GITEA_SECRET_NAMES,
    GITEA_USER,
)

GITEA_SERVICE = "neutrino_hub_gitea"

# What accounts may be called. Gitea has its own rules; this is the subset
# that survives both it and a shell command line.
ADMIN_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,38}\Z")


@dataclass
class GiteaState:
    """What the box actually has, next to what config/ asks for.

    Attributes:
        is_installed: Whether the binary exists.
        version: The installed version, empty when not installed.
        admin_usernames: The administrator accounts, by name. Empty on a
            fresh install and the page says so, because a Gitea with no
            accounts and registration off is a Gitea nobody can enter.
    """

    is_installed: bool
    version: str
    admin_usernames: list[str]

    @property
    def has_admin(self) -> bool:
        """Whether any administrator account exists yet."""
        return len(self.admin_usernames) > 0


class GiteaSecretStore:
    """Generates and keeps the machine secrets ``app.ini`` needs.

    They live in ``config/gitea/secrets.json``, gitignored: losing them on a
    rebuild invalidates sessions and tokens, never repositories, so they are
    a convenience worth keeping and not a treasure worth guarding in git.
    """

    def load(self) -> dict:
        """Read the secrets, generating any that are missing.

        Returns:
            Every named secret, by name.

        Raises:
            CommandError: If a secret must be generated and gitea cannot.
        """
        path = UTILS_CONFIG_DIR / "gitea/secrets.json"
        secrets = {}
        if path.is_file():
            secrets = read_config("gitea/secrets.json")
        missing = [name for name in GITEA_SECRET_NAMES if not secrets.get(name)]
        for name in missing:
            result = run([str(GITEA_BINARY_PATH), "generate", "secret", name])
            secrets[name] = result.stdout.strip()
        if missing:
            write_config("gitea/secrets.json", secrets)
        return secrets


class GiteaConfigApplier:
    """Installs a rendered ``app.ini`` and puts it into effect."""

    def apply(self, rendered: str) -> str:
        """Install the rendered configuration and restart a running server.

        Args:
            rendered: The full ``app.ini`` text.

        Returns:
            A short summary of what was done.

        Raises:
            CommandError: If the server refuses to come back up.
        """
        generated_path = UTILS_GENERATED_DIR / GITEA_GENERATED_NAME
        # Group-readable by the git user only: the file carries the session
        # and internal-auth secrets.
        write_generated(generated_path, rendered, mode=0o640)
        shutil.chown(generated_path, group=GITEA_USER)
        self._link_config()
        self._own_work_root()

        is_active = run(
            ["systemctl", "is-active", GITEA_SERVICE], is_checked=False
        ).stdout.strip()
        if is_active == "active":
            # Restart rather than reload: Gitea re-reads app.ini only at
            # start, and a restart drops nothing durable — clones in flight
            # fail and retry, sessions live in files and survive.
            run(["systemctl", "restart", GITEA_SERVICE])
            return "restarted gitea"
        return "gitea not running; configuration staged"

    def refresh_unit(self, unit_text: str) -> bool:
        """Install the packaged unit file when it differs from what is live.

        Args:
            unit_text: The content of ``services/neutrino_hub_gitea.service``.

        Returns:
            Whether anything changed.
        """
        unit_path = SYSTEM_SYSTEMD_DIR / "neutrino_hub_gitea.service"
        if unit_path.is_file() and unit_path.read_text(encoding="utf-8") == unit_text:
            return False
        unit_path.write_text(unit_text, encoding="utf-8")
        run(["systemctl", "daemon-reload"])
        return True

    def _own_work_root(self) -> None:
        """Give the git account the work root and its ``.ssh``.

        Gitea creates ``.ssh`` under its work root on start, so a root-owned
        root is fatal on every start. Runs on every apply, which is what
        heals a box that installed with the root owned wrong. Nothing to do
        while the git account does not exist yet.
        """
        try:
            pwd.getpwnam(GITEA_USER)
        except KeyError:
            return
        GITEA_DIR.mkdir(parents=True, exist_ok=True)
        ssh_dir = GITEA_DIR / ".ssh"
        ssh_dir.mkdir(mode=0o700, exist_ok=True)
        for path in (GITEA_DIR, ssh_dir):
            shutil.chown(path, user=GITEA_USER, group=GITEA_USER)

    def _link_config(self) -> None:
        generated_path = UTILS_GENERATED_DIR / GITEA_GENERATED_NAME
        if (
            GITEA_CONF_LINK_PATH.is_symlink()
            and GITEA_CONF_LINK_PATH.readlink() == generated_path
        ):
            return
        GITEA_CONF_LINK_PATH.parent.mkdir(parents=True, exist_ok=True)
        GITEA_CONF_LINK_PATH.unlink(missing_ok=True)
        GITEA_CONF_LINK_PATH.symlink_to(generated_path)


class GiteaAdminManager:
    """Administers accounts through the gitea CLI, as the git user.

    The commands run through ``runuser`` rather than ``sudo``: the panel is
    already root, so this is a step down rather than up, and sudo refuses to
    run at all under the unit's ``NoNewPrivileges``.
    """

    def survey(self) -> GiteaState:
        """Read what the box actually has.

        Returns:
            Installed-ness, version, and the administrators by name.
        """
        if not GITEA_BINARY_PATH.is_file():
            return GiteaState(is_installed=False, version="", admin_usernames=[])
        version_output = run(
            [str(GITEA_BINARY_PATH), "--version"], is_checked=False
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
            email: The account's address; Gitea insists on one even where no
                mail will ever be sent.

        Raises:
            ValueError: If the username cannot be used.
            CommandError: If Gitea refuses.
        """
        if not ADMIN_NAME_PATTERN.match(username):
            raise ValueError(
                f"username {username!r} is not usable; use letters, digits, "
                f"'.', '-' and '_', up to 39 characters"
            )
        run(
            [
                "runuser",
                "-u",
                GITEA_USER,
                "--",
                str(GITEA_BINARY_PATH),
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
                "--config",
                str(GITEA_CONF_LINK_PATH),
            ]
        )

    def change_password(self, *, username: str, password: str) -> None:
        """Reset an administrator's password.

        The panel's recovery door: a forgotten admin password cannot be fixed
        inside Gitea, because fixing it requires the login it replaces.

        Args:
            username: An existing administrator.
            password: The new password, which goes to Gitea and nowhere else.

        Raises:
            CommandError: If Gitea refuses.
        """
        run(
            [
                "runuser",
                "-u",
                GITEA_USER,
                "--",
                str(GITEA_BINARY_PATH),
                "admin",
                "user",
                "change-password",
                "--username",
                username,
                "--password",
                password,
                "--must-change-password=false",
                "--config",
                str(GITEA_CONF_LINK_PATH),
            ]
        )

    def _admin_names(self) -> list[str]:
        if not GITEA_CONF_LINK_PATH.exists():
            return []
        result = run(
            [
                "runuser",
                "-u",
                GITEA_USER,
                "--",
                str(GITEA_BINARY_PATH),
                "admin",
                "user",
                "list",
                "--admin",
                "--config",
                str(GITEA_CONF_LINK_PATH),
            ],
            is_checked=False,
        )
        if not result.is_success:
            return []
        # Output is a table — ID, Username, Email, IsActive — with one header
        # line before the accounts.
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        return [line.split()[1] for line in lines[1:] if len(line.split()) > 1]
