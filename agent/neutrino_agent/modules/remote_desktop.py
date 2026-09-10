"""Reading and setting up the user-tier remote desktops on this machine.

AnyDesk and TeamViewer are software a person put here; the agent detects
what is there, brings a stopped daemon up, reads the id a peer connects to,
and sets the unattended password. AnyDesk keeps its desktop configuration
per account, so its id and password are read and set as the seated
account inside that account's own display session; TeamViewer's daemon is
root's, so its verbs run as root. RustDesk is the agent's own module and
is not here.

Not pure: runs the products' own binaries.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import re
import shutil
import subprocess

from neutrino_agent.constants import AGENT_OUTPUT_LIMIT_BYTES
from neutrino_agent.modules.subprocess_run import command_detail, run
from neutrino_agent.rdp.host import graphical_accounts, session_environment

SUPPORTED_PRODUCTS = ("anydesk", "teamviewer")

# How each product identifies itself, and what it answers to.
PRODUCTS = {
    "anydesk": {
        "binary": "anydesk",
        "service": "anydesk",
        "package": "anydesk",
        "paths": ("/usr/bin/anydesk",),
        "id_argv": ("anydesk", "--get-id"),
        "is_seated": True,
    },
    "teamviewer": {
        "binary": "teamviewer",
        "service": "teamviewerd",
        "package": "teamviewer",
        "paths": ("/usr/bin/teamviewer",),
        "id_argv": ("teamviewer", "info"),
        "is_seated": False,
    },
}

# What TeamViewer calls its id, in a table it draws with bold escapes.
TEAMVIEWER_ID_LABEL = "TeamViewer ID:"
# What AnyDesk needs to run at all.
UTF8_LOCALE = ("LANG=C.UTF-8", "LC_ALL=C.UTF-8")
PASSWORD_MASK = "***"

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def teamviewer_id(output: str) -> str:
    """The id ``teamviewer info`` printed.

    Args:
        output: Everything the command wrote.

    Returns:
        The id, empty when the command printed none.
    """
    for line in _ANSI_ESCAPE.sub("", output).splitlines():
        if TEAMVIEWER_ID_LABEL not in line:
            continue
        digits = line.split(TEAMVIEWER_ID_LABEL, 1)[1].strip()
        return digits if digits.isdigit() else ""
    return ""


def scrubbed(output: str, password: str) -> str:
    """One command's output with the password masked, bounded."""
    text = output.replace(password, PASSWORD_MASK) if password else output
    return text[-AGENT_OUTPUT_LIMIT_BYTES:]


class RemoteDesktopReader:
    """Reads and changes the user-tier remote desktops on this machine."""

    def __init__(self, *, platform):
        """
        Args:
            platform: The machine's platform, which steps down to accounts.
        """
        self._platform = platform

    def status(self, product: str) -> dict:
        """What one product is doing here.

        A stopped daemon is started on the way: a product that is installed
        but down cannot be connected to.

        Args:
            product: One of :data:`SUPPORTED_PRODUCTS`.

        Returns:
            ``{"product", "is_installed", "is_running", "session_id",
            "can_set_password"}``.

        Raises:
            ValueError: For a product outside the two.
        """
        units = self._units(product)
        status = {
            "product": product,
            "is_installed": False,
            "is_running": False,
            "session_id": None,
            "can_set_password": True,
        }
        if not self._is_installed(units):
            return status
        status["is_installed"] = True
        service = str(units["service"])
        if not self._is_active(service):
            run(["systemctl", "enable", "--now", service], is_checked=False)
        status["is_running"] = self._is_active(service)
        status["session_id"] = self._session_id(product) or None
        return status

    def set_password(self, product: str, password: str) -> dict:
        """Set one product's unattended-access password.

        Args:
            product: One of :data:`SUPPORTED_PRODUCTS`.
            password: The password to set.

        Returns:
            ``{"exit_code", "code", "params", "output"}``; the output
            never carries the password.

        Raises:
            ValueError: For a product outside the two.
        """
        units = self._units(product)
        if not units["is_seated"]:
            result = self._run(["teamviewer", "passwd", password])
            return self._outcome(result, password)
        account = self._seated_account()
        if not account:
            return {
                "exit_code": 1,
                "code": "rdp_nobody_seated",
                "params": {},
                "output": "",
            }
        result = self._run_seated(
            account, ["anydesk", "--set-password"], stdin=f"{password}\n"
        )
        outcome = self._outcome(result, password)
        if outcome["exit_code"] == 0:
            outcome["output"] += self._session_id(product) + "\n"
        return outcome

    def _units(self, product: str) -> dict:
        if product not in PRODUCTS:
            raise ValueError(product)
        return PRODUCTS[product]

    def _is_installed(self, units: dict) -> bool:
        if shutil.which(str(units["binary"])):
            return True
        if any(os.path.exists(path) for path in units["paths"]):
            return True
        package = str(units["package"])
        for argv in (["dpkg", "-s", package], ["rpm", "-q", package]):
            if self._run(argv).returncode == 0:
                return True
        return False

    def _is_active(self, service: str) -> bool:
        result = self._run(["systemctl", "is-active", service])
        return (result.stdout or "").strip() == "active"

    def _session_id(self, product: str) -> str:
        units = PRODUCTS[product]
        argv = list(units["id_argv"])
        if not units["is_seated"]:
            return teamviewer_id(self._run(argv).stdout or "")
        account = self._seated_account()
        if not account:
            return ""
        result = self._run_seated(account, argv)
        output = (result.stdout or "").strip()
        return output if result.returncode == 0 and output.isdigit() else ""

    def _seated_account(self) -> str:
        seated = graphical_accounts() or []
        return str(seated[0]) if seated else ""

    def _run(self, argv: list) -> "subprocess.CompletedProcess":
        try:
            result = run(list(argv), is_checked=False)
        except (OSError, subprocess.SubprocessError) as error:
            return subprocess.CompletedProcess(argv, 127, "", command_detail(error))
        return subprocess.CompletedProcess(
            argv, result.exit_code, result.stdout, result.stderr
        )

    def _run_seated(
        self, account: str, argv: list, *, stdin: str = ""
    ) -> "subprocess.CompletedProcess":
        """Run one of AnyDesk's verbs as the seated account, on its display."""
        environment = session_environment(account) or {}
        pairs = [f"{key}={value}" for key, value in environment.items()]
        command = ["env", *pairs, *UTF8_LOCALE, *argv]
        try:
            return self._platform.run_as_account(account, command, stdin=stdin)
        except (OSError, subprocess.SubprocessError) as error:
            return subprocess.CompletedProcess(command, 127, "", str(error))

    def _outcome(self, result, password: str) -> dict:
        output = scrubbed((result.stdout or "") + (result.stderr or ""), password)
        code = "" if result.returncode == 0 else "command_failed"
        params = {} if result.returncode == 0 else {"detail": output.strip()[:500]}
        return {
            "exit_code": int(result.returncode),
            "code": code,
            "params": params,
            "output": output,
        }
