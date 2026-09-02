"""When a node has been probed, and what "no answer" is allowed to mean.

Three states share one shape here and must not share one rendering: a node
nobody has probed yet, a node that is switched off and therefore never probed,
and a node that was probed and did not answer. The last is the only failure.
"""

import socket
import time

from neutrino_hub.modules.xray import node_probe
from neutrino_hub.modules.xray.constants import XRAY_EGRESS_MARK
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


class _RecordingSocket:
    """A socket that records what was set on it and connects to nothing."""

    def __init__(self, *arguments):
        self.options: list = []
        self.connected: list = []

    def setsockopt(self, level, option, value) -> None:
        self.options.append((level, option, value))

    def settimeout(self, timeout_s) -> None:
        self.timeout_s = timeout_s

    def connect(self, address) -> None:
        self.connected.append(address)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *arguments) -> None:
        self.close()


def test_a_probe_leaves_under_the_egress_mark(monkeypatch):
    """A box proxying its own traffic diverts an unmarked probe into its own
    TPROXY socket: the handshake completes locally in no time at all, so every
    node reads alive at 0 ms whatever the node is doing. The mark is the same
    exemption xray stamps on its own outbound sockets."""
    opened: list = []

    def build(*arguments):
        connection = _RecordingSocket(*arguments)
        opened.append(connection)
        return connection

    monkeypatch.setattr(node_probe.socket, "socket", build)
    monkeypatch.setattr(
        node_probe.socket,
        "getaddrinfo",
        lambda address, port, **keywords: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
        ],
    )

    XrayNodeProbe().probe(NODE)

    assert opened[0].options == [(socket.SOL_SOCKET, socket.SO_MARK, XRAY_EGRESS_MARK)]
    assert opened[0].connected == [("203.0.113.10", 5800)]


def test_a_probe_without_the_privilege_to_mark_still_probes(monkeypatch):
    """The mark needs CAP_NET_ADMIN, which the panel has and a developer
    running this by hand may not."""

    class _Refusing(_RecordingSocket):
        def setsockopt(self, level, option, value) -> None:
            raise PermissionError("no CAP_NET_ADMIN here")

    monkeypatch.setattr(node_probe.socket, "socket", lambda *arguments: _Refusing())
    monkeypatch.setattr(
        node_probe.socket,
        "getaddrinfo",
        lambda address, port, **keywords: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
        ],
    )

    result = XrayNodeProbe().probe(NODE)

    assert result.is_alive
