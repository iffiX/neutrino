"""No state names a recipe older than a forward-only module's newest run, held against module_install.md.

What these pin: a machine that follows the tested version, and one whose
chosen version is older, is sent the newest run's listed recipe, or the
tested recipe when the newest run is the tested version, while
``modules.json`` keeps the choice; a newest run the feeds do not list holds
the module by ``is_taken_over`` in the entry alone; a module without the
flag and a newest run older than the choice change nothing; and Containers'
``hub_containers`` names the newest run's images, or leaves a held module's
containers out.
"""

import json

import pytest

from neutrino_hub.modules.devices import desired_state as desired_state_module
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.hub_containers import compose_hub_containers
from tests.conftest import DEMO_MANIFEST, DEMO_WEB_DIGEST

DEVICE = "device-one"
PLATFORM = {"os": "linux", "family": "debian", "arch": "amd64"}
TESTED = "1.27.3"
AGENT_RECIPE = {"method": "agent", "params": {}}


def recipe_of(name: str, version: str) -> dict:
    return {"runner": name, "method": "hub", "params": {"version": version}}


class ListedReleases:
    """The feeds as read: these versions of each module are listed."""

    def __init__(self, listed=("28.0.0", "1.27.2")):
        self.listed = set(listed)

    def recipe(self, module, platform, version):
        return recipe_of(module, version) if version in self.listed else None


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        desired_state_module,
        "resolved_modules",
        lambda platform: {
            "fwd": {"recipe": recipe_of("fwd", TESTED)},
            "plain": {"recipe": recipe_of("plain", TESTED)},
            "terminal": {"recipe": {"runner": "terminal", **AGENT_RECIPE}},
            "remote_desktop": {"recipe": {"runner": "remote_desktop", **AGENT_RECIPE}},
            "ssh_server": {"recipe": {"runner": "ssh_server", **AGENT_RECIPE}},
        },
    )
    monkeypatch.setattr(
        desired_state_module,
        "load_module_manifests",
        lambda: {"fwd": {"is_data_forward_only": True}, "plain": {}},
    )
    held = DesiredStateStore()
    held.set_want(DEVICE, "fwd", "running")
    held.set_want(DEVICE, "plain", "running")
    return held


def sent(store, newest_runs, releases=None) -> dict:
    desired, _ = store.compose(
        DEVICE,
        PLATFORM,
        releases=releases or ListedReleases(),
        newest_runs=newest_runs,
    )
    return desired["modules"]


def test_a_machine_following_the_tested_version_is_sent_its_newest_run(store):
    modules = sent(store, {"fwd": "28.0.0"})

    assert modules["fwd"]["install"]["params"]["version"] == "28.0.0"
    assert "is_taken_over" not in modules["fwd"]
    assert store.version_of(DEVICE, "fwd") == ""


def test_an_older_choice_is_sent_the_tested_recipe_when_it_is_the_newest_run(store):
    store.set_version(DEVICE, "fwd", "1.27.2")

    modules = sent(store, {"fwd": TESTED})

    assert modules["fwd"]["install"] == recipe_of("fwd", TESTED)
    assert store.version_of(DEVICE, "fwd") == "1.27.2"


def test_an_unlisted_newest_run_holds_the_module_in_the_state_alone(store):
    modules = sent(store, {"fwd": "28.9.0"})

    assert modules["fwd"]["is_taken_over"] is True
    assert modules["fwd"]["install"]["params"]["version"] == TESTED
    assert "is_taken_over" not in store.modules(DEVICE)["fwd"]


def test_a_module_without_the_flag_and_a_newer_choice_change_nothing(store):
    store.set_version(DEVICE, "plain", "1.27.2")
    store.set_version(DEVICE, "fwd", "28.0.0")

    modules = sent(store, {"plain": "28.0.0", "fwd": TESTED})

    assert modules["plain"]["install"]["params"]["version"] == "1.27.2"
    assert modules["fwd"]["install"]["params"]["version"] == "28.0.0"
    assert "is_taken_over" not in modules["fwd"]


@pytest.fixture
def flagged_demo(demo_container_module, monkeypatch, tmp_path):
    (demo_container_module / "demo.json").write_text(
        json.dumps({**DEMO_MANIFEST, "is_data_forward_only": True}), encoding="utf-8"
    )
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "UTILS_CONFIG_DIR", tmp_path)
    held = DesiredStateStore()
    held.set_want(DEVICE, "demo", "running")
    return held


class DemoReleases:
    """Version 2.0.0 of demo names its own digest for ``web``."""

    def recipe(self, module, platform, version):
        if version != "2.0.0":
            return None
        params = DEMO_MANIFEST["platforms"]["linux"]["install"]["params"]
        artifacts = [
            (
                {**artifact, "digest": "sha256:" + "c" * 64}
                if artifact["name"] == "web"
                else dict(artifact)
            )
            for artifact in params["artifacts"]
        ]
        return {"params": {**params, "version": version, "artifacts": artifacts}}


def test_containers_name_the_images_of_the_newest_run(flagged_demo):
    composed = compose_hub_containers(
        flagged_demo,
        DEVICE,
        PLATFORM,
        releases=DemoReleases(),
        newest_runs={"demo": "2.0.0"},
    )

    assert "sha256:" + "c" * 64 in [item["image"]["digest"] for item in composed]
    assert DEMO_WEB_DIGEST not in [item["image"]["digest"] for item in composed]


def test_a_held_container_module_s_containers_are_left_out(flagged_demo):
    composed = compose_hub_containers(
        flagged_demo,
        DEVICE,
        PLATFORM,
        releases=DemoReleases(),
        newest_runs={"demo": "9.9.9"},
    )

    assert [item for item in composed if item["module"] == "demo"] == []
