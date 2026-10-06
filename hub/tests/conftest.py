"""Shared fixtures and builders for the test suite.

Two rules hold everywhere in ``tests/``.

**Nothing touches the real appliance.** No test reads ``config/``, reconfigures
an interface, or restarts a service. The pure layers are exercised directly,
and the layers that talk to the system are given a stub that answers from a
dictionary. A test suite that could take the gateway off the network would be
one nobody dares run on the gateway.

**Anything that shells out declares it.** The renderers are checked against the
real validators where that is possible unprivileged — ``dnsmasq --test`` is —
and marked ``needs_root`` where it is not, because ``nft -c`` needs to open a
netlink socket. Those skip with a reason rather than failing.

The first rule is enforced, not only stated: every test runs under a guard on
``subprocess.run`` that refuses a program changing the machine — a
``systemctl`` that starts, stops, enables or masks, an ``nft`` that loads or
deletes, an ``ip`` that adds or removes, and everything polkit would ask a
person to authorize. A test that reaches one fails naming the command, rather
than stopping a unit on the developer's box or opening a password dialog.
"""

import os
import secrets
import subprocess
import sys

import pytest

from neutrino_hub import edition

# What a test may run: the program, and the verbs of it that only read. A
# program not listed here is refused outright; one listed is refused unless
# the first word of it that is not an option is one of these.
READ_ONLY_VERBS = {
    "systemctl": {
        "is-active",
        "is-enabled",
        "is-failed",
        "show",
        "status",
        "cat",
        "list-units",
        "list-unit-files",
    },
    "ip": {
        "addr",
        "address",
        "link",
        "route",
        "rule",
        "neigh",
        "-json",
        "-4",
        "-6",
        "-d",
        "-br",
        "-brief",
    },
    "nft": {"-c", "--check", "list"},
    "resolvectl": {"status", "query", "dns", "domain"},
    "nmcli": {"-t", "-g", "device", "general", "connection", "-f", "--fields"},
    "iw": {"dev", "list", "reg", "phy"},
    "journalctl": set(),
    "loginctl": {"list-sessions", "show-session", "list-users"},
}
REFUSED_PROGRAMS = {
    "pkexec",
    "sudo",
    "runuser",
    "su",
    "mount",
    "umount",
    "apt-get",
    "apt",
    "dnf",
    "pacman",
    "useradd",
    "usermod",
    "userdel",
    "groupadd",
    "reboot",
    "shutdown",
    "poweroff",
}
MUTATING_IP_VERBS = {"add", "del", "delete", "replace", "change", "set", "flush"}

_real_subprocess_run = subprocess.run
_real_popen = subprocess.Popen


def _refuses(command) -> str | None:
    """Why a command must not run from a test, or None when it may."""
    if not isinstance(command, (list, tuple)) or not command:
        return None
    program = os.path.basename(str(command[0]))
    if program in REFUSED_PROGRAMS:
        return f"{program} would ask for authorization or change the machine"
    if program not in READ_ONLY_VERBS:
        return None
    words = [str(word) for word in command[1:]]
    if program == "ip":
        if "monitor" in words:
            return "ip monitor would run until something killed it"
        if any(word in MUTATING_IP_VERBS for word in words):
            return "ip would change an address, a link, a route or a rule"
        return None
    if program == "journalctl":
        return None
    verbs = READ_ONLY_VERBS[program]
    for word in words:
        if word in verbs:
            return None
        if not word.startswith("-"):
            return f"{program} {word} would change the machine"
    return None


@pytest.fixture(autouse=True)
def _no_test_reaches_the_machine(monkeypatch):
    """Refuse, by name, any command a test would run that changes the box."""

    def guarded_run(command, *arguments, **keywords):
        reason = _refuses(command)
        if reason is not None:
            test = os.environ.get("PYTEST_CURRENT_TEST", "a test")
            raise AssertionError(
                f"{test} reached the machine: {' '.join(map(str, command))} ({reason}); "
                "stub the applier that ran it"
            )
        return _real_subprocess_run(command, *arguments, **keywords)

    class GuardedPopen(_real_popen):
        """The same guard for a process started without `run`."""

        def __init__(self, command, *arguments, **keywords):
            reason = _refuses(command)
            if reason is not None:
                test = os.environ.get("PYTEST_CURRENT_TEST", "a test")
                raise AssertionError(
                    f"{test} reached the machine: "
                    f"{' '.join(map(str, command))} ({reason}); "
                    "stub what started it"
                )
            super().__init__(command, *arguments, **keywords)

    monkeypatch.setattr(subprocess, "run", guarded_run)
    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)


@pytest.fixture(autouse=True)
def _retry_marks_in_the_test(monkeypatch, tmp_path):
    """Keep the retry marks a press writes inside the test's own directory."""
    from neutrino_hub.modules.devices import retry_marks

    monkeypatch.setattr(
        retry_marks, "DEVICE_RETRY_MARKS_PATH", tmp_path / "device_retry_marks.json"
    )


