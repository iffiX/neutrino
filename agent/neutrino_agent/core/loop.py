"""The agent itself: the binding, the socket to the hub, and the module engine.

One object owns everything the local control channel and the hub both talk
to. It runs whether or not the machine belongs to a hub yet: an agent that
has never enrolled still answers locally, waiting for a link.

While bound, the agent keeps one socket open to the hub and reconnects when
it drops. The hub decides everything about modules: its state says what
each is to be, and this machine observes, installs, configures and reports
until it matches, the bytes coming down and the output going up on streams
this side opens. The desktop share is the other way round: decided only on
the machine, and reported upward.

Errors cross the wire as ``{"code", "params"}``, never an English sentence;
every surface does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import operator
import os
import threading
import urllib.parse

from neutrino_agent import AGENT_VERSION
from neutrino_agent.constants import (
    AGENT_BACKOFF_MAX_S,
    AGENT_BACKOFF_MIN_S,
    AGENT_CODE_BINDING_UNKNOWN,
    AGENT_CODE_REPLACED,
    AGENT_CREDENTIALS_DIR_NAME,
    AGENT_DESIRED_STATE_NAME,
    AGENT_HEARTBEAT_INTERVAL_S,
    AGENT_HUB_SOFTWARE_PREFIX,
    AGENT_PACKAGE_DIR,
    AGENT_ROLE,
    AGENT_SOFTWARE_PREFIX,
    AGENT_STATE_NAME,
    AGENT_WS_PATH,
    PROTOCOL,
)
from neutrino_agent.core import enrollment, network, self_update
from neutrino_agent.core.commands import DeviceOperator
from neutrino_agent.core.desired_state import DesiredStateApplier, DesiredStateStore
from neutrino_agent.core.engine import ModuleEngine
from neutrino_agent.core.metrics import HostMetrics, hostname
from neutrino_agent.core.session import AgentSession
from neutrino_agent.core.store import MachineStateStore
from neutrino_agent.core.version import parse_version
from neutrino_agent.core.ws_client import WebSocketClient
from neutrino_agent.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
    PlatformUnsupportedError,
    SelfUpdateError,
)
from neutrino_agent.platforms.detect import detect_platform
from neutrino_agent.rdp.host import RdpShareHost
from neutrino_agent.streams import STREAM_KIND_PACKAGE
from neutrino_agent.streams.package import remove_stale

# How often an unbound or a replaced agent looks again, which is only to
# notice that its binding file has since been written.
IDLE_POLL_INTERVAL_S = 2

# What a version ends in when it was built from a checkout.
DEV_VERSION_SUFFIX = "+dev"


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
    return {"code": "hub_unreachable", "params": {"detail": str(error)}}


def hub_version_of(software: str) -> str:
    """The version a hub's ``software`` names.

    Args:
        software: What the welcome carried.

    Returns:
        The version after ``neutrino_hub/``, empty for anything else.
    """
    if not software.startswith(AGENT_HUB_SOFTWARE_PREFIX):
        return ""
    return software[len(AGENT_HUB_SOFTWARE_PREFIX) :]


def is_dev_version(version: str) -> bool:
    """Whether a version was built from a checkout rather than released.

    Args:
        version: The version text.

    Returns:
        True when it ends in ``+dev``.
    """
    return version.endswith(DEV_VERSION_SUFFIX)


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
            platform=self._platform, log=log, on_change=self._news.set
        )
        # The store and the seat password live under the platform's own
        # data root, and so does the last desired state taken from the hub.
        data_dir = self._platform.agent_data_dir()
        self._data_dir = data_dir
        # Where a package lands, a module's or this agent's own, until its
        # digest is checked; the marks the engine keeps live beside it.
        self._package_dir = AGENT_PACKAGE_DIR
        self._store = MachineStateStore(path=os.path.join(data_dir, AGENT_STATE_NAME))
        self._rdp = RdpShareHost(
            platform=self._platform,
            store=self._store,
            credentials_dir=os.path.join(data_dir, AGENT_CREDENTIALS_DIR_NAME),
            log=log,
        )
        self._desired = DesiredStateApplier(
            engine=self._engine,
            runners=self._engine.module_runners,
            store=DesiredStateStore(
                path=os.path.join(data_dir, AGENT_DESIRED_STATE_NAME)
            ),
            rdp=self._rdp,
            log=log,
            open_stream=self._open_stream,
            package_dir=self._package_dir,
        )
        # The share flow refuses before it configures anything when RustDesk
        # is not on the machine, which is what the engine's report answers.
        self._rdp.bind_modules(self._engine.report)
        self._backoff_s = AGENT_BACKOFF_MIN_S
        self._last_error: "dict | None" = None
        self._operator = None
        self._session: "AgentSession | None" = None
        self._binding: dict = {}
        self._binding_stamp = 0
        # Set by a 4010 close: another socket holds this binding, and this
        # one reconnects only once a person acts.
        self._is_replaced = False
        # The hub version last acted on and how the attempt went, so a target
        # that failed is not retried on every connection.
        self._update_target = ""
        self._update_error: "dict | None" = None
        # Each source of failure the report may show, with the serial of
        # when its current value was first seen; the newest is the one shown.
        self._errors: dict = {}
        self._error_serial = 0
        self._load_connection()

    # --- what the control channel reads ---

    def platform(self) -> dict:
        """This machine's platform tuple."""
        return self._engine.platform_tuple

    def module_states(self) -> dict:
        """What each module is observed to be, as the report says it."""
        return self._engine.report()

    def state_hash(self) -> str:
        """The hash of the hub's state this machine last applied whole."""
        return self._desired.applied_hash

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
            ``{"is_shared", "account", "share_id", "port", "attention",
            "connected_count"}``.
        """
        return self._rdp.declaration()

    # --- what the control channel asks for ---

    def join(self, link: str) -> None:
        """Join the hub an enrollment link points at.

        Args:
            link: The link the owner pasted.

        Raises:
            EnrollmentError: If the link is unusable or the hub refuses.
        """
        enrollment.enroll(link, platform=self._platform)
        self._drop_session()
        self._reset_binding_state()
        self._load_connection()
        self._news.set()
        self._log("joined the hub")

    def leave(self) -> None:
        """Leave the hub, and stop reporting to it.

        The binding goes whether or not the hub could be told; the log says
        when it could not.
        """
        self._drop_session()
        outcome = enrollment.unbind()
        if outcome:
            self._log(f"could not tell the hub we are leaving: {outcome['code']}")
        self._reset_binding_state()
        self._load_connection()
        self._engine.take_state({})
        self._log("left the hub")

    def report_soon(self) -> None:
        """Send the next report now rather than at the end of the interval."""
        self._news.set()

    def _report_module_now(self, module: str) -> None:
        """Read every module again and report at once, after a command took.

        The hub answers the command's route from this report, so it goes
        up whether or not the read found anything different.

        Args:
            module: The module the command belonged to.
        """
        self._engine.refresh_now()
        self._news.set()

    def sync(self) -> dict:
        """Send a report now, from which the hub compares hashes.

        Returns:
            Empty when a report is on its way, ``{"code", "params"}`` when
            there is no live socket to send it on.
        """
        with self._lock:
            session = self._session
        if session is None or not session.is_open:
            return {"code": "hub_unreachable", "params": {}}
        self._news.set()
        return {}

    def rdp_share(self, *, account: str) -> dict:
        """Share this machine's desktop behind the hub's seat password.

        Args:
            account: The account sitting at the machine's screen.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        outcome = self._rdp.share(account)
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
        # A package the last process received and could not delete: the
        # one that installed this agent, or one an install was mid-way on.
        remove_stale(self._package_dir)
        # The desktop host runs on every machine this package installed on,
        # and reaches the LAN and nothing else from the first start.
        self._rdp.apply_baseline()
        while True:
            # Cleared before the turn: news set during it is still standing
            # when the wait begins.
            self._news.clear()
            delay = self.run_once()
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
        except (GatewayRefusedDetail, GatewayUntrusted) as error:
            return self._on_rejected(error)
        except GatewayUnreachable as error:
            return self._on_unreachable(error)
        with self._lock:
            self._session = session
            self._backoff_s = AGENT_BACKOFF_MIN_S
            self._last_error = None
        self._maybe_self_update(session.hub_software)
        failure = session.serve()
        with self._lock:
            if self._session is session:
                self._session = None
        if failure is None:
            return AGENT_BACKOFF_MIN_S
        if isinstance(failure, GatewayRefusedDetail):
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
        except (GatewayUnreachable, GatewayUntrusted) as error:
            with self._lock:
                self._last_error = channel_error(error)
            return
        with self._lock:
            self._last_error = None
        session.close()

    def _open_session(self) -> "AgentSession | None":
        """A session for the current binding, or None while unbound or replaced."""
        with self._lock:
            binding = dict(self._binding)
            is_replaced = self._is_replaced
        if not binding or is_replaced:
            return None
        parts = urllib.parse.urlsplit(binding["gateway_url"])
        client = WebSocketClient(
            host=parts.hostname or "",
            port=parts.port or 443,
            path=AGENT_WS_PATH,
            fingerprint=binding["fingerprint"],
        )
        return AgentSession(
            client=client,
            hello=self._hello_payload(binding),
            report=self._report_payload,
            run_command=self._run_command,
            news=self._news,
            log=self._log,
            interval_s=AGENT_HEARTBEAT_INTERVAL_S,
            on_tick=self._adopt_external_binding,
            on_state=self._desired.take,
        )

    def _hello_payload(self, binding: dict) -> dict:
        """The identity card the hello carries.

        Args:
            binding: The binding the socket is opened for.

        Returns:
            ``{protocol, role, id, name, software, token}``.
        """
        return {
            "protocol": PROTOCOL,
            "role": AGENT_ROLE,
            "id": binding["id"],
            "name": hostname(),
            "software": f"{AGENT_SOFTWARE_PREFIX}{AGENT_VERSION}",
            "token": binding["token"],
        }

    def _report_payload(self) -> dict:
        """What is true of this machine: the report's five sections."""
        return {
            "state_hash": self._desired.applied_hash,
            "machine": {
                "hostname": hostname(),
                "platform": self._engine.platform_tuple,
                "accounts": self._read_accounts(),
                "metrics": self._read_metrics(),
            },
            "network": network.describe(self._link_address(), self._read_interfaces()),
            "modules": self._engine.report(),
            # Whether this machine's desktop is reachable. The seat
            # password it answers with stays on the machine.
            "desktop": self.rdp_declaration(),
            "error": self._error_section(),
        }

    def _error_section(self) -> "dict | None":
        """The most recent failure worth showing, as ``{"code", "params"}``.

        Three sources are read each time: the channel's last error, the
        state error, and the reinstall this agent came from when it failed.
        A source whose value changed is stamped now, and the newest stamp
        is the one reported.

        Returns:
            The error, or None when no source holds one.
        """
        current = (
            ("channel", self.last_error()),
            ("state", self._desired.state_error),
            ("reinstall", self._reinstall_error()),
        )
        with self._lock:
            for source, error in current:
                held = self._errors.get(source)
                if error is None:
                    self._errors.pop(source, None)
                elif held is None or held[1] != error:
                    self._error_serial += 1
                    self._errors[source] = (self._error_serial, dict(error))
            if not self._errors:
                return None
            newest = max(self._errors.values(), key=operator.itemgetter(0))
            return dict(newest[1])

    def _reinstall_error(self) -> "dict | None":
        """The reinstall this launch came from, when its record says it failed.

        The record is written by the transient unit that ran the install
        and read back here.

        Returns:
            ``{"code", "params"}`` naming the exit status, or None when no
            record stands there or the install went through.
        """
        result = self_update.read_reinstall_result(self._data_dir)
        if result is None or result["exit_code"] == 0:
            return None
        return {
            "code": "reinstall_failed",
            "params": {
                "exit_code": result["exit_code"],
                "finished_at": result["finished_at"],
            },
        }

    def _open_stream(self, kind: str, **args):
        """Open a stream to the hub on the live socket.

        Args:
            kind: The stream kind.
            **args: The kind's arguments.

        Returns:
            The stream's channel.

        Raises:
            GatewayUnreachable: When no socket is open.
        """
        with self._lock:
            session = self._session
        if session is None or not session.is_open:
            raise GatewayUnreachable("no socket to the hub")
        return session.open_stream(kind, **args)

    def _resize_shell(self, stream_id, cols: int, rows: int) -> bool:
        """Give one of the hub's shell streams a new size.

        Args:
            stream_id: The shell stream's id.
            cols: The new width.
            rows: The new height.

        Returns:
            True when a live stream of that id took it.
        """
        with self._lock:
            session = self._session
        if session is None:
            return False
        return session.resize_stream(stream_id, cols, rows)

    def _run_command(self, module: str, verb: str, args: dict, on_line=None) -> dict:
        with self._lock:
            operator = self._operator
        if operator is None:
            return {
                "exit_code": 1,
                "code": "hub_unreachable",
                "params": {},
                "output": "",
            }
        self._log(f"running {module} {verb}")
        outcome = operator.run(module, verb, args, on_line)
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

    def _read_interfaces(self) -> list:
        try:
            return self._platform.read_network_interfaces()
        except PlatformUnsupportedError:
            return []

    def _link_address(self) -> str:
        """The socket's own address on this machine, empty with no socket."""
        with self._lock:
            session = self._session
        return session.local_address if session is not None else ""

    def _on_unreachable(self, error: Exception) -> int:
        """Back off after a broken wire."""
        with self._lock:
            self._last_error = channel_error(error)
            delay = self._backoff_s
            self._backoff_s = min(self._backoff_s * 2, AGENT_BACKOFF_MAX_S)
        self._log(f"hub socket failed: {error}; retrying in {delay}s")
        return delay

    def _on_rejected(self, error: Exception) -> int:
        """Split a refusal by its code.

        ``binding_unknown`` deletes the binding and waits for a link;
        ``replaced`` keeps it and waits for a person; every other code keeps
        it and asks again after the longest backoff.

        Args:
            error: What the channel raised.

        Returns:
            Seconds until the next loop turn.
        """
        rejection = channel_error(error)
        code = rejection["code"]
        if code == AGENT_CODE_BINDING_UNKNOWN:
            enrollment.remove_binding()
            self._reset_binding_state()
            self._load_connection()
            with self._lock:
                self._last_error = rejection
            self._engine.take_state({})
            self._log("unbound: the hub does not know this binding")
            return IDLE_POLL_INTERVAL_S
        with self._lock:
            self._last_error = rejection
            if code == AGENT_CODE_REPLACED:
                self._is_replaced = True
        if code == AGENT_CODE_REPLACED:
            self._log("replaced by another socket; reconnecting on nagent join")
            return IDLE_POLL_INTERVAL_S
        self._log(f"refused: {code}; asking again in {AGENT_BACKOFF_MAX_S}s")
        return AGENT_BACKOFF_MAX_S

    def _reset_binding_state(self) -> None:
        """Forget what the last binding's connections recorded."""
        with self._lock:
            self._last_error = None
            self._is_replaced = False
            self._update_target = ""
            self._update_error = None
            self._backoff_s = AGENT_BACKOFF_MIN_S

    def _load_connection(self) -> None:
        binding = enrollment.load_binding()
        with self._lock:
            self._binding = binding
            self._binding_stamp = enrollment.config_stamp()
            if binding:
                self._operator = DeviceOperator(
                    platform=self._platform,
                    reinstall=self._reinstall,
                    resize=self._resize_shell,
                    module_runners=self._engine.module_runners,
                    settle=self._desired.settle,
                    on_module_changed=self._report_module_now,
                )
            else:
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

        ``nagent join`` and ``nagent leave`` edit the binding file from
        their own process. The service notices the file changing and
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
        self._reset_binding_state()
        self._drop_session()
        self._engine.take_state({})
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
        if self._install_from_hub(target, kind):
            self._log("reinstall launched; the service restarts")

    def _maybe_self_update(self, hub_software: str) -> None:
        """Update this agent when the hub runs a later release, once per target.

        A version that does not parse or ends in ``+dev``, on either side,
        updates nothing.

        Args:
            hub_software: The ``software`` the welcome named.
        """
        hub_version = hub_version_of(hub_software)
        with self._lock:
            if not hub_version or hub_version == self._update_target:
                return
            self._update_target = hub_version
            self._update_error = None
        if is_dev_version(hub_version) or is_dev_version(AGENT_VERSION):
            self._log(f"no self-update: {AGENT_VERSION} or {hub_version} is a checkout")
            return
        hub = parse_version(hub_version)
        agent = parse_version(AGENT_VERSION)
        if hub is None or agent is None:
            self._log(f"no self-update: cannot order {AGENT_VERSION} and {hub_version}")
            return
        if agent >= hub:
            return
        kind = self_update.package_kind(self._engine.platform_tuple)
        if not kind:
            self._log(f"no self-update to {hub_version}: no package for this platform")
            return
        self._log(f"updating to {hub_version}")
        if self._install_from_hub(hub_version, kind):
            self._log(f"self-update to {hub_version} launched; the service restarts")

    def _install_from_hub(self, target: str, kind: str) -> bool:
        """Take this agent's package down a ``package {}`` stream and install it.

        A transfer the socket dropped leaves the target unlatched, so the
        next connection asks again; a package that did not match, a hub
        that refused, and an install that could not be launched latch it
        with their code.

        Args:
            target: What the attempt is latched under.
            kind: ``deb`` or ``rpm``.

        Returns:
            True when the install was launched.
        """
        try:
            channel = self._open_stream(STREAM_KIND_PACKAGE)
            path = self_update.receive_package(channel, directory=self._package_dir)
        except GatewayUnreachable as error:
            with self._lock:
                self._update_target = ""
                self._update_error = {
                    "code": "hub_unreachable",
                    "params": {"target": target},
                }
            self._log(f"update to {target} not fetched: {error}")
            return False
        except SelfUpdateError as error:
            with self._lock:
                self._update_error = {"code": str(error), "params": {"target": target}}
            self._log(f"update to {target} refused: {error}")
            return False
        try:
            self_update.run_update(path, kind=kind, data_dir=self._data_dir)
        except SelfUpdateError as error:
            with self._lock:
                self._update_error = {"code": str(error), "params": {"target": target}}
            self._log(f"update to {target} failed: {error}")
            return False
        return True
