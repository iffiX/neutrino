"""Running each vendor's frpc, reading where it stands, and the vendor calls.

The applier makes one stored vendor true: frpc's file under the state root
and the process under the controller's name, ``sakurafrp`` or ``openfrp``,
which is a unit of its own on Linux and a child of the hub's service on
macOS and Windows. The vendor is called only when a tunnel is picked and the
file is missing. The monitor reads the process every second and checks the
public address from outside, and its view is the vendor's state. The login
asks OpenFrp for an authorization URL and polls until the person confirms.
Nothing here prints a credential.
"""

import base64
import concurrent.futures
import datetime
import logging
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from neutrino_hub.exceptions import FrpVendorError, VaultLockedError
from neutrino_hub.modules.frp.config import FrpConfig, read_frp, write_frp
from neutrino_hub.modules.frp.constants import (
    FRP_BINARY_PATH,
    FRP_CHANGE_STARTED,
    FRP_CHANGE_STOPPED,
    FRP_CHECK_FIRST_S,
    FRP_CHECK_FOREIGN,
    FRP_CHECK_INTERVAL_S,
    FRP_CHECK_NO_ANSWER,
    FRP_CHECK_TIMEOUT_S,
    FRP_CODE_CONFIG_UNUSABLE,
    FRP_CODE_NOT_SIGNED_IN,
    FRP_CODE_TUNNEL_UNKNOWN,
    FRP_DIR_MODE,
    FRP_FILE_MODE,
    FRP_FILE_NAME,
    FRP_LATENCY_TIMEOUT_S,
    FRP_LOG_LINES,
    FRP_LOGIN_FAILED,
    FRP_LOGIN_IDLE,
    FRP_LOGIN_TIMED_OUT,
    FRP_LOGIN_WAITING,
    FRP_LOOPBACK_PORTS,
    FRP_OPENFRP,
    FRP_OPENFRP_LOGIN_POLL_S,
    FRP_OPENFRP_LOGIN_TIMEOUT_S,
    FRP_SAKURAFRP,
    FRP_STATE_CONFIG_FAILED,
    FRP_STATE_CONNECTED,
    FRP_STATE_CONNECTING,
    FRP_STATE_DISABLED,
    FRP_STATE_LOOPBACK_PORT_TAKEN,
    FRP_STATE_NO_TUNNEL,
    FRP_STATE_NOT_SIGNED_IN,
    FRP_STATE_PORT_CLOSED,
    FRP_STATE_PROXY_REFUSED,
    FRP_STATE_VAULT_LOCKED,
    FRP_TICK_S,
    FRP_TITLES,
    FRP_UNITS,
)
from neutrino_hub.modules.frp.nacl_box import box_open
from neutrino_hub.modules.frp.renderer import (
    judge_exit,
    refused_line,
    render_frpc,
    server_port,
)
from neutrino_hub.modules.frp.tunnels import (
    FrpTunnel,
    openfrp_tunnels,
    sakurafrp_tunnels,
)
from neutrino_hub.modules.frp.vendor_api import OpenFrpApi, SakuraFrpApi
from neutrino_hub.modules.overlay.relay_ops import check_public_address
from neutrino_hub.platforms.detect import hub_platform, is_linux
from neutrino_hub.system.constants import SYSTEM_SYSTEMD_DIR
from neutrino_hub.utils.constants import (
    UTILS_DATA_DIR,
    UTILS_STATE_ROOT,
    is_dev_root_set,
)
from neutrino_hub.utils.json_file import write_generated

LOGGER = logging.getLogger(__name__)

# One apply at a time for each vendor, each on the file as it stands.
FRP_APPLY_LOCKS = {vendor: threading.Lock() for vendor in FRP_LOOPBACK_PORTS}


def frp_dir(vendor: str) -> Path:
    """The directory holding one vendor's file.

    Args:
        vendor: ``sakurafrp`` or ``openfrp``.

    Returns:
        ``<state>/<vendor>``.
    """
    return UTILS_STATE_ROOT / vendor


def frp_file(vendor: str) -> Path:
    """The file one vendor's frpc runs from.

    Args:
        vendor: ``sakurafrp`` or ``openfrp``.

    Returns:
        ``<state>/<vendor>/frpc.toml``.
    """
    return frp_dir(vendor) / FRP_FILE_NAME


