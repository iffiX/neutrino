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

from neutrino_agent.ai_tools.account_session import POSIX_REMOVE_SHELL
from tests.ai_tools.fake_cc_switch import FakeCcSwitch

# The single-quoted literal a Windows script carries its path in.
LITERAL = re.compile(r"'((?:[^']|'')*)'")


class FakeAccountPlatform:
    """Runs as an account against its own :class:`FakeCcSwitch` and a home in memory."""

    def __init__(self, *, os_name="linux", homes=None, root=""):
        self.os_name = os_name
        self.homes = dict(homes if homes is not None else {"ann": "/home/ann"})
        self.stores: dict = {}
        self.files: dict = {}
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

    def run_as_account(self, account, argv, *, stdin="", timeout_s=0, password=""):
        self.runs.append((account, password, list(argv)))
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
            else:
                code, err = 127, "unknown"
        return subprocess.CompletedProcess(argv, code, out, err)

    def run_as_account_answering(
        self, account, argv, *, prompt, answer, timeout_s=0, password=""
    ):
        self.answered.append((account, password, list(argv), prompt, answer))
        home = _Account(self, account)
        return 0, self.store(account).answer(home, argv[3:], argv[2])[1]

    def _file_operation(self, argv) -> tuple:
        """``(verb, path)`` of one file operation's command."""
        if argv[0] == "powershell.exe":
            script = base64.b64decode(argv[-1]).decode("utf-16-le")
            path = LITERAL.search(script).group(1).replace("''", "'")
            if "Remove-Item" in script:
                return "remove", path
            if "ReadToEnd" in script:
                return "write", path
            if "ReadAllText" in script:
                return "read", path
            return "is_file", path
        if argv[:3] == ["sh", "-c", POSIX_REMOVE_SHELL]:
            return "remove", argv[4]
        verbs = {"cat": "read", "test": "is_file", "sh": "write", "rm": "remove"}
        return verbs.get(argv[0], ""), argv[-1]


class _Account:
    """The store's view of one account's home on the fake platform."""

    def __init__(self, platform, account):
        self.account = account
        self.files = platform.files
        self.home = platform.homes[account]

    def path(self, *parts):
        separator = "\\" if platform_is_windows(self.home) else "/"
        return separator.join([self.home, *parts])


def platform_is_windows(home: str) -> bool:
    """Whether a home is spelled the way Windows spells one."""
    return ":" in home[:3]
