"""The agent itself: connection state, the heartbeat, and the module engine.

One object owns everything the machine's own page and the gateway both talk
to. It runs whether or not the machine belongs to a gateway yet — an agent
that has never enrolled still serves its page, waiting for a link, which is
the whole point on a machine the gateway cannot reach first.

The gateway stays the source of truth for which modules should be on: a
toggle on the local page is sent up with the next heartbeat and comes back as
part of the desired state, so the panel and the page can never disagree for
longer than one beat. Services are the other way round: visible and decided
only on the machine, one typed handler per service type.

Errors cross the wire as ``{"code", "params"}``, never an English sentence;
every surface does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import threading

from neutrino_agent import AGENT_VERSION
from neutrino_agent.constants import (
    AGENT_WIRE_GENERATION,
    AGENT_BACKOFF_MAX_S,
    AGENT_BACKOFF_MIN_S,
    AGENT_HEARTBEAT_INTERVAL_S,
    AGENT_HEARTBEAT_PATH,
    AGENT_LEAVE_PATH,
    AGENT_REFUSALS_BEFORE_UNBIND,
    AGENT_RESULT_PATH,
)
from neutrino_agent.core import enrollment, self_update
from neutrino_agent.core.channel import (
    GatewayWireStale,
    GatewayHttpChannel,
    GatewayRefused,
    GatewayUnreachable,
    GatewayUntrusted,
    GatewayVersionRefused,
)
from neutrino_agent.core.commands import DeviceOperator
from neutrino_agent.core.engine import ModuleEngine
from neutrino_agent.core.metrics import HostMetrics, hostname
from neutrino_agent.core.version import parse_version
from neutrino_agent.platforms.base import PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform
from neutrino_agent.services.ai import AiServiceHandler, AiServiceReconciler
from neutrino_agent.services.file import FileServiceHandler
from neutrino_agent.services.port import PortServiceHandler
from neutrino_agent.services.store import MachineServiceStore
from neutrino_agent.services.web import WebServiceHandler

# How often an unenrolled agent looks again, which is only to notice that its
# own page has since been used to join a gateway.
IDLE_POLL_INTERVAL_S = 2


def channel_error(error: Exception) -> dict:
    """The typed form of a channel exception.

    Args:
        error: What the channel raised.

    Returns:
        ``{"code", "params"}``.
    """
    if isinstance(error, GatewayUntrusted):
        return {"code": "hub_untrusted", "params": {}}
    if isinstance(error, GatewayVersionRefused):
        return {
            "code": "agent_newer_than_hub",
            "params": {
                "hub_version": error.hub_version,
                "agent_version": error.agent_version,
            },
        }
    if isinstance(error, GatewayRefused):
        return {"code": "hub_refused", "params": {}}
    return {"code": "hub_unreachable", "params": {"detail": str(error)}}


class Agent:
    """Everything the agent is, running or waiting to be told where to run."""

    def __init__(self, *, log=print, platform=None):
        """
        Args:
            log: Callable used for progress messages; defaults to printing,
                which systemd captures into the journal.
            platform: The machine's platform; None detects it.
        """
        self._log = log
        self._lock = threading.Lock()
        self._platform = platform if platform is not None else detect_platform()
        # Set whenever there is something new to report, so the loop beats
        # then rather than at the end of its next interval.
        self._news = threading.Event()
        self._engine = ModuleEngine(
            platform=self._platform, log=log, on_change=self._news.set
        )
        self._store = MachineServiceStore()
        self._ai = AiServiceReconciler(
            store=self._store,
            platform_tuple=self._engine.platform_tuple,
            log=log,
        )
        self._services = {
            handler.service_type: handler
            for handler in (
                WebServiceHandler(),
                PortServiceHandler(log=log),
                AiServiceHandler(
                    store=self._store,
                    accounts=self._read_accounts,
                    on_change=self._news.set,
                ),
                FileServiceHandler(platform=self._platform, store=self._store, log=log),
            )
        }
        self._backoff_s = AGENT_BACKOFF_MIN_S
        self._last_error: "dict | None" = None
        self._desired: dict = {}
        self._pending: dict = {}
        self._channel = None
        self._operator = None
        self._binding: tuple = ("", "", "")
        self._binding_stamp = 0
        self._refusals = 0
        # The hub version last acted on and how the attempt went, so a target
        # that failed is not retried every beat.
        self._update_target = ""
        self._update_error: "dict | None" = None
        self._load_connection()

    # --- what the local page reads ---

    def platform(self) -> dict:
        """This machine's platform tuple."""
        return self._engine.platform_tuple

    def catalog(self) -> dict:
        """The catalog the gateway last sent: ``{"modules", "services"}``."""
        return self._engine.catalog()

    def service_entries(self) -> list:
        """The typed service list, as the hub last sent it."""
        entries = self.catalog().get("services", [])
        return [entry for entry in entries if isinstance(entry, dict)]

    def module_states(self) -> dict:
        """What state each module is actually in."""
        return self._engine.report()

    def desired_modules(self) -> dict:
        """What the gateway says should be true, with local toggles applied."""
        with self._lock:
            merged = {name: dict(value) for name, value in self._desired.items()}
            for name, wish in self._pending.items():
                merged.setdefault(name, {"config": {}}).update(wish)
            return merged

    def last_error(self) -> "dict | None":
        """The most recent problem worth showing, as ``{"code", "params"}``."""
        with self._lock:
            return self._last_error or self._update_error

    def accounts(self) -> list:
        """The machine's human accounts, by the platform's own judgment."""
        return self._read_accounts()

    def ai_targets(self) -> dict:
        """Which accounts are switched at the hub's gateway."""
        return self._store.ai_targets()

    def ai_states(self) -> dict:
        """Each account's AI service state, as the reconcile last saw it."""
        return self._ai.report()

    def ai_tool_configs(self) -> dict:
        """The per-tool model choices this machine keeps."""
        return self._store.ai_tool_configs()

    def account_home(self, account: str) -> str:
        """One account's home directory, empty when it cannot be resolved."""
        try:
            return self._platform.account_home(account)
        except (KeyError, PlatformUnsupportedError):
            return ""

    def service_states(self) -> dict:
        """Every service type's machine state, merged for the page payload."""
        merged = {}
        for handler in self._services.values():
            merged.update(handler.state())
        return merged

    # --- what the local page does ---

    def connect(self, link: str) -> None:
        """Join the gateway an enrollment link points at.

        Args:
            link: The link the owner pasted.

        Raises:
            EnrollmentError: If the link is unusable or the gateway refuses.
        """
        enrollment.enroll(link)
        with self._lock:
            self._last_error = None
            self._refusals = 0
            self._update_target = ""
            self._update_error = None
            self._backoff_s = AGENT_BACKOFF_MIN_S
        self._load_connection()
        self._log("joined the gateway")

    def disconnect(self) -> None:
        """Leave the gateway, and stop reconciling anything for it.

        The gateway is told first, so its panel stops showing this machine as
        managed straight away rather than waiting for the heartbeats to be
        missed. A gateway that cannot be reached does not hold the machine
        here: the local state is cleared either way.
        """
        with self._lock:
            channel = self._channel
        if channel is not None:
            try:
                channel.post(AGENT_LEAVE_PATH, {})
            except (GatewayUnreachable, GatewayUntrusted) as error:
                self._log(f"could not tell the gateway we are leaving: {error}")
        enrollment.disconnect()
        with self._lock:
            self._desired = {}
            self._pending = {}
            self._last_error = None
            self._update_target = ""
            self._update_error = None
        self._load_connection()
        self._engine.update(desired={}, catalog=None, catalog_hash="")
        self._log("disconnected from the gateway")

    def beat_soon(self) -> None:
        """Cut the wait before the next heartbeat short."""
        self._news.set()

    def request_module(
        self,
        name: str,
        *,
        is_enabled: "bool | None" = None,
        is_activated: "bool | None" = None,
    ) -> None:
        """Ask for a module to be changed, from this machine's own page.

        The request is sent up with the next heartbeat rather than applied
        here, so the hub remains the one place that decides.

        Args:
            name: The module name.
            is_enabled: Whether it should be on, when that is what changed.
            is_activated: Whether it should point at the hub, when that is
                what changed.
        """
        if not name:
            return
        with self._lock:
            wish = dict(self._pending.get(name, {}))
            if is_enabled is not None:
                wish["is_enabled"] = is_enabled
                if not is_enabled:
                    wish["is_activated"] = False
            if is_activated is not None:
                wish["is_activated"] = is_activated
                if is_activated:
                    wish["is_enabled"] = True
            self._pending[name] = wish
        self._engine.update(
            desired=self.desired_modules(), catalog=None, catalog_hash=""
        )
        self.beat_soon()

    def service_action(
        self, service_type: str, *, account: str, is_privileged: bool, body: dict
    ) -> dict:
        """Hand one page action to the handler for its service type.

        Args:
            service_type: The type the page acted on.
            account: The asking account.
            is_privileged: Whether the caller holds the privileged scope.
            body: The action's own fields.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        handler = self._services.get(service_type)
        if handler is None:
            return {"code": "unknown_request", "params": {}}
        return handler.act(
            entries=self.service_entries(),
            account=account,
            is_privileged=is_privileged,
            body=body,
        )

    # --- the loop ---

    def run_forever(self) -> None:
        """Beat, or wait to be enrolled, until the process is stopped.

        The wait between beats ends early when a module changes state, so
        the panel sees a step start and finish rather than only its result.
        The service handlers' own reconciles start here: enabled mounts are
        remounted now and on a timer, which is what brings them back after a
        reboot.
        """
        self._log(f"neutrino_agent {AGENT_VERSION} starting on {hostname()}")
        for handler in self._services.values():
            handler.start()
        while True:
            delay = self.run_once()
            self._news.clear()
            self._news.wait(timeout=delay)

    def run_once(self) -> int:
        """Do one beat's worth of work.

        Returns:
            How many seconds to wait before the next one: the normal interval
            after a success, a backing-off delay after a failure, and a short
            idle poll while the machine belongs to no gateway.
        """
        self._adopt_external_binding()
        with self._lock:
            channel = self._channel
        if channel is None:
            return IDLE_POLL_INTERVAL_S

        with self._lock:
            requests = dict(self._pending)
        payload = {
            "hostname": hostname(),
            "client_version": AGENT_VERSION,
            "wire": AGENT_WIRE_GENERATION,
            "metrics": self._read_metrics(),
            "platform": self._engine.platform_tuple,
            "accounts": self._read_accounts(),
            # The gateway sends the catalog only when this differs from what
            # it serves, so a converged fleet is not shipped it every beat.
            "catalog_hash": self._engine.catalog_hash,
            "modules": self._engine.report(),
            "module_requests": requests,
            "ai_targets": self._store.ai_targets(),
            "last_error": self.last_error(),
        }
        try:
            reply = channel.post(AGENT_HEARTBEAT_PATH, payload)
        except GatewayWireStale as error:
            # An answer about this build, not about the binding: the fix is
            # the hub's own package, so it never counts toward an unbind.
            with self._lock:
                self._last_error = {
                    "code": "agent_wire_stale",
                    "params": {
                        "hub_wire": error.hub_wire,
                        "agent_wire": error.agent_wire,
                    },
                }
            self._log(f"{error}")
            self._force_self_update(f"wire-{error.hub_wire}")
            return AGENT_HEARTBEAT_INTERVAL_S
        except (GatewayRefused, GatewayUntrusted, GatewayVersionRefused) as error:
            return self._on_rejected(error)
        except GatewayUnreachable as error:
            # A broken wire is not an answer: back off and retry forever.
            # The one non-obvious rule of the rejection counter applies here:
            # only a successful beat resets it, so an unreachable beat in the
            # middle of a run of rejections leaves the count standing.
            with self._lock:
                self._last_error = channel_error(error)
                delay = self._backoff_s
                self._backoff_s = min(self._backoff_s * 2, AGENT_BACKOFF_MAX_S)
            self._log(f"heartbeat failed: {error}; retrying in {delay}s")
            return delay

        with self._lock:
            self._backoff_s = AGENT_BACKOFF_MIN_S
            self._last_error = None
            self._refusals = 0
            # Accepted requests are dropped: what comes back is now the truth.
            for name in requests:
                self._pending.pop(name, None)

        # A reply this build cannot read must never take the process down:
        # the service stays up, says so, and asks again — a crash here is a
        # machine nobody can reach to fix.
        try:
            with self._lock:
                self._desired = dict(reply.get("desired_modules") or {})
            self._engine.update(
                desired=self.desired_modules(),
                catalog=reply.get("catalog"),
                catalog_hash=str(reply.get("catalog_hash", "")),
            )
            self._ai.update(
                entry=self._ai_entry(),
                accounts=self._read_accounts(),
                credentials=reply.get("ai_accounts") or {},
            )
            for command in reply.get("commands", []):
                self._execute(command)
        except Exception as error:  # noqa: BLE001 - reported, never fatal
            with self._lock:
                self._last_error = {
                    "code": "hub_reply_unreadable",
                    "params": {"detail": str(error)[:200]},
                }
            self._log(f"could not apply the hub's reply: {error}")
            return AGENT_HEARTBEAT_INTERVAL_S
        self._maybe_self_update(str(reply.get("hub_version", "")))
        return AGENT_HEARTBEAT_INTERVAL_S

    def _read_metrics(self) -> dict:
        try:
            return self._platform.read_host_metrics().to_dict()
        except PlatformUnsupportedError:
            return HostMetrics().to_dict()

    def _read_accounts(self) -> list:
        try:
            return self._platform.human_accounts()
        except PlatformUnsupportedError:
            return []

    def _ai_entry(self) -> dict:
        """The service list's ai entry, empty when the hub publishes none."""
        for entry in self.service_entries():
            if entry.get("type") == "ai":
                return entry
        return {}

    def _on_rejected(self, error: Exception) -> int:
        """Take a definitive rejection for what it is, after a short grace.

        A rejection is an answer, not an outage: the hub — or whatever stands
        where it stood — said no, and retrying the same binding cannot make
        it a yes. One counter covers every kind; after a few in a row the
        binding is dropped and the machine goes back to waiting for a link,
        with the local page saying which no it heard.

        Args:
            error: What the channel raised.

        Returns:
            Seconds until the next loop turn.
        """
        rejection = channel_error(error)
        with self._lock:
            self._refusals += 1
            rejections = self._refusals
            self._last_error = rejection
        if rejections < AGENT_REFUSALS_BEFORE_UNBIND:
            self._log(f"{error}; asking again")
            return AGENT_HEARTBEAT_INTERVAL_S
        enrollment.disconnect()
        with self._lock:
            self._desired = {}
            self._pending = {}
            self._refusals = 0
            self._update_target = ""
            self._update_error = None
        self._load_connection()
        with self._lock:
            self._last_error = {
                "code": "self_unbound",
                "params": {"cause": rejection["code"]},
            }
        self._engine.update(desired={}, catalog=None, catalog_hash="")
        self._log(f"unbound: {rejection['code']}")
        return IDLE_POLL_INTERVAL_S

    def _load_connection(self) -> None:
        config = enrollment.load_config()
        gateway_url = config.get("gateway_url", "")
        token = config.get("token", "")
        fingerprint = config.get("fingerprint", "")
        with self._lock:
            self._binding = (gateway_url, token, fingerprint)
            self._binding_stamp = enrollment.config_stamp()
            if gateway_url and token:
                self._channel = GatewayHttpChannel(
                    gateway_url=gateway_url, token=token, fingerprint=fingerprint
                )
                self._operator = DeviceOperator(platform=self._platform)
            else:
                self._channel = None
                self._operator = None

    def _adopt_external_binding(self) -> None:
        """Pick up a binding another process wrote.

        ``nagent connect`` and ``nagent disconnect`` edit the configuration
        from their own process. The service notices the file changing and
        converges, so leaving the hub takes no restart and never goes on
        beating with a token the hub already dropped.
        """
        with self._lock:
            if enrollment.config_stamp() == self._binding_stamp:
                return
            binding = self._binding
        self._load_connection()
        with self._lock:
            if self._binding == binding:
                return
            self._desired = {}
            self._pending = {}
            self._last_error = None
            self._refusals = 0
            self._update_target = ""
            self._update_error = None
            self._backoff_s = AGENT_BACKOFF_MIN_S
        self._engine.update(desired={}, catalog=None, catalog_hash="")
        self._log("adopted the binding written on disk")

    def _execute(self, command: dict) -> None:
        with self._lock:
            channel = self._channel
            operator = self._operator
        if channel is None or operator is None:
            return
        action = command.get("action", "")
        command_id = command.get("id", action)
        self._log(f"running {action}")
        outcome = operator.run(action, command.get("args", {}))
        try:
            channel.post(
                AGENT_RESULT_PATH,
                {
                    "id": command_id,
                    "exit_code": outcome.exit_code,
                    "output": outcome.output,
                },
            )
        except (GatewayUnreachable, GatewayUntrusted) as error:
            self._log(f"could not report {action} result: {error}")

    def _force_self_update(self, target: str) -> None:
        """Reinstall this agent from the hub's package, version equal or not.

        The wire-stale answer means this build misreads the hub however the
        versions compare, so the version gate does not apply; the target
        latch still does, so a failed attempt is not retried every beat.

        Args:
            target: A name for what asked, latched like a version target.
        """
        with self._lock:
            if target == self._update_target:
                return
            self._update_target = target
            self._update_error = None
            channel = self._channel
        if channel is None:
            return
        kind = self_update.package_kind(self._engine.platform_tuple)
        if not kind:
            self._log("no reinstall: no package for this platform")
            return
        self._log("reinstalling from the hub's package")
        try:
            self_update.run_update(channel, kind=kind)
        except (
            self_update.SelfUpdateError,
            GatewayRefused,
            GatewayUnreachable,
            GatewayUntrusted,
            GatewayWireStale,
        ) as error:
            code = (
                str(error)
                if isinstance(error, self_update.SelfUpdateError)
                else "agent_update_fetch_failed"
            )
            with self._lock:
                self._update_error = {"code": code, "params": {"target": target}}
            self._log(f"reinstall failed: {error}")

    def _maybe_self_update(self, hub_version: str) -> None:
        """Update this agent when the hub runs a later release, once per target.

        The hub and the agent share a version, so a heartbeat reply naming a
        later ``hub_version`` means this machine's package is behind. The
        install is launched detached and restarts the agent's own service; a
        target that failed is remembered and not retried until the hub
        reports a different one.

        Args:
            hub_version: What the heartbeat reply named.
        """
        with self._lock:
            if not hub_version or hub_version == self._update_target:
                return
            self._update_target = hub_version
            self._update_error = None
            channel = self._channel
        hub = parse_version(hub_version)
        agent = parse_version(AGENT_VERSION)
        if hub is None or agent is None:
            self._log(f"no self-update: cannot order {AGENT_VERSION} and {hub_version}")
            return
        if agent >= hub or channel is None:
            return
        kind = self_update.package_kind(self._engine.platform_tuple)
        if not kind:
            self._log(f"no self-update to {hub_version}: no package for this platform")
            return
        self._log(f"updating to {hub_version}")
        try:
            self_update.run_update(channel, kind=kind)
        except (
            self_update.SelfUpdateError,
            GatewayRefused,
            GatewayUnreachable,
            GatewayUntrusted,
        ) as error:
            code = (
                str(error)
                if isinstance(error, self_update.SelfUpdateError)
                else channel_error(error)["code"]
            )
            with self._lock:
                self._update_error = {"code": code, "params": {"target": hub_version}}
            self._log(f"self-update to {hub_version} failed: {error}")
            return
        self._log(f"self-update to {hub_version} launched; the service restarts")
