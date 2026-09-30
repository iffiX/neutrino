"""The ai service type: pointing this person's AI tools at the exit hub's gateway.

The page stages one Enabled toggle and per-tool model choices, and Apply
commits them here in one step: the tools are pointed at once the exit hub
has answered its ``ai`` entry's ``service`` stream with a credential. The
store keeps the model choices only; whether the tools point at a hub, and
which hub and endpoint the last activation granted, are this run's own and
go with it.

The staged choices are what each tool is pointed with; the grant's ``model``
is only the prefill default for a slot nobody has chosen. A change of exit
is one activation at the new hub, never a deactivation first. Deactivation
uses the endpoint activation recorded, because by then the hub may no
longer name it.

A run that ended without putting the tools back leaves cc-switch standing on
the hub and an adopt record beside it; :meth:`AiServiceHandler.clear_leftovers`
is what the resident calls at start to undo that.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import os
import threading

from neutrino_client.exceptions import (
    GatewayUnreachable,
    GatewayUntrusted,
    ToolSwitchError,
)
from neutrino_client.services import switcher
from neutrino_client.services.base import ServiceTypeHandler, channel_refusal
from neutrino_client.services.worker import IF_BUSY_KEEP_ONE, ServiceWorker

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


def resolved_configs(credential: dict, tool_configs: dict) -> dict:
    """The staged choices with the grant's model filling unchosen slots.

    Args:
        credential: The grant, whose ``model`` is the prefill default.
        tool_configs: The staged per-tool choices.

    Returns:
        ``{tool: {knob: value}}`` ready for the switcher; every Claude slot
        carries a model.
    """
    default_model = str(credential.get("model", ""))
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


# The one step the AI lane runs, in the page's vocabulary.
AI_STEP_SWITCHING = "switching"


def ai_entry_id(entries: list, hub_id: str) -> str:
    """The id of the AI gateway entry one hub publishes.

    Args:
        entries: The merged service list, each entry stamped with ``hub_id``.
        hub_id: The hub whose entry is wanted.

    Returns:
        That hub's first ``ai`` entry's id, empty when it publishes none.
    """
    for entry in entries or []:
        if (
            isinstance(entry, dict)
            and entry.get("type") == "ai"
            and entry.get("hub_id") == hub_id
        ):
            return str(entry.get("id", "") or "")
    return ""


def _nobody() -> None:
    """Nobody listening for changes."""


class AiServiceHandler(ServiceTypeHandler):
    """Commits the page's AI apply and keeps the tools converged on it."""

    service_type = "ai"

    def __init__(
        self,
        *,
        store,
        original_dir,
        open_service,
        exit_hub_id,
        log=print,
        switcher_module=None,
        on_change=None,
        start_thread=None,
    ):
        """
        Args:
            store: The :class:`~neutrino_client.services.store.ClientServiceStore`.
            original_dir: Where the switcher keeps its adopt records.
            open_service: Callable ``(hub_id, entry_id) -> dict`` opening
                the entry's ``service`` stream on that hub and returning its
                close's params, the credential ``{"base_url", "api_key",
                "model"}``; raises the channel's exceptions.
            exit_hub_id: Callable ``() -> str`` naming the hub whose
                gateway the tools point at, empty when there is none.
            log: Callable used for progress messages.
            switcher_module: The switcher to drive; None uses the real one.
            on_change: Called after every change of standing; None for
                nobody listening.
            start_thread: The lane's thread starter; None uses a daemon
                thread.
        """
        self._store = store
        self._original_dir = original_dir
        self._open_service = open_service
        self._exit_hub_id = exit_hub_id
        self._log = log
        self._switcher = switcher_module if switcher_module is not None else switcher
        self._lock = threading.Lock()
        # The exit hub and its ai entry, as of the last apply or refresh.
        self._hub_id = ""
        self._entry_id = ""
        self._is_enabled = False
        # What the last activation pointed the tools at: hub_id, base_url
        # and the default model.
        self._granted: dict = {}
        self._status: dict = self._steady(is_active=False)
        self._on_change = on_change if on_change is not None else _nobody
        self._worker = ServiceWorker(
            name="ai", on_change=self._on_change, log=log, start_thread=start_thread
        )

    def act(self, *, entries: list, body: dict):
        """Commit one apply: the toggle and the tool configs together.

        Args:
            entries: The merged service list.
            body: ``{"is_enabled": bool, "tool_configs": {...}}``; the hub
                acted on is the exit hub.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        if "is_enabled" not in body:
            return {"code": "unknown_request", "params": {}}
        if self._worker.is_working:
            return self._worker.submit(AI_STEP_SWITCHING, self.reconcile)
        tool_configs = body.get("tool_configs")
        if isinstance(tool_configs, dict):
            self._store.set_ai_tool_configs(clean_tool_configs(tool_configs))
        self._aim(entries)
        with self._lock:
            self._is_enabled = bool(body.get("is_enabled"))
        return self._worker.submit(AI_STEP_SWITCHING, self.reconcile)

    def state(self) -> dict:
        """This person's AI standing, for the state payload.

        Returns:
            ``{"ai": {"is_enabled", "is_active", "state", "code",
            "params"}, "ai_tool_configs": {...}}``.
        """
        with self._lock:
            status = dict(self._status)
            status["is_enabled"] = self._is_enabled
        status["work"] = self._worker.status()
        return {"ai": status, "ai_tool_configs": self._store.ai_tool_configs()}

    def refresh(self, *, entries: list) -> None:
        """Converge on what the exit hub grants now, after a state changed.

        Args:
            entries: The merged service list.
        """
        self._aim(entries)
        # The hub's word is never dropped: a lane at work runs it next.
        self._worker.submit(AI_STEP_SWITCHING, self.reconcile, if_busy=IF_BUSY_KEEP_ONE)

    def reconcile(self) -> None:
        """Point the tools where the choice says, once, and record it."""
        with self._lock:
            hub_id = self._hub_id
            entry_id = self._entry_id
            is_enabled = self._is_enabled
        try:
            if is_enabled:
                status = self._activate(hub_id, entry_id)
            else:
                status = self._deactivate()
        except ToolSwitchError as error:
            status = self._failure("switch_failed", error)
        except Exception as error:  # noqa: BLE001 - reported, not raised
            status = self._failure("reconcile_failed", error)
        with self._lock:
            self._status = status
        self._on_change()

    def restore(self) -> None:
        """Put the tools back the way activation found them.

        Raises:
            ToolSwitchError: If cc-switch refuses to put a tool back; the
                tools then still point at the hub.
        """
        with self._lock:
            granted = dict(self._granted)
        if not granted:
            return
        self._log("ai service: pointing the tools away from the hub")
        self._switcher.deactivate(base_url=granted.get("base_url", ""))
        with self._lock:
            self._granted = {}
            self._status = self._steady(is_active=False)

    def release(self) -> int:
        """Restore the tools; the toggle this run holds is kept.

        Returns:
            Zero: the tools are one thing, put back or already back.

        Raises:
            ToolSwitchError: If cc-switch refuses to put a tool back.
        """
        self.restore()
        return 0

    def release_hub(self, hub_id: str) -> int:
        """Restore the tools when they point at one hub; the toggle is kept.

        While the toggle is on and another hub is the exit, the tools are
        left standing: the refresh that follows moves them there in one
        activation.

        Args:
            hub_id: The hub let go of.

        Returns:
            Zero: the tools are one thing, put back or already back.

        Raises:
            ToolSwitchError: If cc-switch refuses to put a tool back.
        """
        with self._lock:
            is_pointed_there = self._granted.get("hub_id") == hub_id
            is_enabled = self._is_enabled
        if not is_pointed_there:
            return 0
        if is_enabled and str(self._exit_hub_id() or "") not in ("", hub_id):
            return 0
        self.restore()
        return 0

    def clear_leftovers(self) -> None:
        """Put the tools back when an earlier run did not.

        Raises:
            ToolSwitchError: If cc-switch refuses to put a tool back.
        """
        if not self._is_left_over():
            return
        self._switcher.deactivate()
        self._log("ai service: put the tools back after an unclean exit")

    def _is_left_over(self) -> bool:
        """Whether a tool still stands on the hub, or a record was kept."""
        try:
            if os.listdir(self._original_dir):
                return True
        except OSError:
            pass
        if self._switcher.find_cli() is None:
            return False
        for app in switcher.SWITCHER_APPS:
            if self._switcher.is_active_for(app):
                return True
        return False

    def _aim(self, entries: list) -> None:
        """Take the exit hub and its ai entry from the merged list."""
        hub_id = str(self._exit_hub_id() or "")
        with self._lock:
            self._hub_id = hub_id
            self._entry_id = ai_entry_id(entries, hub_id)

    def _activate(self, hub_id: str, entry_id: str) -> dict:
        if not entry_id:
            return self._no_endpoint()
        try:
            credential = self._open_service(hub_id, entry_id)
        except (GatewayUntrusted, GatewayUnreachable) as error:
            return dict(
                channel_refusal(error), state=self._steady_state(), is_active=False
            )
        base_url = str(credential.get("base_url", ""))
        api_key = str(credential.get("api_key", ""))
        if not base_url or not api_key:
            return self._no_endpoint()
        resolved = resolved_configs(credential, self._store.ai_tool_configs())
        default_model = resolved["claude"]["default"]
        if self._switcher.find_cli() is None:
            return {
                "state": "absent",
                "code": "bundle_missing",
                "params": {"binary": "cc-switch"},
                "is_active": False,
            }
        # Every tool is looked at each time: one whose provider must change
        # is switched, the others are left as they stand.
        switched = self._switcher.activate(
            base_url=base_url, api_key=api_key, tool_configs=resolved
        )
        if switched:
            self._log(f"ai service: pointed {switched} at the hub")
        with self._lock:
            self._granted = {
                "hub_id": hub_id,
                "base_url": base_url,
                "model": default_model,
            }
        return {"state": "installed", "code": "", "params": {}, "is_active": True}

    def _deactivate(self) -> dict:
        with self._lock:
            granted = dict(self._granted)
        if granted:
            self._log("ai service: pointing the tools away from the hub")
            self._switcher.deactivate(base_url=granted.get("base_url", ""))
            with self._lock:
                self._granted = {}
        return self._steady(is_active=False)

    def _no_endpoint(self) -> dict:
        return {
            "state": self._steady_state(),
            "code": "no_endpoint",
            "params": {},
            "is_active": False,
        }

    def _steady(self, *, is_active: bool) -> dict:
        return {
            "state": self._steady_state(),
            "code": "",
            "params": {},
            "is_active": is_active,
        }

    def _steady_state(self) -> str:
        return "installed" if self._switcher.is_installed() else "absent"

    @staticmethod
    def _failure(code: str, error: Exception) -> dict:
        return {
            "state": "failed",
            "code": code,
            "params": {"detail": str(error)[:200]},
            "is_active": False,
        }
