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
"""

import os
import secrets
import subprocess
import threading

import pytest

from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.router.link_status import (
    LINK_KIND_ETHERNET,
    LINK_KIND_WIFI,
    LinkStatus,
)
from neutrino_hub.modules.router.uplink_plan import UplinkFacts


def pytest_collection_modifyitems(config, items):
    """Skip the tests that need privileges the current run does not have."""
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


class ScriptedAgentStream:
    """One stream as a route sees it, with the agent played by a test.

    Built on the loop the route runs on; a test on another thread drives it
    through :meth:`feed` and :meth:`finish`, which hop onto that loop.

    Attributes:
        kind: The stream kind it was opened as.
        args: What the open carried.
        sent: Every byte the route sent, in order.
        resizes: Every ``(cols, rows)`` the route sent.
        close_info: What the stream closed with, once it has.
    """

    def __init__(self, kind: str, args: dict):
        import asyncio

        self.kind = kind
        self.args = dict(args)
        self.sent: list = []
        self.resizes: list = []
        self.close_info = None
        self.is_abandoned = False
        self.is_close_asked = False
        self._loop = asyncio.get_running_loop()
        self._inbound: asyncio.Queue = asyncio.Queue()
        self._closed = asyncio.Event()

    @property
    def is_closed(self) -> bool:
        return self._closed.is_set()

    async def recv(self):
        if self._closed.is_set() and self._inbound.empty():
            return None
        return await self._inbound.get()

    async def send_bytes(self, data: bytes) -> None:
        from neutrino_hub.modules.devices.agent_sessions import AgentOfflineError

        if self._closed.is_set():
            raise AgentOfflineError("scripted")
        self.sent.append(bytes(data))

    async def resize(self, cols: int, rows: int) -> None:
        self.resizes.append((int(cols), int(rows)))

    async def close(self) -> None:
        self.is_close_asked = True

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


class FakeAgentSessions:
    """The live-socket registry as routes see it: who is online, what ran.

    Attributes:
        commands: Every command run, ``(key, action, args)``.
        validations: Every configuration checked, ``(key, module, config)``.
        pushes: Every state pushed, ``(key, hash, desired)``.
        verdict: What a validate closes with.
        outcome: What a command closes with; ``outcomes`` by action wins
            over it where set.
        versions: What each device's last hello named, by key.
        ended_at: When each device's last channel ended, by key.
        reported_at: When each device's last report arrived, by key.
        streams: Every stream opened, in order.
        scripts: Stream kind to a callable of the open's args answering
            ``(items, close_info)``: the items are delivered at once and
            the stream closed with the info, or left open when it is None.
        refusal: A ``(code, params)`` every open is refused with.
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
        self.verdict = {"is_valid": True, "code": "", "params": {}}
        self.outcome = {"exit_code": 0, "code": "", "params": {}, "output": ""}
        self.outcomes: dict = {}
        self.streams: list = []
        self.scripts: dict = {}
        self.refusal = None

    async def open_stream(self, key, kind, args):
        from neutrino_hub.modules.devices.agent_sessions import StreamRefusedError

        self._require(key)
        if self.refusal is not None:
            raise StreamRefusedError(*self.refusal)
        stream = ScriptedAgentStream(kind, dict(args))
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

    def run_command_from_thread(
        self, key, action, args=None, on_line=None, timeout=None
    ) -> dict:
        self._require(key)
        self.commands.append((key.lower(), action, dict(args or {})))
        return dict(self.outcomes.get(action, self.outcome))

    def validate_from_thread(self, key, module, config, timeout=None) -> dict:
        self._require(key)
        self.validations.append((key.lower(), module, dict(config)))
        return dict(self.verdict)

    def push_state_from_thread(self, key, state_hash, desired, timeout=5.0) -> None:
        self._require(key)
        self.pushes.append((key.lower(), state_hash, desired))

    def _require(self, key: str) -> None:
        from neutrino_hub.modules.devices.agent_sessions import AgentOfflineError

        if key.lower() not in self.online:
            raise AgentOfflineError(key.lower())

    def close_from_thread(self, key, code, reason="") -> None:
        self.closed.append((key.lower(), code, reason))
        self.online.discard(key.lower())


def holding_dispatch(order) -> None:
    """A dispatch that keeps an order open for a moment and never answers."""
    threading.Event().wait(2.0)


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
        from neutrino_hub.modules.devices.agent_module_controller import (
            AgentModuleController,
        )
        from neutrino_hub.modules.devices.desired_state import DesiredStateStore
        from neutrino_hub.modules.devices.install_lock import DeviceInstallLocks

        self.devices = {device.mac_address.lower(): device for device in devices}
        self.agent_sessions = FakeAgentSessions(online)
        self.desired_states = DesiredStateStore()
        self.client_modules: dict = {}
        self.client_platform: dict = {}
        self.client_hostname: dict = {}
        self.client_address: dict = {}
        self.lan_addresses = list(lan_addresses)
        self.agent_module_orders = AgentModuleController(
            cache=None, locks=DeviceInstallLocks(), dispatch=holding_dispatch
        )

    def network(self):
        return _Network(self.lan_addresses)

    def push_desired_state(self, key: str) -> None:
        self.agent_sessions.push_state_from_thread(key, f"hash-{key}", {"modules": {}})

    def report(self, key: str, module: str, state: str = "installed", **details):
        """Let the runtime hold one module's last report for one device."""
        self.client_modules.setdefault(key.lower(), {})[module] = {
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

    def get(self, mac_address: str):
        from neutrino_hub.modules.devices.registry import ManagedDevice

        key = mac_address.lower()
        return FakeDeviceRegistry.runtime.devices.get(key) or ManagedDevice(
            mac_address=key
        )


def managed_device(mac_address: str, name: str = ""):
    """A stored device the hub issued an agent token for."""
    from neutrino_hub.modules.devices.registry import DeviceClientInfo, ManagedDevice

    return ManagedDevice(
        mac_address=mac_address.lower(),
        name=name or None,
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
