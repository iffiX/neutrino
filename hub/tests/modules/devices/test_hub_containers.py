"""The hub containers the machine's container modules compose into the Containers state.

What these pin, with the test-only module ``demo``: each container with its
module, its image's digest and sources as the manifest entry for the
machine's platform pins them, the entry's source sets, and starting with
the box while the module is wanted running; nothing for a module wanted
absent or with no composition; the refusals of a composition the agent
could not run; and the owner rule's hub side.
"""

import pytest

from neutrino_hub.modules.devices import hub_containers as hub_containers_module
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.hub_containers import (
    HUB_CONTAINER_COMPOSERS,
    HubContainer,
    check_composition,
    compose_hub_containers,
    container_modules,
    is_hub_container,
)
from neutrino_hub.modules.devices.manifests import (
    entry_method,
    entry_params,
    load_module_manifests,
)
from tests.conftest import DEMO_ENTRY, DEMO_WEB_DIGEST, DEMO_WORKER_DIGEST

DEVICE = "dev-1"
LINUX = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}
PARAMS = DEMO_ENTRY["install"]["params"]


@pytest.fixture
def store(monkeypatch, tmp_path, demo_container_module):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        "neutrino_hub.modules.devices.desired_state.UTILS_CONFIG_DIR", tmp_path
    )
    return DesiredStateStore()


def test_a_container_module_s_containers_are_composed_with_their_images(store):
    store.set_want(DEVICE, "demo", "installed")
    store.write(DEVICE, "demo", {"password": "pw"})

    composed = compose_hub_containers(store, DEVICE, LINUX)

    assert composed == [
        {
            "module": "demo",
            "name": "neutrino_demo_worker",
            "image": {
                "digest": DEMO_WORKER_DIGEST,
                "sources": ["docker.io/acme/worker"],
            },
            "ports": [],
            "volumes": ["neutrino_demo_data:/data"],
            "environment": ["EXTRA_INDEX={pypi}/extra"],
            "command": "worker run",
            "is_autostart": False,
            "services": [],
            "source_sets": ["pypi"],
            "after": [],
            "page_port": 0,
        },
        {
            "module": "demo",
            "name": "neutrino_demo",
            "image": {
                "digest": DEMO_WEB_DIGEST,
                "sources": ["ghcr.io/acme/demo", "ghcr.nju.edu.cn/acme/demo"],
            },
            "ports": [],
            "volumes": ["neutrino_demo_data:/srv"],
            "environment": ["DEMO_PASSWORD=pw"],
            "command": "",
            "is_autostart": False,
            "services": [],
            "source_sets": ["pypi"],
            "after": ["neutrino_demo_worker"],
            "page_port": 8080,
        },
    ]


@pytest.mark.parametrize(
    "want, is_autostart", [("installed", False), ("stopped", False), ("running", True)]
)
def test_a_module_s_containers_start_with_the_box_while_it_is_wanted_running(
    store, want, is_autostart
):
    store.set_want(DEVICE, "demo", want)

    composed = compose_hub_containers(store, DEVICE, LINUX)

    assert {container["is_autostart"] for container in composed} == {is_autostart}


def test_a_module_wanted_absent_or_not_named_composes_nothing(store):
    assert compose_hub_containers(store, DEVICE, LINUX) == []

    store.set_want(DEVICE, "demo", "absent")

    assert compose_hub_containers(store, DEVICE, LINUX) == []
    assert container_modules(store.modules(DEVICE)) == []


def test_a_module_with_no_composition_composes_nothing(store, monkeypatch):
    store.set_want(DEVICE, "demo", "running")
    monkeypatch.delitem(HUB_CONTAINER_COMPOSERS, "demo")

    assert compose_hub_containers(store, DEVICE, LINUX) == []


def test_a_platform_the_manifest_does_not_name_composes_nothing(store):
    store.set_want(DEVICE, "demo", "running")

    composed = compose_hub_containers(
        store, DEVICE, {"os": "windows", "arch": "arm64", "version": "26100"}
    )

    assert composed == []


def test_the_container_modules_are_those_of_the_container_method(store):
    store.set_want(DEVICE, "cloudcli", "running")
    store.set_want(DEVICE, "demo", "stopped")

    assert container_modules(store.modules(DEVICE)) == ["demo"]


def demo(**overrides) -> HubContainer:
    fields = {"name": "neutrino_demo", "image": "web"}
    fields.update(overrides)
    return HubContainer(**fields)


@pytest.mark.parametrize(
    "containers, words",
    [
        ((demo(name="other"),), "must start neutrino_demo"),
        ((demo(name="neutrino_demox"),), "must start neutrino_demo"),
        ((demo(), demo()), "twice"),
        ((demo(image="nothing"),), "names no image artifact"),
        ((demo(volumes=("/srv:/data",)),), "no named volume"),
        ((demo(volumes=("neutrino_other_x:/data",)),), "no named volume"),
        ((demo(environment=("A={nosuch}",)),), "names no source set"),
        ((demo(environment=("A={npm}",)),), "lists not"),
        ((demo(after=("neutrino_demo_ghost",)),), "starts after no container"),
        ((demo(after=("neutrino_demo",)),), "starts after no container"),
        ((demo(page_port=70000),), "is no port"),
    ],
)
def test_a_composition_the_agent_could_not_run_is_refused(
    demo_container_module, containers, words
):
    with pytest.raises(ValueError) as refused:
        check_composition("demo", containers, PARAMS)

    assert words in str(refused.value)


def test_a_sound_composition_passes(demo_container_module):
    check_composition(
        "demo",
        (
            demo(name="neutrino_demo_db", image="worker"),
            demo(after=("neutrino_demo_db",), environment=("I={pypi}",)),
        ),
        PARAMS,
    )


def test_every_shipped_container_module_composes_a_sound_list(store):
    """Each manifest of the container method has a composition, and what it
    composes passes the check on every platform it names."""
    for name, manifest in load_module_manifests().items():
        for entry in manifest["platforms"].values():
            if entry_method(entry) != "container":
                continue
            assert name in HUB_CONTAINER_COMPOSERS, name
            request = hub_containers_module.HubContainerRequest(
                store=store, key=DEVICE, platform=LINUX
            )
            check_composition(
                name, tuple(HUB_CONTAINER_COMPOSERS[name](request)), entry_params(entry)
            )


def test_a_hub_container_is_known_by_its_label_or_the_composition():
    details = {
        "containers": [
            {"name": "neutrino_demo", "module": "demo"},
            {"name": "web", "module": ""},
        ]
    }

    assert is_hub_container("neutrino_demo", details, []) is True
    assert is_hub_container("web", details, []) is False
    assert is_hub_container(
        "neutrino_demo_worker", {}, [{"name": "neutrino_demo_worker"}]
    )
    assert is_hub_container("adhoc", details, []) is False
