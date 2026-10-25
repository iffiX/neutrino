"""Every operation the Modules page offers, and what it refuses.

Nothing here installs anything: an install is minutes of package manager on a
machine these tests are meant to leave as they found it, and it needs an agent
answering. What is checked is the list the page is drawn from and every
refusal around it, against a device that has never joined.

One fact the page does not show is read through the installed hub's own
interpreter: the recipe a Linux machine of this box's platform is sent, which
names the artifacts the agent fetches one `package` stream each.
"""

import json
import subprocess

import pytest

import test_panel_update as update

MODULE_VERBS = ["install", "start", "stop", "uninstall"]
# A row the page can offer, and one no catalog has.
KNOWN_MODULE = "samba"
UNKNOWN_MODULE = "nosuchmodule"
# The programs run as a person's account the hub fetches, and the artifacts
# each one's Linux recipe takes from the package stream, in the manifest's
# order.
HUB_MODULE_ARTIFACTS = {"codeg": ["server", "node"], "cloudcli": ["node"]}
# The modules the agent's own package carries: no press is offered on them.
AGENT_MODULES = ["terminal", "remote_desktop"]
# A page the shared instances router serves.
INSTANCE_MODULE = "codeg"
# How a row is installed: the closed set of methods, as the manifests name it.
INSTALL_METHODS = frozenset({"agent", "builtin", "system", "hub", "container"})
# A person's own remote desktop products: detected by a module, never rows.
REMOTE_DESKTOP_PRODUCTS = ["anydesk", "teamviewer"]
# Each module's artifacts the package stream serves, in the recipe the hub
# resolves for a Linux machine of this box's family and architecture, run in
# the hub's interpreter.
RECIPE_SCRIPT = """
import json
from neutrino_hub.modules.devices.manifests import (
    load_module_manifests,
    module_recipe,
    resolve_platform_entry,
)
from neutrino_hub.system.machine import distribution_family, machine_architecture
platform = {"os": "linux", "family": distribution_family(), "arch": machine_architecture()}
recipes = {}
for name, manifest in load_module_manifests().items():
    _, entry = resolve_platform_entry(manifest, platform)
    artifacts = module_recipe(entry).get("params", {}).get("artifacts") or []
    recipes[name] = [item["name"] for item in artifacts if item["kind"] != "npm"]
print(json.dumps(recipes))
"""
# The states a row may report, the closed set the panel words.
STATE_WORDS = frozenset(
    {
        "absent",
        "installed",
        "stopped",
        "running",
        "install_failed",
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


@pytest.fixture(scope="module")
def linux_recipes() -> dict:
    """Each module's package stream artifacts in a Linux machine's recipe, by name."""
    result = subprocess.run(
        [update.HUB_PYTHON, "-c", RECIPE_SCRIPT], capture_output=True, text=True
    )
    assert result.returncode == 0, (result.stderr or result.stdout).strip()
    return json.loads(result.stdout)


def test_the_catalog_is_listed_for_a_device_with_no_agent(modules):
    """A page that cannot say why draws every row as "not installed", so the
    list answers even when nothing is beating."""
    assert modules, "a hub with no module catalog has no Modules page"
    assert KNOWN_MODULE in {entry["name"] for entry in modules}


def test_every_row_carries_a_state_of_the_closed_set(modules):
    assert {entry["state"] for entry in modules} <= STATE_WORDS


def test_every_row_is_installed_by_one_of_the_methods(modules):
    assert {entry["method"] for entry in modules} <= INSTALL_METHODS | {""}


@pytest.mark.parametrize("name", sorted(HUB_MODULE_ARTIFACTS))
def test_a_program_run_as_an_account_is_a_hub_row(modules, name):
    rows = {entry["name"]: entry for entry in modules}

    assert name in rows, sorted(rows)
    assert rows[name]["method"] == "hub"


@pytest.mark.parametrize("name", sorted(HUB_MODULE_ARTIFACTS))
def test_a_linux_recipe_names_each_artifact_the_agent_fetches(linux_recipes, name):
    """The row shows no recipe; the state the agent is sent does, and the
    agent opens one ``package`` stream per artifact the hub serves."""
    assert linux_recipes[name] == HUB_MODULE_ARTIFACTS[name]


def test_a_persons_own_remote_desktop_product_is_no_row(modules):
    """AnyDesk and TeamViewer are what the remote desktop module detects on
    a machine, not modules of their own."""
    assert not set(REMOTE_DESKTOP_PRODUCTS) & {entry["name"] for entry in modules}


def test_a_device_that_never_joined_asks_only_the_agents_own_modules(modules):
    """``want`` is what the hub asks. Of a device it has asked nothing of, it
    asks only the two modules the agent's package carries: the terminal is
    always wanted running, and the remote desktop stopped while its switch
    is off (protocol.md)."""
    wants = {entry["name"]: entry["want"] for entry in modules if entry["want"]}

    assert wants == {"terminal": "running", "remote_desktop": "stopped"}


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
@pytest.mark.parametrize("name", AGENT_MODULES)
def test_a_module_the_agent_carries_refuses_every_press(panel, device_id, name, verb):
    """The agent's own package holds these two, so the row offers none of the
    four presses, and a press sent anyway is refused before the device is
    looked up."""
    body = {"device_id": device_id, "module": name}

    status, answer = panel.call("POST", f"/agent/module/{verb}", body)
    assert status == 400, answer
    assert answer["detail"] == {"code": "module_not_optional", "params": {"name": name}}


@pytest.mark.parametrize("verb", MODULE_VERBS)
def test_a_device_the_hub_lacks_is_a_404(panel, verb):
    body = {"device_id": "00000000000000000000000000000000", "module": KNOWN_MODULE}

    status, answer = panel.call("POST", f"/agent/module/{verb}", body)
    assert status == 404, answer
    assert answer["detail"]["code"] == "device_unknown"


def test_the_list_of_a_device_the_hub_lacks_is_a_404(panel):
    path = "/agent/module?device_id=00000000000000000000000000000000"

    assert panel.status("GET", path) == 404


@pytest.mark.parametrize("name", [KNOWN_MODULE, INSTANCE_MODULE])
def test_a_modules_own_page_needs_a_device_the_hub_manages(panel, device_id, name):
    """The configuration pane belongs to a machine the hub has a binding
    with: a row nobody's agent ever joined has nothing to configure."""
    path = f"/agent/module/{name}?device_id={device_id}"

    status, answer = panel.call("GET", path)
    assert status == 404, answer
    assert answer["detail"]["code"] == "device_unknown"


def test_an_instance_pages_read_and_set_know_no_device_the_hub_lacks(panel):
    """Both routes of the shared instances router answer at Codeg's path, and
    each names the device it cannot find in the panel's own refusal shape."""
    device = "00000000000000000000000000000000"

    status, answer = panel.call(
        "GET", f"/agent/module/{INSTANCE_MODULE}?device_id={device}"
    )
    assert status == 404, answer
    assert answer["detail"]["code"] == "device_unknown"

    status, answer = panel.call(
        "POST",
        f"/agent/module/{INSTANCE_MODULE}/set",
        {"device_id": device, "instances": []},
    )
    assert status == 404, answer
    assert answer["detail"]["code"] == "device_unknown"
