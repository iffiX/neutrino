"""The hub on macOS: the root LaunchDaemon ``com.neutrino.hub`` and its children.

Not pure: runs ``launchctl``, ``open`` and the children.
"""

import subprocess

from neutrino_hub.platforms.base import HubPlatform
from neutrino_hub.platforms.constants import (
    PLATFORM_BROWSER_TIMEOUT_S,
    PLATFORM_COMMAND_TIMEOUT_S,
    PLATFORM_DARWIN_BROWSER_OPENER,
    PLATFORM_DARWIN_SERVICE_PLIST,
    PLATFORM_DARWIN_SERVICE_TARGET,
    PLATFORM_DARWIN_STATE_PATTERN,
    PLATFORM_NETBIRD_SOCKET_NAME,
    PLATFORM_OS_DARWIN,
    PLATFORM_SERVICE_STOPPED,
    PLATFORM_SERVICE_UNKNOWN,
)


class DarwinHubPlatform(HubPlatform):
    """macOS, where one LaunchDaemon runs the panel and every daemon."""

    os_name = PLATFORM_OS_DARWIN

    def process_controller(self):
        """The controller of the service's children.

        Returns:
            A :class:`neutrino_hub.system.process_control.SupervisedProcessController`.
        """
        from neutrino_hub.system.child_supervisor import ChildProcessSupervisor
        from neutrino_hub.system.constants import (
            SYSTEM_CHILD_LOG_DIR,
            SYSTEM_SERVICES_STATE_PATH,
        )
        from neutrino_hub.system.process_control import SupervisedProcessController

        return SupervisedProcessController(
            supervisor=ChildProcessSupervisor(log_dir=SYSTEM_CHILD_LOG_DIR),
            service=self,
            state_path=SYSTEM_SERVICES_STATE_PATH,
            log_dir=SYSTEM_CHILD_LOG_DIR,
        )

    def open_browser(self, url: str) -> bool:
        """Open a page through LaunchServices.

        Args:
            url: The page.

        Returns:
            True when ``open`` accepted it.
        """
        try:
            result = subprocess.run(
                [PLATFORM_DARWIN_BROWSER_OPENER, url],
                capture_output=True,
                timeout=PLATFORM_BROWSER_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def service_state(self) -> str:
        """What launchd says about the hub's job.

        Returns:
            ``running``, another launchd state word, ``stopped`` when the job
            is not loaded, or ``unknown`` when launchctl cannot be run.
        """
        try:
            result = subprocess.run(
                ["launchctl", "print", PLATFORM_DARWIN_SERVICE_TARGET],
                capture_output=True,
                text=True,
                timeout=PLATFORM_COMMAND_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return PLATFORM_SERVICE_UNKNOWN
        if result.returncode != 0:
            return PLATFORM_SERVICE_STOPPED
        match = PLATFORM_DARWIN_STATE_PATTERN.search(result.stdout or "")
        return match.group(1) if match else PLATFORM_SERVICE_UNKNOWN

    def start_service(self) -> None:
        """Load the hub's job and start it.

        Raises:
            subprocess.CalledProcessError: When launchd refuses the start.
        """
        subprocess.run(
            ["launchctl", "bootstrap", "system", PLATFORM_DARWIN_SERVICE_PLIST],
            capture_output=True,
            timeout=PLATFORM_COMMAND_TIMEOUT_S,
            check=False,
        )
        subprocess.run(
            ["launchctl", "kickstart", PLATFORM_DARWIN_SERVICE_TARGET],
            capture_output=True,
            timeout=PLATFORM_COMMAND_TIMEOUT_S,
            check=True,
        )

    def stop_service(self) -> None:
        """Unload the hub's job; its plist loads it again at the next boot.

        Raises:
            subprocess.CalledProcessError: When launchd refuses the stop of a
                job that is loaded.
        """
        if self.service_state() == PLATFORM_SERVICE_STOPPED:
            return
        subprocess.run(
            ["launchctl", "bootout", PLATFORM_DARWIN_SERVICE_TARGET],
            capture_output=True,
            timeout=PLATFORM_COMMAND_TIMEOUT_S,
            check=True,
        )

    def restart_service(self) -> None:
        """End the running job and start it again at once.

        Raises:
            subprocess.CalledProcessError: When launchd refuses.
        """
        if self.service_state() == PLATFORM_SERVICE_STOPPED:
            self.start_service()
            return
        subprocess.run(
            ["launchctl", "kickstart", "-k", PLATFORM_DARWIN_SERVICE_TARGET],
            capture_output=True,
            timeout=PLATFORM_COMMAND_TIMEOUT_S,
            check=True,
        )

    def agent_install_command(self, package: str) -> list:
        """The command that installs the agent's ``.pkg``.

        Args:
            package: The package file.

        Returns:
            The argument vector.
        """
        return ["installer", "-pkg", str(package), "-target", "/"]

    def netbird_daemon_address(self) -> str:
        """The socket the hub's own NetBird daemon answers on.

        Returns:
            ``unix://`` and the socket under the runtime root.
        """
        from neutrino_hub.utils.constants import UTILS_RUNTIME_ROOT

        return f"unix://{UTILS_RUNTIME_ROOT / PLATFORM_NETBIRD_SOCKET_NAME}"
