"""Files and folders in a place an account can write, each touched as that account.

Every read, write, rename and removal the agent makes in an account's home
or in a folder the account owns runs as the account, and reaches only what
the account reaches itself. On Linux and macOS each step
is a ``/bin/sh`` the platform's step-down starts as the account, its
groups, group and user taken before it opens any path; on Windows each
step is the agent's own code on a thread acting as the account, under a
logon with the account's login.

Not pure: runs commands as an account and acts as one.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ntpath
import os
import shutil
import subprocess

from neutrino_agent.constants import AGENT_ACCOUNT_FILE_TIMEOUT_S
from neutrino_agent.exceptions import PlatformUnsupportedError

# What ``sh`` runs as the account to print the file ``$0``; it exits 3 when
# the file is not there.
READ_SHELL = 'if [ -e "$0" ]; then exec cat -- "$0"; fi; exit 3'
# What ``sh`` runs as the account to print the file ``$0``'s size, then its
# last ``$1`` bytes; it exits 3 when the file is not there.
READ_TAIL_SHELL = (
    'if [ -f "$0" ]; then wc -c < "$0" && exec tail -c "$1" -- "$0"; fi; exit 3'
)
# What ``sh`` runs as the account to print the names in the folder ``$0``,
# one a line; it exits 3 when the folder is not there.
NAMES_SHELL = 'if [ -d "$0" ]; then exec ls -A -- "$0"; fi; exit 3'
# What ``sh`` runs as the account to write its input into the file ``$0`` in
# place, its folder made first.
WRITE_IN_PLACE_SHELL = 'mkdir -p -- "$(dirname -- "$0")" && cat > "$0"'
# What ``sh`` runs as the account to write its input whole beside the file
# ``$0``, give it the mode ``$1`` and rename it into place, its folder made
# first.
WRITE_SHELL = (
    'mkdir -p -- "$(dirname -- "$0")" && (umask 077 && cat > "$0.new")'
    ' && chmod -- "$1" "$0.new" && mv -f -- "$0.new" "$0"'
)
# What ``sh`` runs as the account to print each of its arguments that is
# there.
EXISTING_SHELL = 'for p do [ -e "$p" ] && printf "%s\\n" "$p"; done; exit 0'
# What ``sh`` runs as the account to make the folder ``$0`` and each one
# missing above it under the umask ``$1``; it exits 3 when the folder was
# there.
MAKE_DIR_SHELL = '[ -d "$0" ] && exit 3; umask "$1" && mkdir -p -- "$0"'
# What ``sh`` runs as the account to delete the file ``$0``.
REMOVE_SHELL = 'rm -f -- "$0"'
# What ``sh`` runs as the account to delete the tree ``$0``.
REMOVE_TREE_SHELL = 'rm -rf -- "$0"'
# What ``sh`` runs as the account to delete each of its arguments while it is
# an empty folder, deepest first, stopping at the first that is not.
REMOVE_EMPTY_SHELL = 'for p do rmdir -- "$p" 2>/dev/null || exit 0; done; exit 0'
# The exit code a step uses for "not there".
ABSENT_EXIT = 3
# How much of a failed command's words an error keeps.
DETAIL_CHARS = 300
# The name a file is written as beside its place until it is renamed in.
STAGED_SUFFIX = ".new"


def _step_read(path: str) -> "bytes | None":
    """A file's bytes; None when it is not there."""
    try:
        with open(path, "rb") as stream:
            return stream.read()
    except FileNotFoundError:
        return None


