"""The agent's one PowerShell on Windows, kept running and asked one operation at a time.

The host is ``powershell.exe`` running the library this package ships,
``data/windows/powershell_host.ps1``, started on the first call as a child
of the agent with no window and reached over its standard input and output
alone: one JSON line per request ``{id, op, args}``, one per answer. Calls
are serialized and each has a timeout, past which the process is killed. A
refusal is :class:`ModuleApplyError`, an error or a dead process
:class:`OSError`, and the next call starts the process again. The host is
stopped once the private bytes it reports pass a ceiling, and after ten
idle minutes; the agent's kill-on-close job ends it with the agent.

Not pure: starts and stops a process.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.platforms import win32

# Every operation the agent asks of the host, by the function that does it
# in the library.
WINDOWS_POWERSHELL_HOST_OPS = {
    "task_read": "Get-NeutrinoTask",
    "task_states": "Get-NeutrinoTaskState",
    "task_write": "Register-NeutrinoTask",
    "task_run_once": "Invoke-NeutrinoOneShotTask",
    "task_start": "Start-NeutrinoTask",
    "task_stop": "Stop-NeutrinoTask",
    "task_remove": "Unregister-NeutrinoTask",
    "rules_forget": "Remove-NeutrinoFirewallRule",
    "added_list": "Get-NeutrinoAddition",
    "added_remove": "Remove-NeutrinoAddition",
    "thermal_zones": "Get-NeutrinoThermalZone",
    "share_status": "Get-NeutrinoShare",
    "share_apply": "Set-NeutrinoShare",
    "share_withdraw": "Remove-NeutrinoShare",
    "share_log": "Get-NeutrinoShareLog",
    "share_password": "Set-NeutrinoSharePassword",
}
WINDOWS_POWERSHELL_HOST_PROGRAM = "powershell.exe"
# The library, under the package's own directory.
WINDOWS_POWERSHELL_HOST_LIBRARY_PARTS = ("data", "windows", "powershell_host.ps1")
WINDOWS_POWERSHELL_HOST_CALL_TIMEOUT_S = 120
WINDOWS_POWERSHELL_HOST_IDLE_S = 600
WINDOWS_POWERSHELL_HOST_PRIVATE_BYTES_MAX = 200 * 1024 * 1024
# How long a stop waits for the host to end by itself before ending it.
WINDOWS_POWERSHELL_HOST_STOP_WAIT_S = 2.0
WINDOWS_POWERSHELL_HOST_ENCODING = "utf-8"

_AGENT_HOST = None
_AGENT_HOST_LOCK = threading.Lock()
_AGENT_JOB = None
_AGENT_JOB_LOCK = threading.Lock()


def library_path() -> str:
    """The host's library, as this package carries it.

    Returns:
        The absolute file path.
    """
    package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(package, *WINDOWS_POWERSHELL_HOST_LIBRARY_PARTS)


def host_command(library: str) -> list:
    """The command line the host runs as.

    Args:
        library: The library's path.

    Returns:
        The argument vector.
    """
    return [
        WINDOWS_POWERSHELL_HOST_PROGRAM,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        library,
    ]


def start_host_process(argv: list) -> "subprocess.Popen":
    """Start the host with no window, its pipes to this process, in the agent's job.

    Its standard error is discarded: every failure comes back as an answer.

    Args:
        argv: The command line.

    Returns:
        The process.

    Raises:
        OSError: When the process cannot start.
    """
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=win32.CREATE_NO_WINDOW,
    )
    try:
        _hold_in_agent_job(process.pid)
    except OSError:
        # The end of its standard input still ends the host with the agent.
        pass
    return process


def agent_host() -> "WindowsPowerShellHost":
    """The one host of this process, made on first use.

    Returns:
        The host.
    """
    global _AGENT_HOST
    with _AGENT_HOST_LOCK:
        if _AGENT_HOST is None:
            _AGENT_HOST = WindowsPowerShellHost()
        return _AGENT_HOST


def _hold_in_agent_job(pid: int) -> None:
    """Put a process into the job that ends everything in it with the agent."""
    global _AGENT_JOB
    kernel32 = win32.libraries().kernel32
    with _AGENT_JOB_LOCK:
        if _AGENT_JOB is None:
            _AGENT_JOB = win32.kill_on_close_job(kernel32)
        process = kernel32.OpenProcess(
            win32.PROCESS_SET_QUOTA | win32.PROCESS_TERMINATE, False, pid
        )
        if not process:
            raise win32.last_error()
        try:
            if not kernel32.AssignProcessToJobObject(_AGENT_JOB, process):
                raise win32.last_error()
        finally:
            kernel32.CloseHandle(process)


def _read_answers(stream, answers: "queue.Queue") -> None:
    """Hand on each line the host writes, then None once it writes no more."""
    try:
        for line in iter(stream.readline, b""):
            answers.put(line.decode(WINDOWS_POWERSHELL_HOST_ENCODING, "replace"))
    except (OSError, ValueError):
        pass
    finally:
        answers.put(None)
        try:
            stream.close()
        except OSError:
            pass


def _parsed_answer(line: str) -> "dict | None":
    """One line as an answer; None for a line that is no JSON object."""
    text = line.strip().lstrip("\ufeff")
    if not text.startswith("{"):
        return None
    try:
        answer = json.loads(text)
    except ValueError:
        return None
    return answer if isinstance(answer, dict) else None


def _value_of(op: str, answer: dict) -> dict:
    """The value one answer carries, or what it refused or failed with."""
    if answer.get("ok") is True:
        value = answer.get("value")
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise OSError(f"the PowerShell host answered {op} with no object")
        return value
    if answer.get("kind") == "refusal":
        params = answer.get("params")
        raise ModuleApplyError(
            str(answer.get("code") or "apply_failed"),
            dict(params) if isinstance(params, dict) else {},
        )
    raise OSError(str(answer.get("message") or f"the PowerShell host failed {op}"))


class WindowsPowerShellHost:
    """One resident PowerShell running the agent's library, asked over its pipes."""

    def __init__(
        self,
        *,
        library: str = "",
        start_process=None,
        idle_s: float = WINDOWS_POWERSHELL_HOST_IDLE_S,
        private_bytes_max: int = WINDOWS_POWERSHELL_HOST_PRIVATE_BYTES_MAX,
    ):
        """
        Args:
            library: The library's path; empty is the one this package
                carries.
            start_process: Starts the host from its command line and returns
                the process, with ``stdin``, ``stdout``, ``poll``, ``wait``
                and ``kill`` as a ``subprocess.Popen`` has them; None is
                :func:`start_host_process`.
            idle_s: How long the host waits for a call before it is stopped.
            private_bytes_max: The private bytes past which the host is
                stopped once it has answered.
        """
        self._library = library or library_path()
        self._start_process = (
            start_process if start_process is not None else start_host_process
        )
        self._idle_s = idle_s
        self._private_bytes_max = private_bytes_max
        self._lock = threading.Lock()
        self._process = None
        self._answers: "queue.Queue | None" = None
        self._last_request_id = 0
        self._last_used = time.monotonic()

    def call(
        self,
        op: str,
        args: dict,
        *,
        timeout_s: float = WINDOWS_POWERSHELL_HOST_CALL_TIMEOUT_S,
    ) -> dict:
        """Ask the host one operation and wait for its answer.

        Args:
            op: The operation, a name in :data:`WINDOWS_POWERSHELL_HOST_OPS`.
            args: What the operation reads; it travels on the host's
                standard input, passwords included.
            timeout_s: How long the call waits for the host, a call before
                it included; past it a host that took the request is killed.

        Returns:
            The value the operation answered; empty when it answered none.

        Raises:
            ValueError: When the operation is not one the library has.
            ModuleApplyError: The code and params the operation refused with.
            TimeoutError: When the host is busy past the timeout, or does
                not answer within it.
            OSError: When the host cannot start, fails the operation, ends
                or answers out of turn.
        """
        if op not in WINDOWS_POWERSHELL_HOST_OPS:
            raise ValueError(f"the PowerShell host has no operation {op!r}")
        if not self._lock.acquire(timeout=timeout_s):
            raise TimeoutError(f"the PowerShell host stayed busy past {timeout_s} s")
        try:
            answer = self._ask(op, args, timeout_s)
        finally:
            self._last_used = time.monotonic()
            self._lock.release()
        return _value_of(op, answer)

    def stop(self) -> None:
        """End the host: its standard input closed, then killed if it lingers."""
        with self._lock:
            self._stop_locked(is_killed=False)

    def _ask(self, op: str, args: dict, timeout_s: float) -> dict:
        """Send one request and read its answer, with the lock held."""
        if self._process is None or self._process.poll() is not None:
            self._start_locked()
        self._last_request_id += 1
        request_id = self._last_request_id
        request = json.dumps({"id": request_id, "op": op, "args": args}) + "\n"
        try:
            self._process.stdin.write(request.encode("ascii"))
            self._process.stdin.flush()
        except (OSError, ValueError) as error:
            self._stop_locked(is_killed=True)
            raise OSError(f"the PowerShell host took no request: {error}") from error
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            try:
                if remaining <= 0:
                    raise queue.Empty
                answered = self._answers.get(timeout=remaining)
            except queue.Empty:
                self._stop_locked(is_killed=True)
                raise TimeoutError(
                    f"the PowerShell host did not answer {op} within {timeout_s} s"
                ) from None
            if answered is None:
                self._stop_locked(is_killed=True)
                raise OSError(f"the PowerShell host ended during {op}")
            answer = _parsed_answer(answered)
            if answer is None:
                continue
            if answer.get("id") != request_id:
                self._stop_locked(is_killed=True)
                raise OSError(
                    f"the PowerShell host answered request {answer.get('id')!r} "
                    f"to request {request_id}"
                )
            break
        try:
            private_bytes = int(answer.get("private_bytes") or 0)
        except (TypeError, ValueError):
            private_bytes = 0
        if private_bytes > self._private_bytes_max:
            self._stop_locked(is_killed=False)
        return answer

    def _start_locked(self) -> None:
        """Start the host, its answer reader and its idle watch."""
        self._stop_locked(is_killed=True)
        process = self._start_process(host_command(self._library))
        answers: "queue.Queue" = queue.Queue()
        threading.Thread(
            target=_read_answers,
            args=(process.stdout, answers),
            name="agent_powershell_host_answers",
            daemon=True,
        ).start()
        self._process = process
        self._answers = answers
        self._last_used = time.monotonic()
        threading.Thread(
            target=self._stop_when_idle,
            args=(process,),
            name="agent_powershell_host_idle",
            daemon=True,
        ).start()

    def _stop_locked(self, *, is_killed: bool) -> None:
        """End the host, at once or after its standard input closed."""
        process = self._process
        self._process = None
        self._answers = None
        if process is None:
            return
        if not is_killed:
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                process.wait(timeout=WINDOWS_POWERSHELL_HOST_STOP_WAIT_S)
                return
            except subprocess.TimeoutExpired:
                pass
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            process.wait(timeout=WINDOWS_POWERSHELL_HOST_STOP_WAIT_S)
        except subprocess.TimeoutExpired:
            pass

    def _stop_when_idle(self, process) -> None:
        """Stop one host process once no call has come for the idle time."""
        while True:
            wait = self._last_used + self._idle_s - time.monotonic()
            if wait > 0:
                time.sleep(wait)
                continue
            with self._lock:
                if self._process is not process:
                    return
                if self._last_used + self._idle_s > time.monotonic():
                    continue
                self._stop_locked(is_killed=False)
                return
