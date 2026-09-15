"""Every operation the Modules page offers, and what it refuses.

Nothing here installs anything: an install is minutes of package manager on a
machine these tests are meant to leave as they found it, and it needs an agent
answering. What is checked is the list the page is drawn from and every
refusal around it, against a device that has never joined.
"""

import pytest

MODULE_VERBS = ["install", "start", "stop", "uninstall"]
# A row the page can offer, and one no catalog has.
KNOWN_MODULE = "samba"
UNKNOWN_MODULE = "nosuchmodule"
# The states a row may report, the closed set the panel words.
STATE_WORDS = frozenset(
    {
        "absent",
        "installed",
        "stopped",
        "running",
        "installing",
        "uninstalling",
        "failed",
        "unsupported",
        "unknown",
    }
)


@pytest.fixture(scope="module")
def device_id(panel):
    """A stored device with no agent, adopted from a scan row of its own."""
    status, device = panel.call(
        "POST",
        "/hub/device/set",
        {"device_id": "scan:52:54:00:cc:dd:ee", "name": "modules audit"},
    )
    assert status == 200, device
    yield device["id"]
    panel.call("POST", "/hub/device/remove", {"device_id": device["id"]})


@pytest.fixture(scope="module")
def modules(panel, device_id) -> list:
    """Every module as the page lists it for that device."""
    return panel.read(f"/agent/module?device_id={device_id}")["modules"]


def test_the_catalog_is_listed_for_a_device_with_no_agent(modules):
    """A page that cannot say why draws every row as "not installed", so the
    list answers even when nothing is beating."""
    assert modules, "a hub with no module catalog has no Modules page"
    assert KNOWN_MODULE in {entry["name"] for entry in modules}


def test_every_row_carries_a_state_of_the_closed_set(modules):
    assert {entry["state"] for entry in modules} <= STATE_WORDS


def test_a_device_that_never_joined_asks_nothing_of_any_module(modules):
    """``want`` is what the hub asks; a device it has asked nothing of holds
    no want at all."""
    assert [entry["name"] for entry in modules if entry["want"]] == []


@pytest.mark.parametrize("verb", MODULE_VERBS)
def test_a_verb_needs_an_agent_on_the_socket(panel, device_id, verb):
    body = {"device_id": device_id, "module": KNOWN_MODULE}

    status, answer = panel.call("POST", f"/agent/module/{verb}", body)
    assert status == 409, answer
    assert answer["detail"]["code"] == "agent_offline"


@pytest.mark.parametrize("verb", MODULE_VERBS)
def test_a_module_the_catalog_lacks_is_a_404(panel, device_id, verb):
    body = {"device_id": device_id, "module": UNKNOWN_MODULE}

    status, answer = panel.call("POST", f"/agent/module/{verb}", body)
    assert status == 404, answer
    assert answer["detail"]["code"] == "module_unknown"


@pytest.mark.parametrize("verb", MODULE_VERBS)
def test_a_device_the_hub_lacks_is_a_404(panel, verb):
    body = {"device_id": "00000000000000000000000000000000", "module": KNOWN_MODULE}

    status, answer = panel.call("POST", f"/agent/module/{verb}", body)
    assert status == 404, answer
    assert answer["detail"]["code"] == "device_unknown"


def test_the_list_of_a_device_the_hub_lacks_is_a_404(panel):
    path = "/agent/module?device_id=00000000000000000000000000000000"

    assert panel.status("GET", path) == 404


def test_a_modules_own_page_needs_a_device_the_hub_manages(panel, device_id):
    """The configuration pane belongs to a machine the hub has a binding
    with: a row nobody's agent ever joined has nothing to configure."""
    path = f"/agent/module/{KNOWN_MODULE}?device_id={device_id}"

    status, answer = panel.call("GET", path)
    assert status == 404, answer
    assert answer["detail"]["code"] == "device_unknown"
