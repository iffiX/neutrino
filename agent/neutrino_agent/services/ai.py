"""The ai service type: pointing each account's AI tools at the hub's gateway.

The page stages a chips row and per-tool model choices, and Apply commits
them here in one step: targets and tool configs land in the store, the next
heartbeat carries the targets up, and the reply's grant is what drives the
switch. The store keeps only the targets, the choices and the last-granted
endpoint; the key itself arrives fresh in every heartbeat reply and is held
in memory for the turn.

The staged choices are what each tool is pointed with; the grant's ``model``
is only the prefill default for a slot nobody has chosen. Deactivation uses
the endpoint activation recorded, because by then the hub has revoked the
key and the reply no longer names it.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json

from neutrino_agent.core.engine import ReconcileWorker
from neutrino_agent.modules.downloader import DownloadError
from neutrino_agent.modules.installers import InstallError
from neutrino_agent.platforms.detect import platform_keys
from neutrino_agent.services import switcher
from neutrino_agent.services.base import ServiceTypeHandler

AI_CLAUDE_SLOTS = ("default", "opus", "sonnet", "haiku")
AI_TOOL_CONFIG_KEYS = {
    "claude": AI_CLAUDE_SLOTS,
    "codex": ("model", "model_reasoning_effort"),
    "gemini": ("model",),
}
AI_REASONING_EFFORTS = ("minimal", "low", "medium", "high")


def clean_tool_configs(raw: dict) -> dict:
    """The staged tool choices with unknown tools and knobs dropped.

    Args:
        raw: What the page sent.

    Returns:
        ``{tool: {knob: value}}`` holding only the tools and knobs that
        exist; an effort outside its scale is dropped.
    """
    configs = {}
    for tool, knobs in AI_TOOL_CONFIG_KEYS.items():
        values = raw.get(tool)
        if not isinstance(values, dict):
            values = {}
        kept = {}
        for knob in knobs:
            value = str(values.get(knob, "") or "")
            if knob == "model_reasoning_effort" and value not in AI_REASONING_EFFORTS:
                value = ""
            if value:
                kept[knob] = value
        configs[tool] = kept
    return configs


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


class AiServiceHandler(ServiceTypeHandler):
    """Commits the page's staged AI apply into the store."""

    service_type = "ai"

    def __init__(self, *, store, accounts, on_change=None):
        """
        Args:
            store: The :class:`~neutrino_agent.services.store.MachineServiceStore`.
            accounts: Callable answering the machine's human accounts.
            on_change: Called after a commit, so the next heartbeat is soon.
        """
        self._store = store
        self._accounts = accounts
        self._on_change = on_change

    def act(self, *, entries: list, account: str, is_privileged: bool, body: dict):
        """Commit one staged apply: targets and tool configs together.

        Every named account is checked against the reported people, for
        activation and deactivation alike, and an ordinary caller may name
        only itself.

        Args:
            entries: The catalog's service list.
            account: The asking account.
            is_privileged: Whether the caller holds the privileged scope.
            body: ``{"targets": {account: bool}, "tool_configs": {...}}``.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        targets = body.get("targets")
        if not isinstance(targets, dict) or not targets:
            return {"code": "unknown_request", "params": {}}
        reported = self._accounts()
        for name in targets:
            if not is_privileged and name != account:
                return {"code": "control_scope_refused", "params": {}}
            if not name or name not in reported:
                return {"code": "no_target_user", "params": {}}
        tool_configs = body.get("tool_configs")
        if isinstance(tool_configs, dict):
            self._store.set_ai_tool_configs(clean_tool_configs(tool_configs))
        for name, wish in targets.items():
            self._store.set_ai_target(name, is_activated=bool(wish))
        if self._on_change is not None:
            self._on_change()
        return {}


class AiServiceReconciler(ReconcileWorker):
    """Keeps every account's AI tools converged on its switching target."""

    def __init__(self, *, store, platform_tuple: dict, log=print, switcher_module=None):
        """
        Args:
            store: The :class:`~neutrino_agent.services.store.MachineServiceStore`.
            platform_tuple: This machine's platform tuple, to pick the CLI
                release.
            log: Callable used for progress messages.
            switcher_module: The switcher to drive; None uses the real one.
        """
        self._store = store
        self._platform_tuple = platform_tuple
        self._switcher = switcher_module if switcher_module is not None else switcher
        self._entry: dict = {}
        self._accounts: list = []
        self._credentials: dict = {}
        super().__init__(log=log)

    def update(self, *, entry: dict, accounts: list, credentials: dict) -> None:
        """Take one heartbeat reply's worth of inputs.

        Args:
            entry: The service list's ai entry; empty when the hub publishes
                none, which reconciles nothing.
            accounts: The machine's reported human accounts.
            credentials: Account name to ``{"base_url", "api_key", "model"}``
                for the accounts the hub granted this turn.
        """
        with self._lock:
            self._entry = dict(entry)
            self._accounts = list(accounts)
            self._credentials = {
                str(account): dict(value)
                for account, value in credentials.items()
                if isinstance(value, dict)
            }
        self._wakeup.set()

    def _reconcile(self) -> None:
        targets = self._store.ai_targets()
        granted = self._store.ai_granted()
        tool_configs = self._store.ai_tool_configs()
        with self._lock:
            entry = dict(self._entry)
            accounts = list(self._accounts)
            credentials = dict(self._credentials)
            if not entry:
                self._statuses = {}
                return
            signature = json.dumps(
                [targets, granted, tool_configs, sorted(accounts), entry, credentials],
                sort_keys=True,
                default=str,
            )
            is_stale = self._is_stale(signature)
        if not is_stale:
            return
        names = sorted(set(accounts) | set(targets) | set(granted))
        for account in names:
            self._publish(
                account,
                self._reconcile_account(
                    account,
                    is_wanted=bool(targets.get(account)),
                    creds=credentials.get(account, {}),
                    tool_configs=tool_configs,
                ),
            )
        self._keep_only(names)

    def _reconcile_account(
        self, account: str, *, is_wanted: bool, creds: dict, tool_configs: dict
    ) -> dict:
        granted = self._store.ai_granted().get(account, {})
        try:
            if is_wanted:
                return self._activate(account, creds=creds, tool_configs=tool_configs)
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

    def _activate(self, account: str, *, creds: dict, tool_configs: dict) -> dict:
        base_url = str(creds.get("base_url", ""))
        api_key = str(creds.get("api_key", ""))
        if not base_url or not api_key:
            return {
                "state": "installed" if self._switcher.is_installed() else "absent",
                "code": "no_endpoint",
                "params": {},
                "is_active": False,
            }
        resolved = self._resolved_configs(creds, tool_configs)
        default_model = resolved["claude"]["default"]
        if not self._switcher.is_active(
            run_as=account, base_url=base_url, api_key=api_key, model=default_model
        ):
            if self._switcher.find_cli() is None:
                self._publish(account, _transient("installing"))
                self._log("ai service: installing the cc-switch command line")
                self._switcher.install_cli(
                    switcher.release_entry(platform_keys(self._platform_tuple))
                )
            self._publish(account, _transient("activating"))
            self._log(f"ai service: pointing {account}'s tools at the hub")
            self._switcher.activate(
                base_url=base_url,
                api_key=api_key,
                run_as=account,
                tool_configs=resolved,
            )
        self._store.set_ai_granted(
            account, {"base_url": base_url, "model": default_model}
        )
        return {"state": "installed", "code": "", "params": {}, "is_active": True}

    @staticmethod
    def _resolved_configs(creds: dict, tool_configs: dict) -> dict:
        """The staged choices with the grant's model filling unchosen slots.

        Args:
            creds: The account's grant, whose ``model`` is the prefill
                default.
            tool_configs: The staged per-tool choices.

        Returns:
            ``{tool: {knob: value}}`` ready for the switcher; every Claude
            slot carries a model.
        """
        default_model = str(creds.get("model", ""))
        claude = tool_configs.get("claude", {})
        codex = tool_configs.get("codex", {})
        gemini = tool_configs.get("gemini", {})
        return {
            "claude": {
                slot: str(claude.get(slot, "") or "") or default_model
                for slot in AI_CLAUDE_SLOTS
            },
            "codex": {
                "model": str(codex.get("model", "") or ""),
                "model_reasoning_effort": str(
                    codex.get("model_reasoning_effort", "") or ""
                ),
            },
            "gemini": {"model": str(gemini.get("model", "") or "")},
        }
