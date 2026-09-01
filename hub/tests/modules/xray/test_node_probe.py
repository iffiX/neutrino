"""When a node has been probed, and what "no answer" is allowed to mean.

Three states share one shape here and must not share one rendering: a node
nobody has probed yet, a node that is switched off and therefore never probed,
and a node that was probed and did not answer. The last is the only failure.
"""

import time

from neutrino_hub.modules.xray.node_config import XrayNodeConfig
from neutrino_hub.modules.xray.node_probe import XrayNodeProbe

NODE = XrayNodeConfig(
    id="one",
    name="one",
    address="203.0.113.10",
    is_enabled=True,
    protocol="shadowsocks",
    port=5800,
)


def test_the_first_read_probes_however_young_the_machine_is(monkeypatch):
    """`time.monotonic` counts from boot on Linux, so a panel that starts
    early in one used to be younger than the cache's own age and never probe
    at all: every node read unreachable until uptime passed the window."""
    probe = XrayNodeProbe()
    monkeypatch.setattr(time, "monotonic", lambda: 3.0)
    probed: list = []
    monkeypatch.setattr(
        XrayNodeProbe, "refresh", lambda self, nodes: probed.append(nodes) or []
    )

    probe.results([NODE])

    assert probed == [[NODE]]


def test_a_second_read_inside_the_window_does_not_probe_again(monkeypatch):
    probe = XrayNodeProbe()
    monkeypatch.setattr(
        XrayNodeProbe,
        "refresh",
        lambda self, nodes: setattr(probe, "_probed_at", time.monotonic()),
    )
    probe.results([NODE])
    probed: list = []
    monkeypatch.setattr(
        XrayNodeProbe, "refresh", lambda self, nodes: probed.append(nodes)
    )

    probe.results([NODE])

    assert probed == []
