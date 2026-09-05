"""The AI service: pointing each account's AI tools at the hub's gateway.

A service, not a function: the panel neither renders nor controls it. One
chip per account — switching a chip on asks the hub for that account's
gateway key and points the account's tools at the gateway; switching it off
puts the account's own configuration back. The store keeps only the target
and the last-granted endpoint; the key itself arrives fresh in every
heartbeat reply and is held in memory for the turn.

Deactivation uses the endpoint activation recorded, because by then the hub
has revoked the key and the reply no longer names it.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import threading
import time

from neutrino_agent import switcher
from neutrino_agent.downloader import DownloadError
from neutrino_agent.installers import InstallError
from neutrino_agent.platforms.detect import platform_keys

# How often to re-check accounts whose inputs have not changed. Each check
# reads the account's own settings file, which steps down per account.
AI_IDLE_RECHECK_INTERVAL_S = 60


def _steady(is_present: bool, is_active: bool) -> dict:
    return {
        "state": "installed" if is_present else "absent",
        "code": "",
        "params": {},
        "is_active": is_active,
    }


def _transient(state: str, *, is_active: bool = False) -> dict:
    return {"state": state, "code": "", "params": {}, "is_active": is_active}


def _failure(code: str, error: Exception) -> dict:
    return {
        "state": "failed",
        "code": code,
        "params": {"detail": str(error)[:200]},
        "is_active": False,
    }


class AiServiceReconciler:
    """Keeps every account's AI tools converged on its switching target."""

    def __init__(self, *, store, platform_tuple: dict, log=print, switcher_module=None):
        """
        Args:
            store: The :class:`~neutrino_agent.services.store.MachineServiceStore`.
            platform_tuple: This machine's platform tuple, to pick the
                offer's switcher block.
            log: Callable used for progress messages.
            switcher_module: The switcher to drive; None uses the real one.
        """
        self._store = store
        self._platform_tuple = platform_tuple
        self._log = log
        self._switcher = switcher_module if switcher_module is not None else switcher
        self._lock = threading.Lock()
        self._offer: dict = {}
        self._accounts: list = []
        self._credentials: dict = {}
        self._statuses: dict = {}
        self._signature = ""
        self._checked_at = 0.0
        self._wakeup = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def update(self, *, offer: dict, accounts: list, credentials: dict) -> None:
        """Take one heartbeat reply's worth of inputs.

        Args:
            offer: The catalog's AI service offer; empty when the hub
                extends none, which reconciles nothing.
            accounts: The machine's reported human accounts.
            credentials: Account name to ``{"base_url", "api_key", "model"}``
                for the accounts the hub granted this turn.
        """
        with self._lock:
            self._offer = dict(offer)
            self._accounts = list(accounts)
            self._credentials = {
                str(account): dict(value)
                for account, value in credentials.items()
                if isinstance(value, dict)
            }
        self._wakeup.set()

    def report(self) -> dict:
        """The per-account states for the page.

        Returns:
            Account name to ``{"state", "code", "params", "is_active"}``.
        """
        with self._lock:
            return {name: dict(value) for name, value in self._statuses.items()}

    def _run(self) -> None:
        while True:
            self._wakeup.wait()
            self._wakeup.clear()
            try:
                self._reconcile()
            except Exception as error:  # noqa: BLE001 - the loop must survive
                self._log(f"ai service reconcile crashed: {error}")

    def _reconcile(self) -> None:
        targets = self._store.ai_targets()
        granted = self._store.ai_granted()
        with self._lock:
            offer = dict(self._offer)
            accounts = list(self._accounts)
            credentials = dict(self._credentials)
            if not offer:
                self._statuses = {}
                return
            signature = json.dumps(
                [targets, granted, sorted(accounts), offer, credentials],
                sort_keys=True,
                default=str,
            )
            is_stale = (
                signature != self._signature
                or time.monotonic() - self._checked_at > AI_IDLE_RECHECK_INTERVAL_S
            )
            self._signature = signature
            if is_stale:
                self._checked_at = time.monotonic()
        if not is_stale:
            return
        names = sorted(set(accounts) | set(targets) | set(granted))
        for account in names:
            self._publish(
                account,
                self._reconcile_account(
                    account,
                    entry=self._switcher_entry(offer),
                    is_wanted=bool(targets.get(account)),
                    creds=credentials.get(account, {}),
                ),
            )
        with self._lock:
            self._statuses = {
                name: value for name, value in self._statuses.items() if name in names
            }

    def _reconcile_account(
        self, account: str, *, entry: dict, is_wanted: bool, creds: dict
    ) -> dict:
        granted = self._store.ai_granted().get(account, {})
        try:
            if is_wanted:
                return self._activate(account, entry=entry, creds=creds)
            if granted:
                self._publish(account, _transient("deactivating", is_active=True))
                self._log(f"ai service: pointing {account}'s tools away from the hub")
                self._switcher.deactivate(
                    run_as=account, base_url=granted.get("base_url", "")
                )
                self._store.clear_ai_granted(account)
        except switcher.NoTargetUserError as error:
            return {
                "state": "failed",
                "code": error.code,
                "params": {},
                "is_active": False,
            }
        except DownloadError as error:
            return _failure("download_failed", error)
        except InstallError as error:
            return _failure("install_failed", error)
        except Exception as error:  # noqa: BLE001 - reported, not raised
            return _failure("reconcile_failed", error)
        return _steady(self._switcher.is_installed(), False)

    def _activate(self, account: str, *, entry: dict, creds: dict) -> dict:
        base_url = str(creds.get("base_url", ""))
        api_key = str(creds.get("api_key", ""))
        model = str(creds.get("model", ""))
        if not base_url or not api_key:
            return {
                "state": "installed" if self._switcher.is_installed() else "absent",
                "code": "no_endpoint",
                "params": {},
                "is_active": False,
            }
        if not self._switcher.is_active(
            run_as=account, base_url=base_url, api_key=api_key, model=model
        ):
            if self._switcher.find_cli() is None:
                self._publish(account, _transient("installing"))
                self._log("ai service: installing the cc-switch command line")
                self._switcher.install_cli(entry)
            self._publish(account, _transient("activating"))
            self._log(f"ai service: pointing {account}'s tools at the hub")
            self._switcher.activate(
                base_url=base_url, api_key=api_key, run_as=account, model=model
            )
        self._store.set_ai_granted(account, {"base_url": base_url, "model": model})
        return {"state": "installed", "code": "", "params": {}, "is_active": True}

    def _switcher_entry(self, offer: dict) -> dict:
        platforms = offer.get("platforms", {})
        for key in platform_keys(self._platform_tuple):
            if key in platforms:
                return platforms[key].get("switcher", {})
        return {}

    def _publish(self, account: str, status: dict) -> None:
        with self._lock:
            self._statuses[account] = status
