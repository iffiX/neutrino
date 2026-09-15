"""One pass of the routing state: the order, the lock, and a step that fails
or waits without taking the others with it.

The pass reads `config/` fresh, renders the ruleset for real, and drives the
appliers, which are replaced here by recorders.
"""

import pytest

from neutrino_hub.modules.router import controller, routes
from neutrino_hub.modules.router.constants import (
    ROUTER_CODE_COMMAND_FAILED,
    ROUTER_CODE_INTERFACE_DOWN,
    ROUTER_CODE_POLICY_ROUTE_MISSING,
    ROUTER_STEP_APPLIED,
    ROUTER_STEP_FAILED,
    ROUTER_STEP_PENDING,
    ROUTER_STEP_UNCHANGED,
)
from neutrino_hub.modules.router.controller import (
    RouterStateController,
    failure_text,
    router_lock,
)
from neutrino_hub.modules.router.steps import RouterStepResult

from tests.conftest import lan_entry, wan_entry

ROUTING = {
    "is_proxy_enabled": True,
    "is_local_proxy_enabled": False,
    "socks_ports": [],
}


def network_file(*interfaces) -> dict:
    return {"mode": "router", "interfaces": list(interfaces), "overlays": []}


class _Ran:
    def __init__(self, stdout: str = "", *, is_success: bool = True):
        self.stdout = stdout
        self.stderr = ""
        self.is_success = is_success
        self.exit_code = 0 if is_success else 1


class Kernel:
    """Answers the commands the ruleset applier runs, and records them.

    Attributes:
        commands: Every command run, in order.
        is_table_loaded: What `nft list table` answers.
        refused: Commands whose first three words are here fail.
    """

    def __init__(self, *, is_table_loaded: bool = False, table: str = ""):
        self.commands: list[list[str]] = []
        self.is_table_loaded = is_table_loaded
        self.table = table
        self.refused: set = set()

    def __call__(self, command, **keywords):
        import subprocess

        command = [str(word) for word in command]
        self.commands.append(command)
        if tuple(command[:3]) in self.refused:
            raise subprocess.CalledProcessError(1, command, stderr="refused")
        if command[:2] == ["nft", "list"]:
            return _Ran(is_success=self.is_table_loaded)
        if command[:3] == ["ip", "route", "show"]:
            return _Ran(self.table)
        return _Ran()

    def loads(self) -> int:
        return sum(1 for command in self.commands if command[:3] == ["nft", "-f", "-"])


class Interfaces:
    """Stands in for the interface applier, answering fixed step results."""

    built: list = []
    results: list = []
    calls: list = []

    def __init__(self, *, network, trigger, is_lease_awaited):
        Interfaces.built.append({"trigger": trigger, "awaited": is_lease_awaited})

    def apply_steps(self, only=None):
        Interfaces.calls.append(("interfaces", only))
        return list(Interfaces.results)


@pytest.fixture
def box(monkeypatch, tmp_path):
    """A router with one uplink and two served networks, the machine recorded."""
    files = {
        "router/network.json": network_file(
            wan_entry("enp2s0"),
            lan_entry("enp1s0", address="192.168.110.1"),
            lan_entry("wlp3s0", address="192.168.111.1"),
        ),
        "xray/routing.json": dict(ROUTING),
    }
    kernel = Kernel()
    Interfaces.built, Interfaces.results, Interfaces.calls = [], [], []
    monkeypatch.setattr(controller, "read_config", lambda name: files[name])
    monkeypatch.setattr(controller, "lookup_xray_uid", lambda: 0)
    monkeypatch.setattr(controller, "ROUTER_NFT_PATH", tmp_path / "router.nft")
    monkeypatch.setattr(
        controller, "write_generated", lambda path, text: path.write_text(text)
    )
    monkeypatch.setattr(controller, "RouterInterfaceApplier", Interfaces)
    monkeypatch.setattr(controller, "admin_up_interfaces", lambda: {"enp1s0", "wlp3s0"})
    monkeypatch.setattr(routes, "run", kernel)
    monkeypatch.setattr(controller, "NetbirdInboundGate", _Gate)
    return files, kernel


class _Gate:
    """A NetBird daemon that already agrees."""

    def converge(self, *, is_blocked):
        return ""


def pass_of(**keywords) -> RouterStateController:
    return RouterStateController(**keywords)


def names(results) -> list[str]:
    return [result.name for result in results]


def test_the_firewall_comes_first_and_the_served_routes_after_the_ports(box):
    order = []
    Interfaces.results = [RouterStepResult(name="interface enp1s0", state="applied")]

    results = pass_of(on_base_ready=lambda: order.append("ready")).reconcile()

    assert names(results)[:4] == [
        "forwarding",
        "policy_route",
        "ruleset",
        "interface enp1s0",
    ]
    assert names(results)[4:] == ["served_route enp1s0", "served_route wlp3s0"]
    assert order == ["ready"]