@pytest.fixture(autouse=True)
def _one_controller_per_test(monkeypatch):
    """Start every test with no process controller handed out yet."""
    from neutrino_hub.platforms import detect

    monkeypatch.setattr(detect, "_CONTROLLER", None)


@pytest.fixture(params=["darwin", "win32"])
def hub_service(request, monkeypatch):
    """The hub's one service on macOS and on Windows, its manager faked.

    The test runs as that system: ``sys.platform`` says so for its length.
    """
    from neutrino_hub.platforms import darwin, detect, windows

    if request.param == "darwin":
        manager = FakeLaunchd()
        monkeypatch.setattr(darwin.subprocess, "run", manager)
    else:
        manager = FakeServiceControlManager()
        monkeypatch.setattr(windows.subprocess, "run", manager)
        monkeypatch.setattr(windows, "PLATFORM_SERVICE_POLL_S", 0.001)
        monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt())
    monkeypatch.setattr(detect.sys, "platform", request.param)
    return manager


@pytest.fixture(params=["darwin", "win32"])
def elsewhere(request, monkeypatch):
    """The hub runs on macOS, then on Windows, for the test's length.

    Returns:
        ``darwin`` or ``win32``, what ``sys.platform`` says.
    """
    from neutrino_hub.platforms import detect

    monkeypatch.setattr(detect.sys, "platform", request.param)
    if request.param == "win32":
        monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt())
    return request.param


@pytest.fixture
def on_darwin(monkeypatch):
    """The hub runs on macOS for the test's length."""
    from neutrino_hub.platforms import detect

    monkeypatch.setattr(detect.sys, "platform", "darwin")


@pytest.fixture
def on_windows(monkeypatch):
    """The hub runs on Windows for the test's length."""
    from neutrino_hub.platforms import detect

    monkeypatch.setattr(detect.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt())


@pytest.fixture(autouse=True)
def _router_lock_in_a_test_directory(tmp_path, monkeypatch):
    """Point the routing-state lock, its records and the ticket file where a
    test may create them."""
    from neutrino_hub.modules.channel import tickets
    from neutrino_hub.modules.firewall import ops as firewall_ops
    from neutrino_hub.modules.router import controller, routes

    monkeypatch.setattr(
        firewall_ops, "FIREWALL_INTERFACES_PATH", tmp_path / "firewall_interfaces.json"
    )
    monkeypatch.setattr(controller, "ROUTER_LOCK_PATH", tmp_path / "router.lock")
    monkeypatch.setattr(
        tickets, "CHANNEL_TICKET_PATH", tmp_path / "enrollment_tickets.json"
    )
    monkeypatch.setattr(
        controller,
        "ROUTER_OVERLAY_DEVICES_PATH",
        tmp_path / "router_overlay_devices.json",
    )
    monkeypatch.setattr(
        controller,
        "ROUTER_ENGINE_CGROUPS_PATH",
        tmp_path / "router_engine_cgroups.json",
    )
    monkeypatch.setattr(
        routes,
        "ROUTER_NETWORK_RESOLVERS_PATH",
        tmp_path / "router_network_resolvers.json",
    )


from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.link_status import (
    LINK_KIND_ETHERNET,
    LINK_KIND_WIFI,
    LinkStatus,
)
from neutrino_hub.modules.router.uplink_plan import UplinkFacts


def pytest_collection_modifyitems(config, items):
    """Skip the tests that need privileges the current run does not have,
    and the tests of a left-out feature the tree does not carry."""
    for item in items:
        for marker in item.iter_markers(name="feature"):
            if not edition.has_feature(marker.args[0]):
                item.add_marker(
                    pytest.mark.skip(reason=f"this tree has no {marker.args[0]}")
                )
    if os.geteuid() == 0:
        return
    skip = pytest.mark.skip(reason="needs root: `nft -c` cannot open netlink")
    for item in items:
        if "needs_root" in item.keywords:
            item.add_marker(skip)


def unlock_vault(monkeypatch, tmp_path) -> bytes:
    """Point the vault's state root at a fresh unlocked key under tmp_path.

    Args:
        monkeypatch: pytest's patcher.
        tmp_path: pytest's per-test directory.

    Returns:
        The data key the vault now seals with.
    """
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    data_key = secrets.token_bytes(32)
    (state / "vault.key").write_text(data_key.hex() + "\n")
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATE_ROOT", state)
    return data_key


