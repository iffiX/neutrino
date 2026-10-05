"""Making the state's ``ai_tools`` section true, account by account.

The section says whether the machine's AI tools use the hub's gateway, with
its endpoint, the device's key and each tool's models, and names the
accounts it acts on. While it is on, each named account is switched with the
desktop client's steps, run as that account; an account this agent switched
that the section no longer names, and every one of them when the section is
off, is switched back with the client's deactivation. An account whose
records already carry the wanted settings is not run again, and a state the
agent applied once is not applied again, so a failed account is tried again
only with a state of another hash.

The records live under the state root, one directory per account, root's
own. Each account's switch or switch back holds that account's lock from
start to end, so two agent processes never run cc-switch for one account at
once, and a run that waits too long for it is that account's
``switch_failed``. On Windows the account's login travels in the state only while the
section is on, so the login an account was switched with is kept beside its
records, root's own, until it is switched back.

Not pure: runs cc-switch as accounts and writes the records.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import json
import ntpath
import os
import shutil
import tempfile
import threading

from neutrino_agent.ai_tools.account_lock import AiToolsAccountLock
from neutrino_agent.ai_tools.account_session import AiToolsAccountSession
from neutrino_agent.ai_tools.constants import (
    AI_TOOLS_APPS,
    AI_TOOLS_CC_SWITCH_BINARY,
    AI_TOOLS_CC_SWITCH_PATHS,
    AI_TOOLS_CC_SWITCH_WINDOWS_PARTS,
    AI_TOOLS_CODE_ACCOUNT_UNKNOWN,
    AI_TOOLS_CODE_BUNDLE_MISSING,
    AI_TOOLS_CODE_CREDENTIAL_MISSING,
    AI_TOOLS_CODE_SWITCH_FAILED,
    AI_TOOLS_DETAIL_LIMIT,
    AI_TOOLS_DIR_NAME,
    AI_TOOLS_LOCK_DIR_NAME,
    AI_TOOLS_LOGIN_NAME,
    AI_TOOLS_RECORD_SUFFIX,
    AI_TOOLS_STATE_FAILED,
    AI_TOOLS_STATE_SWITCHED,
    AI_TOOLS_STATE_SWITCHED_BACK,
)
from neutrino_agent.ai_tools.switcher import AiToolsAccountSwitcher
from neutrino_agent.constants import (
    AGENT_WINDOWS_PROGRAM_FILES_DEFAULT,
    AGENT_WINDOWS_PROGRAM_SUBDIR,
)
from neutrino_agent.exceptions import ToolSwitchError


def cc_switch_path(os_name: str) -> str:
    """Where the agent's package carries cc-switch on one system.

    Args:
        os_name: ``linux``, ``darwin`` or ``windows``.

    Returns:
        The binary's path; empty on a system the package carries none for.
    """
    if os_name == "windows":
        root = os.environ.get("ProgramFiles", "") or AGENT_WINDOWS_PROGRAM_FILES_DEFAULT
        return ntpath.join(
            root, *AGENT_WINDOWS_PROGRAM_SUBDIR, *AI_TOOLS_CC_SWITCH_WINDOWS_PARTS
        )
    return AI_TOOLS_CC_SWITCH_PATHS.get(os_name, "")


def result(
    account: str, state: str, code: str = "", params: "dict | None" = None
) -> dict:
    """One account's line in the report."""
    return {
        "account": account,
        "state": state,
        "code": code,
        "params": dict(params or {}),
    }