def test_ready_is_said_before_any_step_that_starts_a_unit(box, monkeypatch):
    """hostapd and the lease client are ordered after the router unit, so a
    start of either waits for the router's own start to finish."""
    events = []
    Interfaces.results = []

    def interfaces_ran(self, only=None):
        events.append("interfaces")
        return []

    monkeypatch.setattr(Interfaces, "apply_steps", interfaces_ran)
    pass_of(on_base_ready=lambda: events.append("ready")).reconcile()

    assert events == ["ready", "interfaces"]


def test_a_port_down_at_boot_leaves_the_firewall_loaded(box, monkeypatch):
    """The boot this was written after: enp1s0 was still down when its
    served route was added, the kernel refused it, and nothing after it ran,
    the firewall and NAT included."""
    _, kernel = box
    monkeypatch.setattr(controller, "admin_up_interfaces", lambda: {"wlp3s0"})

    results = pass_of().reconcile()

    by_name = {result.name: result for result in results}
    assert by_name["ruleset"].state == ROUTER_STEP_APPLIED
    assert kernel.loads() == 1
    assert (
        by_name["served_route enp1s0"].state,
        by_name["served_route enp1s0"].code,
    ) == (
        ROUTER_STEP_PENDING,
        ROUTER_CODE_INTERFACE_DOWN,
    )
    assert by_name["served_route wlp3s0"].state == ROUTER_STEP_APPLIED


def test_a_failed_interface_does_not_stop_the_steps_after_it(box):
    Interfaces.results = [
        RouterStepResult(
            name="interface enp1s0",
            state=ROUTER_STEP_FAILED,
            code=ROUTER_CODE_COMMAND_FAILED,
            detail="refused",
        ),
        RouterStepResult(name="interface wlp3s0", state=ROUTER_STEP_APPLIED),
    ]

    results = pass_of().reconcile()

    assert "served_route wlp3s0" in names(results)
    assert failure_text(results) == "interface enp1s0: failed command_failed: refused"


def test_the_ruleset_the_kernel_already_holds_is_not_loaded_again(box):
    _, kernel = box
    pass_of().reconcile()
    kernel.is_table_loaded = True
    kernel.commands.clear()

    results = pass_of().reconcile()

    ruleset = next(result for result in results if result.name == "ruleset")
    assert ruleset.state == ROUTER_STEP_UNCHANGED
    assert kernel.loads() == 0


def test_the_ruleset_is_recorded_only_after_the_kernel_takes_it(box, monkeypatch):
    """The panel reads that file to say where traffic is going. Written first,
    it answers with where traffic was about to go."""
    _, kernel = box
    order = []
    monkeypatch.setattr(
        controller, "write_generated", lambda path, text: order.append("wrote")
    )
    original = kernel.__call__

    def recording(command, **keywords):
        if list(command[:3]) == ["nft", "-f", "-"]:
            order.append("loaded")
        return original(command, **keywords)

    monkeypatch.setattr(routes, "run", recording)

    pass_of().reconcile()

    assert order == ["loaded", "wrote"]


def test_a_missing_policy_route_keeps_the_ruleset_the_kernel_holds(box):
    """A diverting ruleset with no policy route sends what it diverts
    nowhere."""
    _, kernel = box
    kernel.is_table_loaded = True
    kernel.refused = {("ip", "rule", "add")}

    results = pass_of().reconcile()

    ruleset = next(result for result in results if result.name == "ruleset")
    assert (ruleset.state, ruleset.code) == (
        ROUTER_STEP_FAILED,
        ROUTER_CODE_POLICY_ROUTE_MISSING,
    )
    assert kernel.loads() == 0


def test_with_no_table_at_all_the_ruleset_loads_anyway(box):
    """A closed firewall with a broken proxy beats an open box."""
    _, kernel = box
    kernel.refused = {("ip", "rule", "add")}

    results = pass_of().reconcile()

    ruleset = next(result for result in results if result.name == "ruleset")
    assert ruleset.state == ROUTER_STEP_APPLIED
    assert kernel.loads() == 1


def test_only_limits_the_interfaces_and_runs_every_other_step(box):
    results = pass_of().reconcile(only="enp1s0")

    assert Interfaces.calls == [("interfaces", "enp1s0")]
    assert {"forwarding", "policy_route", "ruleset"} <= set(names(results))


def test_an_interface_nobody_configured_is_refused_before_anything_runs(box):
    _, kernel = box

    with pytest.raises(ValueError):
        pass_of().reconcile(only="eth9")

    assert kernel.commands == []


def test_the_resident_unit_leaves_leases_to_their_events(box):
    pass_of(trigger="event").reconcile()

    assert Interfaces.built == [{"trigger": "event", "awaited": False}]


def test_a_second_writer_waits_for_the_first(tmp_path):
    """The panel, `nhub apply` and the resident unit each open the lock on
    their own, and two opens in one process conflict the same way."""
    path = tmp_path / "router.lock"

    with router_lock(path=path):
        with pytest.raises(TimeoutError):
            with router_lock(path=path, timeout_s=0):
                pass

    with router_lock(path=path, timeout_s=0):
        pass