class ScriptedChannelStream:
    """One stream as a route sees it, with the agent played by a test.

    Built on the loop the route runs on; a test on another thread drives it
    through :meth:`feed` and :meth:`finish`, which hop onto that loop.

    Attributes:
        id: The stream id, even as the hub allots them.
        kind: The stream kind it was opened as.
        args: What the open carried.
        sent: Every byte the route sent, in order.
        close_info: ``{"code", "params"}`` once the stream closed.
        is_close_asked: Whether the route closed the stream from its side.
    """

    def __init__(self, kind: str, args: dict, stream_id: int = 0):
        import asyncio

        self.id = stream_id
        self.kind = kind
        self.args = dict(args)
        self.sent: list = []
        self.close_info = None
        self.is_abandoned = False
        self.is_close_asked = False
        self._loop = asyncio.get_running_loop()
        self._inbound: asyncio.Queue = asyncio.Queue()
        self._closed = asyncio.Event()

    @property
    def is_closed(self) -> bool:
        return self._closed.is_set()

    @property
    def has_credit_arrived(self) -> bool:
        return True

    async def wait_first_credit(self) -> None:
        return None

    async def recv(self):
        if self._closed.is_set() and self._inbound.empty():
            return None
        return await self._inbound.get()

    async def send_bytes(self, data: bytes) -> None:
        from neutrino_hub.exceptions import AgentOfflineError

        if self._closed.is_set():
            raise AgentOfflineError("scripted")
        self.sent.append(bytes(data))

    async def send_datagram(self, data: bytes) -> bool:
        await self.send_bytes(data)
        return True

    async def close(self, code: str = "", params=None) -> None:
        self.is_close_asked = True
        if not self._closed.is_set():
            self.close_info = {"code": code, "params": dict(params or {})}
            self._closed.set()
            self._inbound.put_nowait(None)

    async def wait_closed(self):
        await self._closed.wait()
        return self.close_info

    def _deliver(self, item) -> None:
        self._inbound.put_nowait(item)

    def feed(self, item) -> None:
        """Deliver one item from any thread."""
        self._loop.call_soon_threadsafe(self._inbound.put_nowait, item)

    def finish(self, info: dict, *, is_abandoned: bool = False) -> None:
        """Close the stream from any thread, as the agent would."""

        def close_now():
            self.is_abandoned = is_abandoned
            self.close_info = dict(info)
            self._closed.set()
            self._inbound.put_nowait(None)

        self._loop.call_soon_threadsafe(close_now)

    def sent_bytes(self) -> bytes:
        return b"".join(self.sent)


