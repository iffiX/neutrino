"""The agent itself: the binding, the session to the hub, and the module engine.

One object owns everything the local control channel and the hub both talk
to. It runs whether or not the machine belongs to a hub yet: an agent that
has never enrolled still answers locally, waiting for a link.

The session is its transport's. The agent starts ``neutrino_transport`` as
its child, hands it the binding with ``dial``, and the transport keeps one
session to the hub, dialling every address of the hub at once and again
after each end. The agent writes every frame: ``hello`` when the transport says a
session opened, then a report every few seconds and at once when something
changed. The hub decides everything about modules: its state says what
each is to be, and this machine observes, installs, configures and reports
until it matches, the bytes coming down and the output going up on streams
this side opens. A ``connect`` from the hub is the transport's own, after
it asks here whether the port is published. The desktop share is the other
way round: decided only on the machine, and reported upward. While the
state's ``ai_tools`` section says ``is_forwarded``, the transport listens
on the AI gateway forward's port, and the machine's containers reach the
agent's loopback listeners through its relays.

Errors cross the wire as ``{"code", "params"}``, never an English sentence;
every surface does its own wording.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import functools
import operator
import os
import queue
import threading
import time

from neutrino_agent import AGENT_VERSION
from neutrino_agent.ai_tools.applier import AiToolsApplier
from neutrino_agent.constants import (
    AGENT_BACKOFF_MAX_S,
    AGENT_BACKOFF_MIN_S,
    AGENT_CODE_BINDING_UNKNOWN,
    AGENT_CODE_CONTROL_UNAVAILABLE,
    AGENT_CODE_HUB_KEY_MISSING,
    AGENT_CODE_PORT_NOT_PUBLISHED,
    AGENT_CODE_REPLACED,
    AGENT_CONFIGURED_DIR_NAME,
    AGENT_CONNECT_TCP,
    AGENT_CREDENTIALS_DIR_NAME,
    AGENT_DESIRED_STATE_NAME,
    AGENT_FAILURES_DIR_NAME,
    AGENT_HUB_SOFTWARE_PREFIX,
    AGENT_LOCK_SELF_UPDATE_HOLDER,
    AGENT_PACKAGE_DIR_NAME,
    AGENT_PROBE_TIMEOUT_S,
    AGENT_REFUSAL_LOG_INTERVAL_S,
    AGENT_REINSTALL_INSTALLED_CODES,
    AGENT_REINSTALL_WAIT_S,
    AGENT_REPORT_INTERVAL_S,
    AGENT_ROLE,
    AGENT_SOFTWARE_PREFIX,
    AGENT_STATE_NAME,
    AGENT_UPDATE_HOLD_S,
    AGENT_UPDATE_UNIT,
    PROTOCOL,
)
from neutrino_agent.core import enrollment, network, self_update
from neutrino_agent.core.commands import DeviceOperator, is_reading_command
from neutrino_agent.core.container_relay import ContainerRelays, gateway_port_of
from neutrino_agent.core.desired_state import DesiredStateApplier, DesiredStateStore
from neutrino_agent.core.engine import ModuleEngine
from neutrino_agent.core.metrics import HostMetrics, hostname
from neutrino_agent.core.session import AgentSession, refusal_of
from neutrino_agent.core.store import MachineStateStore
from neutrino_agent.core.version import parse_version
from neutrino_agent.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    PlatformUnsupportedError,
    SelfUpdateError,
)
from neutrino_agent.modules.podman.constants import PODMAN_BINARY, PODMAN_MODULE_NAME
from neutrino_agent.modules.podman.machine_runner import PodmanMachineModuleRunner
from neutrino_agent.modules.remote_desktop.constants import REMOTE_DESKTOP_NAME
from neutrino_agent.modules.remote_desktop.rdp.host import RdpShareHost
from neutrino_agent.modules.shared.hub_clock import hub_clock
from neutrino_agent.modules.shared.step_locks import PACKAGE_MANAGER_LOCKS
from neutrino_agent.modules.terminal.config import TerminalConfig
from neutrino_agent.modules.terminal.constants import TERMINAL_NAME
from neutrino_agent.platforms.detect import detect_platform
from neutrino_agent.streams import (
    STREAM_KIND_EXEC,
    STREAM_KIND_PACKAGE,
    STREAM_KIND_SHELL,
    STREAM_KINDS,
)
from neutrino_agent.streams.ai_forward import AiGatewayForward
from neutrino_agent.streams.connect import published_ports
from neutrino_agent.streams.exec import open_exec_stream
from neutrino_agent.streams.package import remove_stale
from neutrino_agent.streams.shell import open_shell_stream
from neutrino_agent.streams.shell_session import ShellSessionRegistry
from neutrino_agent.transport.connection import open_local
from neutrino_agent.transport.control import TransportControlClient
from neutrino_agent.transport.process import (
    TransportProcess,
    listen_path,
    one_shot_transport,
    program_path,
)

# How often an unbound or a replaced agent looks again, which is only to
# notice that its binding file has since been written; also how often an
# agent whose transport holds no session looks for one.
IDLE_POLL_INTERVAL_S = 2

# What a version ends in when it was built from a checkout.
DEV_VERSION_SUFFIX = "+dev"

# The events of the agent's local channel.
EVENT_SESSION_OPEN = "session_open"
EVENT_SESSION_END = "session_end"
EVENT_ROUND_END = "round_end"
# The codes a round ends with that the transport gives itself, not the hub.
ROUND_CODES_OF_THE_TRANSPORT = ("hub_unreachable", "hub_untrusted")
EVENT_STREAM = "stream"
QUESTION_PORT = "port"
# The commands this side sends its transport.
COMMAND_DIAL = "dial"
COMMAND_UNDIAL = "undial"


def channel_error(error: Exception) -> dict:
    """The typed form of a channel exception.

    Args:
        error: What the channel raised.

    Returns:
        ``{"code", "params"}``.
    """
    if isinstance(error, GatewayRefusedDetail):
        return {"code": error.code, "params": dict(error.params)}
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


def link_address(local_address: str) -> str:
    """The address the report names as the link, without a port.

    Args:
        local_address: What ``session_open`` named: ``host:port``,
            ``[host]:port``, or a bare address.

    Returns:
        The host alone.
    """
    text = str(local_address or "").strip()
    if text.startswith("["):
        return text[1:].split("]", 1)[0]
    if text.count(":") == 1:
        return text.split(":", 1)[0]
    return text


def start_transport(platform, log) -> TransportProcess:
    """The service's transport, started on the system's own listener.

    Args:
        platform: The machine's platform.
        log: Callable used for the transport's lines.

    Returns:
        The started transport.

    Raises:
        OSError: When it cannot start or does not answer.
    """
    process = TransportProcess(
        program=program_path(platform),
        listen=listen_path(platform.os_name),
        log=log,
    )
    process.start()
    return process


class Agent:
    """Everything the agent is, running or waiting to be told where to run."""

    def __init__(
        self,
        *,
        log=print,
        platform=None,
        transport_starter=None,
        one_shot=None,
        clock=time.monotonic,
    ):
        """
        Args:
            log: Callable used for progress messages; defaults to printing,
                which systemd captures into the journal.
            platform: The machine's platform; None detects it.
            transport_starter: Called with ``(platform, log)`` for the
                service's started transport, with ``listen``, ``secret``,
                ``is_running()`` and ``stop()``; None starts
                ``neutrino_transport``.
            one_shot: Called with ``on_event`` and ``on_frame`` keywords for
                a context manager yielding a started control client of a
                transport of this process's own, for a join, a leave or a
                probe while the service's transport does not run here; None
                starts one.
            clock: The monotonic clock the refusal lines are spaced on.
        """
        self._log = log
        self._clock = clock
        self._lock = threading.Lock()
        self._platform = platform if platform is not None else detect_platform()
        self._transport_starter = transport_starter or start_transport
        self._one_shot = one_shot or functools.partial(
            one_shot_transport, self._platform, log=log
        )
        # Set whenever there is something new to report, so a report goes up
        # then rather than at the end of the interval.
        self._news = threading.Event()
        # The shells kept by id, across sessions, for as long as this runs.
        self._shells = ShellSessionRegistry(on_change=self._news.set)
        var_dir = self._platform.agent_var_dir()
        self._engine = ModuleEngine(
            platform=self._platform,
            log=log,
            on_change=self._news.set,
            configured_dir=os.path.join(var_dir, AGENT_CONFIGURED_DIR_NAME),
            failures_dir=os.path.join(var_dir, AGENT_FAILURES_DIR_NAME),
        )
        # The store and the seat password live under the platform's own
        # data root, and so does the last desired state taken from the hub.
        data_dir = self._platform.agent_data_dir()
        self._var_dir = var_dir
        # Where a package lands, a module's or this agent's own, until its
        # digest is checked; the marks the engine keeps live beside it.
        self._package_dir = os.path.join(var_dir, AGENT_PACKAGE_DIR_NAME)
        self._store = MachineStateStore(path=os.path.join(data_dir, AGENT_STATE_NAME))
        self._rdp = RdpShareHost(
            platform=self._platform,
            store=self._store,
            credentials_dir=os.path.join(data_dir, AGENT_CREDENTIALS_DIR_NAME),
            state_dir=var_dir,
            log=log,
        )
        self._engine.module_runners[REMOTE_DESKTOP_NAME].bind_host(self._rdp)
        # The machine's AI tools, switched as each account the state names.
        self._ai_tools = AiToolsApplier(
            platform=self._platform, log=log, is_bound=enrollment.is_bound
        )
        # The machine's AI tools reach the hub's gateway through it.
        self._ai_forward = AiGatewayForward(command=self._command, log=log)
        # The machine's containers reach the agent's loopback listeners
        # through them.
        self._relays = ContainerRelays(
            platform=self._platform, ports=self._relayed_ports, log=log
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
            ai_tools=self._ai_tools,
        )
        self._engine.set_configure_asker(self._desired.ask_configure)
        self._backoff_s = AGENT_BACKOFF_MIN_S
        self._last_error: "dict | None" = None
        self._operator = None
        # The service's transport and its control connection; None until
        # the loop starts them.
        self._transport = None
        self._control: "TransportControlClient | None" = None
        # Moves on each end of a transport, so a line the ended one still
        # delivers is dropped.
        self._generation = 0
        # The dial last sent, so a binding is dialled once.
        self._dialed: "dict | None" = None
        # The session the transport opened last, and the one a report went
        # up on last.
        self._session: "AgentSession | None" = None
        self._reported: "AgentSession | None" = None
        self._binding: dict = {}
        self._binding_stamp = 0
        # This machine's own address on the route to the hub as last seen;
        # None before the first look.
        self._source_address: "str | None" = None
        # Set by a ``replaced`` refusal: another session holds this binding,
        # and this one dials again only once a person acts.
        self._is_replaced = False
        # The ``control_unavailable`` refusals since the line at
        # ``_unavailable_logged_at``. It is None outside a run of them.
        self._unavailable_count = 0
        self._unavailable_logged_at: "float | None" = None
        # The hub version last acted on and how the attempt went, so a target
        # that failed is not retried on every session.
        self._update_target = ""
        self._update_error: "dict | None" = None
        # Each source of failure the report may show, with the serial of
        # when its current value was first seen; the newest is the one shown.
        self._errors: dict = {}
        self._error_serial = 0
        # Set once the process is asked to stop; the loop ends at its next turn.
        self._is_stop_asked = threading.Event()
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
        """Whether a session to the hub is up and welcomed."""
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
        enrollment.enroll(link, platform=self._platform, transport=self._transport_for)
        self._desired.forget_tried()
        self._engine.take_state({})
        self._undial()
        self._ai_forward.stop()
        self._stop_transport()
        self._reset_binding_state()
        self._load_connection()
        self._news.set()
        self._log("joined the hub")

    def leave(self) -> tuple:
        """Leave the hub, and stop reporting to it.

        The binding goes whether or not the hub could be told; the log says
        when it could not.

        Returns:
            ``(outcome, switched_back)``: empty when the hub took the leave
            and ``{"code", "params"}`` when it could not be told, then each
            account's result of switching its AI tools back.
        """
        self._undial()
        self._ai_forward.stop()
        outcome = enrollment.unbind(
            platform=self._platform, transport=self._transport_for
        )
        if outcome:
            self._log(f"could not tell the hub we are leaving: {outcome['code']}")
        switched_back = self._ai_tools.switch_back_all()
        self._rdp.leave_hub()
        self._desired.forget_tried()
        self._reset_binding_state()
        self._load_connection()
        self._engine.take_state({})
        self._log("left the hub")
        return outcome, switched_back

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
            there is no live session to send it on.
        """
        if not self.is_online():
            return {"code": "hub_unreachable", "params": {}}
        self._news.set()
        return {}

    # --- the loop ---

    def stop(self) -> None:
        """Ask the loop to end; the wait is cut short.

        Every module task's result from now on counts as the stop, so a
        command the stop's signal ended keeps no failure. Returns at once;
        :meth:`run_forever` returns once its turn ends.
        """
        self._desired.stop()
        self._is_stop_asked.set()
        self._news.set()

    def run_forever(self) -> None:
        """Hold the session, or wait to be enrolled, until :meth:`stop` is called."""
        self._log(f"neutrino_agent {AGENT_VERSION} starting on {hostname()}")
        # A package the last process received and could not delete: the
        # one that installed this agent, or one an install was mid-way on.
        remove_stale(self._package_dir)
        if self_update.remove_stale_job(
            self_update.package_kind(self._engine.platform_tuple)
        ):
            self._log(f"removed the stale update job {AGENT_UPDATE_UNIT}")
        if self_update.clear_failed_result(self._var_dir, version=AGENT_VERSION):
            self._log(f"cleared the failed install record of {AGENT_VERSION}")
        # A share an earlier agent's command made runs again on this agent's
        # copy, beside the connection rather than before it.
        threading.Thread(
            target=self._rdp.settle_at_start, name="rdp_resume", daemon=True
        ).start()
        self._relays.start()
        try:
            while not self._is_stop_asked.is_set():
                # Cleared before the turn: news set during it is still
                # standing when the wait begins.
                self._news.clear()
                delay = self.run_once()
                if self._is_stop_asked.is_set():
                    break
                self._wait_out(delay)
        finally:
            self._ai_forward.stop()
            self._relays.stop()
            self._stop_transport()
        self._log("neutrino_agent stopped")

    def run_once(self) -> float:
        """One turn: the transport, the dial, and a report while a session is up.

        Returns:
            How many seconds to wait before the next turn: the report
            interval while a session is up, a backing-off delay while the
            transport cannot start, and a short poll otherwise.
        """
        self._adopt_external_binding()
        self._note_hub_key_missing()
        if not self._is_bound_and_wanted():
            self._undial()
            return IDLE_POLL_INTERVAL_S
        if not self._ensure_transport():
            with self._lock:
                delay = self._backoff_s
                self._backoff_s = min(self._backoff_s * 2, AGENT_BACKOFF_MAX_S)
            return delay
        self._ensure_dialed()
        self._ai_forward.take(self._desired.latest())
        with self._lock:
            session = self._session
        if session is None:
            self._tick()
            return IDLE_POLL_INTERVAL_S
        if session.is_ended:
            return self._on_session_ended(session)
        if not session.is_open:
            return IDLE_POLL_INTERVAL_S
        if self._reported is not session:
            self._on_welcomed(session)
        try:
            session.report(self._report_payload())
        except GatewayUnreachable as error:
            self._log(f"report not sent: {error}")
            return IDLE_POLL_INTERVAL_S
        if self._reported is not session:
            self._reported = session
            # The hub names this agent's package by the platform the first
            # report carries.
            self._maybe_self_update(session.hub_software)
        self._tick()
        return AGENT_REPORT_INTERVAL_S

    def probe(self) -> None:
        """Dial once on a transport of this process's own, take the welcome,
        and end: the status check.

        The outcome lands in :meth:`last_error`, empty when the hub
        answered.
        """
        self._adopt_external_binding()
        if not self._is_bound_and_wanted():
            return
        with self._lock:
            binding = dict(self._binding)
        lines: queue.Queue = queue.Queue()
        error: "dict | None" = {
            "code": "hub_unreachable",
            "params": {"detail": "no address answered"},
        }
        try:
            with self._one_shot(on_event=lines.put, on_frame=_framed(lines)) as control:
                control.command(COMMAND_DIAL, **enrollment.dial_fields(binding))
                error = _probe_outcome(control, lines, self._hello_payload(binding))
                with contextlib.suppress(GatewayUnreachable):
                    control.command(COMMAND_UNDIAL)
        except (GatewayUnreachable, OSError) as failure:
            error = {"code": "hub_unreachable", "params": {"detail": str(failure)}}
        with self._lock:
            self._last_error = error

    # --- the transport ---

    def _ensure_transport(self) -> bool:
        """Start the transport and its control connection when either is gone.

        Returns:
            True when the control connection is up.
        """
        with self._lock:
            control = self._control
            transport = self._transport
        if control is not None and control.is_open and transport is not None:
            if transport.is_running():
                return True
        self._stop_transport()
        with self._lock:
            generation = self._generation
        try:
            transport = self._transport_starter(self._platform, self._log)
        except OSError as error:
            self._log(f"the transport did not start: {error}")
            with self._lock:
                self._last_error = {
                    "code": "transport_unavailable",
                    "params": {"detail": str(error)[:200]},
                }
            return False
        control = TransportControlClient(
            connect=functools.partial(open_local, transport.listen),
            secret=transport.secret,
            on_event=functools.partial(self._on_event_of, generation),
            on_frame=functools.partial(self._on_frame_of, generation),
            on_question=self._on_question,
            on_closed=functools.partial(self._on_closed_of, generation),
            log=self._log,
        )
        try:
            control.start()
        except OSError as error:
            transport.stop()
            self._log(f"the transport did not answer: {error}")
            return False
        with self._lock:
            self._transport = transport
            self._control = control
            self._dialed = None
            self._backoff_s = AGENT_BACKOFF_MIN_S
        self._ai_forward.reset()
        return True

    def _stop_transport(self) -> None:
        """End the control connection and the transport child; what the
        ended transport still sends afterwards is dropped."""
        with self._lock:
            self._generation += 1
            control, self._control = self._control, None
            transport, self._transport = self._transport, None
            self._dialed = None
            session, self._session = self._session, None
        if session is not None:
            session.end()
        if control is not None:
            control.close()
        if transport is not None:
            transport.stop()

    def _command(self, name: str, /, **fields) -> dict:
        """Send one command to the service's transport.

        Raises:
            GatewayUnreachable: When the transport is not running.
        """
        with self._lock:
            control = self._control
        if control is None:
            raise GatewayUnreachable("the transport is not running")
        return control.command(name, **fields)

    @contextlib.contextmanager
    def _transport_for(self):
        """The service's control client while it runs here, else a transport
        of this process's own for one command."""
        with self._lock:
            control = self._control
        if control is not None and control.is_open:
            yield control
            return
        with self._one_shot() as own:
            yield own

    def _ensure_dialed(self) -> None:
        """Send ``dial`` for the binding, once, and again when its addresses
        changed while no session is up."""
        with self._lock:
            binding = dict(self._binding)
            dialed = self._dialed
            session = self._session
        is_live = session is not None and not session.is_ended
        if dialed is not None and is_live:
            return
        fields = enrollment.dial_fields(binding)
        if fields == dialed:
            return
        try:
            answer = self._command(COMMAND_DIAL, **fields)
        except GatewayUnreachable as error:
            self._log(f"dial not sent: {error}")
            return
        if answer.get("code"):
            self._log(f"the transport refused the dial: {answer['code']}")
            return
        with self._lock:
            self._dialed = fields

    def _undial(self) -> None:
        """Tell the transport to end the session and dial no more."""
        with self._lock:
            dialed, self._dialed = self._dialed, None
            session, self._session = self._session, None
        if session is not None:
            session.end()
        if dialed is None:
            return
        with contextlib.suppress(GatewayUnreachable):
            self._command(COMMAND_UNDIAL)

    def _on_event_of(self, generation: int, event: dict) -> None:
        """One event of the transport started as ``generation``."""
        if self._is_current(generation):
            self._on_event(event)

    def _on_frame_of(self, generation: int, frame: dict) -> None:
        """One frame through the transport started as ``generation``."""
        if self._is_current(generation):
            self._on_frame(frame)

    def _on_closed_of(self, generation: int) -> None:
        """The control connection of the transport started as ``generation`` ended."""
        if self._is_current(generation):
            self._on_transport_closed()

    def _is_current(self, generation: int) -> bool:
        """Whether a transport is the one running now, not one ended since."""
        with self._lock:
            return generation == self._generation

    def _on_event(self, event: dict) -> None:
        """One event of the transport's: a session opened or ended, a stream."""
        kind = event.get("event")
        if kind == EVENT_SESSION_OPEN:
            self._on_session_open(event)
        elif kind == EVENT_SESSION_END:
            with self._lock:
                session = self._session
            if session is not None:
                session.end(refusal_of(event) if event.get("code") else None)
            elif event.get("code"):
                self._take_refusal(refusal_of(event))
            self._news.set()
        elif kind == EVENT_ROUND_END:
            self._on_round_end(event)
        elif kind == EVENT_STREAM:
            with self._lock:
                session = self._session
            if session is not None:
                session.serve_stream(str(event.get("stream", "")), event.get("open"))
            else:
                self._log("a stream came with no session; it is not taken")
        else:
            self._log(f"ignoring a {kind!r} event from the transport")

    def _on_round_end(self, event: dict) -> None:
        """A round through every address ended with no session: why, as the
        error the report shows, and a refusal read by its code."""
        with self._lock:
            session = self._session
        if session is not None and not session.is_ended:
            return
        code = str(event.get("code", "") or "")
        if code and code not in ROUND_CODES_OF_THE_TRANSPORT:
            self._take_refusal(refusal_of(event))
        else:
            params = event.get("params")
            with self._lock:
                self._last_error = {
                    "code": code or "hub_unreachable",
                    "params": (
                        dict(params)
                        if isinstance(params, dict) and code
                        else {"detail": "no address answered"}
                    ),
                }
        self._news.set()

    def _on_session_open(self, event: dict) -> None:
        """A session opened: write ``hello`` on it."""
        with self._lock:
            binding = dict(self._binding)
            control = self._control
            previous = self._session
        if not binding or control is None:
            return
        if previous is not None:
            previous.end()
        session = AgentSession(
            control=control,
            hello=self._hello_payload(binding),
            address=enrollment.address_url(str(event.get("address", "") or "")),
            local_address=link_address(str(event.get("local_address", "") or "")),
            run_command=self._run_command,
            shells=self._shells,
            on_state=self._take_state,
            on_unreadable=self._note_unreadable,
            stream_kinds=self._stream_kinds(),
            log=self._log,
        )
        with self._lock:
            self._session = session
        try:
            session.say_hello()
        except GatewayUnreachable as error:
            session.end()
            self._log(f"hello not sent: {error}")

    def _on_frame(self, frame: dict) -> None:
        """One frame from the hub, for the session it came on."""
        with self._lock:
            session = self._session
        if session is None:
            return
        session.take(frame)
        if session.is_open or session.is_ended:
            self._news.set()

    def _on_question(self, question: dict) -> dict:
        """Answer the transport: is a port published now, and where."""
        if question.get("question") != QUESTION_PORT:
            return {"code": "control_unavailable", "params": {}}
        port = question.get("port")
        protocol = str(question.get("protocol", "") or AGENT_CONNECT_TCP)
        published = self._published_ports(protocol)
        if isinstance(port, int) and not isinstance(port, bool) and port in published:
            return {"address": published[port]}
        return {"code": AGENT_CODE_PORT_NOT_PUBLISHED, "params": {"port": port}}

    def _on_transport_closed(self) -> None:
        """The control connection ended: the next turn starts the transport again."""
        with self._lock:
            session = self._session
        if session is not None:
            session.end()
        self._ai_forward.reset()
        self._news.set()

    def _on_welcomed(self, session: AgentSession) -> None:
        """A session the hub welcomed: the hub's clock, the address, no error."""
        hub_clock().take(session.hub_time)
        if session.address:
            self._note_url(session.address)
        with self._lock:
            self._backoff_s = AGENT_BACKOFF_MIN_S
            self._last_error = None
            is_run = self._unavailable_logged_at is not None
            count = self._unavailable_count
            self._unavailable_count = 0
            self._unavailable_logged_at = None
        line = f"the hub welcomed this machine at {session.address or '?'}"
        if is_run and count:
            line += (
                f"; refused {AGENT_CODE_CONTROL_UNAVAILABLE} {count} times"
                " since the last line"
            )
        self._log(line)

    def _on_session_ended(self, session: AgentSession) -> float:
        """A session that ended: its refusal read by code, or the wire's end."""
        with self._lock:
            if self._session is session:
                self._session = None
        if session.refusal is not None:
            return self._take_refusal(session.refusal)
        with self._lock:
            if self._last_error is None:
                self._last_error = {
                    "code": "hub_unreachable",
                    "params": {"detail": "the session ended"},
                }
        self._log("the session to the hub ended; the transport dials again")
        return IDLE_POLL_INTERVAL_S

    def _take_refusal(self, error: GatewayRefusedDetail) -> float:
        """Split a refusal by its code.

        ``binding_unknown`` deletes the binding, switches the AI tools back,
        turns the desktop share off and waits for a link; ``replaced`` keeps
        the binding and dials no more until a person acts; every other code
        keeps it while the transport dials again.

        Args:
            error: The refusal.

        Returns:
            Seconds until the next loop turn.
        """
        rejection = channel_error(error)
        code = rejection["code"]
        if code == AGENT_CODE_BINDING_UNKNOWN and self._is_binding_rewritten():
            self._log("a refusal of the binding written over since; it is not taken")
            return IDLE_POLL_INTERVAL_S
        if code == AGENT_CODE_BINDING_UNKNOWN:
            self._undial()
            enrollment.remove_binding()
            self._ai_forward.stop()
            self._ai_tools.switch_back_all()
            self._rdp.leave_hub()
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
            self._undial()
            self._log("replaced by another session; dialling again on nagent join")
            return IDLE_POLL_INTERVAL_S
        self._log_refusal(code)
        return IDLE_POLL_INTERVAL_S

    def _log_refusal(self, code: str) -> None:
        """Log a refusal the transport asks again after.

        ``control_unavailable`` writes its line at the first refusal, then at
        most once every ``AGENT_REFUSAL_LOG_INTERVAL_S`` with the count since
        the line before.

        Args:
            code: The refusal's code.
        """
        if code != AGENT_CODE_CONTROL_UNAVAILABLE:
            self._log(f"refused: {code}; the transport asks again")
            return
        now = self._clock()
        with self._lock:
            self._unavailable_count += 1
            logged_at = self._unavailable_logged_at
            if logged_at is not None and now - logged_at < AGENT_REFUSAL_LOG_INTERVAL_S:
                return
            count = self._unavailable_count
            self._unavailable_count = 0
            self._unavailable_logged_at = now
        if logged_at is None:
            self._log(f"refused: {code}; the transport asks again")
        else:
            self._log(
                f"refused: {code} {count} times since the last line;"
                " the transport asks again"
            )

    def _note_unreadable(self, error: dict) -> None:
        """A frame this build cannot read is the error the report shows."""
        with self._lock:
            self._last_error = dict(error)
        self._news.set()

    def _note_hub_key_missing(self) -> None:
        """Record ``hub_key_missing`` once while the binding file is of 0.5."""
        if self._binding or not enrollment.has_legacy_binding():
            return
        missing = {"code": AGENT_CODE_HUB_KEY_MISSING, "params": {}}
        with self._lock:
            if self._last_error == missing:
                return
            self._last_error = missing
        self._log("the binding of 0.5 holds no hub key; join again with a new link")

    def _stream_kinds(self) -> dict:
        """The stream kinds the hub opens, bound to this agent's parts."""
        return dict(
            STREAM_KINDS,
            **{
                STREAM_KIND_SHELL: functools.partial(
                    open_shell_stream,
                    sessions=self._shells,
                    terminal=self._terminal_settings,
                    platform=self._platform,
                    container_podman=self._container_podman,
                ),
                STREAM_KIND_EXEC: functools.partial(
                    open_exec_stream,
                    terminal=self._terminal_settings,
                    platform=self._platform,
                ),
            },
        )

    def _is_bound_and_wanted(self) -> bool:
        """Whether a session is to be dialled: bound, and not replaced."""
        with self._lock:
            return bool(self._binding) and not self._is_replaced

    def _terminal_settings(self):
        """The Terminal module's settings a new shell runs with."""
        runner = self._engine.module_runners.get(TERMINAL_NAME)
        return runner.settings() if runner is not None else TerminalConfig()

    def _container_podman(self) -> tuple:
        """The podman command a container's shell runs through.

        Returns:
            The Podman machine's read command where the machine runner
            holds the module, empty while it has no machine; this machine's
            ``podman`` everywhere else.

        Raises:
            ModuleApplyError: The machine runner's ``machine_unreachable``
                or ``account_unknown {account}``.
        """
        runner = self._engine.module_runners.get(PODMAN_MODULE_NAME)
        if isinstance(runner, PodmanMachineModuleRunner):
            return runner.read_command()
        return (PODMAN_BINARY,)

    def _relayed_ports(self) -> set:
        """The agent's loopback listeners a container reaches through the relays.

        Returns:
            The AI gateway forward's port while it listens, the gateway's
            own port the state names on the hub's own machine while the
            machine is bound, and every port a module's forwarder listens
            on.
        """
        with self._lock:
            is_bound = bool(self._binding)
        ports = {self._ai_forward.local_port}
        if is_bound:
            ports.add(gateway_port_of(self._desired.latest()))
        for runner in self._engine.module_runners.values():
            ports.update(runner.forwarder_ports())
        ports.discard(0)
        return ports

    def _published_ports(self, protocol: str = AGENT_CONNECT_TCP) -> dict:
        """Every port this machine publishes now on one protocol, each to the
        address it is dialled on, as :func:`published_ports` reads them."""
        modules = self._desired.latest().get("modules")
        return published_ports(
            self._engine.report(),
            modules if isinstance(modules, dict) else {},
            self.rdp_declaration(),
            protocol,
        )

    def _take_state(self, document: dict) -> None:
        """Keep the addresses a state names, open or close the AI gateway
        forward by it, then hand it to the applier.

        Args:
            document: The state, ``{hash, urls, modules, desktop}``.
        """
        urls = document.get("urls")
        if isinstance(urls, list):
            self._note_urls(urls)
        self._ai_forward.take(document)
        self._desired.take(document)

    def _note_url(self, gateway_url: str) -> None:
        """Write the address that answered onto the binding, when it changed."""
        with self._lock:
            if self._binding.get("gateway_url") == gateway_url:
                return
            try:
                enrollment.note_url(gateway_url)
            except OSError as error:
                self._log(f"could not record the hub's address: {error}")
                return
            self._binding["gateway_url"] = gateway_url
            self._binding_stamp = enrollment.config_stamp()

    def _note_urls(self, urls: list) -> None:
        """Write the hub's address list onto the binding, when it changed."""
        cleaned = enrollment.clean_urls(urls)
        with self._lock:
            if not self._binding or self._binding.get("gateway_urls") == cleaned:
                return
            try:
                enrollment.note_urls(cleaned)
            except OSError as error:
                self._log(f"could not record the hub's addresses: {error}")
                return
            self._binding["gateway_urls"] = cleaned
            self._binding_stamp = enrollment.config_stamp()
        self._log(f"the hub answers at {', '.join(cleaned)}")

    def _tick(self) -> None:
        """Between reports: look at the network, ask the transport for the AI
        gateway forward if it could not listen, write RustDesk's service
        settings again if they were replaced, and read the hub clock, so a
        setting of this machine's clock is taken up within one interval."""
        self._watch_network()
        self._ai_forward.ensure()
        self._rdp.repair_settings()
        hub_clock().now()

    def _watch_network(self) -> bool:
        """Look at the route to the hub; a change with no session up dials again.

        Returns:
            True when this machine's address on it changed since the last
            look; the first look and an unbound machine are no change.
        """
        with self._lock:
            binding = dict(self._binding)
            held = self._source_address
        if not binding:
            return False
        current = enrollment.default_source_address(enrollment.stored_urls(binding))
        with self._lock:
            self._source_address = current
            session = self._session
        if held is None or current == held:
            return False
        self._log(f"this machine's address toward the hub is now {current or 'none'}")
        if session is None or session.is_ended:
            with self._lock:
                self._dialed = None
        return True

    def _wait_out(self, delay: float) -> None:
        """Wait for the next turn: the delay, news, a binding written on
        disk, or a network change.

        The binding file is looked at every :data:`IDLE_POLL_INTERVAL_S`, so
        a ``nagent join`` from another process is taken within seconds; the
        route to the hub is looked at every report interval.

        Args:
            delay: How long the turn asked to wait.
        """
        deadline = time.monotonic() + delay
        network_at = time.monotonic()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if self._news.wait(timeout=min(remaining, IDLE_POLL_INTERVAL_S)):
                return
            is_changed = self._is_binding_rewritten()
            if not is_changed and time.monotonic() - network_at >= (
                AGENT_REPORT_INTERVAL_S
            ):
                network_at = time.monotonic()
                is_changed = self._watch_network()
            if is_changed:
                with self._lock:
                    self._backoff_s = AGENT_BACKOFF_MIN_S
                return

    def _is_binding_rewritten(self) -> bool:
        """Whether another process wrote the binding file since it was read."""
        with self._lock:
            return enrollment.config_stamp() != self._binding_stamp

    def _hello_payload(self, binding: dict) -> dict:
        """The identity card the hello carries.

        Args:
            binding: The binding the session runs under.

        Returns:
            ``{protocol, role, id, name, software}``.
        """
        return {
            "protocol": PROTOCOL,
            "role": AGENT_ROLE,
            "id": binding["id"],
            "name": hostname(),
            "software": f"{AGENT_SOFTWARE_PREFIX}{AGENT_VERSION}",
        }

    def _report_payload(self) -> dict:
        """What is true of this machine: the report's sections."""
        return {
            "state_hash": self._desired.applied_hash,
            "machine": {
                "hostname": hostname(),
                "platform": self._engine.platform_tuple,
                "accounts": self._read_accounts(),
                "account_details": self._read_account_details(),
                "metrics": self._read_metrics(),
                "sessions": self._shells.describe(),
            },
            "network": network.describe(self._link_address(), self._read_interfaces()),
            "modules": self._engine.report(),
            # Whether this machine's desktop is reachable. The seat
            # password it answers with stays on the machine.
            "desktop": self.rdp_declaration(),
            "ai_tools": self._ai_tools.report(),
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
            ``{"code", "params"}`` naming the exit status, the finish time
            and the installer's masked log tail as ``output``, or None when
            no record stands there or the install went through.
        """
        result = self_update.read_reinstall_result(self._var_dir)
        if result is None or result["exit_code"] in AGENT_REINSTALL_INSTALLED_CODES:
            return None
        return {
            "code": "reinstall_failed",
            "params": {
                "exit_code": result["exit_code"],
                "finished_at": result["finished_at"],
                "output": result["output"],
            },
        }

    def _open_stream(self, kind: str, **args):
        """Open a stream to the hub on the live session.

        Args:
            kind: The stream kind.
            **args: The kind's arguments.

        Returns:
            The stream's channel; a stream the hub refused holds its close.

        Raises:
            GatewayUnreachable: When no session is up.
        """
        with self._lock:
            control = self._control
            session = self._session
        if control is None or session is None or not session.is_open:
            raise GatewayUnreachable("no session to the hub")
        return control.open_stream({"kind": kind, **args})

    def _run_command(self, module: str, verb: str, args: dict, on_line=None) -> dict:
        with self._lock:
            operator_ = self._operator
        if operator_ is None:
            return {
                "exit_code": 1,
                "code": "hub_unreachable",
                "params": {},
                "output": "",
            }
        if not is_reading_command(module, verb):
            self._log(f"running {module} {verb}")
        outcome = operator_.run(module, verb, args, on_line)
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

        After the launch the install's result is waited for; an install
        that goes through restarts this process before the wait ends.

        Returns:
            Empty when the install was launched and wrote no failure in
            time; ``{"code", "params"}`` when it was not launched; and
            ``{"code": "reinstall_failed", "params", "output"}`` when the
            installer exited non-zero, ``output`` its masked log tail.
        """
        with self._lock:
            self._update_target = ""
        self._force_self_update("reinstall")
        with self._lock:
            if self._update_error:
                return dict(self._update_error)
        result = self_update.wait_reinstall_result(
            self._var_dir, timeout_s=AGENT_REINSTALL_WAIT_S
        )
        if result is None or result["exit_code"] in AGENT_REINSTALL_INSTALLED_CODES:
            return {}
        self._log(f"reinstall failed: the installer exited {result['exit_code']}")
        return {
            "code": "reinstall_failed",
            "params": {
                "exit_code": result["exit_code"],
                "finished_at": result["finished_at"],
            },
            "output": result["output"],
        }

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

    def _read_account_details(self) -> list:
        try:
            return self._platform.account_details()
        except PlatformUnsupportedError:
            return []

    def _read_interfaces(self) -> list:
        try:
            return self._platform.read_network_interfaces()
        except PlatformUnsupportedError:
            return []

    def _link_address(self) -> str:
        """The session's own address on this machine, empty with no session."""
        with self._lock:
            session = self._session
        return session.local_address if session is not None else ""

    def _reset_binding_state(self) -> None:
        """Forget what the last binding's sessions recorded."""
        with self._lock:
            self._last_error = None
            self._is_replaced = False
            self._update_target = ""
            self._update_error = None
            self._backoff_s = AGENT_BACKOFF_MIN_S
            self._reported = None

    def _load_connection(self) -> None:
        binding = enrollment.load_binding()
        with self._lock:
            self._binding = binding
            self._binding_stamp = enrollment.config_stamp()
            if binding:
                self._operator = DeviceOperator(
                    platform=self._platform,
                    reinstall=self._reinstall,
                    runner_of=self._engine.runner_of,
                    settle=self._desired.settle,
                    on_module_changed=self._report_module_now,
                    locks=self._desired.locks,
                )
            else:
                self._operator = None

    def _adopt_external_binding(self) -> None:
        """Pick up a binding another process wrote.

        ``nagent join`` and ``nagent leave`` edit the binding file from
        their own process. The service notices the file changing and
        converges: the session for a binding that is gone ends, and a new
        binding is dialled.
        """
        with self._lock:
            if enrollment.config_stamp() == self._binding_stamp:
                return
            binding = self._binding
        self._load_connection()
        with self._lock:
            if self._binding == binding:
                return
        self._desired.reload_tried()
        self._reset_binding_state()
        self._undial()
        self._ai_forward.stop()
        self._stop_transport()
        self._engine.take_state({})
        self._log("adopted the binding written on disk")

    def _force_self_update(self, target: str) -> None:
        """Reinstall this agent from the hub's package, version equal or not.

        Args:
            target: A name for what asked, latched like a version target so
                a failed attempt is not retried on every session.
        """
        with self._lock:
            if target == self._update_target:
                return
            self._update_target = target
            self._update_error = None
            session = self._session
        kind = self_update.package_kind(self._engine.platform_tuple)
        if not kind:
            self._log("no reinstall: no package for this platform")
            with self._lock:
                self._update_error = {
                    "code": "agent_package_missing",
                    "params": {"target": target},
                }
            return
        hub_version = (
            hub_version_of(session.hub_software) if session is not None else ""
        )
        self._log("reinstalling from the hub's package")
        if self._install_from_hub(target, kind, hub_version):
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
        if self._install_from_hub(hub_version, kind, hub_version):
            self._log(f"self-update to {hub_version} launched; the service restarts")

    def _install_from_hub(self, target: str, kind: str, version: str) -> bool:
        """Take this agent's package down a ``package {}`` stream and install it.

        A transfer the session dropped leaves the target unlatched, so the
        next session asks again; a package that did not match, a hub that
        refused, and an install that could not be launched latch it with
        their code.

        Args:
            target: What the attempt is latched under.
            kind: ``deb``, ``rpm``, ``msi`` or ``pkg``.
            version: The package's version, the hub's own, empty when the
                welcome named none. The install reinstalls when it is
                empty or this agent's own, and is to that version
                otherwise.

        Returns:
            True when the install was launched.
        """
        try:
            channel = self._open_stream(STREAM_KIND_PACKAGE)
            path = self_update.receive_package(
                channel, directory=self._package_dir, kind=kind
            )
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
        launch = functools.partial(self._launch_update, target, path, kind, version)
        locks = self._desired.locks
        if locks.try_acquire(PACKAGE_MANAGER_LOCKS, AGENT_LOCK_SELF_UPDATE_HOLDER):
            return launch()
        self._log(f"update to {target} waits for a module's package step to end")
        threading.Thread(
            target=self._launch_when_free,
            args=(launch,),
            name="self_update",
            daemon=True,
        ).start()
        return True

    def _launch_when_free(self, launch) -> None:
        """Take ``package_manager`` once a module's step lets it go, then launch the install."""
        self._desired.locks.acquire(
            PACKAGE_MANAGER_LOCKS, AGENT_LOCK_SELF_UPDATE_HOLDER
        )
        launch()

    def _launch_update(self, target: str, path: str, kind: str, version: str) -> bool:
        """Launch the install of this agent's package, holding ``package_manager``.

        The lock is held until the install's result is written or the hold
        runs out; an install that goes through restarts the agent first.

        Args:
            target: What the attempt is latched under.
            path: The package file, its digest checked.
            kind: ``deb``, ``rpm``, ``msi`` or ``pkg``.
            version: The package's version, as :meth:`_install_from_hub`
                takes it.

        Returns:
            True when the install was launched.
        """
        try:
            self_update.run_update(
                path,
                kind=kind,
                state_dir=self._var_dir,
                version=version,
                is_reinstall=version in ("", AGENT_VERSION),
            )
        except SelfUpdateError as error:
            self._desired.locks.release(
                PACKAGE_MANAGER_LOCKS, AGENT_LOCK_SELF_UPDATE_HOLDER
            )
            with self._lock:
                self._update_error = {"code": str(error), "params": {"target": target}}
            self._log(f"update to {target} failed: {error}")
            return False
        threading.Thread(
            target=self._release_after_update, name="self_update_hold", daemon=True
        ).start()
        return True

    def _release_after_update(self) -> None:
        """Let ``package_manager`` go once the launched install wrote its result."""
        self_update.wait_reinstall_result(self._var_dir, timeout_s=AGENT_UPDATE_HOLD_S)
        self._desired.locks.release(
            PACKAGE_MANAGER_LOCKS, AGENT_LOCK_SELF_UPDATE_HOLDER
        )


def _framed(lines: queue.Queue):
    """A frame callback that puts each frame on a queue as ``{frame}``."""

    def put(frame: dict) -> None:
        lines.put({"frame": frame})

    return put


def _probe_outcome(control, lines: queue.Queue, hello: dict) -> "dict | None":
    """Wait for one session's welcome, writing ``hello`` when it opens.

    Args:
        control: The one-shot transport's control client.
        lines: Its events and frames, in order.
        hello: The identity card.

    Returns:
        None when the hub welcomed this machine; the refusal, or
        ``hub_unreachable``, otherwise.
    """
    deadline = time.monotonic() + AGENT_PROBE_TIMEOUT_S
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {
                "code": "hub_unreachable",
                "params": {"detail": "no address answered in time"},
            }
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            continue
        frame = line.get("frame")
        if isinstance(frame, dict):
            if frame.get("type") == "welcome":
                return None
            if frame.get("type") == "refused":
                return channel_error(refusal_of(frame))
            continue
        if line.get("event") == EVENT_SESSION_OPEN:
            control.send_frame({"type": "hello", **hello})
        elif line.get("event") == EVENT_SESSION_END and line.get("code"):
            return channel_error(refusal_of(line))
