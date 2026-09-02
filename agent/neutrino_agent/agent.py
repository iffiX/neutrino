"""The agent itself: connection state, the heartbeat, and the feature engine.

One object owns everything the machine's own page and the gateway both talk
to. It runs whether or not the machine belongs to a gateway yet — an agent
that has never enrolled still serves its page, waiting for a link, which is
the whole point on a machine the gateway cannot reach first.

The gateway stays the source of truth for which features should be on: a
toggle on the local page is sent up with the next heartbeat and comes back as
part of the desired state, so the panel and the page can never disagree for
longer than one beat.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import threading
import time

from neutrino_agent import AGENT_VERSION, enrollment
from neutrino_agent.constants import (
    AGENT_BACKOFF_MAX_S,
    AGENT_BACKOFF_MIN_S,
    AGENT_HEARTBEAT_INTERVAL_S,
    AGENT_HEARTBEAT_PATH,
    AGENT_LEAVE_PATH,
    AGENT_REFUSALS_BEFORE_UNBIND,
    AGENT_RESULT_PATH,
)
from neutrino_agent.features import FeatureManager
from neutrino_agent.http_channel import (
    GatewayHttpChannel,
    GatewayRefused,
    GatewayUnreachable,
)
from neutrino_agent.metrics import HostMetricsReader, hostname
from neutrino_agent.ops import DeviceOperator

# How often an unenrolled agent looks again, which is only to notice that its
# own page has since been used to join a gateway.
IDLE_POLL_INTERVAL_S = 2


class Agent:
    """Everything the agent is, running or waiting to be told where to run."""

    def __init__(self, *, log=print):
        """
        Args:
            log: Callable used for progress messages; defaults to printing,
                which systemd captures into the journal.
        """
        self._log = log
        self._lock = threading.Lock()
        self._metrics = HostMetricsReader()
        # Set whenever there is something new to report, so the loop beats
        # then rather than at the end of its next interval.
        self._news = threading.Event()
        self._features = FeatureManager(log=log, on_change=self._news.set)
        self._backoff_s = AGENT_BACKOFF_MIN_S
        self._last_error = ""
        self._desired: dict = {}
        self._pending: dict = {}
        self._channel = None
        self._operator = None
        self._binding: tuple = ("", "")
        self._binding_stamp = 0
        self._refusals = 0
        self._load_connection()

    # --- what the local page reads ---

    def platform(self) -> dict:
        """This machine's platform tuple."""
        return self._features.platform

    def catalog(self) -> dict:
        """The manifest catalog the gateway last sent."""
        return self._features.catalog()

    def feature_states(self) -> dict:
        """What state each feature is actually in."""
        return self._features.report()

    def desired_features(self) -> dict:
        """What the gateway says should be true, with local toggles applied."""
        with self._lock:
            merged = {name: dict(value) for name, value in self._desired.items()}
            for name, wish in self._pending.items():
                merged.setdefault(name, {"config": {}}).update(wish)
            return merged

    def last_error(self) -> str:
        """The most recent problem worth showing on the page."""
        with self._lock:
            return self._last_error

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
            self._last_error = ""
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
            except GatewayUnreachable as error:
                self._log(f"could not tell the gateway we are leaving: {error}")
        enrollment.disconnect()
        with self._lock:
            self._desired = {}
            self._pending = {}
            self._last_error = ""
        self._load_connection()
        self._features.update(desired={}, catalog=None, catalog_hash="")
        self._log("disconnected from the gateway")

    def beat_soon(self) -> None:
        """Cut the wait before the next heartbeat short."""
        self._news.set()

    def request_feature(
        self,
        name: str,
        *,
        is_enabled: "bool | None" = None,
        is_activated: "bool | None" = None,
    ) -> None:
        """Ask for a feature to be changed, from this machine's own page.

        The request is sent up with the next heartbeat rather than applied
        here, so the hub remains the one place that decides. Either wish can
        be sent alone: having cc-switch and having it point at the hub are
        separate things.

        Args:
            name: The feature name.
            is_enabled: Whether it should be installed, when that is what
                changed.
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
        self._features.update(
            desired=self.desired_features(), catalog=None, catalog_hash=""
        )
        self.beat_soon()

    # --- the loop ---

    def run_forever(self) -> None:
        """Beat, or wait to be enrolled, until the process is stopped.

        The wait between beats ends early when a feature changes state, so
        the panel sees a step start and finish rather than only its result.
        """
        self._log(f"neutrino_agent {AGENT_VERSION} starting on {hostname()}")
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
            "metrics": self._metrics.read().to_dict(),
            "platform": self._features.platform,
            # The gateway sends the catalog only when this differs from what
            # it serves, so a converged fleet is not shipped it every beat.
            "catalog_hash": self._features.catalog_hash,
            "features": self._features.report(),
            "feature_requests": requests,
        }
        try:
            reply = channel.post(AGENT_HEARTBEAT_PATH, payload)
        except GatewayRefused as error:
            return self._on_refused(str(error))
        except GatewayUnreachable as error:
            with self._lock:
                self._last_error = str(error)
                delay = self._backoff_s
                self._backoff_s = min(self._backoff_s * 2, AGENT_BACKOFF_MAX_S)
            self._log(f"heartbeat failed: {error}; retrying in {delay}s")
            return delay

        with self._lock:
            self._backoff_s = AGENT_BACKOFF_MIN_S
            self._last_error = ""
            self._refusals = 0
            # Accepted requests are dropped: what comes back is now the truth.
            for name in requests:
                self._pending.pop(name, None)
            self._desired = reply.get("desired_features", {})

        self._features.update(
            desired=self.desired_features(),
            catalog=reply.get("catalog"),
            catalog_hash=reply.get("catalog_hash", ""),
        )
        for command in reply.get("commands", []):
            self._execute(command)
        return AGENT_HEARTBEAT_INTERVAL_S

    def _on_refused(self, reason: str) -> int:
        """Take a deliberate rejection for what it is, after a short grace.

        The hub authenticates a heartbeat against its own device records, so
        a refusal means this machine was forgotten there or the hub was
        reset. After a few in a row the binding is dropped: retrying with the
        same token can never succeed, and the machine goes back to waiting
        for a link. The local page says why.

        Args:
            reason: What the channel reported.

        Returns:
            Seconds until the next loop turn.
        """
        with self._lock:
            self._refusals += 1
            refusals = self._refusals
            self._last_error = reason
        if refusals < AGENT_REFUSALS_BEFORE_UNBIND:
            self._log(f"{reason}; asking again")
            return AGENT_HEARTBEAT_INTERVAL_S
        enrollment.disconnect()
        with self._lock:
            self._desired = {}
            self._pending = {}
            self._refusals = 0
        self._load_connection()
        with self._lock:
            self._last_error = (
                "the hub no longer knows this machine; paste a new link to rejoin"
            )
        self._features.update(desired={}, catalog=None, catalog_hash="")
        self._log("the hub let this machine go; unbound")
        return IDLE_POLL_INTERVAL_S

    def _load_connection(self) -> None:
        config = enrollment.load_config()
        gateway_url = config.get("gateway_url", "")
        token = config.get("token", "")
        with self._lock:
            self._binding = (gateway_url, token)
            self._binding_stamp = enrollment.config_stamp()
            if gateway_url and token:
                self._channel = GatewayHttpChannel(gateway_url=gateway_url, token=token)
                self._operator = DeviceOperator(gateway_url=gateway_url)
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
            self._last_error = ""
            self._backoff_s = AGENT_BACKOFF_MIN_S
        self._features.update(desired={}, catalog=None, catalog_hash="")
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
        except GatewayUnreachable as error:
            self._log(f"could not report {action} result: {error}")
