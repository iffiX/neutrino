"""The ai service type: pointing this person's AI tools at the hub's gateway.

The page stages one Enabled toggle and per-tool model choices, and Apply
commits them here in one step: the choice lands in the store and the tools
are pointed at once when the poll reply has granted a credential. The store
keeps only the choice and the last-granted endpoint; the key itself arrives
fresh in every poll reply and is held in memory.

The staged choices are what each tool is pointed with; the grant's ``model``
is only the prefill default for a slot nobody has chosen. Deactivation uses
the endpoint activation recorded, because by then the hub may no longer name
it.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import threading

from neutrino_client.exceptions import ToolSwitchError
from neutrino_client.services import switcher
from neutrino_client.services.worker import IF_BUSY_KEEP_ONE, ServiceWorker
from neutrino_client.services.base import ServiceTypeHandler

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


def _nobody() -> None:
    """Nobody listening for changes."""


class AiServiceHandler(ServiceTypeHandler):
    """Commits the page's AI apply and keeps the tools converged on it."""

    service_type = "ai"

    def __init__(
        self,
        *,
        store,
        log=print,
        switcher_module=None,
        on_change=None,
        start_thread=None,
    ):
        """
        Args:
            store: The :class:`~neutrino_client.services.store.ClientServiceStore`.
            log: Callable used for progress messages.
            switcher_module: The switcher to drive; None uses the real one.
            on_change: Called after every change of standing; None for
                nobody listening.
            start_thread: The lane's thread starter; None uses a daemon
                thread.
        """
        self._store = store
        self._log = log
        self._switcher = switcher_module if switcher_module is not None else switcher
        self._lock = threading.Lock()
        self._credential: dict = {}
        self._status: dict = self._steady(is_active=False)
        self._on_change = on_change if on_change is not None else _nobody
        self._worker = ServiceWorker(
            name="ai", on_change=self._on_change, log=log, start_thread=start_thread
        )

    def act(self, *, entries: list, body: dict):
        """Commit one apply: the toggle and the tool configs together.

        Args:
            entries: The catalog's service list.
            body: ``{"is_enabled": bool, "tool_configs": {...}}``.

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
        self._store.set_ai_enabled(bool(body.get("is_enabled")))
        return self._worker.submit(AI_STEP_SWITCHING, self.reconcile)

    def state(self) -> dict:
        """This person's AI standing, for the state payload.

        Returns:
            ``{"ai": {"is_enabled", "is_active", "state", "code",
            "params"}, "ai_tool_configs": {...}}``.
        """
        with self._lock:
            status = dict(self._status)
        status["is_enabled"] = self._store.is_ai_enabled()
        status["work"] = self._worker.status()
        return {"ai": status, "ai_tool_configs": self._store.ai_tool_configs()}

    def update_credential(self, credential: "dict | None") -> None:
        """Take the poll reply's grant and converge on it.

        Args:
            credential: ``{"base_url", "api_key", "model"}``, or None when
                the hub granted nothing this turn.
        """
        with self._lock:
            self._credential = dict(credential) if isinstance(credential, dict) else {}
        # The hub's word is never dropped: a lane at work runs it next.
        self._worker.submit(AI_STEP_SWITCHING, self.reconcile, if_busy=IF_BUSY_KEEP_ONE)

    def reconcile(self) -> None:
        """Point the tools where the choice says, once, and record it."""
        with self._lock:
            credential = dict(self._credential)
        try:
            if self._store.is_ai_enabled():
                status = self._activate(credential)
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
        """Put the tools back the way activation found them."""
        granted = self._store.ai_granted()
        if not granted:
            return
        self._log("ai service: pointing the tools away from the hub")
        try:
            self._switcher.deactivate(base_url=granted.get("base_url", ""))
        except Exception as error:  # noqa: BLE001 - reported, not raised
            self._log(f"ai service: could not restore the tools: {error}")
            return
        self._store.clear_ai_granted()
        with self._lock:
            self._status = self._steady(is_active=False)

    def release(self) -> None:
        """Restore the tools; the enabled choice itself is kept."""
        self.restore()

    def _activate(self, credential: dict) -> dict:
        base_url = str(credential.get("base_url", ""))
        api_key = str(credential.get("api_key", ""))
        if not base_url or not api_key:
            return {
                "state": "installed" if self._switcher.is_installed() else "absent",
                "code": "no_endpoint",
                "params": {},
                "is_active": False,
            }
        resolved = resolved_configs(credential, self._store.ai_tool_configs())
        default_model = resolved["claude"]["default"]
        if not self._switcher.is_active(
            base_url=base_url, api_key=api_key, model=default_model
        ):
            if self._switcher.find_cli() is None:
                return {
                    "state": "absent",
                    "code": "bundle_missing",
                    "params": {"binary": "cc-switch"},
                    "is_active": False,
                }
            self._log("ai service: pointing the tools at the hub")
            self._switcher.activate(
                base_url=base_url, api_key=api_key, tool_configs=resolved
            )
        self._store.set_ai_granted({"base_url": base_url, "model": default_model})
        return {"state": "installed", "code": "", "params": {}, "is_active": True}

    def _deactivate(self) -> dict:
        granted = self._store.ai_granted()
        if granted:
            self._log("ai service: pointing the tools away from the hub")
            self._switcher.deactivate(base_url=granted.get("base_url", ""))
            self._store.clear_ai_granted()
        return self._steady(is_active=False)

    def _steady(self, *, is_active: bool) -> dict:
        return {
            "state": "installed" if self._switcher.is_installed() else "absent",
            "code": "",
            "params": {},
            "is_active": is_active,
        }

    @staticmethod
    def _failure(code: str, error: Exception) -> dict:
        return {
            "state": "failed",
            "code": code,
            "params": {"detail": str(error)[:200]},
            "is_active": False,
        }
