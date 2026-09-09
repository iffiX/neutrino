"""The agent itself: the binding, the socket to the hub, and the module engine.

One object owns everything the local control channel and the hub both talk
to. It runs whether or not the machine belongs to a hub yet: an agent that
has never enrolled still answers locally, waiting for a link.

While bound, the agent keeps one socket open to the hub and reconnects when
it drops. The hub decides everything about modules: an order arrives as a
stream on the socket, runs here, and closes with how it went. The desktop
share is the other way round: decided only on the machine, and reported
upward.

Errors cross the wire as ``{"code", "params"}``, never an English sentence;
every surface does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hashlib
import os
import threading
import urllib.parse

from neutrino_agent import AGENT_VERSION
from neutrino_agent.constants import (
    AGENT_BACKOFF_MAX_S,
    AGENT_BACKOFF_MIN_S,
    AGENT_CREDENTIALS_DIR_NAME,
    AGENT_DESIRED_STATE_NAME,
    AGENT_HEARTBEAT_INTERVAL_S,
    AGENT_LEAVE_PATH,
    AGENT_MODULE_PACKAGE_PATH,
    AGENT_REFUSALS_BEFORE_UNBIND,
    AGENT_STATE_NAME,
    AGENT_WIRE_GENERATION,
    AGENT_WS_PATH,
)
from neutrino_agent.core import enrollment, self_update
from neutrino_agent.core.channel import (
    GatewayHttpChannel,
    GatewayRefused,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
    GatewayVersionRefused,
    GatewayWireStale,
)
from neutrino_agent.core.commands import DeviceOperator
from neutrino_agent.core.desired_state import DesiredStateApplier, DesiredStateStore
from neutrino_agent.core.engine import ModuleEngine
from neutrino_agent.core.metrics import HostMetrics, hostname
from neutrino_agent.core.session import AgentSession
from neutrino_agent.core.store import MachineStateStore
from neutrino_agent.core.version import parse_version
from neutrino_agent.core.ws_client import WebSocketClient
from neutrino_agent.modules.base import ModuleApplyError
from neutrino_agent.platforms.base import PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform
from neutrino_agent.rdp.host import RdpShareHost

# How often an unenrolled agent looks again, which is only to notice that its
# binding file has since been written.
IDLE_POLL_INTERVAL_S = 2


def _sha256_file(path: str) -> str:
    """The SHA-256 of a file on disk.

    Args:
        path: The file.

    Returns:
        Its digest, or empty when it cannot be read.
    """
    try:
        with open(path, "rb") as stream:
            return hashlib.sha256(stream.read()).hexdigest()
    except OSError:
        return ""


def channel_error(error: Exception) -> dict:
    """The typed form of a channel exception.

    Args:
        error: What the channel raised.

    Returns:
        ``{"code", "params"}``.
    """
    if isinstance(error, GatewayRefusedDetail):
        return {"code": error.code, "params": dict(error.params)}
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
    if isinstance(error, GatewayWireStale):
        return {
            "code": "agent_wire_stale",
            "params": {"hub_wire": error.hub_wire, "agent_wire": error.agent_wire},
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
        # Set whenever there is something new to report, so a report goes up
        # then rather than at the end of the interval.
        self._news = threading.Event()
        self._engine = ModuleEngine(
            fetch_artifact=self._fetch_artifact,
            platform=self._platform,
            log=log,
            on_change=self._news.set,
        )
        # The store and the access password live under the platform's own
        # data root, and so does the last desired state taken from the hub.
        data_dir = self._platform.agent_data_dir()
        self._data_dir = data_dir
        self._store = MachineStateStore(path=os.path.join(data_dir, AGENT_STATE_NAME))
        self._desired = DesiredStateApplier(
            engine=self._engine,
            runners=self._engine.module_runners,
            store=DesiredStateStore(
                path=os.path.join(data_dir, AGENT_DESIRED_STATE_NAME)
            ),
            log=log,
        )
        self._rdp = RdpShareHost(
            platform=self._platform,
            store=self._store,
            credentials_dir=os.path.join(data_dir, AGENT_CREDENTIALS_DIR_NAME),
            log=log,
        )
        # The share flow refuses before it configures anything when RustDesk
        # is not on the machine, which is what the engine's report answers.
        self._rdp.bind_modules(self._engine.report)
        self._backoff_s = AGENT_BACKOFF_MIN_S
        self._last_error: "dict | None" = None
        self._channel = None
        self._operator = None
        self._session: "AgentSession | None" = None
        self._binding: tuple = ("", "", "")
        self._binding_stamp = 0
        self._refusals = 0
        # The hub version last acted on and how the attempt went, so a target
        # that failed is not retried on every connection.
        self._update_target = ""
        self._update_error: "dict | None" = None
        self._load_connection()

    # --- what the control channel reads ---

    def platform(self) -> dict:
        """This machine's platform tuple."""
        return self._engine.platform_tuple

    def catalog(self) -> dict:
        """The catalog this machine holds: ``{"modules"}``."""
        return self._engine.catalog()

    def module_states(self) -> dict:
        """What state each module is actually in."""
        return self._engine.report()

    def last_error(self) -> "dict | None":
        """The most recent problem worth showing, as ``{"code", "params"}``."""
        with self._lock:
            return self._last_error or self._update_error

    def is_online(self) -> bool:
        """Whether the socket to the hub is up."""
        with self._lock:
            session = self._session
        return session is not None and session.is_open

    def accounts(self) -> list:
        """The machine's human accounts, by the platform's own judgment."""
        return self._read_accounts()

    def rdp_state(self) -> dict:
        """Where this machine's own desktop share stands."""
        return self._rdp.state()

    def rdp_declaration(self) -> dict:
        """What this machine says upward about sharing its desktop.

        Returns:
            ``{"is_shared", "account", "share_id", "port", "attention"}``.
        """
        return self._rdp.declaration()

    # --- what the control channel asks for ---

    def connect(self, link: str) -> None:
        """Join the hub an enrollment link points at.

        Args:
            link: The link the owner pasted.

        Raises:
            EnrollmentError: If the link is unusable or the hub refuses.
        """
        enrollment.enroll(link)
        self._drop_session()
        with self._lock:
            self._last_error = None
            self._refusals = 0
            self._update_target = ""
            self._update_error = None
            self._backoff_s = AGENT_BACKOFF_MIN_S
        self._load_connection()
        self._news.set()
        self._log("joined the hub")

    def disconnect(self) -> None:
        """Leave the hub, and stop reporting to it.

        The hub is told first, so its panel stops showing this machine as
        managed straight away. A hub that cannot be reached does not hold
        the machine here: the local state is cleared either way.
        """
        with self._lock:
            channel = self._channel
        if channel is not None:
            try:
                channel.post(AGENT_LEAVE_PATH, {})
            except (GatewayUnreachable, GatewayUntrusted) as error:
                self._log(f"could not tell the hub we are leaving: {error}")
        self._drop_session()
        enrollment.disconnect()
        with self._lock:
            self._last_error = None
            self._update_target = ""
            self._update_error = None
        self._load_connection()
        self._engine.update(catalog=None, catalog_hash="")
        self._log("disconnected from the hub")

    def report_soon(self) -> None:
        """Send the next report now rather than at the end of the interval."""
        self._news.set()

    def sync(self) -> dict:
        """Ask the hub for this machine's desired state.

        Returns:
            Empty when the request went up, ``{"code", "params"}`` when
            there is no live socket to send it on.
        """
        with self._lock:
            session = self._session
        if session is None or not session.is_open:
            return {"code": "hub_unreachable", "params": {}}
        try:
            session.request_state()
        except GatewayUnreachable:
            return {"code": "hub_unreachable", "params": {}}
        return {}

    def rdp_share(self, *, account: str, password: str) -> dict:
        """Share this machine's desktop behind an access password.

        Args:
            account: The account sitting at the machine's screen.
            password: The access password a peer connects with.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        outcome = self._rdp.share(account, password)
        self._news.set()
        return outcome

    def rdp_unshare(self) -> dict:
        """Stop sharing this machine's desktop.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        outcome = self._rdp.unshare()
        self._news.set()
        return outcome

    # --- the loop ---

    def run_forever(self) -> None:
        """Hold the socket, or wait to be enrolled, until the process stops."""
        self._log(f"neutrino_agent {AGENT_VERSION} starting on {hostname()}")
        while True:
            delay = self.run_once()
            self._news.clear()
            self._news.wait(timeout=delay)

    def run_once(self) -> int:
        """One connection's lifetime, or one idle poll while unbound.

        Returns:
            How many seconds to wait before the next one: the interval
            after a refusal, a backing-off delay after a failure, and a
            short idle poll while the machine belongs to no hub.
        """
        self._adopt_external_binding()
        session = self._open_session()
        if session is None:
            return IDLE_POLL_INTERVAL_S
        try:
            session.connect()
        except GatewayWireStale as error:
            return self._on_wire_stale(error)
        except (GatewayRefused, GatewayUntrusted, GatewayVersionRefused) as error:
            return self._on_rejected(error)
        except GatewayUnreachable as error:
            return self._on_unreachable(error)
        with self._lock:
            self._session = session
            self._backoff_s = AGENT_BACKOFF_MIN_S
            self._last_error = None
            self._refusals = 0
        self._maybe_self_update(session.hub_version)
        failure = session.serve()
        with self._lock:
            if self._session is session:
                self._session = None
        if failure is None:
            return AGENT_BACKOFF_MIN_S
        if isinstance(failure, GatewayWireStale):
            return self._on_wire_stale(failure)
        if isinstance(failure, (GatewayRefused, GatewayVersionRefused)):
            return self._on_rejected(failure)
        return self._on_unreachable(failure)

    def probe(self) -> None:
        """Connect once, take the welcome, and close: the status check.

        The outcome lands in :meth:`last_error`, empty when the hub
        answered.
        """
        self._adopt_external_binding()
        session = self._open_session()
        if session is None:
            return
        try:
            session.connect()
        except GatewayWireStale as error:
            with self._lock:
                self._last_error = channel_error(error)
            return
        except (
            GatewayRefused,
            GatewayUntrusted,
            GatewayVersionRefused,
            GatewayUnreachable,
        ) as error:
            with self._lock:
                self._last_error = channel_error(error)
            return
        with self._lock:
            self._last_error = None
        session.close()

    def _open_session(self) -> "AgentSession | None":
        """A session for the current binding, or None while unbound."""
        with self._lock:
            gateway_url, token, fingerprint = self._binding
        if not gateway_url or not token:
            return None
        parts = urllib.parse.urlsplit(gateway_url)
        client = WebSocketClient(
            host=parts.hostname or "",
            port=parts.port or 443,
            path=AGENT_WS_PATH,
            fingerprint=fingerprint,
        )
        return AgentSession(
            client=client,
            token=token,
            hello=self._hello_payload(),
            report=self._report_payload,
            run_order=self._run_order,
            run_command=self._run_command,
            news=self._news,
            log=self._log,
            interval_s=AGENT_HEARTBEAT_INTERVAL_S,
            on_tick=self._adopt_external_binding,
            on_state=self._desired.take,
            validate=self._validate,
        )

    def _hello_payload(self) -> dict:
        return {
            "client_version": AGENT_VERSION,
            "wire": AGENT_WIRE_GENERATION,
            "hostname": hostname(),
            "platform": self._engine.platform_tuple,
            "addresses": enrollment.machine_addresses(),
            "accounts": self._read_accounts(),
            "state_hash": self._desired.applied_hash,
            "last_reinstall": self._read_reinstall(),
        }

    def _report_payload(self) -> dict:
        return {
            "metrics": self._read_metrics(),
            "platform": self._engine.platform_tuple,
            # Each interface's address with the MAC carrying it, so the hub
            # can name the one on this machine's own wire.
            "addresses": enrollment.machine_addresses(),
            "accounts": self._read_accounts(),
            "modules": self._engine.report(),
            "state_hash": self._desired.applied_hash,
            "state_error": self._desired.state_error,
            # Whether this machine's desktop is reachable. The access
            # password it was set up with stays on the machine.
            "rdp": self.rdp_declaration(),
            "last_error": self.last_error(),
            # What the install this agent came from said, written by the
            # transient unit that ran it and read back here.
            "last_reinstall": self._read_reinstall(),
        }

    def _read_reinstall(self) -> "dict | None":
        """What the reinstall this launch came from did, if it left a record."""
        return self_update.read_reinstall_result(self._data_dir)

    def _run_order(self, order: dict, on_line=None) -> dict:
        """Run one order, then give the changed machine its configuration.

        Args:
            order: The order on the wire.
            on_line: Called with each output line.

        Returns:
            ``{"state", "code", "params", "output"}``.
        """
        result = self._engine.run_order(order, on_line)
        self._desired.apply_again()
        return result

    def _validate(self, module: str, config: dict) -> dict:
        """Check a configuration the hub is about to store for one module.

        Args:
            module: The module name.
            config: The configuration.

        Returns:
            Empty when sound, ``{"code", "params"}`` when not.
        """
        runner = self._engine.module_runners.get(module)
        if runner is None:
            return {"code": "unknown_module", "params": {"module": module}}
        try:
            runner.validate(dict(config))
        except ModuleApplyError as error:
            return {"code": error.code, "params": dict(error.params)}
        except PlatformUnsupportedError:
            return {"code": "unsupported_platform", "params": {}}
        except Exception as error:  # noqa: BLE001 - reported, never raised
            return {"code": "validate_failed", "params": {"detail": str(error)[:200]}}
        return {}

    def _run_command(self, action: str, args: dict, on_line=None) -> dict:
        with self._lock:
            operator = self._operator
        if operator is None:
            return {
                "exit_code": 1,
                "code": "hub_unreachable",
                "params": {},
                "output": "",
            }
        self._log(f"running {action}")
        outcome = operator.run(action, args, on_line)
        reply = {
            "exit_code": outcome.exit_code,
            "code": outcome.code,
            "params": dict(outcome.params),
            "output": outcome.output,
        }
        if outcome.result:
            reply["result"] = dict(outcome.result)
        return reply

    def _reinstall(self) -> dict:
        """Reinstall this agent from the hub's package, on the hub's order.

        Returns:
            Empty when the install was launched, ``{"code", "params"}``
            when it was not.
        """
        with self._lock:
            self._update_target = ""
        self._force_self_update("reinstall")
        with self._lock:
            return dict(self._update_error) if self._update_error else {}

    def _fetch_artifact(self, artifact_key: str, destination: str) -> dict:
        """Take the bytes an order named from the hub, onto disk.

        Args:
            artifact_key: What the order named the artifact by.
            destination: Where to write what comes back.

        Returns:
            Empty when the bytes landed, ``{"code", "params"}`` when they
            did not.
        """
        with self._lock:
            channel = self._channel
        if channel is None:
            return {"code": "hub_unreachable", "params": {}}
        try:
            named = channel.post_download(
                AGENT_MODULE_PACKAGE_PATH,
                {"artifact_key": artifact_key},
                destination,
            )
        except GatewayRefusedDetail as error:
            return {"code": error.code, "params": error.params}
        except (
            GatewayRefused,
            GatewayUnreachable,
            GatewayUntrusted,
            GatewayVersionRefused,
            GatewayWireStale,
        ) as error:
            return channel_error(error)
        if named and named != _sha256_file(destination):
            return {"code": "module_digest_mismatch", "params": {}}
        return {}

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

    def _on_unreachable(self, error: Exception) -> int:
        """Back off after a broken wire; the rejection count stands."""
        with self._lock:
            self._last_error = channel_error(error)
            delay = self._backoff_s
            self._backoff_s = min(self._backoff_s * 2, AGENT_BACKOFF_MAX_S)
        self._log(f"hub socket failed: {error}; retrying in {delay}s")
        return delay

    def _on_wire_stale(self, error: GatewayWireStale) -> int:
        """Reinstall on a stale-wire answer; it never counts toward an unbind."""
        with self._lock:
            self._last_error = channel_error(error)
        self._log(f"{error}")
        self._force_self_update(f"wire-{error.hub_wire}")
        return AGENT_HEARTBEAT_INTERVAL_S

    def _on_rejected(self, error: Exception) -> int:
        """Take a definitive rejection for what it is, after a short grace.

        One counter covers every kind; after a few in a row the binding is
        dropped and the machine goes back to waiting for a link.

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
            self._refusals = 0
            self._update_target = ""
            self._update_error = None
        self._load_connection()
        with self._lock:
            self._last_error = {
                "code": "self_unbound",
                "params": {"cause": rejection["code"]},
            }
        self._engine.update(catalog=None, catalog_hash="")
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
                self._operator = DeviceOperator(
                    platform=self._platform,
                    reinstall=self._reinstall,
                    module_runners=self._engine.module_runners,
                    settle=self._desired.settle,
                    on_module_changed=lambda module: self._engine.refresh_now(),
                )
            else:
                self._channel = None
                self._operator = None

    def _drop_session(self) -> None:
        """End the live socket, if there is one."""
        with self._lock:
            session = self._session
            self._session = None
        if session is not None:
            session.close()

    def _adopt_external_binding(self) -> None:
        """Pick up a binding another process wrote.

        ``nagent connect`` and ``nagent disconnect`` edit the configuration
        from their own process. The service notices the file changing and
        converges: a live socket for a binding that is gone is closed.
        """
        with self._lock:
            if enrollment.config_stamp() == self._binding_stamp:
                return
            binding = self._binding
        self._load_connection()
        with self._lock:
            if self._binding == binding:
                return
            self._last_error = None
            self._refusals = 0
            self._update_target = ""
            self._update_error = None
            self._backoff_s = AGENT_BACKOFF_MIN_S
        self._drop_session()
        self._engine.update(catalog=None, catalog_hash="")
        self._log("adopted the binding written on disk")

    def _force_self_update(self, target: str) -> None:
        """Reinstall this agent from the hub's package, version equal or not.

        Args:
            target: A name for what asked, latched like a version target so
                a failed attempt is not retried on every connection.
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
            with self._lock:
                self._update_error = {
                    "code": "agent_package_missing",
                    "params": {"target": target},
                }
            return
        self._log("reinstalling from the hub's package")
        try:
            self_update.run_update(
                channel,
                kind=kind,
                architecture=self._engine.platform_tuple.get("arch", ""),
                data_dir=self._data_dir,
            )
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

        Args:
            hub_version: What the welcome named.
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
            self_update.run_update(
                channel,
                kind=kind,
                architecture=self._engine.platform_tuple.get("arch", ""),
                data_dir=self._data_dir,
            )
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
