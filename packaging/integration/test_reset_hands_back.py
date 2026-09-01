"""What is left of the machine after `nhub reset all`.

A reset hands the network back before it replaces `config/`, and takes no
address off anything: `config/` is the only record of which interfaces had
units on them, and an interface losing its address mid-reset drops the session
that asked for the reset.

Run these after the reset, with the same `--before` snapshot the install was
measured against.
"""

import pytest

import machine_state


def test_the_machine_still_runs_its_own_manager(before):
    if not before["manager"]:
        pytest.skip("this machine arrived running no manager this knows about")

    assert machine_state.is_active(before["manager"])


def test_the_addresses_and_routes_it_arrived_with_are_intact(before):
    """Everything the machine held before the hub is still held.

    Not equality: a reset takes no address off anything, and that includes
    addresses the router phase put on ports that arrived bare — those stay,
    as residue rather than damage. What must not appear is an extra address
    on a port the machine was already using.
    """
    had = set(before["addresses_and_routes"])
    now = set(machine_state.addresses_and_routes())
    assert had <= now

    addressed = {line.split()[0] for line in had if "/" in line}
    extras = [
        line for line in now - had if "/" in line and line.split()[0] in addressed
    ]
    assert extras == []


def test_the_network_configuration_files_are_untouched(before):
    assert machine_state.config_trees() == before["config_trees"]


def test_it_still_resolves(before):
    """Takes the snapshot it does not read, so a run without a box skips this
    with the rest of the file rather than passing on a workstation."""
    assert machine_state.run(["getent", "hosts", "github.com"]).strip() != ""
