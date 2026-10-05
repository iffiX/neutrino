"""The part of ``packaging/integration/connect_probe.py`` that reads a hub URL.

The probe itself runs against a live hub; what is asserted here is that a
link's IPv6 address reaches the agent's WebSocket client as a bare host and
a port, and goes out in brackets in the ``Host`` header.
"""

import importlib.util
from pathlib import Path

import pytest

PROBE = (
    Path(__file__).resolve().parents[3]
    / "packaging"
    / "integration"
    / "connect_probe.py"
)


@pytest.fixture(scope="module")
def probe():
    spec = importlib.util.spec_from_file_location("connect_probe", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("url", "host", "authority"),
    [
        ("https://[2001:db8::5]:8443", "2001:db8::5", "[2001:db8::5]:8443"),
        ("https://192.168.8.1:8443", "192.168.8.1", "192.168.8.1:8443"),
    ],
)
def test_a_hub_url_is_split_into_its_host_and_port(probe, url, host, authority):
    client = probe.Channel(url, "ab" * 32).client

    assert (client._host, client._port) == (host, 8443)
    assert client._authority() == authority
