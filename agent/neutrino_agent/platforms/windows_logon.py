"""An account logged on with its password, and processes started under that logon.

The Terminal module's shell and command run as the account itself, never
as SYSTEM: ``LogonUserW`` makes a primary token from the account's password,
an interactive logon first and a batch logon where the account may not log
on interactively; ``LoadUserProfileW`` loads the account's profile, and
``CreateEnvironmentBlock`` gives the account's own environment. A process
is started under the token with ``CreateProcessAsUserW``, on the window
station of the logon's own session. Every call takes the bound libraries as
its seam, so nothing here needs Windows to import or to test.

Not pure: logs accounts on and starts processes.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import ctypes
import os
import subprocess

from neutrino_agent.platforms import win32
from neutrino_agent.platforms.windows_accounts import logon_token

# The logons tried in turn for an account's terminal.
WINDOWS_LOGON_TERMINAL_KINDS = (
    win32.LOGON32_LOGON_INTERACTIVE,
    win32.LOGON32_LOGON_BATCH,
)
# An empty desktop name puts the process on a window station of its own
# logon session, which the account may use; the service's own refuses it.
WINDOWS_LOGON_DESKTOP = ""


class WindowsAccountLogon:
    """One account logged on: its token, its loaded profile, its environment."""

    def __init__(
        self, account: str, password: str, *, advapi32=None, kernel32=None, userenv=None
    ):
        """
        Args:
            account: The account's name on this computer.
            password: Its login.
            advapi32: The bound advapi32; None binds the real one.
            kernel32: The bound kernel32; None binds the real one.
            userenv: The bound userenv; None binds the real one.
        """
        self.account = account
        self._password = password
        self._advapi32 = advapi32
        self._kernel32 = kernel32
        self._userenv = userenv
        self._token = None
        self._profile = None
        self._environment = None

    def open(self) -> None:
        """Log the account on and load its profile and environment.

        Raises:
            ModuleApplyError: ``credential_invalid {account}`` when Windows
                refuses the password.
            OSError: When no logon is granted, or the profile or the
                environment cannot be loaded.
        """
        self._bind()
        self._token = logon_token(
            self._advapi32,
            self.account,
            self._password,
            kinds=WINDOWS_LOGON_TERMINAL_KINDS,
        )
        try:
            profile = win32.ProfileInfo()
            profile.dwSize = ctypes.sizeof(win32.ProfileInfo)
            profile.dwFlags = win32.PI_NOUI
            profile.lpUserName = self.account
            if not self._userenv.LoadUserProfileW(self._token, ctypes.byref(profile)):
                raise win32.last_error()
            self._profile = profile.hProfile
            environment = ctypes.c_void_p()
            if not self._userenv.CreateEnvironmentBlock(
                ctypes.byref(environment), self._token, False
            ):
                raise win32.last_error()
            self._environment = environment
        except OSError:
            self.close()
            raise

    def start(
        self,
        command_line: str,
        *,
        start_dir: str,
        startup,
        flags: int,
        is_inheriting: bool = False,
    ):
        """Start a process as the account.

        Args:
            command_line: The command line.
            start_dir: Its working directory; empty is the logon's own.
            startup: A :class:`win32.StartupInfoEx` or
                :class:`win32.StartupInfo`; its desktop is set here.
            flags: The creation flags; the environment's is added.
            is_inheriting: Whether the handles the startup names are handed
                to the process.

        Returns:
            The started process's :class:`win32.ProcessInformation`.

        Raises:
            OSError: When the process cannot be started.
        """
        record = startup.StartupInfo if hasattr(startup, "StartupInfo") else startup
        record.lpDesktop = WINDOWS_LOGON_DESKTOP
        process = win32.ProcessInformation()
        if not self._advapi32.CreateProcessAsUserW(
            self._token,
            None,
            command_line,
            None,
            None,
            is_inheriting,
            flags | win32.CREATE_UNICODE_ENVIRONMENT,
            self._environment,
            start_dir or None,
            ctypes.byref(startup),
            ctypes.byref(process),
        ):
            raise win32.last_error()
        return process

    def close(self) -> None:
        """Release the environment, the profile and the token."""
        environment, self._environment = self._environment, None
        if environment is not None:
            with contextlib.suppress(OSError):
                self._userenv.DestroyEnvironmentBlock(environment)
        profile, self._profile = self._profile, None
        if profile is not None and self._token is not None:
            with contextlib.suppress(OSError):
                self._userenv.UnloadUserProfile(self._token, profile)
        token, self._token = self._token, None
        if token is not None:
            with contextlib.suppress(OSError):
                self._kernel32.CloseHandle(token)

    def _bind(self) -> None:
        """Bind the libraries a fake did not stand in for."""
        if None in (self._advapi32, self._kernel32, self._userenv):
            libraries = win32.libraries()
            self._advapi32 = self._advapi32 or libraries.advapi32
            self._kernel32 = self._kernel32 or libraries.kernel32
            self._userenv = self._userenv or libraries.userenv


def _inheritable_pipe(kernel32, *, is_child_reading: bool) -> tuple:
    """An anonymous pipe whose child end alone is inheritable.

    Args:
        kernel32: The bound kernel32.
        is_child_reading: Whether the child reads the pipe, as its stdin.

    Returns:
        ``(parent_end, child_end)``.

    Raises:
        OSError: When the pipe cannot be made.
    """
    attributes = win32.SecurityAttributes()
    attributes.nLength = ctypes.sizeof(win32.SecurityAttributes)
    attributes.bInheritHandle = True
    read = ctypes.c_void_p()
    write = ctypes.c_void_p()
    if not kernel32.CreatePipe(
        ctypes.byref(read), ctypes.byref(write), ctypes.byref(attributes), 0
    ):
        raise win32.last_error()
    parent, child = (write, read) if is_child_reading else (read, write)
    kernel32.SetHandleInformation(parent, win32.HANDLE_FLAG_INHERIT, 0)
    return parent, child


def _handle_list(kernel32, handles):
    """A process attribute list that hands the process these handles alone.

    Args:
        kernel32: The bound kernel32.
        handles: A ctypes array of the handles.

    Returns:
        The attribute list buffer.

    Raises:
        OSError: When the list cannot be built.
    """
    size = ctypes.c_size_t(0)
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    attributes = ctypes.create_string_buffer(size.value)
    if not kernel32.InitializeProcThreadAttributeList(
        attributes, 1, 0, ctypes.byref(size)
    ):
        raise win32.last_error()
    if not kernel32.UpdateProcThreadAttribute(
        attributes,
        0,
        win32.PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
        ctypes.byref(handles),
        ctypes.sizeof(handles),
        None,
        None,
    ):
        raise win32.last_error()
    return attributes


class WindowsAccountPipeProcess:
    """A command started as an account on three pipes, in a kill-on-close job.

    It answers what :class:`subprocess.Popen` answers for a command an
    ``exec`` stream runs: ``stdin``, ``stdout`` and ``stderr`` as files,
    ``poll``, ``wait`` and ``returncode``.

    Attributes:
        stdin: Its standard input, a binary file.
        stdout: Its standard output, a buffered binary file.
        stderr: Its standard error, a buffered binary file.
        returncode: Its exit code once it ended; None before.
    """

    def __init__(
        self,
        logon: WindowsAccountLogon,
        argv: list,
        *,
        start_dir: str,
        kernel32=None,
        open_handle=None,
    ):
        """Start the command, suspended, put it in its job, and resume it.

        Args:
            logon: The account's logon, opened.
            argv: The command.
            start_dir: Its working directory.
            kernel32: The bound kernel32; None binds the real one.
            open_handle: Turns a handle into a file descriptor; None is
                ``msvcrt.open_osfhandle``.

        Raises:
            OSError: When the pipes, the job or the process cannot be made.
        """
        self._kernel32 = (
            kernel32 if kernel32 is not None else win32.libraries().kernel32
        )
        if open_handle is None:
            import msvcrt

            open_handle = msvcrt.open_osfhandle
        self.returncode = None
        self._job = None
        self._process = None
        kernel32 = self._kernel32
        ends = [
            _inheritable_pipe(kernel32, is_child_reading=True),
            _inheritable_pipe(kernel32, is_child_reading=False),
            _inheritable_pipe(kernel32, is_child_reading=False),
        ]
        children = (ctypes.c_void_p * 3)(*(child for _, child in ends))
        attributes = None
        try:
            attributes = _handle_list(kernel32, children)
            startup = win32.StartupInfoEx()
            startup.StartupInfo.cb = ctypes.sizeof(win32.StartupInfoEx)
            startup.StartupInfo.dwFlags = win32.STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = ends[0][1]
            startup.StartupInfo.hStdOutput = ends[1][1]
            startup.StartupInfo.hStdError = ends[2][1]
            startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
            self._process = logon.start(
                subprocess.list2cmdline(argv),
                start_dir=start_dir,
                startup=startup,
                flags=win32.EXTENDED_STARTUPINFO_PRESENT
                | win32.CREATE_SUSPENDED
                | win32.CREATE_NO_WINDOW,
                is_inheriting=True,
            )
            self._job = win32.kill_on_close_job(kernel32)
            kernel32.AssignProcessToJobObject(self._job, self._process.hProcess)
            kernel32.ResumeThread(self._process.hThread)
        except OSError:
            if self._process is not None:
                kernel32.TerminateProcess(self._process.hProcess, 1)
            for parent, _ in ends:
                kernel32.CloseHandle(parent)
            self._release()
            raise
        finally:
            for _, child in ends:
                kernel32.CloseHandle(child)
            if attributes is not None:
                kernel32.DeleteProcThreadAttributeList(attributes)
        self.stdin = os.fdopen(open_handle(_value(ends[0][0]), 0), "wb", buffering=0)
        self.stdout = os.fdopen(open_handle(_value(ends[1][0]), 0), "rb")
        self.stderr = os.fdopen(open_handle(_value(ends[2][0]), 0), "rb")

    @property
    def pid(self) -> int:
        """The process's id; 0 once it was released."""
        return int(self._process.dwProcessId) if self._process is not None else 0

    def poll(self) -> "int | None":
        """The exit code when the process ended; None while it runs."""
        return self.wait(timeout=0) if self.returncode is None else self.returncode

    def wait(self, timeout: "float | None" = None) -> "int | None":
        """Wait for the process to end.

        Args:
            timeout: Seconds to wait; None waits until it ends.

        Returns:
            The exit code; None when a zero timeout found it running.

        Raises:
            subprocess.TimeoutExpired: When it runs on past a timeout.
        """
        if self.returncode is not None or self._process is None:
            return self.returncode
        wait_ms = win32.INFINITE if timeout is None else int(timeout * 1000)
        if (
            self._kernel32.WaitForSingleObject(self._process.hProcess, wait_ms)
            != win32.WAIT_OBJECT_0
        ):
            if timeout == 0:
                return None
            raise subprocess.TimeoutExpired("exec", timeout)
        code = win32.DWORD(0)
        self._kernel32.GetExitCodeProcess(self._process.hProcess, ctypes.byref(code))
        self.returncode = int(code.value)
        return self.returncode

    def end(self) -> int:
        """End the process and everything it started, and release its handles.

        Returns:
            Its exit code; the terminated code when it was still running.
        """
        job, self._job = self._job, None
        if job is not None:
            self._kernel32.CloseHandle(job)
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.wait(timeout=5)
        code = self.returncode
        self._release()
        return code if code is not None else win32.TERMINATED_EXIT_CODE

    def _release(self) -> None:
        if self._job is not None:
            self._kernel32.CloseHandle(self._job)
            self._job = None
        process, self._process = self._process, None
        if process is not None:
            for handle in (process.hThread, process.hProcess):
                with contextlib.suppress(OSError):
                    self._kernel32.CloseHandle(handle)


def _value(handle) -> int:
    """A handle as the integer ``open_osfhandle`` takes."""
    return int(handle.value if hasattr(handle, "value") else handle)
