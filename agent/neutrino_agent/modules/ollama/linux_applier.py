"""Ollama on Linux: the account ``neutrino_ollama``, a systemd unit, a person's unit.

The program is unpacked under ``ollama/`` in the module's directory, and the
models live in ``ollama_data`` under the state root, the account's own,
mode 0700: root makes the folder in its own place and gives it on its open
descriptor, a tree another uid owns is handed over by open descriptor
following no link, and ``models`` inside it is made as the account. The unit
``neutrino_ollama.service`` runs ``ollama serve`` as the account with the
module's environment. A person's own unit ``ollama.service`` is driven
through ``systemctl`` alone and nothing of it is written.

Not pure: writes under ``/etc/systemd/system`` and the state root, drives
``useradd``, ``usermod`` and ``systemctl``.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import shlex

from neutrino_agent.modules.gitea.applier import own_dir
from neutrino_agent.modules.ollama.constants import (
    OLLAMA_DATA_DIR_NAME,
    OLLAMA_ENVIRONMENT,
    OLLAMA_HOST,
    OLLAMA_LINUX_ACCOUNT,
    OLLAMA_LINUX_ACCOUNT_COMMENT,
    OLLAMA_LINUX_GPU_GROUPS,
    OLLAMA_LINUX_PROGRAM_PARTS,
    OLLAMA_LINUX_SHELLS,
    OLLAMA_LINUX_SYSTEMD_DIR,
    OLLAMA_LINUX_UNIT,
    OLLAMA_MODELS_DIR_NAME,
    OLLAMA_NAME,
    OLLAMA_PERSON_UNIT,
    OLLAMA_PERSON_UNIT_PATHS,
    OLLAMA_PORT,
    OLLAMA_PROGRAM_DIR_NAME,
    OLLAMA_SERVE_ARGUMENTS,
)
from neutrino_agent.modules.shared.account_files import AccountFiles
from neutrino_agent.modules.shared.account_service import write_if_changed
from neutrino_agent.modules.shared.handle_walk import give_tree
from neutrino_agent.modules.shared.subprocess_run import run, unit_state
from neutrino_agent.modules.shared.unpacked_tree import remove_tree

try:
    import pwd
except ImportError:  # Windows has no account database module.
    pwd = None


def service_environment(data_dir: str) -> dict:
    """The variables the server starts with, by name. Pure.

    Args:
        data_dir: The data directory, the server's home.

    Returns:
        ``HOME``, ``OLLAMA_HOST``, ``OLLAMA_MODELS`` and ``OLLAMA_NO_CLOUD``.
    """
    return {
        "HOME": data_dir,
        "OLLAMA_HOST": f"{OLLAMA_HOST}:{OLLAMA_PORT}",
        "OLLAMA_MODELS": os.path.join(data_dir, OLLAMA_MODELS_DIR_NAME),
        **OLLAMA_ENVIRONMENT,
    }


def render_unit(program: str, data_dir: str) -> str:
    """The server's systemd unit. Pure.

    Args:
        program: The ``ollama`` program.
        data_dir: The data directory.

    Returns:
        The unit's text.
    """
    environment = "".join(
        f"Environment={shlex.quote(f'{name}={value}')}\n"
        for name, value in sorted(service_environment(data_dir).items())
    )
    command = " ".join(shlex.quote(part) for part in (program, *OLLAMA_SERVE_ARGUMENTS))
    return (
        "[Unit]\n"
        "Description=Ollama\n"
        "Documentation=https://github.com/ollama/ollama\n"
        "After=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"User={OLLAMA_LINUX_ACCOUNT}\n"
        f"WorkingDirectory={data_dir}\n"
        f"ExecStart={command}\n"
        f"{environment}"
        "Restart=always\n"
        "RestartSec=3\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


class OllamaLinuxApplier:
    """Runs Ollama as a unit of its own system account, or drives a person's unit.

    Attributes:
        account: The system account the server runs as.
        is_app_system: False: a person's Ollama here is a unit.
    """

    account = OLLAMA_LINUX_ACCOUNT
    is_app_system = False

    def __init__(
        self,
        *,
        state_dir: str,
        platform=None,
        run_command=run,
        systemd_dir: str = OLLAMA_LINUX_SYSTEMD_DIR,
        person_unit_paths: tuple = OLLAMA_PERSON_UNIT_PATHS,
    ):
        """
        Args:
            state_dir: The agent's state root.
            platform: The machine's platform, which steps down to the
                account and labels the unpack.
            run_command: Runs one command as :func:`subprocess_run.run` does.
            systemd_dir: Where the unit is written.
            person_unit_paths: Where a person's unit file is looked for.
        """
        self.module_dir = os.path.join(state_dir, OLLAMA_NAME)
        self.data_dir = os.path.join(state_dir, OLLAMA_DATA_DIR_NAME)
        self.program_path = os.path.join(
            self.module_dir, OLLAMA_PROGRAM_DIR_NAME, *OLLAMA_LINUX_PROGRAM_PARTS
        )
        self._platform = platform
        self._run = run_command
        self._unit_path = os.path.join(systemd_dir, OLLAMA_LINUX_UNIT)
        self._person_unit_paths = tuple(person_unit_paths)

    def person_unit_path(self) -> str:
        """The file of a person's own unit, empty when there is none."""
        for path in self._person_unit_paths:
            if os.path.isfile(path):
                return path
        return ""

    def person_unit_name(self) -> str:
        """The name of a person's own unit."""
        return OLLAMA_PERSON_UNIT

    def person_unit_state(self) -> dict:
        """Whether a person's unit is enabled and active now.

        Returns:
            ``{"is_enabled", "is_active"}``.
        """
        enabled = self._run(
            ["systemctl", "is-enabled", OLLAMA_PERSON_UNIT], is_checked=False
        )
        return {
            "is_enabled": enabled.stdout.strip() == "enabled",
            "is_active": unit_state(OLLAMA_PERSON_UNIT) == "active",
        }

    def start_person(self) -> None:
        """Enable a person's unit and start it.

        Raises:
            subprocess.CalledProcessError: When systemd refuses.
        """
        self._run(["systemctl", "enable", "--now", OLLAMA_PERSON_UNIT])

    def stop_person(self) -> None:
        """Stop a person's unit and disable it."""
        self._run(
            ["systemctl", "disable", "--now", OLLAMA_PERSON_UNIT], is_checked=False
        )

    def restore_person(self, found: dict) -> None:
        """Put a person's unit back as the module's first start found it.

        Args:
            found: ``{"is_enabled", "is_active"}`` as kept then.
        """
        verb = "enable" if found.get("is_enabled") else "disable"
        self._run(["systemctl", verb, OLLAMA_PERSON_UNIT], is_checked=False)
        verb = "start" if found.get("is_active") else "stop"
        self._run(["systemctl", verb, OLLAMA_PERSON_UNIT], is_checked=False)

    def app_path(self) -> str:
        """Empty: the publisher's app is for Windows and macOS."""
        return ""

    def ensure_account(self, *, log=None) -> bool:
        """Make the account when it is missing, and the data directory its own.

        The account joins the groups that reach a GPU where the machine has
        them. A data directory another uid owns, as after the account was
        removed by hand and made again, is given to the account with
        everything under it.

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
        account = pwd.getpwnam(OLLAMA_LINUX_ACCOUNT)
        is_given = False
        try:
            is_given = os.lstat(self.data_dir).st_uid != account.pw_uid
        except FileNotFoundError:
            is_given = False
        if is_given:
            for path in give_tree(self.data_dir, account.pw_uid, account.pw_gid):
                if log is not None:
                    log(f"ollama: left {path}, which is outside {self.data_dir}")
        self._prepare_data(account)
        return is_given

    def apply(self, *, is_started: bool = True) -> str:
        """Write the unit and run the server on it; with ``is_started`` false, write it alone.

        Args:
            is_started: Whether the unit is enabled and started.

        Returns:
            ``unchanged``, ``written``, ``restarted`` or ``started``.

        Raises:
            subprocess.CalledProcessError: When systemd refuses.
            OSError: When the unit cannot be written.
        """
        if self._platform is not None:
            self._platform.label_programs(
                os.path.dirname(os.path.dirname(self.program_path))
            )
        try:
            self._prepare_data(pwd.getpwnam(OLLAMA_LINUX_ACCOUNT))
        except KeyError:
            pass
        is_changed = write_if_changed(
            self._unit_path, render_unit(self.program_path, self.data_dir), 0o644
        )
        if is_changed:
            self._run(["systemctl", "daemon-reload"])
        if not is_started:
            return "written" if is_changed else "unchanged"
        if unit_state(OLLAMA_LINUX_UNIT) == "active":
            if not is_changed:
                return "unchanged"
            self._run(["systemctl", "restart", OLLAMA_LINUX_UNIT])
            return "restarted"
        self._run(["systemctl", "enable", "--now", OLLAMA_LINUX_UNIT])
        return "started"

    def stop(self) -> None:
        """Stop the unit and disable it until the next start."""
        self._run(
            ["systemctl", "disable", "--now", OLLAMA_LINUX_UNIT], is_checked=False
        )

    def is_active(self) -> bool:
        """Whether the module's unit is active."""
        return unit_state(OLLAMA_LINUX_UNIT) == "active"

    def uninstall(self) -> str:
        """Remove the unit and the program; the data directory and the account stay.

        Returns:
            Empty.
        """
        self._run(
            ["systemctl", "disable", "--now", OLLAMA_LINUX_UNIT], is_checked=False
        )
        try:
            os.unlink(self._unit_path)
        except FileNotFoundError:
            pass
        self._run(["systemctl", "daemon-reload"], is_checked=False)
        remove_tree(self.module_dir)
        return ""

    def journal_units(self) -> list:
        """The module's unit, whose journal is the server's output."""
        return [OLLAMA_LINUX_UNIT]

    def output_path(self) -> str:
        """Empty: the journal holds the server's output."""
        return ""

    def _create_account(self) -> None:
        """Make the account when it is missing, in the groups that reach a GPU.

        Raises:
            subprocess.CalledProcessError: If ``useradd`` refuses.
        """
        if not self._run(["id", OLLAMA_LINUX_ACCOUNT], is_checked=False).is_success:
            shell = next(
                (path for path in OLLAMA_LINUX_SHELLS if os.path.exists(path)),
                OLLAMA_LINUX_SHELLS[-1],
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
                    OLLAMA_LINUX_ACCOUNT_COMMENT,
                    OLLAMA_LINUX_ACCOUNT,
                ]
            )
        groups = [
            group
            for group in OLLAMA_LINUX_GPU_GROUPS
            if self._run(["getent", "group", group], is_checked=False).is_success
        ]
        if groups:
            self._run(
                ["usermod", "-a", "-G", ",".join(groups), OLLAMA_LINUX_ACCOUNT],
                is_checked=False,
            )

    def _prepare_data(self, account) -> None:
        """Make the data directory the account's by open descriptor, and ``models`` as the account.

        Raises:
            OSError: When a folder cannot be made or given.
        """
        own_dir(self.data_dir, account.pw_uid, account.pw_gid, 0o700)
        AccountFiles(platform=self._platform, account=OLLAMA_LINUX_ACCOUNT).make_dir(
            os.path.join(self.data_dir, OLLAMA_MODELS_DIR_NAME), umask=0o077
        )
