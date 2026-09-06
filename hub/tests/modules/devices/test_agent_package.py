"""Which agent package the hub hands a device.

The agent carries its own interpreter now, so one family is no longer one
file: the machine picks as much as the format does. A build dropped under
``config/devices/packages`` wins over the one the hub package baked.
"""

import pytest

from neutrino_hub.modules.devices import agent_package
from neutrino_hub.modules.devices.agent_package import (
    agent_packages,
    package_architecture,
)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """The two places a package is looked for, both empty."""
    config = tmp_path / "config"
    data = tmp_path / "data"
    (config / "devices" / "packages").mkdir(parents=True)
    (data / "agent_package").mkdir(parents=True)
    monkeypatch.setattr(agent_package, "UTILS_CONFIG_DIR", config)
    monkeypatch.setattr(agent_package, "UTILS_DATA_DIR", data)
    return config / "devices" / "packages", data / "agent_package"


@pytest.mark.parametrize(
    "name, architecture",
    [
        ("neutrino-agent_0.1.0_amd64.deb", "amd64"),
        ("neutrino-agent_0.1.0_arm64.deb", "arm64"),
        ("neutrino-agent-0.1.0-1.x86_64.rpm", "amd64"),
        ("neutrino-agent-0.1.0-1.aarch64.rpm", "arm64"),
        ("neutrino-agent_0.1.0_all.deb", ""),
        ("neutrino-agent-0.1.0-1.noarch.rpm", ""),
    ],
)
def test_every_name_either_family_writes_says_its_machine(name, architecture):
    """The two families punctuate the same machine differently, and the older
    machine-independent names say no machine at all."""
    assert package_architecture(name) == architecture


def test_the_baked_packages_are_found_per_family_and_machine(roots):
    _, baked = roots
    (baked / "neutrino-agent_0.1.0_amd64.deb").write_bytes(b"deb")
    (baked / "neutrino-agent_0.1.0_arm64.deb").write_bytes(b"deb")
    (baked / "neutrino-agent-0.1.0-1.x86_64.rpm").write_bytes(b"rpm")

    found = agent_packages()

    assert sorted(found) == ["deb", "rpm"]
    assert sorted(found["deb"]) == ["amd64", "arm64"]
    assert found["deb"]["arm64"].name == "neutrino-agent_0.1.0_arm64.deb"
    assert sorted(found["rpm"]) == ["amd64"]


def test_a_pinned_build_wins_over_the_baked_one(roots):
    pinned, baked = roots
    (baked / "neutrino-agent_0.1.0_amd64.deb").write_bytes(b"baked")
    (pinned / "neutrino-agent_0.2.0_amd64.deb").write_bytes(b"pinned")

    found = agent_packages()

    assert found["deb"]["amd64"].read_bytes() == b"pinned"


def test_a_pinned_build_of_one_family_leaves_the_other_baked(roots):
    """Dropping in one file is not a decision about the other family."""
    pinned, baked = roots
    (baked / "neutrino-agent-0.1.0-1.x86_64.rpm").write_bytes(b"baked")
    (pinned / "neutrino-agent_0.2.0_amd64.deb").write_bytes(b"pinned")

    found = agent_packages()

    assert found["deb"]["amd64"].read_bytes() == b"pinned"
    assert found["rpm"]["amd64"].read_bytes() == b"baked"


def test_a_package_naming_no_machine_is_not_offered(roots):
    """A file this hub cannot say the machine of is not one it may hand to a
    device: the interpreter inside it is for one machine either way."""
    _, baked = roots
    (baked / "neutrino-agent_0.1.0_all.deb").write_bytes(b"deb")

    assert agent_packages() == {}


def test_nothing_carried_is_nothing_offered(roots):
    assert agent_packages() == {}
