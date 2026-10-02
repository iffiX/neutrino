"""The hub on Windows: the SYSTEM service ``neutrino_hub`` and its children.

The children run in a job object that ends them with the service.

Not pure: runs ``sc``, the shell's opener and the children.
"""

import ctypes
import os
import subprocess
import time

from neutrino_hub.platforms import win32
from neutrino_hub.platforms.base import HubPlatform
from neutrino_hub.platforms.constants import (
    PLATFORM_COMMAND_TIMEOUT_S,
    PLATFORM_NETBIRD_DAEMON_PORT_WINDOWS,
    PLATFORM_OS_WINDOWS,
    PLATFORM_SERVICE_POLL_S,
    PLATFORM_SERVICE_STOPPED,
    PLATFORM_SERVICE_UNKNOWN,
    PLATFORM_SERVICE_WAIT_S,
    PLATFORM_WINDOWS_CREATE_NO_WINDOW,
    PLATFORM_WINDOWS_SERVICE_NAME,
    PLATFORM_WINDOWS_SERVICE_STATES,
    PLATFORM_WINDOWS_STATE_PATTERN,
)


class WindowsHubPlatform(HubPlatform):
    """Windows, where one SYSTEM service runs the panel and every daemon."""

    os_name = PLATFORM_OS_WINDOWS
    elevation_word = "an administrator"

    def __init__(self, *, libraries=None, sleep=None):
        """
        Args:
            libraries: The bound :class:`win32.Win32Libraries`; None binds
                the real ones on first use.
            sleep: Waits a number of seconds; None is ``time.sleep``.
        """
        self._libraries = libraries
        self._sleep = sleep if sleep is not None else time.sleep
        self._job = None

    def is_elevated(self) -> bool:
        """Whether this process runs with an administrator's token.

        Returns:
            True for an elevated administrator or the SYSTEM account.
        """
        try:
            return bool(self._bound().shell32.IsUserAnAdmin())
        except (OSError, AttributeError):
            return False

    def elevation_hint(self, arguments: str) -> str:
        """The command to run again, in an administrator PowerShell.

        Args:
            arguments: What followed ``nhub`` on the command line.

        Returns:
            One line naming the command and where to run it.
        """
        return f"nhub {arguments}".rstrip() + "   (in an administrator PowerShell)"

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
            supervisor=ChildProcessSupervisor(
                log_dir=SYSTEM_CHILD_LOG_DIR,
                on_started=self.tie_to_service,
                creation_flags=PLATFORM_WINDOWS_CREATE_NO_WINDOW,
            ),
            service=self,
            state_path=SYSTEM_SERVICES_STATE_PATH,
            log_dir=SYSTEM_CHILD_LOG_DIR,
        )

    def open_browser(self, url: str) -> bool:
        """Open a page with the shell's own handler.

        Args:
            url: The page.

        Returns:
            True when the shell accepted it.
        """
        try:
            os.startfile(url)
        except (OSError, AttributeError):
            return False
        return True

    def try_lock(self, descriptor: int) -> bool:
        """Lock the first byte of an open file without waiting.

        Args:
            descriptor: The open file.

        Returns:
            True when the lock is held now; False when another holds it.
        """
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def unlock(self, descriptor: int) -> None:
        """Let go of a lock :meth:`try_lock` took.

        Args:
            descriptor: The open file.

        Raises:
            OSError: When the lock cannot be released.
        """
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)

    def service_state(self) -> str:
        """What the service control manager says about the hub's service.

        Returns:
            ``running``, ``stopped``, another state word, or ``unknown``.
        """
        try:
            result = subprocess.run(
                ["sc.exe", "query", PLATFORM_WINDOWS_SERVICE_NAME],
                capture_output=True,
                text=True,
                timeout=PLATFORM_COMMAND_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return PLATFORM_SERVICE_UNKNOWN
        match = PLATFORM_WINDOWS_STATE_PATTERN.search(result.stdout or "")
        if match is None:
            return PLATFORM_SERVICE_UNKNOWN
        return PLATFORM_WINDOWS_SERVICE_STATES.get(
            int(match.group(1)), PLATFORM_SERVICE_UNKNOWN
        )

    def start_service(self) -> None:
        """Start the hub's service.

        Raises:
            subprocess.CalledProcessError: When the manager refuses.
        """
        subprocess.run(
            ["sc.exe", "start", PLATFORM_WINDOWS_SERVICE_NAME],
            capture_output=True,
            timeout=PLATFORM_COMMAND_TIMEOUT_S,
            check=True,
        )

    def stop_service(self) -> None:
        """Stop the hub's service, and wait for it to have stopped.

        Raises:
            subprocess.CalledProcessError: When the manager refuses the stop
                of a service that runs.
            TimeoutError: When it has not stopped in time.
        """
        if self.service_state() == PLATFORM_SERVICE_STOPPED:
            return
        subprocess.run(
            ["sc.exe", "stop", PLATFORM_WINDOWS_SERVICE_NAME],
            capture_output=True,
            timeout=PLATFORM_COMMAND_TIMEOUT_S,
            check=True,
        )
        for _ in range(int(PLATFORM_SERVICE_WAIT_S / PLATFORM_SERVICE_POLL_S)):
            if self.service_state() == PLATFORM_SERVICE_STOPPED:
                return
            self._sleep(PLATFORM_SERVICE_POLL_S)
        raise TimeoutError(
            f"{PLATFORM_WINDOWS_SERVICE_NAME} did not stop in "
            f"{PLATFORM_SERVICE_WAIT_S} s"
        )

    def restart_service(self) -> None:
        """Stop the hub's service and start it again.

        Raises:
            subprocess.CalledProcessError: When the manager refuses.
            TimeoutError: When it has not stopped in time.
        """
        self.stop_service()
        self.start_service()

    def agent_install_command(self, package: str) -> list:
        """The command that installs the agent's ``.msi``.

        Args:
            package: The package file.

        Returns:
            The argument vector.
        """
        return ["msiexec", "/i", str(package), "/qn", "/norestart"]

    def netbird_daemon_address(self) -> str:
        """The loopback port the hub's own NetBird daemon answers on.

        Returns:
            A ``tcp://`` address.
        """
        return f"tcp://127.0.0.1:{PLATFORM_NETBIRD_DAEMON_PORT_WINDOWS}"

    def tie_to_service(self, process) -> None:
        """Put one child in the job that ends it with the service.

        Args:
            process: The started child.

        Raises:
            OSError: When the job cannot be made or the child put in it.
        """
        kernel32 = self._bound().kernel32
        if self._job is None:
            self._job = self._kill_on_close_job(kernel32)
        if not kernel32.AssignProcessToJobObject(self._job, int(process._handle)):
            raise win32.last_error()

    def _bound(self):
        """The Win32 libraries, bound on first use."""
        if self._libraries is None:
            self._libraries = win32.libraries()
        return self._libraries

    def _kill_on_close_job(self, kernel32) -> int:
        """A job whose processes end when its last handle closes."""
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise win32.last_error()
        limits = win32.JobObjectExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = (
            win32.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        if not kernel32.SetInformationJobObject(
            job,
            win32.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = win32.last_error()
            kernel32.CloseHandle(job)
            raise error
        return job
