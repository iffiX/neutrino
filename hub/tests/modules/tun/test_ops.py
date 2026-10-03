"""The TUN device's plan, its child and its routes on macOS and Windows.

The machine's facts are faked: the default route, the addresses, the
direct resolver, the overlays' daemons. What these pin: the plan each
scope renders on each system, held against goldens; no plan on Linux, with
both scopes off, with no exit or with no way out; the routing pass keeps
the plan and enables tun2socks while it stands and disables it when it
does not; the keeper brings the routes up once the device is there,
withdraws them when tun2socks ends or the plan changes, keeps exactly what
it added, and logs a step that cannot run rather than stopping the
supervisor; and xray exiting under the supervisor takes tun2socks and the
default route with it.
"""

import json

import pytest

from neutrino_hub.modules.easytier.config import EasyTierConfig
from neutrino_hub.modules.netbird.ops import NetbirdState
from neutrino_hub.modules.tun import ops
from neutrino_hub.modules.tun.applied_state import (
    TunAppliedState,
    read_applied,
    write_applied,
)
from neutrino_hub.modules.tun.renderer import TunPlan, render_tun_plan
from neutrino_hub.system.child_supervisor import ChildProcessSupervisor, ChildStartLine
from neutrino_hub.system.constants import SYSTEM_CHILD_RESTART_MIN_S
from tests.modules.tun.golden_plans import PLANS
from tests.conftest import (
    FakeClock,
    FakePopen,
    FakeProcessController,
    network_config,
)

# The upper half of the address space and the device's own address, as
# the plan names them.
UPPER_HALF = "128.0.0.0/1"  # scan: allow
TUN_ADDRESS = "198.18.0.1"  # scan: allow


NODES = {
    "nodes": [
        {
            "id": "hk1",
            "name": "Tokyo",
            "address": "exit.example.net",
            "is_enabled": True,
            "protocol": "shadowsocks",
            "secret_id": "0" * 32,
            "shadowsocks": {"port": 5800, "method": "aes-256-gcm"},
        },
        {
            "id": "hk2",
            "name": "Osaka",
            "address": "203.0.113.11",
            "is_enabled": False,
            "protocol": "shadowsocks",
            "secret_id": "1" * 32,
            "shadowsocks": {"port": 5800, "method": "aes-256-gcm"},
        },
    ],
    "balancer": {
        "reference_url": "http://www.msftconnecttest.com/connecttest.txt",
    },
}
ANSWERS = {
    "exit.example.net": "203.0.113.10",
    "www.msftconnecttest.com": "198.51.100.4",
    "api.netbird.io": "198.51.100.11",
    "signal.netbird.io": "198.51.100.12",
    "streamline-de-fra1-0.relay.netbird.io": "198.51.100.13",
    "public.easytier.top": "192.0.2.61",
}
# What each system calls the uplink, the TUN device and the overlays' devices.
SYSTEMS = {
    "darwin": {
        "uplink": "en0",
        "device": "utun225",
        "binary": "/app/bin/tun2socks",
        "overlays": {"netbird": ["utun4"], "easytier": ["utun6"]},
    },
    "windows": {
        "uplink": "Ethernet",
        "device": "neutrino_tun",
        "binary": "C:\\hub\\bin\\tun2socks.exe",
        "overlays": {"netbird": ["wt0"], "easytier": ["easytier"]},
    },
}
SCOPES = {
    "hub": {"is_local_proxy_enabled": True},
    "overlay": {"is_overlay_proxy_enabled": True},
    "both": {"is_local_proxy_enabled": True, "is_overlay_proxy_enabled": True},
}
ROUTING = {
    "is_proxy_enabled": False,
    "is_overlay_proxy_enabled": False,
    "is_local_proxy_enabled": False,
    "direct_dns": {"address": "223.5.5.5", "port": 53},
}


class FakeNetbirdReader:
    def survey(self):
        return NetbirdState(
            is_installed=True,
            server_urls=[
                "https://api.netbird.io:443",
                "https://signal.netbird.io:443",
                "rels://streamline-de-fra1-0.relay.netbird.io:443",
            ],
        )


def _no_system_answer(*args, **keywords):
    raise OSError("no resolver")


