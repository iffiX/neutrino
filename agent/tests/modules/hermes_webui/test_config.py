"""Hermes WebUI's configuration: the forwarder's port and its two secrets."""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.hermes_webui.config import HermesWebuiConfig


def test_the_state_s_fields_are_read_and_a_missing_port_is_8787():
    config = HermesWebuiConfig.from_dict({"secret": "s", "password": "p"})

    assert (config.port, config.secret, config.password) == (8787, "s", "p")
    config.validate()


@pytest.mark.parametrize("port", [0, 80, 1023, 65536, True, "8787", None])
def test_a_port_outside_1024_to_65535_is_refused_port_invalid(port):
    config = HermesWebuiConfig.from_dict({"port": port, "secret": "s"})

    with pytest.raises(ModuleApplyError) as refused:
        config.validate()

    assert (refused.value.code, refused.value.params) == (
        "port_invalid",
        {"port": port},
    )


@pytest.mark.parametrize("port", [1024, 8787, 65535])
def test_a_port_in_the_range_is_taken(port):
    HermesWebuiConfig.from_dict({"port": port}).validate()
