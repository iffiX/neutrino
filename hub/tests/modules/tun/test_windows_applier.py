"""The TUN plan on Windows, with PowerShell faked.

What these pin: one script gives the adapter its address, turns forwarding
on where the plan forwards and adds every route in the plan's order; what
it reports added is what is recorded, in that order, with the refused ones
as failures; a withdrawal removes the recorded routes in reverse and turns
off only the forwarding the hub turned on.
"""

import pytest

from neutrino_hub.modules.tun.applied_state import TunAppliedState
from neutrino_hub.modules.tun.constants import (
    TUN_WINDOWS_DOWN_SCRIPT,
    TUN_WINDOWS_ROUTES_SCRIPT,
    TUN_WINDOWS_UP_SCRIPT,
)
from neutrino_hub.modules.tun.renderer import render_tun_plan
from neutrino_hub.modules.tun.windows_applier import TunWindowsApplier
from tests.conftest import FakePowerShell

# The upper half of the address space and the device's own address, as
# the plan names them.
UPPER_HALF = "128.0.0.0/1"  # scan: allow
TUN_ADDRESS = "198.18.0.1"  # scan: allow


def plan(*, forwarding=()):
    return render_tun_plan(
        device="neutrino_tun",
        start_argv=["C:\\hub\\bin\\tun2socks.exe"],
        uplink="Ethernet",
        gateway="192.168.1.1",
        local_networks=["192.168.1.20/24"],
        kept_out=["203.0.113.10", "223.5.5.5"],
        forwarding_devices=list(forwarding),
    )


def route(prefix, alias, next_hop):
    return {"prefix": prefix, "alias": alias, "next_hop": next_hop, "metric": 1}


ROUTES = [
    route("203.0.113.10/32", "Ethernet", "192.168.1.1"),
    route("223.5.5.5/32", "Ethernet", "192.168.1.1"),
    route("0.0.0.0/1", "neutrino_tun", "0.0.0.0"),
    route(UPPER_HALF, "neutrino_tun", "0.0.0.0"),
]


def test_one_script_addresses_the_adapter_and_adds_every_route_in_order():
    powershell = FakePowerShell(
        {
            TUN_WINDOWS_UP_SCRIPT: {
                "added": [entry["prefix"] for entry in ROUTES],
                "forwarded": ["wt0", "neutrino_tun"],
                "failed": [],
            }
        }
    )
    kept = []

    state = TunWindowsApplier(powershell=powershell).bring_up(
        plan(forwarding=["wt0", "neutrino_tun"]), keep=kept.append
    )

    assert powershell.runs == [
        (
            TUN_WINDOWS_UP_SCRIPT,
            {
                "alias": "neutrino_tun",
                "address": TUN_ADDRESS,
                "prefix_length": 30,
                "forwarding": ["wt0", "neutrino_tun"],
                "routes": ROUTES,
            },
        )
    ]
    assert [entry.destination for entry in state.routes] == [
        entry["prefix"] for entry in ROUTES
    ]
    assert state.forwarded_devices == ["wt0", "neutrino_tun"]
    assert kept == [state]


def test_a_route_the_script_could_not_add_is_a_failure_and_not_recorded():
    powershell = FakePowerShell(
        {
            TUN_WINDOWS_UP_SCRIPT: {
                "added": ["223.5.5.5/32", "0.0.0.0/1", UPPER_HALF],
                "forwarded": [],
                "failed": {
                    "prefix": "203.0.113.10/32",
                    "detail": "The object already exists.",
                },
            }
        }
    )

    state = TunWindowsApplier(powershell=powershell).bring_up(plan())

    assert [entry.destination for entry in state.routes] == [
        "223.5.5.5/32",
        "0.0.0.0/1",
        UPPER_HALF,
    ]
    assert state.failures == ["203.0.113.10/32: The object already exists."]


def test_a_withdrawal_removes_in_reverse_and_turns_off_what_was_turned_on():
    powershell = FakePowerShell(
        {
            TUN_WINDOWS_UP_SCRIPT: {
                "added": [entry["prefix"] for entry in ROUTES],
                "forwarded": "wt0",
            }
        }
    )
    applier = TunWindowsApplier(powershell=powershell)
    state = applier.bring_up(plan(forwarding=["wt0", "neutrino_tun"]))

    notes = applier.withdraw(state)

    assert powershell.runs[-1] == (
        TUN_WINDOWS_DOWN_SCRIPT,
        {"routes": list(reversed(ROUTES)), "forwarding": ["wt0"]},
    )
    assert notes[0] == f"route {UPPER_HALF} withdrawn"
    assert notes[-1] == "forwarding off on wt0"


def test_nothing_applied_runs_no_script():
    powershell = FakePowerShell()

    assert TunWindowsApplier(powershell=powershell).withdraw(TunAppliedState()) == []
    assert powershell.runs == []


def test_a_powershell_that_cannot_run_is_raised():
    powershell = FakePowerShell(error=OSError("powershell exited 1"))

    with pytest.raises(OSError):
        TunWindowsApplier(powershell=powershell).bring_up(plan())


def test_endpoint_routes_are_added_and_removed_beside_the_plan():
    powershell = FakePowerShell(
        {
            TUN_WINDOWS_ROUTES_SCRIPT: {
                "added": ["203.0.113.10/32"],
                "failed": {"prefix": "223.5.5.5/32", "detail": "exists"},
            }
        }
    )
    applier = TunWindowsApplier(powershell=powershell)

    added, failures = applier.add_routes(list(plan().routes[:2]))
    notes = applier.delete_routes(added)

    assert powershell.runs == [
        (TUN_WINDOWS_ROUTES_SCRIPT, {"routes": ROUTES[:2]}),
        (TUN_WINDOWS_DOWN_SCRIPT, {"routes": ROUTES[:1], "forwarding": []}),
    ]
    assert [route.destination for route in added] == ["203.0.113.10/32"]
    assert failures == ["223.5.5.5/32: exists"]
    assert notes == ["route 203.0.113.10/32 withdrawn"]
