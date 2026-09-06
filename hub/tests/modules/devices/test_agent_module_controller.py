"""The agent module controller: one queue per device, and retry by asking.

The rule this file exists for is that **no timer retries a failed order**.
A vendor refusing now refuses in a minute, so a failure stands until a
person asks again — and clears on its own only when the question is settled
another way: the software turning up anyway, or an order for the opposite
action.

Also pinned: two requests for one device run in the order they were made,
and the SSH bootstrap shares the device's lock without entering the module
queue, because putting the agent on a machine is not a module order.
"""

import threading
import time
from pathlib import Path

import pytest

from neutrino_hub.modules.devices.agent_module_cache import (
    AgentModuleArtifact,
    AgentModuleFetchError,
)
from neutrino_hub.modules.devices.agent_module_controller import (
    ORDER_FAILED,
    AgentModuleController,
    ask_module,
    order_action_for,
)
from neutrino_hub.modules.devices.install_lock import DeviceInstallLocks

MAC = "aa:bb:cc:dd:ee:ff"
OTHER_MAC = "11:22:33:44:55:66"
AMD64 = {"os": "linux", "family": "debian", "arch": "amd64"}

MANIFEST = {
    "name": "fakedesk",
    "installer": "hub",
    "platforms": {
        "linux-debian-amd64": {"url": "https://x/y.deb", "package_kind": "deb"}
    },
}
OPENSSH = {
    "name": "openssh_server",
    "kind": "openssh",
    "installer": "platform",
    "platforms": {"linux-debian": {"packages": ["openssh-server"], "service": "ssh"}},
}
SYSTEM = {
    "name": "samba_mount",
    "kind": "system_package",
    "installer": "platform",
    "platforms": {
        "linux-debian": {"packages": ["cifs-utils"]},
        "windows": {},
        "darwin": {},
    },
}
USER = {
    "name": "teamviewer",
    "kind": "package",
    "installer": "user",
    "platforms": {"linux": {"verify": "command -v teamviewer"}},
}


class StubCache:
    """A cache that answers at once, or refuses when told to."""

    def __init__(self, *, error=None):
        self.asked: list = []
        self.error = error
        self.gate = None

    def artifact(self, *, name, manifest, platform):
        self.asked.append(name)
        if self.gate is not None:
            self.gate.wait(timeout=5)
        if self.error is not None:
            raise self.error
        return AgentModuleArtifact(
            key=f"{name}-key", path=Path("/nonexistent"), digest="d", package_kind="deb"
        )


@pytest.fixture
def controller():
    """A controller whose orders wait only briefly for a machine's word."""
    cache = StubCache()
    locks = DeviceInstallLocks()
    return (
        AgentModuleController(cache=cache, locks=locks, timeout_s=2.0),
        cache,
        locks,
    )