class FakeChannelSessions:
    """The live-socket registry as routes see it: who is online, what ran.

    Attributes:
        commands: Every command run, ``(key, module, verb, args)``.
        validations: Every configuration checked, ``(key, module, config)``.
        pushes: Every state pushed, ``(key, hash, document)``.
        verdict: What a validate answers, ``{is_valid, code, params}``,
            composed into the close the way the agent composes it.
        outcome: What a command answers, ``{exit_code, code, params,
            output, result}``, composed the same way; ``outcomes`` by
            verb wins over it where set.
        versions: What each device's last hello named, by key.
        ended_at: When each device's last channel ended, by key.
        reported_at: When each device's last report arrived, by key.
        streams: Every stream opened, in order.
        after_command: Called with ``(key, module, verb, args)`` after a
            command is recorded, standing in for what the machine's report
            says afterwards.
        report_serials: How many reports each device has sent, by key.
        waited: Every wait for a report, ``(key, after_serial, timeout)``.
        scripts: Stream kind to a callable of the open's args answering
            ``(items, close_info)``: the items are delivered at once and
            the stream closed with the info, or left open when it is None.
        refused: Every binding turned away, ``(key, code, params)``.
    """

    def __init__(self, online=()):
        self.online = {key.lower() for key in online}
        self.versions: dict = {}
        self.ended_at: dict = {}
        self.reported_at: dict = {}
        self.commands: list = []
        self.validations: list = []
        self.pushes: list = []
        self.closed: list = []
        self.refused: list = []
        self.verdict = {"is_valid": True, "code": "", "params": {}}
        self.outcome = {"exit_code": 0, "code": "", "params": {}, "output": ""}
        self.outcomes: dict = {}
        self.streams: list = []
        self.scripts: dict = {}
        # What the machine does behind a command, as a callable of
        # ``(key, module, verb, args)``: a test sets it to change the
        # runtime's held report the way the agent's own report after the
        # command would.
        self.after_command = None
        self.report_serials: dict = {}
        self.waited: list = []

    async def open_stream(self, key, kind, args):
        self._require(key)
        stream = ScriptedChannelStream(kind, dict(args), 2 * len(self.streams))
        self.streams.append(stream)
        script = self.scripts.get(kind)
        if script is not None:
            items, info = script(dict(args))
            for item in items:
                stream._deliver(item)
            if info is not None:
                stream.finish(info)
        return stream

    def is_online(self, key: str) -> bool:
        return key.lower() in self.online

    def get(self, key: str):
        return None

    def version_of(self, key: str) -> str:
        return self.versions.get(key.lower(), "")

    def last_seen_at(self, key: str) -> "str | None":
        return self.ended_at.get(key.lower())

    def last_report_at(self, key: str) -> "str | None":
        return self.reported_at.get(key.lower())

    def keys(self) -> list:
        return sorted(self.online)

    def reports(self) -> dict:
        return {}

    def run_stream_from_thread(
        self, key, kind, args, payload=None, on_chunk=None, timeout=None
    ) -> dict:
        """A ``command`` stream, answered from the outcomes.

        A ``validate`` verb is recorded as ``(key, module, config)`` and
        closes with the verdict; any other verb is recorded as ``(key,
        module, verb, args)`` and closes with the outcome for the verb.
        """
        self._require(key)
        module = args["module"]
        verb = args["verb"]
        rest = {
            name: value
            for name, value in args.items()
            if name not in ("module", "verb")
        }
        if verb == "validate":
            self.validations.append((key.lower(), module, dict(rest["config"])))
            return _close_of(
                self.verdict,
                exit_code=0 if self.verdict.get("is_valid") else 1,
                output="",
                result={},
            )
        self.commands.append((key.lower(), module, verb, rest))
        after = self.after_command
        if after is not None:
            after(key.lower(), module, verb, dict(rest))
        outcome = self.outcomes.get(verb, self.outcome)
        result = {
            "exit_code": int(outcome.get("exit_code", 0)),
            "output": str(outcome.get("output", "") or ""),
        }
        if outcome.get("result"):
            result["result"] = dict(outcome["result"])
        return _close_of(outcome, **result)

    def report_serial_of(self, key: str) -> int:
        return self.report_serials.get(key.lower(), 0)

    def wait_for_report_from_thread(self, key, after_serial, timeout) -> bool:
        self.waited.append((key.lower(), after_serial, timeout))
        return self.report_serials.get(key.lower(), 0) > after_serial

    def push_state_from_thread(self, key, document, timeout=5.0) -> None:
        self._require(key)
        self.pushes.append((key.lower(), document.get("hash", ""), document))

    def _require(self, key: str) -> None:
        from neutrino_hub.exceptions import AgentOfflineError

        if key.lower() not in self.online:
            raise AgentOfflineError(key.lower())

    def refuse_from_thread(self, key, code, params=None) -> None:
        self.refused.append((key.lower(), code, dict(params or {})))
        self.online.discard(key.lower())

    def close_from_thread(self, key, code, reason="") -> None:
        self.closed.append((key.lower(), code, reason))
        self.online.discard(key.lower())


def _close_of(answer: dict, **result) -> dict:
    """The close an agent composes from what a handler answered."""
    return {
        "code": str(answer.get("code", "") or ""),
        "params": {**dict(answer.get("params") or {}), **result},
    }


class StubDesiredStates:
    """The per-device store as the report path touches it.

    Attributes:
        ensured: Every device a report asked a seat password for.
        wants: ``(key, module)`` to the want held, what a report reads.
        settled: Every ``(key, module)`` a report settled in the file.
    """

    def __init__(self):
        self.ensured: list = []
        self.wants: dict = {}
        self.settled: list = []
        self.desktop_switches: dict = {}

    def ensure_seat_password(self, key: str) -> bool:
        key = key.lower()
        if key in self.ensured:
            return False
        self.ensured.append(key)
        return True

    def want_of(self, key: str, module: str) -> str:
        return self.wants.get((key.lower(), module), "")

    def settle_want(self, key: str, module: str) -> bool:
        pair = (key.lower(), module)
        if pair not in self.wants or pair in self.settled:
            return False
        self.settled.append(pair)
        return True

    def is_ai_tools_enabled(self, key: str) -> bool:
        return False

    def remote_desktop(self, key: str) -> dict:
        return {"is_enabled": self.desktop_switches.get(key.lower()) is True}

    def has_remote_desktop(self, key: str) -> bool:
        return key.lower() in self.desktop_switches

    def set_remote_desktop(self, key: str, is_enabled: bool) -> dict:
        self.desktop_switches[key.lower()] = bool(is_enabled)
        return {"is_enabled": bool(is_enabled)}


class StubPublishedServices:
    """The published list as the paths that can move it reach for it.

    Attributes:
        refreshes: How many recomposes were scheduled.
    """

    def __init__(self):
        self.refreshes = 0

    def schedule_refresh(self) -> None:
        self.refreshes += 1


