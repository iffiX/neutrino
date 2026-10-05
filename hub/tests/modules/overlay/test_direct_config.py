"""Direct's settings as config/overlay/direct.json stores them.

A missing file is Direct off with no public address; a stated host is an IP
address or a host name; the port Direct opens is the agent port, while it is
on alone.
"""

import json

import pytest

from neutrino_hub.modules.overlay.direct_config import (
    OverlayDirectConfig,
    direct_agent_port,
    is_public_host_refused,
    read_direct,
    write_direct,
)


@pytest.fixture
def config_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    return tmp_path


def test_a_box_with_no_file_has_direct_off(config_dir):
    assert read_direct() == OverlayDirectConfig()
    assert read_direct().public_host == ""


def test_what_is_written_reads_back(config_dir):
    written = OverlayDirectConfig(
        is_enabled=True, public_host="hub.example.org", public_port=443
    )

    write_direct(written)

    assert read_direct() == written


@pytest.mark.parametrize(
    "host", ["", "hub.example.org", "hub", "203.0.113.7", "2001:db8::7", "a-b.c."]
)
def test_an_address_or_a_host_name_is_accepted(host):
    assert not is_public_host_refused(host)


@pytest.mark.parametrize(
    "host",
    ["two words", "-oProxy", "hub_example.org", "a..b", "-a.b", "a-.b", "x" * 254],
)
def test_anything_else_is_refused(host):
    assert is_public_host_refused(host)


def test_the_port_direct_opens_is_the_agent_port_while_it_is_on(config_dir):
    (config_dir / "web").mkdir()
    (config_dir / "web/settings.json").write_text(
        json.dumps({"agent_listen_port": 9443})
    )

    assert direct_agent_port() is None
    write_direct(OverlayDirectConfig(is_enabled=True))
    assert direct_agent_port() == 9443


def test_a_box_not_set_up_opens_nothing(config_dir):
    write_direct(OverlayDirectConfig(is_enabled=True))

    assert direct_agent_port() is None
