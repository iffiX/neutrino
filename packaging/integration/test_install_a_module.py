"""Installing an optional module the way the Services page does.

Its own file because it is the one check here that takes minutes and changes
the box: everything in `test_panel_api_services.py` reads the list and the
refusals around it, deliberately installing nothing.

That gap is why a real failure reached a person before it reached a test. The
panel's unit is root with `NoNewPrivileges` and systemd's sandboxing, and
under those the effective capability set loses `CAP_SETUID`; apt drops to the
`_apt` account to fetch, cannot, and every download dies with
`seteuid 42 failed`. Nothing that only reads the page can see that — it takes
an install, through the panel, on a machine with a package manager.

`netbird` is the module used, and deliberately: its installer is a vendor
script that runs the machine's own package manager a level below anything the
hub can pass a flag to, which is the hardest shape of the failure above. A
module whose packages happen to be cached would pass with the bug still in
place.

Not `podman`: Debian 12 offers 4.3.1 and containers need 4.4 for Quadlet, so
the hub refuses it there — correctly, and in under three seconds, which looks
exactly like the failure this file is watching for.
"""

import json
import time

import pytest

import machine_state

MODULE = "netbird"
# Something every family's package manager has to reach. Only its resolvability
# is checked: whether the archive answers is the install's own business.
REPOSITORY_HOST = "deb.debian.org"
# An install is a package manager fetching over somebody's network.
INSTALL_LIMIT_S = 600
INSTALL_POLL_S = 3.0


@pytest.fixture(scope="module")
def installed(panel):
    """The module, installed through the panel, with its job watched to the end.

    Returns:
        What the Services page says about it afterwards.
    """
    # An install is a package manager fetching from a repository, so a box
    # that cannot resolve one is a box this has nothing to say about. Skipped
    # rather than failed: the answer would be about the lab's network, and a
    # red test that means "the VM had no DNS" teaches nobody anything.
    if not machine_state.run(["getent", "hosts", REPOSITORY_HOST]).strip():
        pytest.skip(f"this box cannot resolve {REPOSITORY_HOST}")
    entry = _entry(panel)
    if entry["is_installed"]:
        pytest.skip(f"{MODULE} is already installed on this box")
    if not entry["is_installable"] or not entry["is_machine_supported"]:
        pytest.skip(
            f"{MODULE} does not install on this machine: "
            f"{entry.get('unsupported_reason') or 'not offered'}"
        )

    status, answer = panel.call("POST", f"/services/{MODULE}/install", {})
    assert status == 200, answer
    task_id = answer["task_id"]

    # The list holds running jobs only, so "gone from it" is how a job that
    # finished is told from one that has not started yet — and the poll has to
    # see it there once before it can call its absence an ending.
    deadline = time.monotonic() + INSTALL_LIMIT_S
    is_seen = False
    while time.monotonic() < deadline:
        running = [task["id"] for task in panel.read("/services/tasks")["tasks"]]
        if task_id in running:
            is_seen = True
        elif is_seen:
            break
        time.sleep(INSTALL_POLL_S)
    return _entry(panel)


def _entry(panel) -> dict:
    for entry in panel.read("/services")["services"]:
        if entry["name"] == MODULE:
            return entry
    raise AssertionError(f"{MODULE} is not on the Services page")


def test_the_module_is_installed_afterwards(installed):
    """Not "the job ended": a job that fails ends too. What the page says
    about the module is the only answer that matters to the person who
    pressed the button."""
    assert installed["is_installed"], f"{MODULE} did not install"


def test_it_is_running(installed):
    """Installing a thing and leaving it dark would only add a second step
    everyone performs."""
    assert installed["is_active"], f"{MODULE} installed but is not running"


def test_the_package_manager_was_able_to_fetch(installed):
    """The failure this file exists for. apt cannot drop to `_apt` inside the
    panel's sandbox, so every download dies before a byte arrives — and the
    module simply never appears, with the reason only in a job's output."""
    journal = machine_state.run(
        ["journalctl", "-u", "neutrino_hub_web", "--no-pager", "--since", "-30 min"]
    )

    assert "seteuid" not in journal


def test_the_install_ran_outside_the_panels_own_unit(installed):
    """It is handed to systemd rather than run in-process, which is what gives
    it a unit with none of this one's hardening. Read from what systemd
    recorded rather than from our own logging, so the check fails if the
    escape is quietly dropped."""
    journal = machine_state.run(
        ["journalctl", "--no-pager", "--since", "-30 min", "-o", "cat"]
    )

    assert "run-u" in journal or "run-r" in journal, "no transient unit was started"


def test_the_page_offers_to_uninstall_what_is_installed(installed, panel):
    """The other half of the button, and the state the next install starts
    from."""
    status, answer = panel.call("POST", f"/services/{MODULE}/uninstall", {})

    assert status == 200, json.dumps(answer)[:200]