class FakeModuleRuntime:
    """The runtime as a device-hosted module's routes reach for it.

    Devices are stored in memory, the desired states land under a
    temporary config dir the caller monkeypatched, and every socket
    effect is recorded on :attr:`agent_sessions`.
    """

    def __init__(self, *, devices, online=(), lan_addresses=()):
        """
        Args:
            devices: The stored :class:`ManagedDevice` list.
            online: Which of them hold a socket.
            lan_addresses: This hub's own LAN addresses, for the hub-first
                ordering.
        """
        from neutrino_hub.modules.devices.desired_state import DesiredStateStore
        from neutrino_hub.web.task_stream import TaskStreamRegistry

        self.devices = {device.id: device for device in devices}
        self.tasks = TaskStreamRegistry()
        self.agent_sessions = FakeChannelSessions(online)
        self.published_services = StubPublishedServices()
        self.desired_states = DesiredStateStore()
        self.device_modules: dict = {}
        self.device_platform: dict = {}
        self.device_hostname: dict = {}
        self.device_address: dict = {}
        self.device_accounts: dict = {}
        self.device_scope: dict = {}
        self.lan_addresses = list(lan_addresses)

    def network(self):
        return _Network(self.lan_addresses)

    def module_agent_config(self, key: str, name: str, stored: dict) -> dict:
        return self.desired_states.agent_config(
            key,
            name,
            stored,
            self.device_platform.get(key, {}),
            address=self.device_address.get(key, ""),
        )

    def push_desired_state(self, key: str) -> None:
        self.agent_sessions.push_state_from_thread(
            key, {"hash": f"hash-{key}", "modules": {}}
        )

    def report(self, key: str, module: str, state: str = "installed", **details):
        """Let the runtime hold one module's last report for one device."""
        self.device_modules.setdefault(key, {})[module] = {
            "state": state,
            "code": "",
            "params": {},
            "details": details,
        }


class _Network:
    def __init__(self, addresses):
        self.lan_interfaces = [_Lan(address) for address in addresses]


class _Lan:
    def __init__(self, address):
        self.lan = _LanBlock(address)


class _LanBlock:
    def __init__(self, address):
        self.address = address


class FakeDeviceRegistry:
    """A registry answering from a runtime's stored devices."""

    runtime = None

    def all_stored(self) -> list:
        return list(FakeDeviceRegistry.runtime.devices.values())

    def get(self, device_id: str):
        return FakeDeviceRegistry.runtime.devices.get(device_id)


def managed_device(
    name: str = "", *, device_id: str = "", machine_id: str = "", link_mac: str = ""
):
    """A stored device the hub issued an agent token for, under a fresh id.

    Args:
        name: What the device is called.
        device_id: The id to store it under; blank generates one.
        machine_id: The machine's own id, when the case needs one.
        link_mac: The MAC its agent last reported, when the case needs one.
    """
    from uuid import uuid4

    from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice

    return ManagedDevice(
        id=device_id or uuid4().hex,
        name=name or None,
        machine_id=machine_id,
        mac_addresses=[link_mac] if link_mac else [],
        link_mac=link_mac,
        client=DeviceClientInfo(token_sha256="t"),
    )


# --- Builders for configuration ---------------------------------------------


def wan_entry(
    name: str, *, intent: str = "auto", is_exposed: bool = False, **wan
) -> dict:
    """One WAN interface as it appears in ``config/router/network.json``.

    Closed by default, as the planner leaves an uplink: what this box listens
    on has no business answering the whole internet.
    """
    return {
        "name": name,
        "role": "wan",
        "is_exposed": is_exposed,
        "wan": {"intent": intent, **wan},
    }


def lan_entry(
    name: str,
    *,
    address: str,
    prefix_len: int = 24,
    is_dhcp_enabled: bool = True,
    is_exposed: bool = True,
    pool: tuple[str, str] | None = None,
    lease: str = "12h",
    **wifi,
) -> dict:
    """One LAN interface, with a DHCP pool derived from its address by default.

    Exposed by default, as the planner leaves a served network: it is where
    the panel, the leases and DNS are reached.
    """
    if pool is None:
        head = address.rsplit(".", 1)[0]
        pool = (f"{head}.100", f"{head}.200")
    return {
        "name": name,
        "role": "lan",
        "is_exposed": is_exposed,
        "lan": {
            "address": address,
            "prefix_len": prefix_len,
            "is_dhcp_enabled": is_dhcp_enabled,
            "dhcp_range_start": pool[0],
            "dhcp_range_end": pool[1],
            "dhcp_lease_time": lease,
        },
        "wifi": wifi,
    }


def network_config(
    *entries: dict, policy: str = "failover", **rest
) -> RouterNetworkConfig:
    """Build a parsed configuration from interface entries."""
    return RouterNetworkConfig.from_dict(
        {"interfaces": list(entries), "uplink_policy": policy, **rest}
    )


# --- Builders for live state ------------------------------------------------


