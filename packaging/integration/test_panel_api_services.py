"""Every operation the Services page offers, and what it refuses.

Nothing here installs anything: an install is minutes of package manager on a
box these tests are meant to leave as they found it. What is checked is the
list the page is drawn from and every refusal around it.
"""

import pytest

CORE_UNREACHABLE_ACTIONS = [("router", "stop"), ("web", "disable")]


@pytest.fixture(scope="module")
def services(panel) -> list:
    """Every managed unit as the page lists it."""
    return panel.read("/services")["services"]


def test_a_fresh_box_has_installed_no_optional_module(services):
    """A box that reports every module installed is a box whose Services page
    offers no way to install one — which is what a systemd whose wording
    changed used to produce."""
    optional = [entry for entry in services if not entry.get("is_core")]

    assert [entry["name"] for entry in optional if entry["is_installed"]] == []


def test_every_core_unit_is_running(services):
    core = [entry for entry in services if entry.get("is_core")]

    assert core, "a box with no core units is not a gateway"
    assert [entry["name"] for entry in core if not entry["is_active"]] == []


@pytest.mark.parametrize("action", ["enable", "start"])
def test_a_module_that_is_not_installed_cannot_be_acted_on(panel, services, action):
    absent = [
        entry
        for entry in services
        if not entry.get("is_core") and not entry["is_installed"]
    ]
    if not absent:
        pytest.skip("every optional module is installed on this box")
    name = absent[0]["name"]

    assert panel.status("POST", f"/services/{name}/action", {"action": action}) == 400


@pytest.mark.parametrize("name,action", CORE_UNREACHABLE_ACTIONS)
def test_a_core_unit_cannot_be_stopped_or_disabled(panel, name, action):
    """The panel hides these buttons, which is not the same as the gateway
    refusing them: a stopped core unit leaves the same dark box whoever asked."""
    assert panel.status("POST", f"/services/{name}/action", {"action": action}) == 400


def test_an_action_that_is_not_one_is_refused(panel):
    assert panel.status("POST", "/services/router/action", {"action": "sing"}) == 400


def test_a_service_that_is_not_one_is_a_404(panel):
    assert (
        panel.status("POST", "/services/nosuchmodule/action", {"action": "start"})
        == 404
    )


def test_the_journal_of_a_unit_that_is_not_installed_still_answers(panel):
    """An empty journal is an answer; an error here is a page that cannot be
    drawn for the module somebody is about to install."""
    assert panel.status("GET", "/services/netbird/journal") == 200


def test_the_install_plan_of_a_module_answers(panel):
    assert panel.status("GET", "/services/samba/install_plan") == 200


def test_the_install_plan_of_a_module_that_is_not_one_is_a_404(panel):
    assert panel.status("GET", "/services/nosuchmodule/install_plan") == 404


def test_a_box_running_no_job_lists_none(panel):
    """The listing a page reads on load to adopt an install it was watching
    before the browser was reloaded."""
    assert panel.read("/services/tasks")["tasks"] == []