def wait_for(predicate, timeout_s: float = 3.0) -> bool:
    """Wait for the worker thread to get somewhere."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def ask_install(controller, *, mac=MAC, module="fakedesk", manifest=MANIFEST):
    return controller.ask(
        mac_address=mac,
        module=module,
        manifest=manifest,
        platform=AMD64,
        action="install",
    )


def test_an_order_is_handed_down_once_it_has_its_bytes(controller):
    orders, cache, _ = controller

    order = ask_install(orders)

    assert wait_for(lambda: orders.pending_order(MAC) is not None)
    standing = orders.pending_order(MAC)
    assert standing.id == order.id
    assert standing.artifact_key == "fakedesk-key"
    assert cache.asked == ["fakedesk"]


def test_the_same_order_is_handed_down_until_the_machine_answers(controller):
    orders, _, _ = controller
    ask_install(orders)
    assert wait_for(lambda: orders.pending_order(MAC) is not None)

    first = orders.pending_order(MAC)
    second = orders.pending_order(MAC)

    # A beat lost in the wire is not an order lost.
    assert first.id == second.id


def test_two_requests_for_one_device_run_in_turn(controller):
    orders, cache, _ = controller
    cache.gate = threading.Event()

    first = ask_install(orders)
    second = ask_install(orders, module="otherdesk")

    assert wait_for(lambda: cache.asked == ["fakedesk"])
    # The second is queued behind the first, not started beside it: two
    # package managers on one machine is the failure this prevents.
    assert cache.asked == ["fakedesk"]
    assert orders.pending_order(MAC) is None
    cache.gate.set()
    assert wait_for(lambda: orders.pending_order(MAC) is not None)
    assert orders.pending_order(MAC).id == first.id

    orders.record_result(mac_address=MAC, order_id=first.id, state="done")
    assert wait_for(lambda: cache.asked == ["fakedesk", "otherdesk"])
    assert wait_for(lambda: (orders.pending_order(MAC) or first).id == second.id)


def test_two_devices_do_not_wait_on_each_other(controller):
    orders, cache, _ = controller

    ask_install(orders)
    ask_install(orders, mac=OTHER_MAC)

    # One queue per device, so a busy machine does not hold up another.
    assert wait_for(lambda: orders.pending_order(MAC) is not None)
    assert wait_for(lambda: orders.pending_order(OTHER_MAC) is not None)


def test_the_ssh_bootstrap_shares_the_device_lock_without_a_module_order(controller):
    orders, cache, locks = controller
    cache.gate = threading.Event()
    ask_install(orders)
    assert wait_for(lambda: locks.is_held(MAC))

    # The bootstrap is not an order — nothing of it is in the module queue —
    # but it cannot start while one is installing, because it takes the
    # same lock the device owns.
    assert locks.is_held(MAC) is True
    assert locks.is_held(OTHER_MAC) is False
    assert [order.module for order in orders.orders(MAC)] == ["fakedesk"]

    took_it = threading.Event()

    def bootstrap():
        with locks.hold(MAC) as is_held:
            if is_held:
                took_it.set()

    waiter = threading.Thread(target=bootstrap, daemon=True)
    waiter.start()
    assert took_it.wait(timeout=0.3) is False

    cache.gate.set()
    order = orders.pending_order(MAC) or orders.orders(MAC)[0]
    orders.record_result(mac_address=MAC, order_id=order.id, state="done")
    assert took_it.wait(timeout=3) is True


def test_a_failure_is_recorded_and_no_tick_ever_retries_it(controller):
    orders, cache, _ = controller
    cache.error = AgentModuleFetchError("module_fetch_failed", detail="refused")

    order = ask_install(orders)
    assert wait_for(lambda: not order.is_open)

    assert order.state == ORDER_FAILED
    assert order.code == "module_fetch_failed"
    assert order.params == {"detail": "refused"}
    # Nothing is queued behind it and nothing re-runs: the only fetch was
    # the one attempt.
    for _ in range(5):
        orders.pending_order(MAC)
        orders.note_reported_states(MAC, {"fakedesk": {"state": "absent"}})
    time.sleep(0.2)
    assert cache.asked == ["fakedesk"]
    assert orders.failure_for(MAC, "fakedesk").id == order.id


def test_asking_again_is_a_new_order_and_runs(controller):
    orders, cache, _ = controller
    cache.error = AgentModuleFetchError("module_fetch_failed")
    first = ask_install(orders)
    assert wait_for(lambda: not first.is_open)

    cache.error = None
    second = ask_install(orders)

    assert second.id != first.id
    assert wait_for(lambda: orders.pending_order(MAC) is not None)
    assert cache.asked == ["fakedesk", "fakedesk"]
    # A person asking is a fresh start, so the old verdict is gone.
    assert orders.failure_for(MAC, "fakedesk") is None


def test_the_software_turning_up_anyway_clears_the_failure(controller):
    orders, cache, _ = controller
    cache.error = AgentModuleFetchError("module_fetch_failed")
    order = ask_install(orders)
    assert wait_for(lambda: not order.is_open)
    assert orders.failure_for(MAC, "fakedesk") is not None

    # Somebody installed it by hand; the question the failure asked is
    # settled, so it goes without anyone clearing it.
    orders.note_reported_states(MAC, {"fakedesk": {"state": "installed"}})

    assert orders.failure_for(MAC, "fakedesk") is None


def test_the_opposite_action_clears_the_failure_and_orders_nothing(controller):
    orders, cache, _ = controller
    cache.error = AgentModuleFetchError("module_fetch_failed")
    failed = ask_install(orders)
    assert wait_for(lambda: not failed.is_open)

    # Asked to uninstall what the machine says was never there: the
    # question is settled already, so there is nothing to send.
    undone = orders.ask(
        mac_address=MAC,
        module="fakedesk",
        manifest=MANIFEST,
        platform=AMD64,
        action="uninstall",
        reported_state="absent",
    )

    assert undone is None
    assert orders.failure_for(MAC, "fakedesk") is None


def test_an_uninstall_of_something_present_is_ordered(controller):
    orders, _, _ = controller

    order = orders.ask(
        mac_address=MAC,
        module="fakedesk",
        manifest=MANIFEST,
        platform=AMD64,
        action="uninstall",
        reported_state="installed",
    )

    assert order is not None
    assert order.action == "uninstall"


def test_a_machine_that_never_answers_gives_its_lock_back(controller):
    orders, _, locks = controller

    order = ask_install(orders)

    assert wait_for(lambda: not order.is_open, timeout_s=6)
    assert order.code == "agent_never_reported"
    # The lock is the device's, and an agent that went away must not hold
    # it against the next thing somebody asks for.
    assert wait_for(lambda: not locks.is_held(MAC))


def test_a_result_for_an_order_this_device_does_not_own_is_ignored(controller):
    orders, _, _ = controller
    order = ask_install(orders)

    assert (
        orders.record_result(mac_address=OTHER_MAC, order_id=order.id, state="done")
        is False
    )


def test_the_history_is_what_the_install_pane_reads(controller):
    orders, _, _ = controller
    first = ask_install(orders)
    orders.record_result(
        mac_address=MAC,
        order_id=first.id,
        state="failed",
        code="install_failed",
        output="dpkg: held broken packages",
    )

    view = orders.orders(MAC)[0].to_view()

    assert view["module"] == "fakedesk"
    assert view["state"] == "failed"
    assert view["output"] == "dpkg: held broken packages"
    # The manifest it was resolved from is not the panel's business.
    assert "manifest" not in view


def test_forgetting_a_device_drops_everything_held_for_it(controller):
    orders, _, _ = controller
    order = ask_install(orders)
    orders.record_result(
        mac_address=MAC, order_id=order.id, state="failed", code="install_failed"
    )

    orders.forget(MAC)

    assert orders.orders(MAC) == []
    assert orders.failure_for(MAC, "fakedesk") is None


@pytest.mark.parametrize(
    "manifest, is_enabled, expected",
    [
        (MANIFEST, True, "install"),
        (MANIFEST, False, "uninstall"),
        (OPENSSH, True, "install"),
        (OPENSSH, False, "uninstall"),
        (SYSTEM, True, "install"),
        (SYSTEM, False, "uninstall"),
    ],
)
def test_every_click_means_install_or_uninstall(manifest, is_enabled, expected):
    # One verb pair for every kind; the mechanics are each platform's own.
    assert (
        order_action_for(manifest=manifest, platform=AMD64, is_enabled=is_enabled)
        == expected
    )


def test_a_platform_that_carries_the_module_natively_is_asked_nothing():
    # samba_mount on windows and macOS: an empty entry means nothing to
    # install and nothing to uninstall.
    for is_enabled in (True, False):
        assert (
            order_action_for(
                manifest=SYSTEM,
                platform={"os": "windows", "family": "", "arch": "amd64"},
                is_enabled=is_enabled,
            )
            is None
        )


def test_a_user_tier_module_is_asked_nothing_either_way():
    # The person installs it themselves; the hub only detects and manages.
    for is_enabled in (True, False):
        assert (
            order_action_for(manifest=USER, platform=AMD64, is_enabled=is_enabled)
            is None
        )


def test_a_user_tier_click_queues_no_order(controller):
    orders, cache, _ = controller

    order = ask_module(
        controller=orders,
        mac_address=MAC,
        module="teamviewer",
        manifest=USER,
        platform=AMD64,
        is_enabled=True,
    )

    assert order is None
    assert cache.asked == []


def test_the_controller_refuses_a_user_tier_order_outright(controller):
    orders, _, _ = controller

    with pytest.raises(ValueError):
        orders.ask(
            mac_address=MAC,
            module="teamviewer",
            manifest=USER,
            platform=AMD64,
            action="install",
        )


def test_a_distro_package_order_takes_the_queue_but_skips_the_cache(controller):
    orders, cache, locks = controller

    order = orders.ask(
        mac_address=MAC,
        module="samba_mount",
        manifest=SYSTEM,
        platform=AMD64,
        action="install",
    )

    assert wait_for(lambda: orders.pending_order(MAC) is not None)
    # The device's lock is held like any other order's; the cache was never
    # asked, and the order carries no artifact for the agent to fetch.
    assert locks.is_held(MAC)
    assert cache.asked == []
    handed = orders.pending_order(MAC)
    assert handed.to_wire()["artifact_key"] == ""
    orders.record_result(
        mac_address=MAC, order_id=order.id, state="done", output="Setting up"
    )
    assert wait_for(lambda: not locks.is_held(MAC))


def test_a_module_with_no_build_here_is_asked_nothing(controller):
    orders, cache, _ = controller

    order = ask_module(
        controller=orders,
        mac_address=MAC,
        module="fakedesk",
        manifest=MANIFEST,
        platform={"os": "windows", "family": "", "arch": "amd64"},
        is_enabled=True,
    )

    assert order is None
    assert cache.asked == []


def test_an_action_that_is_not_one_of_the_four_is_refused(controller):
    orders, _, _ = controller

    with pytest.raises(ValueError):
        orders.ask(
            mac_address=MAC,
            module="fakedesk",
            manifest=MANIFEST,
            platform=AMD64,
            action="reticulate",
        )