def wired_facts(
    name: str,
    *,
    gateway: str | None = None,
    cidr: str | None = None,
    speed: int | None = 1000,
    is_carrying: bool = True,
) -> UplinkFacts:
    """What the system would say about a working wired uplink."""
    return UplinkFacts(
        name=name,
        medium=LINK_KIND_ETHERNET,
        is_carrying=is_carrying,
        gateway=gateway,
        cidr=cidr,
        speed_mbps=speed,
    )


def wireless_facts(
    name: str,
    *,
    gateway: str | None = None,
    cidr: str | None = None,
    speed: int | None = 300,
    is_carrying: bool = True,
) -> UplinkFacts:
    """What the system would say about an associated radio."""
    return UplinkFacts(
        name=name,
        medium=LINK_KIND_WIFI,
        is_carrying=is_carrying,
        gateway=gateway,
        cidr=cidr,
        speed_mbps=speed,
    )


def link(
    name: str,
    *,
    kind: str = LINK_KIND_ETHERNET,
    address: str | None = None,
    is_up: bool = True,
    gateway: str | None = None,
    is_ap_capable: bool = True,
    speed_mbps: int | None = 1000,
) -> LinkStatus:
    """One interface's live state, as the readers would report it."""
    return LinkStatus(
        name=name,
        kind=kind,
        is_present=True,
        is_up=is_up,
        ipv4_address=address,
        mac_address="aa:bb:cc:dd:ee:ff",
        speed_mbps=speed_mbps,
        is_ap_capable=is_ap_capable,
    )


class StubLinkStatus:
    """A :class:`RouterLinkStatus` that answers from a dictionary.

    Everything the network layer asks the system is routed through the real
    reader, so replacing it is enough to make the layers above it testable
    without a network — and without the chance of a test reconfiguring the
    machine it is running on.
    """

    def __init__(self, links: list[LinkStatus], gateways: dict[str, str] | None = None):
        """
        Args:
            links: The interfaces the box appears to have.
            gateways: Next hop per interface, for the ones that have one.
        """
        self._links = links
        self._gateways = gateways or {}

    def all_links(self) -> list[LinkStatus]:
        return list(self._links)

    def link(self, name: str) -> LinkStatus:
        for entry in self._links:
            if entry.name == name:
                return entry
        return LinkStatus(name=name)

    def gateway_for(self, name: str) -> str | None:
        return self._gateways.get(name)

    def default_gateway(self) -> str | None:
        return next(iter(self._gateways.values()), None)

    def default_routes(self) -> list[dict]:
        return [
            {"dev": name, "gateway": gateway, "metric": 100}
            for name, gateway in self._gateways.items()
        ]


def without_comments(rendered: str) -> str:
    """Strip the comment lines from a rendered artifact.

    The renderers explain themselves in the files they produce, and those
    explanations name the very things a test wants to assert are absent — the
    nft ruleset says "nothing to masquerade", the dnsmasq config says why it
    does not use bind-interfaces. Asserting against the raw text therefore
    matches prose instead of directives. Assert against this instead.

    Args:
        rendered: A rendered ruleset or configuration file.

    Returns:
        The same text with whole-line comments removed.
    """
    return "\n".join(
        line for line in rendered.splitlines() if not line.strip().startswith("#")
    )


# --- External validators ----------------------------------------------------


