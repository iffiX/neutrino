"""Carrying out the commands the gateway sends.

Only the actions in :data:`SUPPORTED_ACTIONS` can run. The gateway is trusted,
but an agent running as root should still not accept an arbitrary shell string
just because something posted one, so ``run_command`` is deliberately absent
from the default set.
"""

import subprocess
from dataclasses import dataclass

from neutrino_agent.constants import (
    ANYDESK_DOWNLOAD_URL,
    AGENT_COMMAND_TIMEOUT_S,
    AGENT_INSTALL_DIR,
    AGENT_OUTPUT_LIMIT_BYTES,
    AGENT_SERVICE_NAME,
    TODESK_DOWNLOAD_URL,
)

SUPPORTED_ACTIONS = (
    "reboot",
    "shutdown",
    "deploy_todesk",
    "deploy_anydesk",
    "self_update",
)


@dataclass
class CommandOutcome:
    """Result of running one command.

    Attributes:
        exit_code: The command's exit status; 0 means success.
        output: Combined output, truncated to a size the gateway will accept.
    """

    exit_code: int
    output: str

    @property
    def is_success(self) -> bool:
        """Whether the command succeeded."""
        return self.exit_code == 0


class DeviceOperator:
    """Runs the supported remote actions on this device."""

    def __init__(self, *, gateway_url: str):
        """
        Args:
            gateway_url: Base URL the self-update package is fetched from.
        """
        self._gateway_url = gateway_url.rstrip("/")

    def run(self, action: str, args: dict) -> CommandOutcome:
        """Run one command by name.

        Args:
            action: One of :data:`SUPPORTED_ACTIONS`.
            args: Action-specific arguments.

        Returns:
            The outcome, including an explanatory message for an unsupported
            action rather than raising, so the gateway always gets a report.
        """
        if action not in SUPPORTED_ACTIONS:
            return CommandOutcome(
                exit_code=1, output=f"unsupported action {action!r}\n"
            )
        if action == "reboot":
            return self._shell("systemctl reboot")
        if action == "shutdown":
            return self._shell("systemctl poweroff")
        if action == "deploy_todesk":
            return self._install_package("todesk", TODESK_DOWNLOAD_URL)
        if action == "deploy_anydesk":
            return self._install_package("anydesk", ANYDESK_DOWNLOAD_URL)
        return self._self_update(args.get("package_url", ""))

    def _install_package(self, name: str, url: str) -> CommandOutcome:
        return self._shell(
            f"curl -fL --retry 2 -o /tmp/{name}.deb {url} && "
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y /tmp/{name}.deb"
        )

    def _self_update(self, package_url: str) -> CommandOutcome:
        if not package_url:
            return CommandOutcome(exit_code=1, output="no package_url given\n")
        if not package_url.startswith(self._gateway_url):
            return CommandOutcome(
                exit_code=1,
                output=(
                    f"refusing to update from {package_url}: "
                    f"it is not on this device's gateway\n"
                ),
            )
        return self._shell(
            f"set -e\n"
            f"curl -fL --retry 2 -o /tmp/neutrino_agent.tar.gz {package_url}\n"
            f"rm -rf /tmp/neutrino_agent_update\n"
            f"mkdir -p /tmp/neutrino_agent_update\n"
            f"tar -xzf /tmp/neutrino_agent.tar.gz -C /tmp/neutrino_agent_update\n"
            f"cp -r /tmp/neutrino_agent_update/client {AGENT_INSTALL_DIR}/\n"
            f"cp -r /tmp/neutrino_agent_update/scripts {AGENT_INSTALL_DIR}/\n"
            f"systemctl restart {AGENT_SERVICE_NAME}\n"
        )

    def _shell(self, script: str) -> CommandOutcome:
        try:
            completed = subprocess.run(
                ["bash", "-lc", script],
                capture_output=True,
                text=True,
                timeout=AGENT_COMMAND_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return CommandOutcome(
                exit_code=124, output=f"timed out after {AGENT_COMMAND_TIMEOUT_S}s\n"
            )
        except OSError as error:
            return CommandOutcome(exit_code=1, output=f"{error}\n")
        output = (completed.stdout or "") + (completed.stderr or "")
        return CommandOutcome(
            exit_code=completed.returncode,
            output=output[-AGENT_OUTPUT_LIMIT_BYTES:],
        )
