"""The contract every platform implements.

The contract names intents, not mechanisms: enumerate human accounts; read,
write and remove a file as an account; run a process as an account; attach,
detach and query a share at a location; control the agent's own service;
power actions; read host metrics; install and remove a package of a kind;
switch on the platform's own SSH server. A new platform is a new class, and
nothing above this seam changes.

Each platform advertises the capabilities it has in ``capabilities``.
Invoking one it does not have raises :class:`PlatformUnsupportedError`, whose
``code`` every surface reports as ``{"code": "unsupported_platform"}``.

Running a process as an account is an optional capability: Windows has no
general way to become another user, so features prefer the file-level
operations, which every platform can provide. The default file operations
here ride ``run_as_account`` through a Python snippet, which is how the
POSIX platforms share one implementation; Windows overrides them with
direct writes into the account's profile.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import shutil
import subprocess

from neutrino_agent.constants import AGENT_STEP_DOWN_TIMEOUT_S


class PlatformUnsupportedError(RuntimeError):
    """Raised when a capability this platform does not have is invoked."""

    code = "unsupported_platform"


class ShareAttachError(RuntimeError):
    """Raised when a share cannot be attached or detached."""

    def __init__(self, code: str, detail: str = ""):
        """
        Args:
            code: The typed reason — ``cifs_missing``, ``credentials_missing``,
                ``mount_failed`` or ``unmount_failed``.
            detail: The tool's own words, for the failure's params.
        """
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def _interpreter() -> str:
    """A Python to run account snippets with.

    Not this process's own: the agent may be a frozen executable, whose
    ``sys.executable`` is the agent rather than an interpreter.

    Returns:
        A path or name to invoke.
    """
    return shutil.which("python3") or shutil.which("python") or "python3"


class AgentPlatform:
    """What the agent asks of the operating system, behind one seam.

    The base class is also the honest answer for a platform the agent does
    not know: it advertises nothing and refuses every capability.
    """

    os_name = ""
    capabilities: frozenset = frozenset()

    def has_capability(self, name: str) -> bool:
        """Whether this platform advertises one capability.

        Args:
            name: The capability name.

        Returns:
            True when the platform has it.
        """
        return name in self.capabilities

    def human_accounts(self) -> list:
        """The accounts this platform judges to be people.

        Root and system accounts are never listed; the floor that separates
        them is each platform's own.

        Returns:
            Account names, sorted.

        Raises:
            PlatformUnsupportedError: When the platform cannot enumerate.
        """
        raise PlatformUnsupportedError("cannot enumerate accounts here")

    def account_home(self, account: str) -> str:
        """One account's home directory, from the account database.

        Never read from ``$HOME``: the agent runs as root, so the
        environment names root's home, not the account's.

        Args:
            account: The account.

        Returns:
            The absolute home path.

        Raises:
            PlatformUnsupportedError: When the platform cannot answer.
            KeyError: When the account database has no such account.
        """
        raise PlatformUnsupportedError("cannot resolve an account home here")

    def read_account_file(self, *, account: str, relative: str) -> str:
        """Read a file below an account's home, as that account.

        Args:
            account: The account; empty reads as the agent itself.
            relative: Path below the account's home.

        Returns:
            The file's text, empty when it is absent or unreadable.
        """
        if not relative:
            return ""
        return self._run_file_snippet(
            account,
            relative,
            "sys.stdout.write(p.read_text() if p.is_file() else '')",
        )

    def read_account_file_mode(self, *, account: str, relative: str) -> str:
        """A file's permission bits as an octal string, empty when absent.

        Args:
            account: The account; empty reads as the agent itself.
            relative: Path below the account's home.

        Returns:
            Something like ``600``, or empty.
        """
        if not relative:
            return ""
        return self._run_file_snippet(
            account,
            relative,
            "print('' if not p.exists() else oct(p.stat().st_mode & 0o777)[2:])",
        ).strip()

    def write_account_file(
        self, *, account: str, relative: str, text: str, mode: str = ""
    ) -> None:
        """Write a file below an account's home, owned by that account.

        The content goes in on standard input rather than inside the
        command: these files hold things people have typed, and a quote in
        them is ordinary.

        Args:
            account: The account; empty writes as the agent itself.
            relative: Path below the account's home.
            text: What to write.
            mode: Permission bits as an octal string; empty leaves them.
        """
        script = (
            "p.parent.mkdir(parents=True, exist_ok=True)\n"
            "p.write_text(sys.stdin.read())\n"
            f"m = {mode!r}\n"
            "p.chmod(int(m, 8)) if m else None"
        )
        self._run_file_snippet(account, relative, script, stdin=text)

    def remove_account_file(self, *, account: str, relative: str) -> None:
        """Delete a file below an account's home, absent being fine.

        Args:
            account: The account; empty removes as the agent itself.
            relative: Path below the account's home.
        """
        if not relative:
            return
        self._run_file_snippet(account, relative, "p.unlink() if p.is_file() else None")

    def control_socket_path(self) -> str:
        """Where the agent's control socket lives on this platform.

        Returns:
            The absolute socket path.

        Raises:
            PlatformUnsupportedError: When the platform has no control socket.
        """
        raise PlatformUnsupportedError("no control socket here")

    def read_peer_identity(self, connection) -> dict:
        """The kernel-reported identity of a control socket peer.

        Args:
            connection: The accepted socket.

        Returns:
            ``{"account", "uid", "is_privileged"}``; ``uid`` is -1 where the
            platform reports names, not uids.

        Raises:
            PlatformUnsupportedError: When the platform cannot read peers.
            KeyError: When the peer's uid names no account.
        """
        raise PlatformUnsupportedError("cannot read a peer identity here")

    def run_as_account(
        self,
        account: str,
        argv: list,
        *,
        stdin: str = "",
        timeout_s: int = AGENT_STEP_DOWN_TIMEOUT_S,
    ) -> "subprocess.CompletedProcess":
        """Run a process as an account. An optional capability.

        Args:
            account: The account; empty runs as the agent itself.
            argv: Argument vector.
            stdin: Sent to the process's standard input.
            timeout_s: How long to wait.

        Returns:
            The completed process, with text output captured.

        Raises:
            PlatformUnsupportedError: When the platform cannot step down.
        """
        raise PlatformUnsupportedError("cannot run as another account here")

    def attach_share(
        self,
        *,
        account: str,
        share_url: str,
        username: str,
        password: str,
        location: str,
        credentials_path: str = "",
    ) -> None:
        """Attach a published share for an account at a location.

        Args:
            account: The asking account.
            share_url: The share to attach.
            username: The share's own username.
            password: The share's own password; it stays on this machine,
                written into the credentials file. Empty reattaches with the
                credentials file already there.
            location: Where the share appears.
            credentials_path: Where this attachment's credentials file lives.

        Raises:
            PlatformUnsupportedError: When the platform cannot attach.
            ShareAttachError: When the tooling is missing, the credentials
                file is gone, or the mount refuses.
        """
        raise PlatformUnsupportedError("cannot attach a share here")

    def detach_share(self, *, location: str) -> None:
        """Detach a share attached at a location.

        Args:
            location: Where the share is attached.

        Raises:
            PlatformUnsupportedError: When the platform cannot detach.
            ShareAttachError: When the unmount refuses.
        """
        raise PlatformUnsupportedError("cannot detach a share here")

    def is_share_attached(self, *, location: str) -> bool:
        """Whether a share is attached at a location.

        Args:
            location: The location to ask about.

        Raises:
            PlatformUnsupportedError: When the platform cannot answer.
        """
        raise PlatformUnsupportedError("cannot query shares here")

    def is_path_writable(self, *, account: str, path: str) -> bool:
        """Whether an account may write at a path, judged as that account.

        The nearest existing ancestor decides for a path that does not exist
        yet, which is what lets a creatable mount point pass.

        Args:
            account: The account; empty judges as the agent itself.
            path: The absolute path to ask about.

        Returns:
            True when the account may write there.

        Raises:
            PlatformUnsupportedError: When the platform cannot step down.
        """
        script = (
            "import os,sys\n"
            f"p = os.path.abspath({path!r})\n"
            "while not os.path.exists(p):\n"
            "    parent = os.path.dirname(p)\n"
            "    if parent == p:\n"
            "        break\n"
            "    p = parent\n"
            "is_writable = (\n"
            "    os.access(p, os.W_OK | os.X_OK)\n"
            "    if os.path.isdir(p)\n"
            "    else os.access(p, os.W_OK)\n"
            ")\n"
            "sys.stdout.write('1' if is_writable else '0')"
        )
        try:
            result = self.run_as_account(account, [_interpreter(), "-c", script])
        except (KeyError, OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0 and (result.stdout or "").strip() == "1"

    def list_directories(self, *, account: str, path: str) -> list:
        """The subdirectory names under a directory, listed as an account.

        Args:
            account: The account; empty lists as the agent itself.
            path: The absolute directory path.

        Returns:
            Subdirectory names, sorted, dot names left out.

        Raises:
            PlatformUnsupportedError: When the platform cannot step down.
            OSError: When the directory cannot be listed as that account.
        """
        script = (
            "import json,os,sys\n"
            "names = sorted(\n"
            f"    entry.name for entry in os.scandir({path!r})\n"
            "    if entry.is_dir() and not entry.name.startswith('.')\n"
            ")\n"
            "sys.stdout.write(json.dumps(names))"
        )
        try:
            result = self.run_as_account(account, [_interpreter(), "-c", script])
        except (KeyError, OSError, subprocess.SubprocessError) as error:
            raise OSError(str(error))
        if result.returncode != 0:
            raise OSError((result.stderr or "").strip()[-200:])
        try:
            names = json.loads(result.stdout or "[]")
        except ValueError:
            raise OSError("unreadable listing")
        return [str(name) for name in names]

    def make_directory(self, *, account: str, path: str) -> None:
        """Create a directory as an account, parents included.

        Args:
            account: The account; empty creates as the agent itself.
            path: The absolute directory path.

        Raises:
            PlatformUnsupportedError: When the platform cannot step down.
            OSError: When the directory cannot be created as that account.
        """
        script = f"import os\nos.makedirs({path!r}, exist_ok=True)"
        try:
            result = self.run_as_account(account, [_interpreter(), "-c", script])
        except (KeyError, OSError, subprocess.SubprocessError) as error:
            raise OSError(str(error))
        if result.returncode != 0:
            raise OSError((result.stderr or "").strip()[-200:])

    def read_agent_service_state(self) -> str:
        """The state of the agent's own service.

        Returns:
            ``running``, an init-system state word, or ``unknown``.

        Raises:
            PlatformUnsupportedError: When there is no service to ask about.
        """
        raise PlatformUnsupportedError("no agent service to read here")

    def start_agent_service(self) -> None:
        """Enable and start the agent's own service. Best-effort.

        Raises:
            PlatformUnsupportedError: When there is no service to start.
        """
        raise PlatformUnsupportedError("no agent service to start here")

    def power(self, action: str) -> "tuple[int, str]":
        """Run one power action.

        Args:
            action: ``reboot`` or ``poweroff``.

        Returns:
            The exit code and combined output.

        Raises:
            PlatformUnsupportedError: When the platform has no power actions.
        """
        raise PlatformUnsupportedError("no power actions here")

    def read_host_metrics(self):
        """One sample of the machine's health.

        Returns:
            A :class:`~neutrino_agent.metrics.HostMetrics`.

        Raises:
            PlatformUnsupportedError: When the platform cannot be sampled.
        """
        raise PlatformUnsupportedError("no metrics here")

    def install_package(self, path: str, *, package_kind: str, entry: dict) -> None:
        """Install one downloaded package of a kind.

        Args:
            path: The downloaded file.
            package_kind: ``deb`` / ``rpm`` / ``msi`` / ``exe`` / ``dmg``.
            entry: The manifest's platform entry.

        Raises:
            PlatformUnsupportedError: When the platform installs nothing.
        """
        raise PlatformUnsupportedError("cannot install packages here")

    def uninstall_package(self, command: str) -> None:
        """Remove a package the way its manifest says to.

        Args:
            command: The manifest's removal command for this platform.

        Raises:
            PlatformUnsupportedError: When the platform removes nothing.
        """
        raise PlatformUnsupportedError("cannot remove packages here")

    def enable_openssh(self, entry: dict) -> None:
        """Install and start the platform's own SSH server.

        Args:
            entry: The manifest's platform entry.

        Raises:
            PlatformUnsupportedError: When the platform has no SSH story.
        """
        raise PlatformUnsupportedError("no SSH server story here")

    def read_openssh_status(self, entry: dict) -> bool:
        """Whether the platform's own SSH server is serving.

        Args:
            entry: The manifest's platform entry.

        Raises:
            PlatformUnsupportedError: When the platform has no SSH story.
        """
        raise PlatformUnsupportedError("no SSH server story here")

    def _run_file_snippet(
        self, account: str, relative: str, body: str, *, stdin: str = ""
    ) -> str:
        """Run a snippet against one path below the account's home.

        Python does the work rather than a shell, so the paths behave the
        same on every platform that has an interpreter. The home comes from
        the account database, never from ``$HOME``, which under a root agent
        names root's home; only the agent's own files (an empty account) use
        the process's home.

        Args:
            account: The account to run as; empty runs as the agent itself.
            relative: Path below the account's home, bound to ``p``.
            body: Statements to run, with ``pathlib``, ``sys`` and ``p`` in
                scope.
            stdin: Sent to the snippet's standard input.

        Returns:
            Standard output, empty when the snippet could not run.
        """
        try:
            if account:
                home = self.account_home(account)
                head = f"p = pathlib.Path({home!r}) / {relative!r}"
            else:
                head = f"p = pathlib.Path.home() / {relative!r}"
            script = f"import pathlib,sys\n{head}\n{body}"
            result = self.run_as_account(
                account, [_interpreter(), "-c", script], stdin=stdin
            )
        except (KeyError, OSError, subprocess.SubprocessError):
            return ""
        return result.stdout or ""
