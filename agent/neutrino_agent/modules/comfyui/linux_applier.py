"""ComfyUI on Linux: the account ``neutrino_comfyui``, a systemd unit, the shared folders' access lists.

The data directory ``comfyui_data`` under the state root is the account's,
mode 0700: root makes it in its own place and gives it on its open
descriptor, a tree another uid owns is handed over by open descriptor
following no link, and every folder in it is made as the account. uv runs
as the account through the step-down, its environment written from scratch
and its working folder the data directory. The unit
``neutrino_comfyui.service`` runs the server as the account with
``UMask=0027``.

Not pure: writes under ``/etc/systemd/system`` and the state root, drives
``useradd``, ``usermod`` and ``systemctl``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import shlex

from neutrino_agent.modules.comfyui.constants import (
    COMFYUI_ACCOUNT_STEP_TIMEOUT_S,
    COMFYUI_BASE_DIR,
    COMFYUI_DATA_DIR_NAME,
    COMFYUI_LINUX_ACCOUNT,
    COMFYUI_LINUX_ACCOUNT_COMMENT,
    COMFYUI_LINUX_GPU_GROUPS,
    COMFYUI_LINUX_SHELLS,
    COMFYUI_LINUX_SYSTEMD_DIR,
    COMFYUI_LINUX_UMASK,
    COMFYUI_LINUX_UNIT,
    COMFYUI_NAME,
    COMFYUI_POSIX_ENV,
    COMFYUI_POSIX_PATH,
    COMFYUI_PYCACHE_DIR,
    COMFYUI_READ_FOLDERS,
    COMFYUI_SERVICE_FOLDERS,
    COMFYUI_TMP_DIR,
    COMFYUI_UV_CACHE_DIR,
    COMFYUI_WRITE_FOLDERS,
)
from neutrino_agent.modules.comfyui.linux_access import LinuxFolderAccess
from neutrino_agent.modules.comfyui.server import (
    ComfyuiServer,
    server_command,
    server_environment,
)
from neutrino_agent.modules.gitea.applier import own_dir
from neutrino_agent.modules.shared.account_files import AccountFiles
from neutrino_agent.modules.shared.account_service import write_if_changed
from neutrino_agent.modules.shared.handle_walk import give_tree
from neutrino_agent.modules.shared.subprocess_run import run, unit_state
from neutrino_agent.modules.shared.unpacked_tree import remove_tree

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None


def environment_lines(environment: dict) -> str:
    """One ``Environment=`` line per variable, by name. Pure."""
    return "".join(
        f"Environment={shlex.quote(f'{name}={value}')}\n"
        for name, value in sorted(environment.items())
    )


def render_unit(server: ComfyuiServer, *, module_dir: str, data_dir: str) -> str:
    """The server's systemd unit. Pure.

    Args:
        server: What the start takes.
        module_dir: The module's directory.
        data_dir: The data directory.

    Returns:
        The unit's text.
    """
    command = " ".join(
        shlex.quote(part)
        for part in server_command(
            server, module_dir=module_dir, data_dir=data_dir, os_name="linux"
        )
    )
    environment = environment_lines(
        server_environment(server, data_dir=data_dir, os_name="linux")
    )
    return (
        "[Unit]\n"
        "Description=ComfyUI\n"
        "Documentation=https://github.com/Comfy-Org/ComfyUI\n"
        "After=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"User={COMFYUI_LINUX_ACCOUNT}\n"
        f"UMask={COMFYUI_LINUX_UMASK}\n"
        f"WorkingDirectory={data_dir}\n"
        f"ExecStart={command}\n"
        f"{environment}"
        "Restart=always\n"
        "RestartSec=3\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def scratch_command(argv: list, environment: dict) -> list:
    """A command run with an environment written from scratch. Pure.

    Args:
        argv: The argument vector.
        environment: Its variables, ``PATH`` beside them.

    Returns:
        ``env -i`` with each variable, then the argument vector.
    """
    variables = {"PATH": COMFYUI_POSIX_PATH, **environment}
    return [
        COMFYUI_POSIX_ENV,
        "-i",
        *(f"{name}={value}" for name, value in sorted(variables.items())),
        *argv,
    ]


class ComfyuiLinuxApplier:
    """Runs ComfyUI as a unit of its own system account.

    Attributes:
        account: The system account the server runs as.
    """

    account = COMFYUI_LINUX_ACCOUNT

    def __init__(
        self,
        *,
        state_dir: str,
        platform=None,
        run_command=run,
        systemd_dir: str = COMFYUI_LINUX_SYSTEMD_DIR,
        files_factory=AccountFiles,
        access_factory=LinuxFolderAccess,
    ):
        """
        Args:
            state_dir: The agent's state root.
            platform: The machine's platform, which steps down to the
                account and labels the unpack.
            run_command: Runs one command as :func:`subprocess_run.run` does.
            systemd_dir: Where the unit is written.
            files_factory: Makes the :class:`AccountFiles` of an account.
            access_factory: Makes the shared folders' writer.
        """
        self.os_name = "linux"
        self.module_dir = os.path.join(state_dir, COMFYUI_NAME)
        self.data_dir = os.path.join(state_dir, COMFYUI_DATA_DIR_NAME)
        self.base_dir = os.path.join(self.data_dir, COMFYUI_BASE_DIR)
        self._platform = platform
        self._run = run_command
        self._unit_path = os.path.join(systemd_dir, COMFYUI_LINUX_UNIT)
        self._files_factory = files_factory
        self._access_factory = access_factory

    def ensure_account(self, *, log=None) -> bool:
        """Make the account when it is missing, and the data directory its own with its folders.

        The account joins the groups that reach a GPU where the machine has
        them. A data directory another uid owns is given to the account
        with everything under it.

        Args:
            log: Called with a line for each entry the handover leaves
                outside the data directory; None for nobody listening.

        Returns:
            Whether the data directory changed hands.

        Raises:
            subprocess.CalledProcessError: If ``useradd`` refuses.
            OSError: If a directory cannot be made or given.
        """
        self._create_account()
        entry = pwd.getpwnam(COMFYUI_LINUX_ACCOUNT)
        try:
            is_given = os.lstat(self.data_dir).st_uid != entry.pw_uid
        except FileNotFoundError:
            is_given = False
        if is_given:
            for path in give_tree(self.data_dir, entry.pw_uid, entry.pw_gid):
                if log is not None:
                    log(f"comfyui: left {path}, which is outside {self.data_dir}")
        self.prepare_data()
        return is_given

    def prepare_data(self) -> None:
        """Make the data directory the account's by open descriptor, and each of its folders as the account.

        Raises:
            KeyError: When the account is missing.
            OSError: When a folder cannot be made or given.
        """
        entry = pwd.getpwnam(COMFYUI_LINUX_ACCOUNT)
        own_dir(self.data_dir, entry.pw_uid, entry.pw_gid, 0o700)
        files = self.service_files()
        for name in (COMFYUI_UV_CACHE_DIR, COMFYUI_TMP_DIR, COMFYUI_PYCACHE_DIR):
            files.make_dir(os.path.join(self.data_dir, name), umask=0o077)
        files.make_dir(self.base_dir, umask=0o027)
        for name in COMFYUI_WRITE_FOLDERS + COMFYUI_READ_FOLDERS:
            files.make_dir(os.path.join(self.base_dir, name), umask=0o027)
        for name in COMFYUI_SERVICE_FOLDERS:
            files.make_dir(os.path.join(self.base_dir, name), umask=0o077)

    def service_files(self) -> AccountFiles:
        """The service's account's places, each touched as that account."""
        return self._files_factory(
            platform=self._platform,
            account=COMFYUI_LINUX_ACCOUNT,
            timeout_s=COMFYUI_ACCOUNT_STEP_TIMEOUT_S,
        )

    def run_as_service(self, argv: list, environment: dict, timeout_s: int) -> tuple:
        """Run one command as the service's account in the data directory under umask 077, its environment written from scratch.

        Args:
            argv: The argument vector.
            environment: Its variables.
            timeout_s: How long it may run.

        Returns:
            ``(exit_code, output)``; 127 with the error when it could not
            start or finish.
        """
        files = self._files_factory(
            platform=self._platform, account=COMFYUI_LINUX_ACCOUNT, timeout_s=timeout_s
        )
        try:
            done = files.run(
                ["/bin/sh", "-c", 'cd -- "$0" && umask 077 && exec "$@"', self.data_dir]
                + scratch_command(argv, environment)
            )
        except OSError as error:
            return 127, str(error)
        words = (done.stdout or b"") + b"\n" + (done.stderr or b"")
        return done.returncode, words.decode("utf-8", "replace")

    def remove_as_service(self, path: str) -> None:
        """Delete one tree of the data directory as the service's account.

        Raises:
            OSError: When it cannot be deleted.
        """
        self.service_files().remove_tree(path)

    def write_access(self, account: str) -> list:
        """Write the default account's entries on the shared folders, or none while there is none.

        Args:
            account: The default account; empty names none.

        Returns:
            The paths left as they are.

        Raises:
            KeyError: When the service's account or the default account is
                missing.
            OSError: When a top folder cannot be opened or written.
        """
        service = pwd.getpwnam(COMFYUI_LINUX_ACCOUNT)
        account_uid = pwd.getpwnam(account).pw_uid if account else None
        return self._access_factory(
            data_dir=self.data_dir, base_dir=self.base_dir, service_uid=service.pw_uid
        ).write(account_uid)

    def service_text(self, server: ComfyuiServer) -> str:
        """The unit a start writes."""
        return render_unit(server, module_dir=self.module_dir, data_dir=self.data_dir)

    def written_text(self) -> str:
        """The unit as it is written now; empty for none."""
        try:
            with open(self._unit_path, "r", encoding="utf-8") as stream:
                return stream.read()
        except OSError:
            return ""

    def apply(self, server: ComfyuiServer, *, is_started: bool = True) -> str:
        """Write the unit and run the server on it; with ``is_started`` false, write it alone.

        Args:
            server: What the start takes.
            is_started: Whether the unit is enabled and started.

        Returns:
            ``unchanged``, ``written``, ``restarted`` or ``started``.

        Raises:
            subprocess.CalledProcessError: When systemd refuses.
            OSError: When the unit cannot be written.
        """
        if self._platform is not None:
            self._platform.label_programs(self.module_dir)
        is_changed = write_if_changed(self._unit_path, self.service_text(server), 0o644)
        if is_changed:
            self._run(["systemctl", "daemon-reload"])
        if not is_started:
            return "written" if is_changed else "unchanged"
        if unit_state(COMFYUI_LINUX_UNIT) == "active":
            if not is_changed:
                return "unchanged"
            self._run(["systemctl", "restart", COMFYUI_LINUX_UNIT])
            return "restarted"
        self._run(["systemctl", "enable", "--now", COMFYUI_LINUX_UNIT])
        return "started"

    def stop(self) -> None:
        """Stop the unit and disable it until the next start."""
        self._run(
            ["systemctl", "disable", "--now", COMFYUI_LINUX_UNIT], is_checked=False
        )

    def is_active(self) -> bool:
        """Whether the module's unit is active."""
        return unit_state(COMFYUI_LINUX_UNIT) == "active"

    def uninstall(self) -> None:
        """Remove the unit and the module's directory; the data directory and the account stay."""
        self.stop()
        try:
            os.unlink(self._unit_path)
        except FileNotFoundError:
            pass
        self._run(["systemctl", "daemon-reload"], is_checked=False)
        remove_tree(self.module_dir)

    def journal_units(self) -> list:
        """The module's unit, whose journal is the server's output."""
        return [COMFYUI_LINUX_UNIT]

    def output_path(self) -> str:
        """Empty: the journal holds the server's output."""
        return ""

    def _create_account(self) -> None:
        """Make the account when it is missing, in the groups that reach a GPU.

        Raises:
            subprocess.CalledProcessError: If ``useradd`` refuses.
        """
        if not self._run(["id", COMFYUI_LINUX_ACCOUNT], is_checked=False).is_success:
            shell = next(
                (path for path in COMFYUI_LINUX_SHELLS if os.path.exists(path)),
                COMFYUI_LINUX_SHELLS[-1],
            )
            self._run(
                [
                    "useradd",
                    "--system",
                    "--no-create-home",
                    "--home-dir",
                    self.data_dir,
                    "--shell",
                    shell,
                    "--comment",
                    COMFYUI_LINUX_ACCOUNT_COMMENT,
                    COMFYUI_LINUX_ACCOUNT,
                ]
            )
        groups = [
            group
            for group in COMFYUI_LINUX_GPU_GROUPS
            if self._run(["getent", "group", group], is_checked=False).is_success
        ]
        if groups:
            self._run(
                ["usermod", "-a", "-G", ",".join(groups), COMFYUI_LINUX_ACCOUNT],
                is_checked=False,
            )
