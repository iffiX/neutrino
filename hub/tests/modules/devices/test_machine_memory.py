"""The memory a machine's container modules need, against its Podman machine's.

What these pin: the sum of the ``memory_mib`` of every container module not
asked ``absent``, rounded up to whole GiB; the machine's memory read from
the report while the stored account's machine runs, else from the stored
Run settings, else from the default the computer reported; no advice on
Linux, while the machine's memory is unknown, or while the need fits.
"""

import json

import pytest

from neutrino_hub.modules.devices.machine_memory import (
    machine_memory_gib,
    memory_need,
)
from tests.conftest import DEMO_MANIFEST

STORED = {"account": "lab", "cpus": 0, "memory_gib": 0, "disk_gib": 120}
RUNNING = {
    "account": "lab",
    "is_running": True,
    "cpus": 4,
    "memory_gib": 2,
    "disk_gib": 120,
    "default_memory_gib": 4,
}


@pytest.fixture
def modules(demo_container_module):
    """Demo at 2600 MiB and a second container module, other, at 1536 MiB."""
    demo = dict(DEMO_MANIFEST, memory_mib=2600)
    other = dict(DEMO_MANIFEST, name="other", title="Other", memory_mib=1536)
    for manifest in (demo, other):
        path = demo_container_module / f"{manifest['name']}.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
    return demo_container_module


def wants(**by_name) -> dict:
    return {name: {"want": want, "is_settled": False} for name, want in by_name.items()}


def test_the_need_sums_every_container_module_not_asked_absent(modules):
    need = memory_need(
        wants(demo="installed", other="running", samba="running"),
        os_name="windows",
        stored=STORED,
        reported=RUNNING,
    )

    assert need == {"need_gib": 5, "memory_gib": 2}


def test_a_module_asked_absent_needs_nothing(modules):
    need = memory_need(
        wants(demo="installed", other="absent"),
        os_name="darwin",
        stored=STORED,
        reported=RUNNING,
    )

    assert need == {"need_gib": 3, "memory_gib": 2}


def test_a_need_that_fits_the_machine_gives_no_advice(modules):
    reported = dict(RUNNING, memory_gib=4)

    need = memory_need(
        wants(demo="running"), os_name="windows", stored=STORED, reported=reported
    )

    assert need is None


def test_linux_gets_no_advice(modules):
    need = memory_need(
        wants(demo="running"), os_name="linux", stored=STORED, reported=RUNNING
    )

    assert need is None


def test_an_unknown_memory_gives_no_advice(modules):
    need = memory_need(wants(demo="running"), os_name="windows", stored={}, reported={})

    assert need is None


def test_the_running_machine_of_the_stored_account_gives_the_memory():
    assert machine_memory_gib(STORED, dict(RUNNING, memory_gib=3.8)) == 4


def test_a_stopped_machine_gives_the_stored_memory():
    stored = dict(STORED, memory_gib=6)
    reported = dict(RUNNING, is_running=False)

    assert machine_memory_gib(stored, reported) == 6


def test_another_accounts_machine_gives_the_stored_memory():
    stored = dict(STORED, account="ann", memory_gib=6)

    assert machine_memory_gib(stored, RUNNING) == 6


def test_a_stored_0_gives_the_default_the_computer_reported():
    reported = dict(RUNNING, is_running=False)

    assert machine_memory_gib(STORED, reported) == 4