@pytest.fixture
def machine(monkeypatch):
    """A macOS or Windows box with one uplink, faked; returns its setter."""
    asked = []

    def resolve(name, *, server, port):
        asked.append((name, server, port))
        return ANSWERS.get(name)

    def resolve_secrets(node_list):
        for node in node_list.nodes:
            node.password = "secret"

    monkeypatch.setattr(ops, "is_linux", lambda: False)
    monkeypatch.setattr(ops, "_config", lambda name: json.loads(json.dumps(NODES)))
    monkeypatch.setattr(ops, "resolve_node_secrets", resolve_secrets)
    monkeypatch.setattr(ops, "resolve_direct", resolve)
    monkeypatch.setattr(ops.socket, "getaddrinfo", _no_system_answer)
    monkeypatch.setattr(ops, "NetbirdStatusReader", FakeNetbirdReader)
    monkeypatch.setattr(
        ops,
        "read_easytier",
        lambda: EasyTierConfig(peers=["tcp://public.easytier.top:11010"]),
    )

    def on(system: str, *, has_overlays: bool):
        facts = SYSTEMS[system]
        devices = facts["overlays"] if has_overlays else {}
        monkeypatch.setattr(ops, "hub_os", lambda: system)
        monkeypatch.setattr(ops, "TUN_BINARY_PATH", facts["binary"])
        monkeypatch.setattr(
            ops,
            "system_default_routes",
            lambda: [{"dev": facts["uplink"], "gateway": "192.168.1.1", "metric": 0}],
        )
        addresses = {facts["uplink"]: "192.168.1.20/24"}
        if has_overlays:
            addresses[devices["netbird"][0]] = "100.92.0.5/16"
            addresses[devices["easytier"][0]] = "10.144.144.1/24"
        monkeypatch.setattr(ops, "device_addresses", lambda: dict(addresses))
        monkeypatch.setattr(
            ops, "_present_devices", lambda: set(addresses) | {facts["device"]}
        )
        overlays = [
            {"provider": "netbird", "is_enabled": has_overlays, "is_exposed": True},
            {"provider": "easytier", "is_enabled": has_overlays, "is_exposed": True},
        ]
        return network_config(mode="server", overlays=overlays).with_overlay_devices(
            devices
        )

    on.asked = asked
    return on


CASES = [
    (system, scope, has_overlays)
    for system in SYSTEMS
    for scope, has_overlays in (
        ("hub", False),
        ("hub", True),
        ("overlay", True),
        ("both", True),
    )
]


def golden_name(system: str, scope: str, has_overlays: bool) -> str:
    overlays = "with_overlays" if has_overlays else "no_overlays"
    return f"plan_{system}_{scope}_{overlays}"


@pytest.mark.parametrize(
    ("system", "scope", "has_overlays"),
    CASES,
    ids=[golden_name(*case) for case in CASES],
)
def test_the_plan_matches_its_golden(machine, system, scope, has_overlays):
    network = machine(system, has_overlays=has_overlays)

    rendered = ops.plan_tun(network, {**ROUTING, **SCOPES[scope]})

    assert rendered.to_dict() == PLANS[golden_name(system, scope, has_overlays)]


def test_every_name_kept_out_is_asked_of_the_direct_resolver(machine):
    network = machine("darwin", has_overlays=True)

    ops.plan_tun(network, {**ROUTING, **SCOPES["hub"]})

    assert {server for _, server, _ in machine.asked} == {"223.5.5.5"}
    assert [name for name, _, _ in machine.asked] == [
        "exit.example.net",
        "www.msftconnecttest.com",
        "api.netbird.io",
        "signal.netbird.io",
        "streamline-de-fra1-0.relay.netbird.io",
        "public.easytier.top",
    ]


def test_a_name_the_direct_resolver_has_no_answer_for_is_asked_of_the_system(
    machine, monkeypatch
):
    monkeypatch.setattr(ops, "resolve_direct", lambda name, *, server, port: None)
    monkeypatch.setattr(
        ops.socket,
        "getaddrinfo",
        lambda name, *a, **k: [(None, None, None, "", ("198.51.100.77", 0))],
    )
    network = machine("darwin", has_overlays=False)

    rendered = ops.plan_tun(network, {**ROUTING, **SCOPES["hub"]})

    assert "198.51.100.77/32" in [route.destination for route in rendered.routes]


def test_a_console_named_by_its_token_alone_is_easytiers_own(machine, monkeypatch):
    network = machine("darwin", has_overlays=True)
    monkeypatch.setattr(ops, "NetbirdStatusReader", None)
    network = network_config(
        mode="server", overlays=[{"provider": "easytier", "is_enabled": True}]
    )

    class Console(EasyTierConfig):
        def config_server(self):
            return "abcdef"

    monkeypatch.setattr(
        ops,
        "read_easytier",
        lambda: Console(mode="console", config_server_sealed={"sealed": 1}),
    )

    ops.plan_tun(network, {**ROUTING, **SCOPES["hub"]})

    assert ("config-server.easytier.cn", "223.5.5.5", 53) in machine.asked


@pytest.mark.parametrize(
    "routing",
    [ROUTING, {**ROUTING, "is_proxy_enabled": True}],
    ids=["every scope off", "the served networks alone"],
)
def test_no_tun_scope_is_no_plan(machine, routing):
    network = machine("darwin", has_overlays=True)

    assert ops.plan_tun(network, routing) is None


def test_no_enabled_exit_is_no_plan(machine, monkeypatch):
    network = machine("windows", has_overlays=False)
    monkeypatch.setattr(ops, "resolve_node_secrets", lambda node_list: None)

    assert ops.plan_tun(network, {**ROUTING, **SCOPES["both"]}) is None


def test_no_way_out_is_no_plan(machine, monkeypatch):
    network = machine("darwin", has_overlays=False)
    monkeypatch.setattr(ops, "system_default_routes", lambda: [])

    assert ops.plan_tun(network, {**ROUTING, **SCOPES["hub"]}) is None


def test_linux_has_no_plan(machine, monkeypatch):
    network = machine("darwin", has_overlays=False)
    monkeypatch.setattr(ops, "is_linux", lambda: True)

    assert ops.plan_tun(network, {**ROUTING, **SCOPES["hub"]}) is None


def test_xray_is_bound_to_the_uplink_while_a_tun_scope_is_on(machine):
    machine("windows", has_overlays=False)

    assert ops.egress_interface({**ROUTING, **SCOPES["overlay"]}) == "Ethernet"
    assert ops.egress_interface(ROUTING) == ""


# --- the routing pass ----------------------------------------------------------


def a_plan(**facts) -> TunPlan:
    given = {
        "device": "utun225",
        "start_argv": ["/app/bin/tun2socks", "--device", "tun://utun225"],
        "uplink": "en0",
        "gateway": "192.168.1.1",
        "local_networks": ["192.168.1.20/24"],
        "kept_out": ["223.5.5.5"],
        "forwarding_devices": [],
        **facts,
    }
    return render_tun_plan(**given)


@pytest.fixture
def files(tmp_path, monkeypatch):
    """The plan and state files of a macOS or Windows box."""
    monkeypatch.setattr(ops, "is_linux", lambda: False)
    return {"plan_path": tmp_path / "tun_plan.json", "state_path": tmp_path / "s.json"}


def test_linux_never_touches_the_tun(monkeypatch):
    controller = FakeProcessController()
    monkeypatch.setattr(ops, "is_linux", lambda: True)

    assert ops.converge_tun(None, ROUTING, controller=controller) == []
    assert controller.calls == []


def test_the_pass_keeps_the_plan_and_enables_tun2socks(files, monkeypatch):
    controller = FakeProcessController()
    monkeypatch.setattr(ops, "plan_tun", lambda network, routing: a_plan())

    notes = ops.converge_tun(None, ROUTING, controller=controller, **files)

    assert notes == ["tun device utun225 takes the default route, 1 addresses kept out"]
    assert ops.read_plan(files["plan_path"]) == a_plan()
    assert controller.verbs() == [
        (
            "set_start_line",
            "tun2socks",
            ["/app/bin/tun2socks", "--device", "tun://utun225"],
            {},
            None,
        ),
        ("enable", "tun2socks"),
    ]


def test_a_pass_that_changes_nothing_writes_nothing(files, monkeypatch):
    controller = FakeProcessController()
    monkeypatch.setattr(ops, "plan_tun", lambda network, routing: a_plan())
    ops.converge_tun(None, ROUTING, controller=controller, **files)
    controller.calls.clear()

    assert ops.converge_tun(None, ROUTING, controller=controller, **files) == []
    assert controller.verbs() == []


def test_a_plan_gone_disables_tun2socks_and_forgets_the_plan(files, monkeypatch):
    controller = FakeProcessController()
    monkeypatch.setattr(ops, "plan_tun", lambda network, routing: a_plan())
    ops.converge_tun(None, ROUTING, controller=controller, **files)
    monkeypatch.setattr(ops, "plan_tun", lambda network, routing: None)
    controller.calls.clear()

    notes = ops.converge_tun(None, ROUTING, controller=controller, **files)

    assert notes == ["tun device utun225 taken down"]
    assert not files["plan_path"].exists()
    assert controller.verbs() == [("disable", "tun2socks")]


def test_a_route_the_service_could_not_add_fails_the_pass(files, monkeypatch):
    controller = FakeProcessController()
    controller.enabled.add("tun2socks")
    monkeypatch.setattr(ops, "plan_tun", lambda network, routing: a_plan())
    write_applied(
        files["state_path"],
        TunAppliedState(
            plan=a_plan().to_dict(), failures=["route -n add -host 223.5.5.5: exists"]
        ),
    )

    with pytest.raises(OSError, match="exists"):
        ops.converge_tun(None, ROUTING, controller=controller, **files)


# --- the keeper ------------------------------------------------------------------


class FakeApplier:
    """Brings a plan up and withdraws it, recording each call."""

    def __init__(self):
        self.calls: list = []

    def bring_up(self, plan, *, keep=None):
        self.calls.append(("up", plan.device))
        state = TunAppliedState(plan=plan.to_dict(), routes=list(plan.routes))
        if keep is not None:
            keep(state)
        return state

    def withdraw(self, state):
        self.calls.append(("down", [route.destination for route in state.routes]))
        return [f"route {route.destination} withdrawn" for route in state.routes]


@pytest.fixture
def keeper(files):
    running = {"tun2socks"}
    present = {"en0"}
    applier = FakeApplier()
    kept = ops.TunRouteKeeper(
        is_running=lambda name: name in running,
        applier=applier,
        devices=lambda: set(present),
        log=lambda line: None,
        **files,
    )
    files["plan_path"].write_text(json.dumps(a_plan().to_dict()))
    return kept, applier, running, present, files


def test_the_routes_wait_for_the_device_then_go_up_once(keeper):
    kept, applier, _running, present, files = keeper

    kept.tick()
    assert applier.calls == []

    present.add("utun225")
    kept.tick()
    kept.tick()

    assert applier.calls == [("up", "utun225")]
    assert read_applied(files["state_path"]).plan == a_plan().to_dict()


def test_tun2socks_ending_withdraws_exactly_what_was_added(keeper):
    kept, applier, running, present, files = keeper
    present.add("utun225")
    kept.tick()

    running.discard("tun2socks")
    kept.child_ended("tun2socks")

    assert applier.calls[-1] == (
        "down",
        ["223.5.5.5/32", "0.0.0.0/1", UPPER_HALF],
    )
    assert read_applied(files["state_path"]) is None


def test_another_child_ending_touches_nothing(keeper):
    kept, applier, _running, present, _files = keeper
    present.add("utun225")
    kept.tick()

    kept.child_ended("netbird")

    assert applier.calls == [("up", "utun225")]


def test_a_changed_plan_is_withdrawn_and_brought_up_again(keeper):
    kept, applier, _running, present, files = keeper
    present.add("utun225")
    kept.tick()

    changed = a_plan(kept_out=["223.5.5.5", "203.0.113.10"])
    files["plan_path"].write_text(json.dumps(changed.to_dict()))
    kept.tick()
    kept.tick()

    assert [call[0] for call in applier.calls] == ["up", "down", "up"]
    assert read_applied(files["state_path"]).plan == changed.to_dict()


def test_a_plan_taken_away_is_withdrawn(keeper):
    kept, applier, _running, present, files = keeper
    present.add("utun225")
    kept.tick()

    files["plan_path"].unlink()
    kept.tick()

    assert applier.calls[-1][0] == "down"
    assert read_applied(files["state_path"]) is None


def test_a_start_withdraws_what_a_service_that_died_left(files):
    write_applied(
        files["state_path"],
        TunAppliedState(plan=a_plan().to_dict(), routes=list(a_plan().routes)),
    )
    applier = FakeApplier()

    notes = ops.TunRouteKeeper(
        is_running=lambda name: False, applier=applier, log=lambda line: None, **files
    ).withdraw()

    assert len(notes) == 3
    assert read_applied(files["state_path"]) is None


def test_xray_exiting_takes_tun2socks_and_the_default_route_with_it(keeper, tmp_path):
    """Every exit dead, xray ends: the supervisor stops tun2socks and the
    keeper withdraws the halves, so nothing is left routing into a device
    nothing reads. Both come back once xray does."""
    _, applier, _running, present, files = keeper
    present.add("utun225")
    popen = FakePopen()
    clock = FakeClock()
    supervisor = ChildProcessSupervisor(
        log_dir=tmp_path / "log",
        base_env={},
        start_process=popen,
        requirements={"tun2socks": "xray"},
        clock=clock,
        log=lambda line: None,
    )
    kept = ops.TunRouteKeeper(
        is_running=supervisor.is_running,
        applier=applier,
        devices=lambda: set(present),
        log=lambda line: None,
        **files,
    )
    supervisor.set_watcher(kept)
    supervisor.set_start_line("xray", ChildStartLine(argv=["/app/bin/xray"]))
    supervisor.set_start_line("tun2socks", ChildStartLine(argv=["/app/bin/tun2socks"]))
    supervisor.start("tun2socks")
    supervisor.start("xray")
    supervisor.tick()
    supervisor.tick()
    assert applier.calls == [("up", "utun225")]

    popen.of("/app/bin/xray")[0].end(1)
    supervisor.tick()

    assert popen.of("/app/bin/tun2socks")[0].is_terminated
    assert applier.calls[-1] == ("down", ["223.5.5.5/32", "0.0.0.0/1", UPPER_HALF])
    assert read_applied(files["state_path"]) is None

    clock.now += SYSTEM_CHILD_RESTART_MIN_S
    supervisor.tick()
    supervisor.tick()

    assert supervisor.is_running("tun2socks")
    assert applier.calls[-1] == ("up", "utun225")


class RefusingApplier(FakeApplier):
    """Whose PowerShell cannot run until told otherwise."""

    def __init__(self):
        super().__init__()
        self.is_refusing = True

    def bring_up(self, plan, *, keep=None):
        if self.is_refusing:
            raise OSError("powershell exited 1")
        return super().bring_up(plan, keep=keep)

    def withdraw(self, state):
        if self.is_refusing:
            raise OSError("powershell exited 1")
        return super().withdraw(state)


def test_a_bring_up_that_cannot_run_is_logged_and_not_tried_again(files):
    applier = RefusingApplier()
    lines = []
    files["plan_path"].write_text(json.dumps(a_plan().to_dict()))
    kept = ops.TunRouteKeeper(
        is_running=lambda name: True,
        applier=applier,
        devices=lambda: {"utun225"},
        log=lines.append,
        **files,
    )

    kept.tick()
    kept.tick()

    assert lines == ["tun: utun225 not brought up: powershell exited 1"]
    assert read_applied(files["state_path"]) is None


def test_a_withdrawal_that_cannot_run_keeps_the_state_and_waits_to_try_again(files):
    applier = RefusingApplier()
    clock = FakeClock()
    write_applied(
        files["state_path"],
        TunAppliedState(plan=a_plan().to_dict(), routes=list(a_plan().routes)),
    )
    kept = ops.TunRouteKeeper(
        is_running=lambda name: False,
        applier=applier,
        devices=set,
        clock=clock,
        log=lambda line: None,
        **files,
    )

    kept.child_ended("tun2socks")
    assert read_applied(files["state_path"]) is not None

    applier.is_refusing = False
    kept.tick()
    assert read_applied(files["state_path"]) is not None

    clock.now += ops.TUN_RETRY_S
    kept.tick()
    assert read_applied(files["state_path"]) is None
