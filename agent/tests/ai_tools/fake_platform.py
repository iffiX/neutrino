"""A platform whose accounts are homes in memory, each with a cc-switch store of its own.

It reads the commands the session sends as the account: the binary is
cc-switch; on Linux and macOS ``cat``, ``test -f``, ``sh -c`` and ``rm -f``
are the file operations, and ``sh -c`` with the payload's removal removes, and on Windows the PowerShell scripts that do the
same, decoded from their ``-EncodedCommand``. Every run is recorded with
the account and the login.
"""

import base64
import re
import subprocess

from neutrino_agent.ai_tools.account_session import (
    POSIX_PRIVATE_DIR_SHELL,
    POSIX_REMOVE_SHELL,
    POSIX_REMOVE_TREE_SHELL,
    POWERSHELL_QUIET_PROGRESS,
)
from tests.ai_tools.fake_cc_switch import FakeCcSwitch, has_dir

# The single-quoted literal a Windows script carries its path in.
LITERAL = re.compile(r"'((?:[^']|'')*)'")


class FakeAccountPlatform:
    """Runs as an account against its own :class:`FakeCcSwitch` and a home in memory."""

    def __init__(self, *, os_name="linux", homes=None, root=""):
        self.os_name = os_name
        self.homes = dict(homes if homes is not None else {"ann": "/home/ann"})
        self.stores: dict = {}
        self.files: dict = {}
        self.dirs: set = set()
        self.environments: list = []
        self.modes: dict = {}
        self.runs: list = []
        self.answered: list = []
        self.refusal = None
        self.opened: list = []
        self._root = root

    def store(self, account) -> FakeCcSwitch:
        """The cc-switch store kept in one account's home."""
        if account not in self.stores:
            self.stores[account] = FakeCcSwitch()
        return self.stores[account]

    def agent_var_dir(self):
        return self._root

    def open_to_accounts(self, directory):
        self.opened.append(directory)

    def account_home(self, account):
        if account not in self.homes:
            raise KeyError(account)
        return self.homes[account]

    def run_as_account(
        self, account, argv, *, stdin="", timeout_s=0, password="", environment=None
    ):
        self.runs.append((account, password, list(argv)))
        self.environments.append(dict(environment or {}))
        if self.refusal is not None:
            raise self.refusal
        home = _Account(self, account)
        if argv[1:2] == ["--app"]:
            code, out, err = self.store(account).answer(home, argv[3:], argv[2])
        else:
            verb, path = self._file_operation(argv)
            code, out, err = 0, "", ""
            if verb == "read":
                found = path in self.files
                code, out = (0, self.files[path]) if found else (1, "")
            elif verb == "is_file":
                code = 0 if path in self.files else 1
            elif verb == "write":
                self.files[path] = stdin
            elif verb == "remove":
                self.files.pop(path, None)
            elif verb == "mode_of":
                if path in self.files:
                    out = mode_letters(self.modes.get(path, 0o644)) + " 1 0 0 1 x\n"
                else:
                    code = 2
            elif verb == "set_mode":
                self.modes[path] = int(argv[-2], 8)
            elif verb == "remove_tree":
                for name in [n for n in self.files if n.startswith(path + "/")]:
                    del self.files[name]
                self.dirs = {
                    d for d in self.dirs if not (d == path or d.startswith(path + "/"))
                }
            elif verb == "is_dir":
                code = 0 if has_dir(self.files, self.dirs, path) else 1
            elif verb == "make_dir":
                self.dirs.add(path)
            elif verb == "remove_empty_dir":
                if not has_dir(self.files, set(), path):
                    self.dirs.discard(path)
            else:
                code, err = 127, "unknown"
        return subprocess.CompletedProcess(argv, code, out, err)

    def run_as_account_answering(
        self,
        account,
        argv,
        *,
        prompt,
        answer,
        timeout_s=0,
        password="",
        environment=None,
    ):
        self.environments.append(dict(environment or {}))
        self.answered.append((account, password, list(argv), prompt, answer))
        home = _Account(self, account)
        return 0, self.store(account).answer(home, argv[3:], argv[2])[1]

    def _file_operation(self, argv) -> tuple:
        """``(verb, path)`` of one file operation's command."""
        if argv[0] == "powershell.exe":
            script = base64.b64decode(argv[-1]).decode("utf-16-le")
            script = script.replace(POWERSHELL_QUIET_PROGRESS, "", 1)
            path = LITERAL.search(script).group(1).replace("''", "'")
            if "PathType Container) -and" in script:
                return "remove_empty_dir", path
            if "PathType Container" in script:
                return "is_dir", path
            if "ItemType Directory" in script and "ReadToEnd" not in script:
                return "make_dir", path
            if "Remove-Item" in script:
                return "remove", path
            if "ReadToEnd" in script:
                return "write", path
            if "ReadAllText" in script:
                return "read", path
            return "is_file", path
        if argv[:2] == ["sh", "-c"] and argv[2] == POSIX_PRIVATE_DIR_SHELL.format(
            mode="700"
        ):
            return "make_dir", argv[4]
        if argv[:3] == ["sh", "-c", POSIX_REMOVE_TREE_SHELL]:
            return "remove_tree", argv[4]
        if argv[:3] == ["sh", "-c", POSIX_REMOVE_SHELL]:
            return "remove", argv[4]
        if argv[:2] == ["test", "-d"]:
            return "is_dir", argv[-1]
        verbs = {
            "cat": "read",
            "test": "is_file",
            "sh": "write",
            "rm": "remove",
            "mkdir": "make_dir",
            "rmdir": "remove_empty_dir",
            "ls": "mode_of",
            "chmod": "set_mode",
        }
        return verbs.get(argv[0], ""), argv[-1]


class _Account:
    """The store's view of one account's home on the fake platform."""

    def __init__(self, platform, account):
        self.account = account
        self.files = platform.files
        self.dirs = platform.dirs
        self.home = platform.homes[account]

    def has_dir(self, path):
        return has_dir(self.files, self.dirs, path)

    def path(self, *parts):
        separator = "\\" if platform_is_windows(self.home) else "/"
        return separator.join([self.home, *parts])


def platform_is_windows(home: str) -> bool:
    """Whether a home is spelled the way Windows spells one."""
    return ":" in home[:3]


def mode_letters(mode: int) -> str:
    """Permission bits as ``ls -l`` spells them, for a plain file."""
    letters = "".join(
        letter if mode & (1 << (8 - at)) else "-"
        for at, letter in enumerate("rwxrwxrwx")
    )
    return "-" + letters