class AiToolsApplier:
    """Switches the named accounts' AI tools to the hub and back."""

    def __init__(
        self, *, platform, log=print, root_dir: str = "", binary: "str | None" = None
    ):
        """
        Args:
            platform: The machine's platform, which runs as an account.
            log: Callable used for progress messages.
            root_dir: Where the records live; empty is ``ai_tools`` under
                the state root.
            binary: The cc-switch to run; None is the one the agent's
                package carries.
        """
        self._platform = platform
        self._log = log
        self._root = root_dir or os.path.join(
            platform.agent_var_dir(), AI_TOOLS_DIR_NAME
        )
        self._binary = (
            binary if binary is not None else cc_switch_path(platform.os_name)
        )
        self._lock = threading.Lock()
        self._applied_hash: "str | None" = None
        self._results: "list | None" = None

    def apply(self, section, state_hash: str) -> None:
        """Make one state's section true, once per state.

        Args:
            section: The state's ``ai_tools``; anything but a dict leaves
                every account as it is.
            state_hash: The state's hash; a hash applied before is not
                applied again.
        """
        if not isinstance(section, dict):
            return
        with self._lock:
            if state_hash and state_hash == self._applied_hash:
                return
        is_enabled = bool(section.get("is_enabled"))
        named = []
        if is_enabled:
            for entry in section.get("accounts") or []:
                if isinstance(entry, dict) and str(entry.get("account", "") or ""):
                    named.append(entry)
        results = []
        names = set()
        for entry in named:
            account = str(entry["account"])
            names.add(account)
            results.append(
                self._switch(account, str(entry.get("password", "") or ""), section)
            )
        for account in self.switched_accounts():
            if account not in names:
                results.append(self._switch_back(account))
        with self._lock:
            self._results = results
            self._applied_hash = state_hash

    def switch_back_all(self) -> list:
        """Switch back every account this agent switched, before it goes.

        Returns:
            Each account's result.
        """
        results = [self._switch_back(account) for account in self.switched_accounts()]
        with self._lock:
            self._results = results
        return results

    def report(self) -> dict:
        """The report's ``ai_tools`` section.

        Returns:
            ``{accounts: [{account, state, code, params}]}``: the results of
            the last state applied, or, before one was applied since the
            agent started, every account whose records stand, as switched.
        """
        with self._lock:
            held = self._results
        if held is None:
            held = [
                result(account, AI_TOOLS_STATE_SWITCHED)
                for account in self.switched_accounts()
            ]
        return {"accounts": [dict(entry) for entry in held]}

    def switched_accounts(self) -> list:
        """The accounts a tool's record is kept for, sorted."""
        try:
            names = os.listdir(self._root)
        except OSError:
            return []
        return sorted(
            name
            for name in names
            if not name.startswith(".") and self._has_records(name)
        )

    def _switch(self, account: str, password: str, section: dict) -> dict:
        """Point one account's tools at the hub, holding its lock, or say why not."""
        try:
            with self._account_lock(account):
                return self._switch_held(account, password, section)
        except ToolSwitchError as error:
            return self._refused(account, error)

    def _switch_held(self, account: str, password: str, section: dict) -> dict:
        """Point one account's tools at the hub, or say why not."""
        session = self._session(account, password)
        if isinstance(session, dict):
            return session
        switcher = AiToolsAccountSwitcher(
            session=session, record_dir=self._account_dir(account)
        )
        base_url = str(section.get("base_url", "") or "")
        api_key = str(section.get("api_key", "") or "")
        configs = section.get("tool_configs")
        configs = configs if isinstance(configs, dict) else {}
        if switcher.is_current(
            base_url=base_url, api_key=api_key, tool_configs=configs
        ):
            return result(account, AI_TOOLS_STATE_SWITCHED)
        if password:
            self._write_login(account, password)
        try:
            switched = switcher.activate(
                base_url=base_url, api_key=api_key, tool_configs=configs
            )
        except ToolSwitchError as error:
            self._drop_unswitched(account)
            return self._refused(account, error)
        except Exception as error:  # noqa: BLE001 - reported, never raised
            self._drop_unswitched(account)
            return self._failed(account, error)
        self._log(
            f"ai_tools: {account} switched {', '.join(switched) or 'nothing new'}"
        )
        return result(account, AI_TOOLS_STATE_SWITCHED)

    def _switch_back(self, account: str) -> dict:
        """Put one account's tools back, holding its lock, or say why not."""
        try:
            with self._account_lock(account):
                return self._switch_back_held(account)
        except ToolSwitchError as error:
            return self._refused(account, error)

    def _switch_back_held(self, account: str) -> dict:
        """Put one account's tools back, and forget its records once that took."""
        session = self._session(account, self._read_login(account))
        if isinstance(session, dict):
            return session
        switcher = AiToolsAccountSwitcher(
            session=session, record_dir=self._account_dir(account)
        )
        try:
            notes = switcher.deactivate()
        except ToolSwitchError as error:
            return self._refused(account, error)
        except Exception as error:  # noqa: BLE001 - reported, never raised
            return self._failed(account, error)
        shutil.rmtree(self._account_dir(account), ignore_errors=True)
        self._log(f"ai_tools: {account} switched back: {', '.join(notes)}")
        return result(account, AI_TOOLS_STATE_SWITCHED_BACK)

    def _session(self, account: str, password: str):
        """The session that reaches one account, or its failure as a result."""
        if not self._binary or not os.path.isfile(self._binary):
            return result(
                account,
                AI_TOOLS_STATE_FAILED,
                AI_TOOLS_CODE_BUNDLE_MISSING,
                {"binary": AI_TOOLS_CC_SWITCH_BINARY},
            )
        try:
            home = self._platform.account_home(account)
        except KeyError:
            return result(
                account,
                AI_TOOLS_STATE_FAILED,
                AI_TOOLS_CODE_ACCOUNT_UNKNOWN,
                {"account": account},
            )
        except Exception as error:  # noqa: BLE001 - reported, never raised
            return self._failed(account, error)
        if self._platform.os_name == "windows" and not password:
            return result(
                account,
                AI_TOOLS_STATE_FAILED,
                AI_TOOLS_CODE_CREDENTIAL_MISSING,
                {"account": account},
            )
        return AiToolsAccountSession(
            platform=self._platform,
            account=account,
            home=home,
            binary=self._binary,
            password=password,
        )

    def _account_lock(self, account: str) -> AiToolsAccountLock:
        """The lock one account's switch or switch back holds."""
        return AiToolsAccountLock(
            path=os.path.join(self._root, AI_TOOLS_LOCK_DIR_NAME, account),
            account=account,
        )

    def _refused(self, account: str, error: ToolSwitchError) -> dict:
        """A refusal as the account's result."""
        self._log(f"ai_tools: {account}: {error.code} {error.params}")
        return result(
            account,
            AI_TOOLS_STATE_FAILED,
            error.code,
            {"account": account, **error.params},
        )

    def _failed(self, account: str, error: Exception) -> dict:
        """An unexpected error as the account's ``switch_failed``."""
        self._log(f"ai_tools: {account}: {error}")
        return result(
            account,
            AI_TOOLS_STATE_FAILED,
            AI_TOOLS_CODE_SWITCH_FAILED,
            {"account": account, "detail": str(error)[:AI_TOOLS_DETAIL_LIMIT]},
        )

    def _has_records(self, account: str) -> bool:
        """Whether any tool of one account has a record."""
        return any(
            os.path.isfile(
                os.path.join(self._account_dir(account), app + AI_TOOLS_RECORD_SUFFIX)
            )
            for app in AI_TOOLS_APPS
        )

    def _drop_unswitched(self, account: str) -> None:
        """Remove an account's directory when no tool of it has a record."""
        if not self._has_records(account):
            shutil.rmtree(self._account_dir(account), ignore_errors=True)

    def _account_dir(self, account: str) -> str:
        return os.path.join(self._root, account)

    def _read_login(self, account: str) -> str:
        """The login an account was switched with; empty when none is kept."""
        try:
            with open(
                os.path.join(self._account_dir(account), AI_TOOLS_LOGIN_NAME),
                "r",
                encoding="utf-8",
            ) as stream:
                held = json.load(stream)
        except (OSError, ValueError):
            return ""
        return str(held.get("password", "") or "") if isinstance(held, dict) else ""

    def _write_login(self, account: str, password: str) -> None:
        """Keep the login an account is switched with, root's own."""
        directory = self._account_dir(account)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".login_")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"password": password}, stream)
            os.chmod(temporary, 0o600)
            os.replace(temporary, os.path.join(directory, AI_TOOLS_LOGIN_NAME))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise
