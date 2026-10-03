"""The TUN plan on macOS, with ifconfig, sysctl and route faked.

What these pin: the utun device takes its address first, forwarding is
turned on only when the plan forwards and was off, the uplink's scoped
default route goes in ahead of the plan's routes and one the system already
holds is no failure, each route is added in the plan's order and kept as it
is added, a route that is refused is recorded and the rest still go in, and
a withdrawal deletes the recorded routes in reverse and sets forwarding
back.
"""

from neutrino_hub.modules.tun.darwin_applier import TunDarwinApplier
from neutrino_hub.modules.tun.renderer import render_tun_plan
from tests.conftest import FakeTools

# The upper half of the address space and the device's own address, as
# the plan names them, and the uplink's scoped default route.
UPPER_HALF = "128.0.0.0/1"  # scan: allow
TUN_ADDRESS = "198.18.0.1"  # scan: allow
EVERYTHING = "0.0.0.0/0"  # scan: allow
SCOPED_DEFAULT = ["-ifscope", "en0", "-net", EVERYTHING, "192.168.1.1"]


def plan(*, forwarding=()):
    return render_tun_plan(
        device="utun225",
        start_argv=["/app/bin/tun2socks"],
        uplink="en0",
        gateway="192.168.1.1",
        local_networks=["192.168.1.20/24"],
        kept_out=["203.0.113.10", "223.5.5.5"],
        forwarding_devices=list(forwarding),
    )


def test_the_address_then_each_route_in_order():
    tools = FakeTools()
    kept = []

    state = TunDarwinApplier(run=tools).bring_up(
        plan(), keep=lambda state: kept.append(len(state.routes))
    )

    assert tools.calls == [
        ["ifconfig", "utun225", TUN_ADDRESS, TUN_ADDRESS, "mtu", "1500", "up"],
        ["route", "-n", "add", *SCOPED_DEFAULT],
        ["route", "-n", "add", "-host", "203.0.113.10", "192.168.1.1"],
        ["route", "-n", "add", "-host", "223.5.5.5", "192.168.1.1"],
        ["route", "-n", "add", "-net", "0.0.0.0/1", "-interface", "utun225"],
        ["route", "-n", "add", "-net", UPPER_HALF, "-interface", "utun225"],
    ]
    assert [route.destination for route in state.routes] == [
        EVERYTHING,
        "203.0.113.10/32",
        "223.5.5.5/32",
        "0.0.0.0/1",
        UPPER_HALF,
    ]
    assert state.routes[0].is_scoped
    assert kept == [1, 2, 3, 4, 5]
    assert state.failures == []
    assert state.forwarding_before == ""


def test_a_scoped_default_the_system_holds_is_left_alone():
    tools = FakeTools()
    tools.failing.add(("route", "-n", "add", "-ifscope"))
    tools.answers  # the refusal reads "File exists" as route prints it

    def run(command, **keywords):
        if tuple(command[:4]) == ("route", "-n", "add", "-ifscope"):
            from neutrino_hub.utils.subprocess_run import CommandResult

            tools.calls.append(list(command))
            return CommandResult(list(command), 1, "", "route: File exists\n")
        return tools(command, **keywords)

    state = TunDarwinApplier(run=run).bring_up(plan())

    assert [route.destination for route in state.routes] == [
        "203.0.113.10/32",
        "223.5.5.5/32",
        "0.0.0.0/1",
        UPPER_HALF,
    ]
    assert state.failures == []


def test_an_uplink_without_a_gateway_gets_no_scoped_default():
    tools = FakeTools()
    rendered = render_tun_plan(
        device="utun225",
        start_argv=["/app/bin/tun2socks"],
        uplink="en0",
        gateway="",
        local_networks=["192.168.1.20/24"],
        kept_out=[],
        forwarding_devices=[],
    )

    state = TunDarwinApplier(run=tools).bring_up(rendered)

    assert not tools.ran("route", "-n", "add", "-ifscope")
    assert [route.destination for route in state.routes] == ["0.0.0.0/1", UPPER_HALF]


def test_forwarding_is_turned_on_when_the_overlays_exit_here_and_set_back_after():
    tools = FakeTools()
    tools.answers[("sysctl", "-n", "net.inet.ip.forwarding")] = "0\n"
    applier = TunDarwinApplier(run=tools)

    state = applier.bring_up(plan(forwarding=["utun4"]))
    applier.withdraw(state)

    assert ["sysctl", "-w", "net.inet.ip.forwarding=1"] in tools.calls
    assert state.forwarding_before == "0"
    assert tools.calls[-1] == ["sysctl", "-w", "net.inet.ip.forwarding=0"]


def test_forwarding_already_on_is_left_alone():
    tools = FakeTools()
    tools.answers[("sysctl", "-n", "net.inet.ip.forwarding")] = "1\n"
    applier = TunDarwinApplier(run=tools)

    state = applier.bring_up(plan(forwarding=["utun4"]))
    applier.withdraw(state)

    assert not tools.ran("sysctl", "-w")
    assert state.forwarding_before == ""


def test_a_refused_route_is_recorded_and_the_rest_still_go_in():
    tools = FakeTools()
    tools.failing.add(("route", "-n", "add", "-host", "203.0.113.10"))

    state = TunDarwinApplier(run=tools).bring_up(plan())

    assert [route.destination for route in state.routes] == [
        EVERYTHING,
        "223.5.5.5/32",
        "0.0.0.0/1",
        UPPER_HALF,
    ]
    assert len(state.failures) == 1
    assert "203.0.113.10" in state.failures[0]


def test_a_device_that_takes_no_address_gets_no_route():
    tools = FakeTools()
    tools.failing.add(("ifconfig", "utun225"))

    state = TunDarwinApplier(run=tools).bring_up(plan())

    assert state.routes == []
    assert not tools.ran("route")
    assert "ifconfig utun225" in state.failures[0]


def test_a_withdrawal_deletes_in_reverse():
    tools = FakeTools()
    applier = TunDarwinApplier(run=tools)
    state = applier.bring_up(plan())
    tools.calls.clear()

    notes = applier.withdraw(state)

    assert tools.calls == [
        ["route", "-n", "delete", "-net", UPPER_HALF, "-interface", "utun225"],
        ["route", "-n", "delete", "-net", "0.0.0.0/1", "-interface", "utun225"],
        ["route", "-n", "delete", "-host", "223.5.5.5", "192.168.1.1"],
        ["route", "-n", "delete", "-host", "203.0.113.10", "192.168.1.1"],
        ["route", "-n", "delete", *SCOPED_DEFAULT],
    ]
    assert len(notes) == 5


def test_a_route_that_went_with_the_device_is_no_error():
    tools = FakeTools()
    applier = TunDarwinApplier(run=tools)
    state = applier.bring_up(plan())
    tools.failing.add(("route", "-n", "delete", "-net"))

    notes = applier.withdraw(state)

    assert notes == [
        "route 223.5.5.5/32 withdrawn",
        "route 203.0.113.10/32 withdrawn",
        f"route {EVERYTHING} withdrawn",
    ]