def is_frpc_present() -> bool:
    """Whether the package's frpc is on this machine."""
    return FRP_BINARY_PATH.is_file()


def vendor_api(config: FrpConfig, *, transport: "Callable | None" = None):
    """The vendor's API under the stored credential.

    A new ``Authorization`` OpenFrp hands back is sealed into the file.

    Args:
        config: The stored vendor.
        transport: How requests reach the vendor.

    Returns:
        A :class:`SakuraFrpApi` or an :class:`OpenFrpApi`.

    Raises:
        FrpVendorError: ``frp_not_signed_in`` when no credential is stored.
        VaultLockedError: If the vault is locked.
        ValueError: If the sealed credential does not open.
    """
    credential = config.credential()
    if not credential:
        raise FrpVendorError(FRP_CODE_NOT_SIGNED_IN, title=FRP_TITLES[config.vendor])
    if config.vendor == FRP_SAKURAFRP:
        return SakuraFrpApi(credential, transport=transport)
    return OpenFrpApi(credential, on_rotated=reseal_authorization, transport=transport)


def reseal_authorization(authorization: str) -> None:
    """Seal a rotated OpenFrp ``Authorization`` in place of the stored one.

    Args:
        authorization: The one OpenFrp handed back.
    """
    config = read_frp(FRP_OPENFRP)
    if not config.is_signed_in:
        return
    try:
        config.set_credential(authorization)
        write_frp(config)
    except (VaultLockedError, OSError) as error:
        LOGGER.warning("openfrp: the new authorization is not kept: %s", error)


def account_tunnels(api, vendor: str, *, agent_port: "int | None") -> list:
    """The account's tunnels the hub would list.

    Args:
        api: The vendor's API.
        vendor: ``sakurafrp`` or ``openfrp``.
        agent_port: The connection port the local port must be; None takes
            a tunnel whatever its local port.

    Returns:
        :class:`FrpTunnel` rows, each ``local_port`` the vendor's own.

    Raises:
        FrpVendorError: When the vendor refuses or does not answer.
    """
    if vendor == FRP_SAKURAFRP:
        tunnels = api.tunnels()
        nodes = api.nodes()
        if agent_port is None:
            return [
                row
                for tunnel in tunnels
                for row in sakurafrp_tunnels(
                    [tunnel], nodes, agent_port=_port_of(tunnel, "local_port")
                )
            ]
        return sakurafrp_tunnels(tunnels, nodes, agent_port=agent_port)
    proxies = api.user_proxies()
    nodes = api.node_list()
    if agent_port is None:
        return [
            row
            for proxy in proxies
            for row in openfrp_tunnels(
                [proxy], nodes, agent_port=_port_of(proxy, "localPort")
            )
        ]
    return openfrp_tunnels(proxies, nodes, agent_port=agent_port)


def tunnel_file_text(api, vendor: str, tunnel: FrpTunnel) -> str:
    """frpc's file for one tunnel, from the vendor's config.

    Args:
        api: The vendor's API.
        vendor: ``sakurafrp`` or ``openfrp``.
        tunnel: The tunnel.

    Returns:
        The TOML :func:`render_frpc` writes.

    Raises:
        FrpVendorError: When the vendor refuses or does not answer, and
            ``frp_config_unusable`` when its config holds no proxy of the
            tunnel's name.
    """
    text = (
        api.tunnel_config(tunnel.tunnel_id)
        if vendor == FRP_SAKURAFRP
        else api.node_conf(tunnel.node_id)
    )
    try:
        return render_frpc(
            text, tunnel_name=tunnel.name, loopback_port=FRP_LOOPBACK_PORTS[vendor]
        )
    except ValueError as error:
        raise FrpVendorError(
            FRP_CODE_CONFIG_UNUSABLE, title=FRP_TITLES[vendor]
        ) from error