def validate_dnsmasq(config_text: str, tmp_path) -> None:
    """Run the real ``dnsmasq --test`` over a rendered config.

    Args:
        config_text: The rendered file.
        tmp_path: pytest's per-test directory.

    Raises:
        AssertionError: If dnsmasq rejects it, quoting what it said.
    """
    path = tmp_path / "neutrino.conf"
    path.write_text(config_text, encoding="utf-8")
    result = subprocess.run(
        ["dnsmasq", "--test", "-C", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"dnsmasq rejected the rendered config:\n"
        f"{result.stderr.strip() or result.stdout.strip()}\n\n{config_text}"
    )


def validate_nft(ruleset: str) -> None:
    """Run the real ``nft -c`` over a rendered ruleset.

    Args:
        ruleset: The rendered ruleset text.

    Raises:
        AssertionError: If nft rejects it, quoting what it said.
    """
    result = subprocess.run(
        ["nft", "-c", "-f", "-"], input=ruleset, capture_output=True, text=True
    )
    assert result.returncode == 0, (
        f"nft rejected the rendered ruleset:\n" f"{result.stderr.strip()}\n\n{ruleset}"
    )


def completed(stdout: str = "", returncode: int = 0, **keywords):
    """A finished process as ``subprocess.run`` hands it back.

    Raises:
        subprocess.CalledProcessError: When ``check`` was asked and it failed.
    """
    if keywords.get("check") and returncode != 0:
        raise subprocess.CalledProcessError(returncode, [], output=stdout)
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


class FakeServiceControlManager:
    """The Windows service control manager through ``sc.exe``, for the hub's
    service; a start or a stop reads pending once before it settles."""

    def __init__(self):
        self.calls: list = []
        self.is_running = False
        self.is_refusing = False
        # sc.exe stop timing out while the service goes on to stop.
        self.is_stop_slow = False
        self._pending = 0

    def __call__(self, command, **keywords):
        command = list(command)
        self.calls.append(command)
        if command[:2] == ["sc.exe", "query"]:
            if self._pending:
                number, self._pending = self._pending, 0
            else:
                number = 4 if self.is_running else 1
            return completed(f"        STATE              : {number}  WORD\n")
        if self.is_refusing:
            return completed("[SC] StartService FAILED 1058", 1058, **keywords)
        if command[:2] == ["sc.exe", "start"]:
            self.is_running, self._pending = True, 2
        elif command[:2] == ["sc.exe", "stop"]:
            self.is_running, self._pending = False, 3
            if self.is_stop_slow:
                raise subprocess.TimeoutExpired(command, keywords.get("timeout"))
        return completed("")


class FakeLaunchd:
    """launchd for the hub's job: ``print``, ``bootstrap``, ``kickstart``,
    ``bootout``."""

    def __init__(self):
        self.calls: list = []
        self.is_running = False
        self.is_refusing = False

    def __call__(self, command, **keywords):
        command = list(command)
        self.calls.append(command)
        if command[:2] == ["launchctl", "print"]:
            if not self.is_running:
                return completed("", 113)
            return completed("system/com.neutrino.hub = {\n\tstate = running\n}\n")
        if self.is_refusing:
            return completed("", 5, **keywords)
        if command[:2] == ["launchctl", "kickstart"]:
            self.is_running = True
        elif command[:2] == ["launchctl", "bootout"]:
            self.is_running = False
        return completed("")


class FakeChildProcess:
    """One child the supervisor started, ended by the test or by a stop."""

    def __init__(self, argv: list, env: dict, cwd, output: bytes, pid: int):
        import io

        self.argv = argv
        self.env = env
        self.cwd = cwd
        self.pid = pid
        self.returncode = None
        self.is_terminated = False
        self.stdout = io.BytesIO(output)

    def poll(self):
        return self.returncode

    def terminate(self):
        self.is_terminated = True
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode

    def end(self, status: int = 1) -> None:
        """The child exits by itself."""
        self.returncode = status


class FakePopen:
    """What the supervisor starts children with: a fake per start, kept."""

    def __init__(self, output: bytes = b""):
        self.started: list = []
        self.is_refusing = False
        self.output = output
        self.creation_flags: list = []

    def __call__(self, argv, env, cwd, creation_flags):
        if self.is_refusing:
            raise FileNotFoundError(argv[0])
        self.creation_flags.append(creation_flags)
        child = FakeChildProcess(
            list(argv), dict(env), cwd, self.output, 1000 + len(self.started)
        )
        self.started.append(child)
        return child

    def of(self, program: str) -> list:
        """Every child started from this program, in order."""
        return [child for child in self.started if child.argv[0] == program]


class FakeClock:
    """A monotonic clock a test moves by hand."""

    def __init__(self):
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class FakeMsvcrt:
    """Windows' ``msvcrt`` file lock, on a system that has none."""

    LK_NBLCK = 2
    LK_UNLCK = 0

    def locking(self, descriptor, mode, size):
        return None


class FakePsutil:
    """psutil's network readings, answered from what a test set.

    Attributes:
        addresses: Interface name to ``(family, address, netmask)`` triples.
        stats: Interface name to ``(is_up, speed_mbps)``.
        counters: Interface name to ``(bytes_received, bytes_sent)``.
        connections: ``(kind, status, port, has_remote, pid)`` per socket,
            ``kind`` being ``tcp`` or ``udp``.
        process_names: Pid to the program's file name.
    """

    import psutil as _psutil

    AF_LINK = _psutil.AF_LINK
    CONN_LISTEN = _psutil.CONN_LISTEN
    Error = _psutil.Error

    def __init__(self):
        self.addresses: dict = {}
        self.stats: dict = {}
        self.counters: dict = {}
        self.connections: list = []
        self.process_names: dict = {}

    def net_if_addrs(self) -> dict:
        import collections

        entry = collections.namedtuple("snicaddr", "family address netmask")
        return {
            name: [entry(*triple) for triple in triples]
            for name, triples in self.addresses.items()
        }

    def net_if_stats(self) -> dict:
        import collections

        entry = collections.namedtuple("snicstats", "isup speed")
        return {name: entry(*pair) for name, pair in self.stats.items()}

    def net_io_counters(self, pernic=False) -> dict:
        import collections

        entry = collections.namedtuple("snetio", "bytes_recv bytes_sent")
        return {name: entry(*pair) for name, pair in self.counters.items()}

    def net_connections(self, kind="inet") -> list:
        import collections
        import socket

        address = collections.namedtuple("addr", "ip port")
        entry = collections.namedtuple("sconn", "type status laddr raddr pid")
        found = []
        for kind_word, status, port, has_remote, pid in self.connections:
            found.append(
                entry(
                    socket.SOCK_STREAM if kind_word == "tcp" else socket.SOCK_DGRAM,
                    status,
                    address("0.0.0.0", port),
                    address("192.0.2.9", 4000) if has_remote else (),
                    pid,
                )
            )
        return found

    def Process(self, pid):
        names = self.process_names

        class _Process:
            def name(self) -> str:
                return names[pid]

        return _Process()


class FakePowerShell:
    """Records each script and document, and answers a canned object.

    Attributes:
        runs: Every ``(script, document)`` run, in order.
    """

    def __init__(self, answers=None, error=None):
        self.runs: list = []
        self._answers = dict(answers or {})
        self._error = error

    def __call__(self, script, document):
        import json

        self.runs.append((script, json.loads(json.dumps(document))))
        if self._error is not None:
            raise self._error
        return dict(self._answers.get(script, {}))


class FakeTools:
    """Every command run, recorded, answered by its first words.

    Attributes:
        calls: Each argument vector, in order.
        answers: Output by the leading words of a command; a command no
            entry names succeeds and prints nothing.
        failing: Leading words of the commands that exit 1.
    """

    def __init__(self):
        self.calls: list = []
        self.answers: dict = {}
        self.failing: set = set()

    def __call__(self, command, *, is_checked=True, timeout_s=0, **keywords):
        from neutrino_hub.utils.subprocess_run import CommandResult

        command = [str(word) for word in command]
        self.calls.append(command)
        for size in (5, 4, 3, 2, 1):
            key = tuple(command[:size])
            if key in self.failing:
                if is_checked:
                    raise subprocess.CalledProcessError(1, command, "", "refused")
                return CommandResult(command, 1, "", "refused")
            if key in self.answers:
                return CommandResult(command, 0, self.answers[key], "")
        return CommandResult(command, 0, "", "")

    def ran(self, *words) -> list:
        """The recorded commands that start with these words."""
        return [call for call in self.calls if tuple(call[: len(words)]) == words]


class FakeProcessController:
    """The process controller, recording each verb.

    Attributes:
        calls: ``(verb, name)`` per call, and ``("set_start_line", name,
            argv, env, cwd)`` per start line.
        active: The names that read as running.
        enabled: The names that read as enabled.
        journals: Name to the text its journal answers.
    """

    def __init__(self):
        self.calls: list = []
        self.active: set = set()
        self.enabled: set = set()
        self.journals: dict = {}

    def is_active(self, name: str) -> bool:
        self.calls.append(("is_active", name))
        return name in self.active

    def is_enabled(self, name: str) -> bool:
        self.calls.append(("is_enabled", name))
        return name in self.enabled

    def start(self, name: str) -> None:
        self.calls.append(("start", name))
        self.active.add(name)

    def stop(self, name: str) -> None:
        self.calls.append(("stop", name))
        self.active.discard(name)

    def restart(self, name: str) -> None:
        self.calls.append(("restart", name))
        self.active.add(name)

    def enable(self, name: str) -> None:
        self.calls.append(("enable", name))
        self.enabled.add(name)

    def disable(self, name: str) -> None:
        self.calls.append(("disable", name))
        self.enabled.discard(name)

    def reload(self) -> None:
        self.calls.append(("reload",))

    def journal(self, name: str, *, line_count: int = 100) -> str:
        self.calls.append(("journal", name))
        return self.journals.get(name, "")

    def set_start_line(self, name, argv, env, cwd) -> None:
        self.calls.append(("set_start_line", name, list(argv or []), env, cwd))

    def verbs(self) -> list:
        """The calls without the reads."""
        return [
            call for call in self.calls if call[0] not in ("is_active", "is_enabled")
        ]


@pytest.fixture
def fake_controller(monkeypatch) -> FakeProcessController:
    """The one process controller this process hands out, faked."""
    from neutrino_hub.platforms import detect

    controller = FakeProcessController()
    monkeypatch.setattr(detect, "_CONTROLLER", controller)
    return controller


def self_signed_pair(directory) -> tuple:
    """A fresh self-signed certificate and its key, written as PEM files.

    Args:
        directory: Where ``certificate.pem`` and ``key.pem`` are written.

    Returns:
        ``(certificate_path, key_path, fingerprint)``, the fingerprint being
        the SHA-256 hex of the certificate's DER form.
    """
    import datetime
    import hashlib

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    certificate_path = directory / "certificate.pem"
    key_path = directory / "key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    der = certificate.public_bytes(serialization.Encoding.DER)
    return certificate_path, key_path, hashlib.sha256(der).hexdigest()