def _step_read_tail(path: str, limit: int) -> "tuple | None":
    """A file's size and its last bytes; None when it is not there."""
    try:
        with open(path, "rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            stream.seek(max(0, size - limit))
            return size, stream.read()
    except FileNotFoundError:
        return None


def _step_names(path: str) -> "list | None":
    """The names in a folder; None when it is not there."""
    try:
        return os.listdir(path)
    except FileNotFoundError:
        return None


def _step_write(path: str, data: bytes) -> None:
    """Write a file whole beside its place and rename it in, its folder made."""
    os.makedirs(ntpath.dirname(path), exist_ok=True)
    staged = path + STAGED_SUFFIX
    with open(staged, "wb") as stream:
        stream.write(data)
    os.replace(staged, path)


def _step_write_in_place(path: str, data: bytes) -> None:
    """Write a file's bytes in place, its folder made."""
    os.makedirs(ntpath.dirname(path), exist_ok=True)
    with open(path, "wb") as stream:
        stream.write(data)


def _step_existing(paths: list) -> list:
    """The paths that are there."""
    return [path for path in paths if os.path.lexists(path)]


def _step_make_dir(path: str) -> bool:
    """Make a folder with the missing ones above it; whether it was made."""
    if os.path.isdir(path):
        return False
    os.makedirs(path, exist_ok=True)
    return True


def _step_remove(path: str) -> None:
    """Delete a file; one that is not there is left."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _step_remove_tree(path: str) -> None:
    """Delete a tree; one that is not there is left."""
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        _step_remove(path)


def _step_remove_empty_dirs(paths: list) -> None:
    """Delete each folder while it is empty, stopping at the first that is not."""
    for path in paths:
        try:
            os.rmdir(path)
        except OSError:
            return


class AccountFiles:
    """One account's places, each read, written and removed as that account."""

    def __init__(
        self,
        *,
        platform,
        account: str,
        password: str = "",
        timeout_s: int = AGENT_ACCOUNT_FILE_TIMEOUT_S,
    ):
        """
        Args:
            platform: The machine's platform, whose ``account_process``
                steps down on Linux and macOS and whose ``as_account`` acts
                as the account on Windows.
            account: The account.
            password: The account's login; Windows needs it.
            timeout_s: How long one step may take on Linux and macOS.
        """
        self.account = account
        self._platform = platform
        self._password = password
        self._timeout_s = timeout_s
        self._is_windows = platform.os_name == "windows"

    def read(self, path: str) -> "bytes | None":
        """A file's bytes, read as the account.

        Args:
            path: The file.

        Returns:
            Its bytes; None when it is not there.

        Raises:
            OSError: When it cannot be read.
            ModuleApplyError: ``credential_invalid`` when Windows refuses
                the account's login.
        """
        if self._is_windows:
            return self._as_account(_step_read, path)
        result = self.run(["/bin/sh", "-c", READ_SHELL, path])
        if result.returncode == ABSENT_EXIT:
            return None
        if result.returncode != 0:
            raise OSError(f"could not read {path}: {_detail(result)}")
        return result.stdout

    def read_tail(self, path: str, limit: int) -> "tuple | None":
        """A file's size and its last bytes, read as the account.

        Args:
            path: The file.
            limit: How many bytes are read at most.

        Returns:
            ``(size, data)``; None when it is not there.

        Raises:
            OSError: When it cannot be read.
            ModuleApplyError: ``credential_invalid`` when Windows refuses
                the account's login.
        """
        if self._is_windows:
            return self._as_account(_step_read_tail, path, int(limit))
        result = self.run(["/bin/sh", "-c", READ_TAIL_SHELL, path, str(int(limit))])
        if result.returncode == ABSENT_EXIT:
            return None
        if result.returncode != 0:
            raise OSError(f"could not read {path}: {_detail(result)}")
        size, _, data = result.stdout.partition(b"\n")
        try:
            return int(size.strip() or b"0"), data
        except ValueError as error:
            raise OSError(f"could not read {path}: {error}") from error

    def names(self, path: str) -> "list | None":
        """The names in a folder, read as the account.

        Args:
            path: The folder.

        Returns:
            The names; None when it is not there.

        Raises:
            OSError: When it cannot be read.
            ModuleApplyError: ``credential_invalid`` when Windows refuses
                the account's login.
        """
        if self._is_windows:
            return self._as_account(_step_names, path)
        result = self.run(["/bin/sh", "-c", NAMES_SHELL, path])
        if result.returncode == ABSENT_EXIT:
            return None
        if result.returncode != 0:
            raise OSError(f"could not read {path}: {_detail(result)}")
        return result.stdout.decode("utf-8", "replace").splitlines()

    def write(self, path: str, data: bytes, mode: int = 0o600) -> None:
        """Write a file whole as the account, beside its place and renamed in, its folder made.

        Args:
            path: The file.
            data: What it holds afterwards.
            mode: Its permission bits on Linux and macOS.

        Raises:
            OSError: When it cannot be written.
            ModuleApplyError: ``credential_invalid`` when Windows refuses
                the account's login.
        """
        if self._is_windows:
            self._as_account(_step_write, path, data)
            return
        result = self.run(["/bin/sh", "-c", WRITE_SHELL, path, format(mode, "o")], data)
        if result.returncode != 0:
            raise OSError(f"could not write {path}: {_detail(result)}")

    def write_in_place(self, path: str, data: bytes) -> None:
        """Write a file's bytes in place as the account, its folder made.

        The file keeps its inode, its owner and its mode.

        Args:
            path: The file.
            data: What it holds afterwards.

        Raises:
            OSError: When it cannot be written.
            ModuleApplyError: ``credential_invalid`` when Windows refuses
                the account's login.
        """
        if self._is_windows:
            self._as_account(_step_write_in_place, path, data)
            return
        result = self.run(["/bin/sh", "-c", WRITE_IN_PLACE_SHELL, path], data)
        if result.returncode != 0:
            raise OSError(f"could not write {path}: {_detail(result)}")

    def existing(self, paths: list) -> list:
        """The paths that are there, as the account sees them.

        Args:
            paths: The paths.

        Returns:
            Those that are there, in their order.

        Raises:
            OSError: When the step cannot run.
            ModuleApplyError: ``credential_invalid`` when Windows refuses
                the account's login.
        """
        if not paths:
            return []
        if self._is_windows:
            return list(self._as_account(_step_existing, list(paths)))
        result = self.run(["/bin/sh", "-c", EXISTING_SHELL, "sh", *paths])
        found = set(result.stdout.decode("utf-8", "replace").splitlines())
        return [path for path in paths if path in found]

    def make_dir(self, path: str, umask: int = 0o077) -> bool:
        """Make a folder as the account, with each one missing above it.

        Args:
            path: The folder.
            umask: What each folder made leaves out of 0777 on Linux and
                macOS; the account's alone by default.

        Returns:
            Whether it was made.

        Raises:
            OSError: When it cannot be made.
            ModuleApplyError: ``credential_invalid`` when Windows refuses
                the account's login.
        """
        if self._is_windows:
            return bool(self._as_account(_step_make_dir, path))
        result = self.run(["/bin/sh", "-c", MAKE_DIR_SHELL, path, format(umask, "03o")])
        if result.returncode == ABSENT_EXIT:
            return False
        if result.returncode != 0:
            raise OSError(f"could not make {path}: {_detail(result)}")
        return True

    def remove(self, path: str) -> None:
        """Delete a file as the account; quiet when it is not there.

        Raises:
            OSError: When it cannot be deleted.
            ModuleApplyError: ``credential_invalid`` when Windows refuses
                the account's login.
        """
        if self._is_windows:
            self._as_account(_step_remove, path)
            return
        result = self.run(["/bin/sh", "-c", REMOVE_SHELL, path])
        if result.returncode != 0:
            raise OSError(f"could not remove {path}: {_detail(result)}")

    def remove_tree(self, path: str) -> None:
        """Delete a folder and everything in it as the account; quiet when it is not there.

        Raises:
            OSError: When it cannot be deleted.
            ModuleApplyError: ``credential_invalid`` when Windows refuses
                the account's login.
        """
        if self._is_windows:
            self._as_account(_step_remove_tree, path)
            return
        result = self.run(["/bin/sh", "-c", REMOVE_TREE_SHELL, path])
        if result.returncode != 0:
            raise OSError(f"could not remove {path}: {_detail(result)}")

    def remove_empty_dirs(self, paths: list) -> None:
        """Delete each folder as the account while it is empty, deepest first, stopping at the first that is not.

        Raises:
            OSError: When the step cannot run.
            ModuleApplyError: ``credential_invalid`` when Windows refuses
                the account's login.
        """
        if not paths:
            return
        if self._is_windows:
            self._as_account(_step_remove_empty_dirs, list(paths))
            return
        self.run(["/bin/sh", "-c", REMOVE_EMPTY_SHELL, "sh", *paths])

    def run(self, argv: list, data: bytes = b"") -> subprocess.CompletedProcess:
        """Run one command as the account on Linux or macOS, its bytes in and out as they are.

        Args:
            argv: The argument vector.
            data: What it reads on its standard input.

        Returns:
            The completed process, its output as bytes.

        Raises:
            OSError: When the account is not there, the command cannot
                start or does not finish in time, or on Windows.
        """
        if self._is_windows:
            raise OSError("no command runs as an account here")
        try:
            command, process = self._platform.account_process(self.account, list(argv))
        except KeyError as error:
            raise OSError(f"no account {self.account}") from error
        except PlatformUnsupportedError as error:
            raise OSError(str(error)) from error
        try:
            return subprocess.run(
                command,
                input=data,
                capture_output=True,
                timeout=self._timeout_s,
                **process,
            )
        except subprocess.SubprocessError as error:
            raise OSError(f"{argv[0]} as {self.account} did not finish") from error

    def _as_account(self, step, *arguments):
        """Run one step of the agent's own code on this thread acting as the account.

        Raises:
            OSError: When the thread cannot act as the account, or the step
                fails.
            ModuleApplyError: ``credential_invalid`` when Windows refuses
                the account's login.
        """
        try:
            return self._platform.as_account(
                self.account, step, *arguments, password=self._password
            )
        except PlatformUnsupportedError as error:
            raise OSError(str(error)) from error


def _detail(result) -> str:
    """The words a failed command left, cut short. Pure."""
    words = (result.stderr or result.stdout or b"").decode("utf-8", "replace")
    return words.strip()[:DETAIL_CHARS] or f"exit {result.returncode}"