def listed_tunnels(
    api,
    vendor: str,
    *,
    agent_port: int,
    dial: "Callable | None" = None,
) -> list:
    """The tunnel list, each row with the latency from the hub to its node.

    SakuraFrp names the node's port in each tunnel's config alone, so each
    listed tunnel's config is read too; every config and every node is
    asked at once.

    Args:
        api: The vendor's API.
        vendor: ``sakurafrp`` or ``openfrp``.
        agent_port: The connection port.
        dial: ``dial(host, port)`` returns the connect time in milliseconds,
            None when none finished in time.

    Returns:
        ``(tunnel, latency_ms)`` pairs in the vendor's order.

    Raises:
        FrpVendorError: When the vendor refuses or does not answer.
    """
    rows = account_tunnels(api, vendor, agent_port=agent_port)
    if vendor == FRP_SAKURAFRP and rows:
        with concurrent.futures.ThreadPoolExecutor(len(rows)) as pool:
            ports = list(pool.map(lambda row: _sakurafrp_port(api, row), rows))
        rows = [
            FrpTunnel(**{**row.__dict__, "dial_port": port})
            for row, port in zip(rows, ports)
        ]
    return list(zip(rows, measure_latencies(rows, dial=dial or connect_ms)))


def measure_latencies(rows: list, *, dial: Callable) -> list:
    """Dial every node at once.

    Args:
        rows: The tunnels.
        dial: ``dial(host, port)``, as :func:`listed_tunnels` takes it.

    Returns:
        One latency per row, None for a row with no node address.
    """
    if not rows:
        return []
    with concurrent.futures.ThreadPoolExecutor(len(rows)) as pool:
        return list(
            pool.map(
                lambda row: (
                    dial(row.dial_host, row.dial_port)
                    if row.dial_host and row.dial_port
                    else None
                ),
                rows,
            )
        )


def connect_ms(host: str, port: int) -> "int | None":
    """How long one TCP connect from the hub takes.

    Args:
        host: The node.
        port: Its port.

    Returns:
        Milliseconds; None when no connect finished within
        ``FRP_LATENCY_TIMEOUT_S``.
    """
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=FRP_LATENCY_TIMEOUT_S):
            return max(1, round((time.monotonic() - started) * 1000))
    except (OSError, ValueError):
        return None


def find_tunnel(rows: list, vendor: str, tunnel_id: str) -> FrpTunnel:
    """One tunnel of a list, by id.

    Args:
        rows: The tunnels.
        vendor: ``sakurafrp`` or ``openfrp``.
        tunnel_id: The id asked for.

    Returns:
        The tunnel.

    Raises:
        FrpVendorError: ``frp_tunnel_unknown`` when the list does not hold it.
    """
    for row in rows:
        if row.tunnel_id == tunnel_id:
            return row
    raise FrpVendorError(
        FRP_CODE_TUNNEL_UNKNOWN, title=FRP_TITLES[vendor], tunnel_id=tunnel_id
    )


def write_frpc_file(vendor: str, text: str) -> None:
    """Write frpc's file root-only.

    Args:
        vendor: ``sakurafrp`` or ``openfrp``.
        text: The file.

    Raises:
        OSError: If it cannot be written.
    """
    frp_dir(vendor).mkdir(mode=FRP_DIR_MODE, parents=True, exist_ok=True)
    write_generated(frp_file(vendor), text, mode=FRP_FILE_MODE)
    hub_platform().make_root_only(frp_file(vendor))


def remove_frpc_file(vendor: str) -> None:
    """Delete frpc's file.

    Args:
        vendor: ``sakurafrp`` or ``openfrp``.
    """
    frp_file(vendor).unlink(missing_ok=True)


def store_tunnel(config: FrpConfig, tunnel: FrpTunnel) -> None:
    """Keep the picked tunnel in the vendor's file.

    Args:
        config: The stored vendor, changed in place.
        tunnel: The tunnel the person picked.

    Raises:
        OSError: If the file cannot be written.
    """
    config.tunnel_id = tunnel.tunnel_id
    config.node_name = tunnel.node_name
    config.local_port = tunnel.local_port
    config.public_host = tunnel.public_host
    config.public_port = tunnel.public_port
    write_frp(config)


def _sakurafrp_port(api, row: FrpTunnel) -> int:
    """The node's port a SakuraFrp tunnel's config names; 0 when unread."""
    try:
        return server_port(api.tunnel_config(row.tunnel_id))
    except (FrpVendorError, ValueError):
        return 0


