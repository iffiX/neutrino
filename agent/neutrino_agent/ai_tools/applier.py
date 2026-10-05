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

cc-switch is the copy the agent fetched from the hub into ``bin`` under the
records' directory. Before any account is run, a copy of the version the
section names is made sure of; one that cannot be had fails every account
and leaves the state to be applied again. Holding an account's lock, no
switch is made once the machine has no binding.

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
import os
import shutil
import tarfile
import tempfile
import threading
import zipfile

from neutrino_agent.ai_tools.account_lock import AiToolsAccountLock
from neutrino_agent.ai_tools.account_session import AiToolsAccountSession
from neutrino_agent.ai_tools import switcher_copy
from neutrino_agent.ai_tools.constants import (
    AI_TOOLS_APPS,
    AI_TOOLS_CC_SWITCH_PACKAGE,
    AI_TOOLS_CODE_ACCOUNT_UNKNOWN,
    AI_TOOLS_CODE_CREDENTIAL_MISSING,
    AI_TOOLS_CODE_DOWNLOAD_FAILED,
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
from neutrino_agent.exceptions import ToolSwitchError
from neutrino_agent.streams.package import CODE_UNREACHABLE


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

    def __init__(self, *, platform, log=print, root_dir: str = "", is_bound=None):
        """
        Args:
            platform: The machine's platform, which runs as an account.
            log: Callable used for progress messages.
            root_dir: Where the records and the copy of cc-switch live;
                empty is ``ai_tools`` under the state root.
            is_bound: Says whether the machine still has a binding; a
                switch is made only while it does. None makes every switch.
        """
        self._platform = platform
        self._log = log
        self._root = root_dir or os.path.join(
            platform.agent_var_dir(), AI_TOOLS_DIR_NAME
        )
        self._binary = switcher_copy.binary_path(self._root, platform.os_name)
        self._is_bound = is_bound
        self._lock = threading.Lock()
        self._applied_hash: "str | None" = None
        self._results: "list | None" = None

    def apply(self, section, state_hash: str, receive=None) -> None:
        """Make one state's section true, once per state.

        Args:
            section: The state's ``ai_tools``; anything but a dict leaves
                every account as it is.
            state_hash: The state's hash; a hash applied before is not
                applied again, and one whose copy of cc-switch could not be
                had is not marked applied.
            receive: Opens ``package {module}`` to the hub and returns
                ``{"path"}`` or ``{"code", "params"}``; None fetches nothing.
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
        names = [str(entry["account"]) for entry in named]
        leaving = [name for name in self.switched_accounts() if name not in names]
        if names or leaving:
            version = (
                str(section.get("cc_switch_version", "") or "") if is_enabled else ""
            )
            refusal = self._ensure_copy(version, receive)
            if refusal is not None:
                with self._lock:
                    self._results = self._refused_all(names + leaving, refusal)
                return
        results = []
        for entry in named:
            switched = self._switch(
                str(entry["account"]), str(entry.get("password", "") or ""), section
            )
            if switched is not None:
                results.append(switched)
        for account in leaving:
            results.append(self._switch_back(account))
        with self._lock:
            self._results = results
            self._applied_hash = state_hash

    def switch_back_all(self) -> list:
        """Switch back every account this agent switched, before it goes.

        Returns:
            Each account's result.
        """
        accounts = self.switched_accounts()
        refusal = self._ensure_copy("", None) if accounts else None
        if refusal is not None:
            results = self._refused_all(accounts, refusal)
        else:
            results = [self._switch_back(account) for account in accounts]
        with self._lock:
            self._results = results
        return results

    def remove_copy(self) -> list:
        """Delete the copy of cc-switch the agent fetched.

        Returns:
            What was removed, one path each.
        """
        return switcher_copy.remove_copy(self._root)

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

    def _switch(self, account: str, password: str, section: dict) -> "dict | None":
        """Point one account's tools at the hub, holding its lock, or say why not.

        Returns:
            The account's result, None when the machine has no binding any
            more and nothing was done.
        """
        try:
            with self._account_lock(account):
                if self._is_bound is not None and not self._is_bound():
                    return None
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

    def _ensure_copy(self, version: str, receive) -> "dict | None":
        """Have a copy of cc-switch of the version named, fetched when it is not there.

        Args:
            version: The version the section names; empty takes any copy.
            receive: Opens a package stream to the hub; None fetches nothing.

        Returns:
            None when a copy is there, else ``{"code", "params"}``:
            ``hub_unreachable`` with no hub to ask, and
            ``cc_switch_download_failed {detail}`` when the hub refused or
            the archive would not unpack.
        """
        is_there = os.path.isfile(self._binary)
        if is_there and (
            not version or switcher_copy.installed_version(self._root) == version
        ):
            return None
        if receive is None:
            return None if is_there else {"code": CODE_UNREACHABLE, "params": {}}
        received = receive(AI_TOOLS_CC_SWITCH_PACKAGE)
        path = str(received.get("path", "") or "")
        if not path:
            code = str(received.get("code", "") or "")
            if code == CODE_UNREACHABLE:
                return {"code": code, "params": {}}
            return {"code": AI_TOOLS_CODE_DOWNLOAD_FAILED, "params": {"detail": code}}
        try:
            switcher_copy.install_copy(
                path,
                root=self._root,
                os_name=self._platform.os_name,
                version=version,
                open_to_accounts=self._platform.open_to_accounts,
            )
        except (OSError, tarfile.TarError, zipfile.BadZipFile, ValueError) as error:
            return {
                "code": AI_TOOLS_CODE_DOWNLOAD_FAILED,
                "params": {"detail": str(error)[:AI_TOOLS_DETAIL_LIMIT]},
            }
        finally:
            with contextlib.suppress(OSError):
                os.unlink(path)
        self._log(f"ai_tools: cc-switch {version or '?'} fetched from the hub")
        return None

    def _refused_all(self, accounts: list, refusal: dict) -> list:
        """The same refusal as every account's result."""
        self._log(f"ai_tools: {refusal['code']} {refusal['params']}")
        return [
            result(
                account,
                AI_TOOLS_STATE_FAILED,
                refusal["code"],
                {"account": account, **refusal["params"]},
            )
            for account in accounts
        ]

    def _session(self, account: str, password: str):
        """The session that reaches one account, or its failure as a result."""
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
