"""The hub on Linux: one systemd unit per daemon, root by euid.

Not pure: runs the browser opener.
"""

import os
import shutil
import subprocess
from pathlib import Path

from neutrino_hub.platforms.base import HubPlatform
from neutrino_hub.platforms.constants import (
    PLATFORM_BROWSER_TIMEOUT_S,
    PLATFORM_LINUX_BROWSER_OPENER,
    PLATFORM_LINUX_USER_RUNTIME_ROOT,
    PLATFORM_OS_LINUX,
)
from neutrino_hub.utils.subprocess_run import run


class LinuxHubPlatform(HubPlatform):
    """Linux, where systemd runs each daemon as a unit of its own."""

    os_name = PLATFORM_OS_LINUX

    def process_controller(self):
        """The controller of the hub's units.

        Returns:
            A :class:`neutrino_hub.system.systemd_ctl.SystemdServiceController`.
        """
        from neutrino_hub.system.systemd_ctl import SystemdServiceController

        return SystemdServiceController()

    def open_browser(
        self,
        url: str,
        *,
        user_runtime_root: Path = Path(PLATFORM_LINUX_USER_RUNTIME_ROOT),
    ) -> bool:
        """Open a page in the signed-in account's browser.

        Args:
            url: The page.
            user_runtime_root: Where signed-in accounts' runtime directories
                are, one per uid.

        Returns:
            True when an opener was started; False when nothing here can
            open a page.
        """
        command = self.browser_command(url, user_runtime_root=user_runtime_root)
        if command is None:
            return False
        try:
            run(command, is_checked=False, timeout_s=PLATFORM_BROWSER_TIMEOUT_S)
        except (subprocess.SubprocessError, OSError):
            pass
        return True

    def browser_command(
        self,
        url: str,
        *,
        user_runtime_root: Path = Path(PLATFORM_LINUX_USER_RUNTIME_ROOT),
    ):
        """The command that opens this machine's own browser, or None.

        Under sudo the opener runs as the account that called sudo, on its
        session bus, through ``runuser``.

        Args:
            url: What the browser should open.
            user_runtime_root: Where signed-in accounts' runtime directories
                are, one per uid.

        Returns:
            An argument vector, or None when nothing here can open a page.
        """
        if shutil.which(PLATFORM_LINUX_BROWSER_OPENER) is None:
            return None
        if not self.is_elevated():
            return [PLATFORM_LINUX_BROWSER_OPENER, url]
        account = os.environ.get("SUDO_USER", "")
        uid = os.environ.get("SUDO_UID", "")
        if not account or account == "root" or not uid.isdigit():
            return None
        runtime_dir = Path(user_runtime_root) / uid
        if not runtime_dir.is_dir():
            return None
        environment = [
            f"XDG_RUNTIME_DIR={runtime_dir}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime_dir}/bus",
        ]
        for name in ("DISPLAY", "WAYLAND_DISPLAY"):
            value = os.environ.get(name)
            if value:
                environment.append(f"{name}={value}")
        return [
            "runuser",
            "-u",
            account,
            "--",
            "env",
            *environment,
            PLATFORM_LINUX_BROWSER_OPENER,
            url,
        ]

    def log_hint(self, name: str, unit: str) -> str:
        """Where a person reads one unit's log.

        Args:
            name: The daemon's own name.
            unit: The systemd unit it runs as.

        Returns:
            The ``journalctl`` command.
        """
        return f"journalctl -u {unit}"