def _port_of(entry: dict, key: str) -> int:
    """A vendor's port field as a number; 0 for none."""
    try:
        return int(entry.get(key) or 0)
    except (TypeError, ValueError):
        return 0


class FrpApplier:
    """Makes one stored vendor the frpc that runs."""

    def __init__(
        self, *, controller, monitor: "FrpMonitor", transport: "Callable | None" = None
    ):
        """
        Args:
            controller: The process controller the hub runs its daemons with.
            monitor: The vendor's monitor, told of a config that could not
                be fetched and of each new run.
            transport: How requests reach the vendor.
        """
        self._controller = controller
        self._monitor = monitor
        self._transport = transport

    def apply(self, config: FrpConfig, *, is_restarted: bool = False) -> str:
        """Run frpc while the way in is on and a tunnel is picked, else stop it.

        A missing file is fetched from the vendor first. Nothing is started
        again when frpc runs and the file was already there, unless asked.

        Args:
            config: The stored vendor.
            is_restarted: Whether a running frpc is started again anyway.

        Returns:
            ``frp_started`` or ``frp_stopped`` for what changed, empty when
            nothing did.

        Raises:
            OSError: If the file cannot be written.
            subprocess.CalledProcessError: If the system refuses the unit.
        """
        vendor = config.vendor
        with FRP_APPLY_LOCKS[vendor]:
            if not (config.is_enabled and config.has_tunnel and is_frpc_present()):
                self._monitor.note_config_failed("")
                return self._stop(vendor)
            is_changed = False
            if not frp_file(vendor).is_file():
                if not self._fetch(config):
                    return self._stop(vendor)
                is_changed = True
            self._monitor.note_config_failed("")
            if not self._is_unit_owned():
                return ""
            if not is_changed and not is_restarted and self._is_running(vendor):
                return ""
            self._start(vendor)
            self._monitor.restart_checks()
            return FRP_CHANGE_STARTED

    def _fetch(self, config: FrpConfig) -> bool:
        """Fetch the picked tunnel's config and write frpc's file.

        The tunnel is found among all the account's tunnels by its id, so a
        tunnel whose local port no longer is the connection port is found
        too.

        Returns:
            Whether the file was written; the monitor is told why when not.
        """
        vendor = config.vendor
        try:
            api = vendor_api(config, transport=self._transport)
            rows = account_tunnels(api, vendor, agent_port=None)
            tunnel = find_tunnel(rows, vendor, config.tunnel_id)
            text = tunnel_file_text(api, vendor, tunnel)
        except VaultLockedError:
            return False
        except (FrpVendorError, ValueError) as error:
            self._monitor.note_config_failed(_failure_text(error))
            return False
        write_frpc_file(vendor, text)
        return True

    def _start(self, vendor: str) -> None:
        """Hand the start line over and run frpc on it."""
        if is_linux():
            self._refresh_unit(vendor)
        else:
            self._controller.set_start_line(
                vendor, [str(FRP_BINARY_PATH), "-c", str(frp_file(vendor))], {}, None
            )
        if self._controller.is_enabled(vendor):
            self._controller.restart(vendor)
            return
        self._controller.enable(vendor)
        if is_linux():
            self._controller.restart(vendor)

    def _stop(self, vendor: str) -> str:
        """Stop frpc, forget its start line and delete its file."""
        note = ""
        if self._is_unit_owned() and self._is_standing(vendor):
            try:
                self._controller.stop(vendor)
            except (RuntimeError, subprocess.SubprocessError, KeyError):
                pass
            self._controller.disable(vendor)
            if not is_linux():
                self._controller.set_start_line(vendor, None, {}, None)
            note = FRP_CHANGE_STOPPED
        remove_frpc_file(vendor)
        return note

    def _is_standing(self, vendor: str) -> bool:
        """Whether frpc runs or would start with the machine."""
        try:
            status = self._controller.status(vendor)
        except (KeyError, OSError):
            return False
        return status.is_active or status.is_enabled

    def _is_running(self, vendor: str) -> bool:
        """Whether frpc runs now."""
        try:
            return self._controller.is_active(vendor)
        except (KeyError, OSError):
            return False

    def _is_unit_owned(self) -> bool:
        """Whether this hub drives frpc; a development root on Linux drives
        no units."""
        return not (is_linux() and is_dev_root_set())

    def _refresh_unit(self, vendor: str) -> None:
        """Install or update the vendor's unit."""
        unit = FRP_UNITS[vendor]
        text = (UTILS_DATA_DIR / "services" / unit).read_text(encoding="utf-8")
        path = SYSTEM_SYSTEMD_DIR / unit
        try:
            if path.read_text(encoding="utf-8") == text:
                return
        except OSError:
            pass
        path.write_text(text, encoding="utf-8")
        self._controller.reload()


