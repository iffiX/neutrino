"""The AI service: pointing an account's AI tools at the hub's gateway.

A service, not a function: the panel neither renders nor controls it. One
chip per account — switching a chip on asks the hub for that account's
gateway key and points the account's tools at the gateway; switching it off
puts the account's own configuration back. The reconcile below is moved from
the function engine and nothing calls it yet; the services flow wires it.

The store is machine state: it survives a hub restore untouched and appears
in no hub backup. The hub-sent per-account credentials are kept in memory
only — they arrive fresh in every heartbeat reply.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json

from neutrino_agent import switcher
from neutrino_agent.constants import AGENT_AI_STORE_PATH


def reconcile(
    name: str,
    entry: dict,
    wanted: "dict | None",
    config: dict,
    *,
    account: str,
    publish,
    log=print,
) -> dict:
    """Have cc-switch on the machine, and have it point at the hub.

    Two independent wishes. Installing puts the switcher there and leaves it
    pointing wherever it already pointed; activating registers the hub in it
    and switches to it. Deactivating removes only the hub's entry, so the
    other providers someone keeps stay untouched.

    Args:
        name: The service name, for the transient states.
        entry: The catalog entry, naming where the CLI comes from.
        wanted: ``is_enabled`` and ``is_activated``, or None when nothing
            has been asked and this only reports.
        config: The endpoint, key and model, resolved by the hub.
        account: The account whose tools to switch.
        publish: Called with ``(name, status)`` for transient states.
        log: Callable used for progress messages.

    Returns:
        ``{"state", "code", "params", "is_active"}``.
    """
    switcher_entry = entry.get("switcher", {})
    base_url = config.get("base_url", "")
    is_present = switcher.is_installed()
    is_active = (
        is_present
        and bool(account)
        and switcher.is_active(
            run_as=account,
            base_url=base_url,
            api_key=config.get("api_key", ""),
            model=config.get("model", ""),
        )
    )

    if wanted is None:
        return _steady_status(is_present, is_active)

    is_enabled = bool(wanted.get("is_enabled"))
    is_activated = bool(wanted.get("is_activated"))

    try:
        if not is_enabled:
            return _remove(name, account, base_url, is_present, is_active, log)
        if not is_present:
            publish(name, _transient("installing"))
            log(f"{name}: installing the cc-switch command line")
            switcher.install_cli(switcher_entry)
            is_present = True
        if is_activated and not is_active:
            return _activate(
                name, switcher_entry, config, account, base_url, publish, log
            )
        if not is_activated and is_active:
            publish(name, _transient("deactivating", is_active=True))
            log(f"{name}: pointing cc-switch away from the hub")
            note = switcher.deactivate(run_as=account, base_url=base_url)
            return {
                "state": "installed",
                "code": "",
                "params": {"detail": note},
                "is_active": False,
            }
    except switcher.NoTargetUserError as error:
        return {
            "state": "failed",
            "code": error.code,
            "params": {},
            "is_active": False,
        }
    return _steady_status(is_present, is_active)


def _remove(
    name: str, account: str, base_url: str, is_present: bool, is_active: bool, log
) -> dict:
    if not is_present:
        return _steady_status(False, False)
    log(f"{name}: removing the cc-switch command line")
    if is_active:
        switcher.deactivate(run_as=account, base_url=base_url)
    switcher.uninstall_cli()
    still_there = switcher.is_installed()
    return {
        "state": "installed" if still_there else "absent",
        "code": "desktop_app_remains" if still_there else "",
        "params": {},
        "is_active": False,
    }


def _activate(
    name: str,
    switcher_entry: dict,
    config: dict,
    account: str,
    base_url: str,
    publish,
    log,
) -> dict:
    if not base_url or not config.get("api_key"):
        return {
            "state": "installed",
            "code": "no_endpoint",
            "params": {},
            "is_active": False,
        }
    publish(name, _transient("activating"))
    if switcher.find_cli() is None:
        # Only the desktop app is here; the command line is what can be
        # driven, and both share one store.
        log(f"{name}: installing the cc-switch command line")
        switcher.install_cli(switcher_entry)
    log(f"{name}: pointing cc-switch at the hub")
    note = switcher.activate(
        base_url=base_url,
        api_key=config["api_key"],
        run_as=account,
        model=config.get("model", ""),
    )
    return {
        "state": "installed",
        "code": "",
        "params": {"detail": note},
        "is_active": True,
    }


def _steady_status(is_present: bool, is_active: bool) -> dict:
    """The steady-state report for the AI service."""
    return {
        "state": "installed" if is_present else "absent",
        "code": "",
        "params": {},
        "is_active": is_active,
    }


def _transient(state: str, *, is_active: bool = False) -> dict:
    return {"state": state, "code": "", "params": {}, "is_active": is_active}


class AiServiceStore:
    """The per-account AI switching state this machine keeps."""

    def __init__(self, *, path: str = AGENT_AI_STORE_PATH):
        """
        Args:
            path: Where the switching state lives on disk.
        """
        self._path = path
        self._accounts: dict = {}

    def targets(self) -> dict:
        """Which accounts are switched at the hub's gateway.

        Returns:
            Account name to bool; empty until an account is switched.
        """
        try:
            with open(self._path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, ValueError):
            return {}
        targets = data.get("targets", {}) if isinstance(data, dict) else {}
        return {
            str(account): bool(is_switched) for account, is_switched in targets.items()
        }

    def accounts(self) -> dict:
        """The hub-sent per-account credentials, as the last reply carried.

        Returns:
            Account name to ``{"base_url", "api_key", "model"}``.
        """
        return dict(self._accounts)

    def take_accounts(self, accounts: dict) -> None:
        """Keep the reply's per-account credentials, in memory only.

        Args:
            accounts: Account name to ``{"base_url", "api_key", "model"}``.
        """
        self._accounts = {
            str(account): dict(value)
            for account, value in accounts.items()
            if isinstance(value, dict)
        }