class FrpMonitor:
    """Reads one vendor's frpc and checks its public address.

    One thread ticks every ``FRP_TICK_S``. A process with a new id is a new
    run: its first check comes ``FRP_CHECK_FIRST_S`` after it is seen and
    the next ones every ``FRP_CHECK_INTERVAL_S``.
    """

    def __init__(
        self,
        *,
        vendor: str,
        controller,
        fingerprint_of: Callable[[], str],
        is_listener_taken: Callable[[str], bool] = lambda vendor: False,
        check=check_public_address,
        clock=time.monotonic,
    ):
        """
        Args:
            vendor: ``sakurafrp`` or ``openfrp``.
            controller: The process controller the hub runs its daemons with.
            fingerprint_of: Returns the hub's own agent certificate's
                SHA-256 hex.
            is_listener_taken: Whether the vendor's loopback listener could
                not open.
            check: ``check(host, port, timeout_s=...)`` returns the
                fingerprint met at the public address, empty for none.
            clock: The monotonic clock.
        """
        self._vendor = vendor
        self._controller = controller
        self._fingerprint_of = fingerprint_of
        self._is_listener_taken = is_listener_taken
        self._check = check
        self._clock = clock
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._process_id = 0
        self._started_at = 0.0
        self._checked_at = 0.0
        self._checked_at_text = ""
        # None before the first check of a run; then whether it met the
        # hub's own certificate.
        self._is_check_matched: "bool | None" = None
        self._check_error = ""
        self._config_error = ""

    def start(self) -> None:
        """Tick on a thread of its own until :meth:`stop`."""
        threading.Thread(
            target=self._run, name=f"{self._vendor}_monitor", daemon=True
        ).start()

    def stop(self) -> None:
        """End the thread."""
        self._stopping.set()

    def restart_checks(self) -> None:
        """Forget the last check; the next run is checked afresh."""
        with self._lock:
            self._process_id = 0
            self._is_check_matched = None
            self._check_error = ""

    def note_config_failed(self, reason: str) -> None:
        """Record why the picked tunnel's config could not be fetched.

        Args:
            reason: The failure; empty once a file is there again.
        """
        with self._lock:
            self._config_error = reason

    def tick(self) -> None:
        """Read the process once, and check the public address when due.

        A way in that is off or has no tunnel reads nothing.
        """
        config = read_frp(self._vendor)
        if not (config.is_enabled and config.has_tunnel):
            return
        process_id = self._read_process_id()
        now = self._clock()
        with self._lock:
            if process_id and process_id != self._process_id:
                self._started_at = now
                self._is_check_matched = None
                self._check_error = ""
            self._process_id = process_id
            is_due = bool(process_id) and (
                (
                    self._is_check_matched is None
                    and now - self._started_at >= FRP_CHECK_FIRST_S
                )
                or (
                    self._is_check_matched is not None
                    and now - self._checked_at >= FRP_CHECK_INTERVAL_S
                )
            )
        if not is_due or not config.public_host:
            return
        self._run_check(config)

    def view(self) -> dict:
        """Where the vendor stands now.

        Returns:
            ``{state, last_error, checked_at}``.
        """
        state, last_error = self._state(read_frp(self._vendor))
        with self._lock:
            checked_at = self._checked_at_text
        return {"state": state, "last_error": last_error, "checked_at": checked_at}

    def _state(self, config: FrpConfig) -> tuple:
        """The state code and its last error, in network.md's order."""
        if not config.is_enabled:
            return FRP_STATE_DISABLED, ""
        if not config.is_signed_in:
            return FRP_STATE_NOT_SIGNED_IN, ""
        try:
            config.credential()
        except (VaultLockedError, ValueError):
            return FRP_STATE_VAULT_LOCKED, ""
        if not config.tunnel_id:
            return FRP_STATE_NO_TUNNEL, ""
        if self._is_listener_taken(self._vendor):
            return FRP_STATE_LOOPBACK_PORT_TAKEN, ""
        with self._lock:
            config_error = self._config_error
        if config_error and not frp_file(self._vendor).is_file():
            return FRP_STATE_CONFIG_FAILED, config_error
        process_id = self._read_process_id()
        with self._lock:
            is_same_run = process_id and process_id == self._process_id
            matched = self._is_check_matched if is_same_run else None
            error = self._check_error
        if process_id:
            if matched:
                return FRP_STATE_CONNECTED, ""
            refused = refused_line(self._output())
            if refused:
                return FRP_STATE_PROXY_REFUSED, refused
            if matched is None:
                return FRP_STATE_CONNECTING, ""
            return FRP_STATE_PORT_CLOSED, error
        lines = self._output()
        if not lines:
            return FRP_STATE_CONNECTING, ""
        return judge_exit(lines)

    def _output(self) -> list:
        """frpc's last lines, of the run going on or the last one."""
        try:
            return self._controller.run_output(self._vendor, line_count=FRP_LOG_LINES)
        except (KeyError, OSError):
            return []

    def _run_check(self, config: FrpConfig) -> None:
        """Dial the public address and compare what answers with the hub."""
        address = f"{config.public_host}:{config.public_port}"
        met = self._check(
            config.public_host, config.public_port, timeout_s=FRP_CHECK_TIMEOUT_S
        )
        try:
            own = self._fingerprint_of()
        except (OSError, ValueError):
            own = ""
        if not met:
            error = FRP_CHECK_NO_ANSWER.format(address=address)
        elif met != own:
            error = FRP_CHECK_FOREIGN.format(address=address)
        else:
            error = ""
        with self._lock:
            self._checked_at = self._clock()
            self._checked_at_text = (
                datetime.datetime.now(datetime.timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            )
            self._is_check_matched = not error
            self._check_error = error

    def _read_process_id(self) -> int:
        """frpc's process id now, 0 when none runs."""
        try:
            return self._controller.process_id(self._vendor)
        except (KeyError, OSError, NotImplementedError):
            return 0

    def _run(self) -> None:
        """Tick until stopped; a tick that fails waits for the next."""
        while not self._stopping.wait(FRP_TICK_S):
            try:
                self.tick()
            except (OSError, ValueError, RuntimeError):
                continue


class OpenFrpLogin:
    """OpenFrp's remote login: one at a time, polled on a thread.

    Attributes:
        is_expired: Whether OpenFrp answered 401 to the stored
            ``Authorization``; cleared by a login and a logout.
    """

    def __init__(
        self,
        *,
        on_signed_in: Callable[[], None] = lambda: None,
        transport: "Callable | None" = None,
        clock=time.monotonic,
        wait: "Callable[[float], bool] | None" = None,
        spawn: "Callable | None" = None,
    ):
        """
        Args:
            on_signed_in: Called after a login's ``Authorization`` is stored.
            transport: How requests reach OpenFrp.
            clock: The monotonic clock.
            wait: ``wait(seconds)`` sleeps and returns True when the login
                was replaced or ended meanwhile; None waits on an event.
            spawn: ``spawn(target, args)`` runs the poll; None runs it on a
                thread of its own.
        """
        self._on_signed_in = on_signed_in
        self._transport = transport
        self._clock = clock
        self._wait = wait
        self._spawn = spawn or _spawn_thread
        self._lock = threading.Lock()
        self._generation = 0
        self._cancelled = threading.Event()
        self._state = FRP_LOGIN_IDLE
        self._authorization_url = ""
        self.is_expired = False

    def view(self) -> dict:
        """Where the login stands.

        Returns:
            ``{state, authorization_url}``, the URL empty unless ``waiting``.
        """
        with self._lock:
            url = self._authorization_url if self._state == FRP_LOGIN_WAITING else ""
            return {"state": self._state, "authorization_url": url}

    def start(self) -> None:
        """Ask for an authorization URL and poll for the person's confirmation.

        Any login in progress is replaced.

        Raises:
            FrpVendorError: ``frp_vendor_unreachable`` when OpenFrp gives no
                URL.
        """
        private = X25519PrivateKey.generate()
        public = base64.urlsafe_b64encode(
            private.public_key().public_bytes_raw()
        ).decode()
        api = OpenFrpApi(transport=self._transport)
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._cancelled.set()
            self._cancelled = threading.Event()
            cancelled = self._cancelled
        try:
            url, request_uuid = api.request_login(public)
        except FrpVendorError:
            self._settle(generation, FRP_LOGIN_FAILED)
            raise
        with self._lock:
            if generation != self._generation:
                return
            self._state = FRP_LOGIN_WAITING
            self._authorization_url = url
        self._spawn(
            self.poll,
            (api, request_uuid, private.private_bytes_raw(), generation, cancelled),
        )

    def end(self) -> None:
        """Stop any login in progress and go back to idle."""
        with self._lock:
            self._generation += 1
            self._cancelled.set()
            self._state = FRP_LOGIN_IDLE
            self._authorization_url = ""

    def poll(
        self,
        api: OpenFrpApi,
        request_uuid: str,
        private_key: bytes,
        generation: int,
        cancelled: threading.Event,
    ) -> None:
        """Poll every ``FRP_OPENFRP_LOGIN_POLL_S`` for at most
        ``FRP_OPENFRP_LOGIN_TIMEOUT_S``, and store what the person confirmed.

        Args:
            api: The client the URL came from.
            request_uuid: The login request.
            private_key: The X25519 private key the answer is sealed to.
            generation: Which login this is; a newer one ends this one.
            cancelled: Set when this login is replaced or ended.
        """
        started = self._clock()
        while True:
            if self._is_waited_out(cancelled):
                return
            if generation != self._generation:
                return
            try:
                answer = api.poll_login(request_uuid)
            except FrpVendorError as error:
                LOGGER.info("openfrp login: %s", error.params.get("detail", ""))
                answer = None
            if answer is not None:
                self._finish(answer, private_key, generation)
                return
            if self._clock() - started >= FRP_OPENFRP_LOGIN_TIMEOUT_S:
                self._settle(generation, FRP_LOGIN_TIMED_OUT)
                return

    def _is_waited_out(self, cancelled: threading.Event) -> bool:
        """Wait one poll interval; True when the login ended meanwhile."""
        if self._wait is not None:
            return self._wait(FRP_OPENFRP_LOGIN_POLL_S)
        return cancelled.wait(FRP_OPENFRP_LOGIN_POLL_S)

    def _finish(self, answer: tuple, private_key: bytes, generation: int) -> None:
        """Open the sealed ``Authorization`` and store it."""
        sealed_text, server_key = answer
        try:
            authorization = box_open(
                _base64_bytes(sealed_text),
                peer_public=_base64_bytes(server_key),
                own_private=private_key,
            ).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            LOGGER.warning("openfrp login: the answer does not open: %s", error)
            self._settle(generation, FRP_LOGIN_FAILED)
            return
        config = read_frp(FRP_OPENFRP)
        try:
            config.set_credential(authorization)
            write_frp(config)
        except (VaultLockedError, OSError) as error:
            LOGGER.warning("openfrp login: not stored: %s", error)
            self._settle(generation, FRP_LOGIN_FAILED)
            return
        self.is_expired = False
        self._settle(generation, FRP_LOGIN_IDLE)
        self._on_signed_in()

    def _settle(self, generation: int, state: str) -> None:
        """End this login in a state, unless a newer one replaced it."""
        with self._lock:
            if generation != self._generation:
                return
            self._state = state
            self._authorization_url = ""


def _spawn_thread(target: Callable, args: tuple) -> None:
    """Run the login's poll on a daemon thread."""
    threading.Thread(
        target=target, args=args, name="openfrp_login", daemon=True
    ).start()


def _base64_bytes(text: str) -> bytes:
    """Base64 in either alphabet, with or without its padding."""
    cleaned = text.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(cleaned + "=" * (-len(cleaned) % 4), validate=True)


def _failure_text(error: Exception) -> str:
    """The reason a fetch failed, for ``last_error``."""
    if isinstance(error, FrpVendorError):
        detail = error.params.get("detail", "")
        return f"{error.code}: {detail}" if detail else error.code
    return str(error)
